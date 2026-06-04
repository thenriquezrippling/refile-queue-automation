#!/usr/bin/env python3
"""TaxOps filing ticket automation — see docs/cursor-automation-filing-tickets.md"""
import argparse
import os
import re
import sys
import logging
from datetime import date
from calendar import monthrange
import requests
from requests.auth import HTTPBasicAuth

_env = os.environ.get
JIRA_BASE_URL = _env("JIRA_BASE_URL", "https://rippling.atlassian.net")
JIRA_EMAIL = _env("JIRA_EMAIL", "")
JIRA_API_TOKEN = _env("JIRA_API_TOKEN", "")
JIRA_PROJECT = "FILING"
LABEL_MONTHLY = "monthly-filings-epic"
LABEL_QUARTERLY = "quarterly-filings-epic"
LABEL_SEMIM = "semi-monthly-filings-epic"
FIELD_FILING_UNIT = "customfield_21471"
FIELD_STATE_CODE = "customfield_21080"
FIELD_TAX_TYPES = "customfield_21075"
FIELD_REVIEWER = "customfield_21472"
FIELD_PAYMENT = "customfield_21079"
FIELD_FILING_MTH = "customfield_21077"
FIELD_TEMPLATE = "customfield_21076"
FIELD_NOTES = "customfield_21476"
FIELD_APPROVAL = "customfield_21479"
FIELD_SEMIM_TYPE = "customfield_21650"
COPY_FIELDS = [FIELD_FILING_UNIT, FIELD_STATE_CODE, FIELD_TAX_TYPES, FIELD_REVIEWER, FIELD_PAYMENT, FIELD_FILING_MTH, FIELD_TEMPLATE, FIELD_NOTES, FIELD_APPROVAL, FIELD_SEMIM_TYPE, "customfield_21477", "customfield_21473", "customfield_21474", "customfield_21475", "customfield_21478"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
STATE_ALIASES = {"COLORADO": "CO", "OHIO": "OH"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

class JiraClient:
    def __init__(self):
        self.base = JIRA_BASE_URL.rstrip("/") + "/rest/api/3"
        self.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
        self.hdrs = {"Accept": "application/json", "Content-Type": "application/json"}
    def _post(self, path, body):
        r = requests.post(f"{self.base}{path}", auth=self.auth, headers=self.hdrs, json=body)
        r.raise_for_status()
        return r.json() if r.text else {}
    def _put(self, path, body):
        r = requests.put(f"{self.base}{path}", auth=self.auth, headers=self.hdrs, json=body)
        r.raise_for_status()
        return r.json() if r.text else {}
    def search_jql(self, jql, fields, max_results=100):
        issues, next_token = [], None
        while True:
            body = {"jql": jql, "fields": fields, "maxResults": max_results}
            if next_token: body["nextPageToken"] = next_token
            resp = self._post("/search/jql", body)
            chunk = resp.get("issues", [])
            issues.extend(chunk)
            next_token = resp.get("nextPageToken")
            if not chunk or not next_token: break
        return issues
    def create_issue(self, fields):
        return self._post("/issue", {"fields": fields})
    def update_issue(self, key, fields):
        return self._put(f"/issue/{key}", {"fields": fields})

def advance_month(d, months):
    m = d.month + months; y = d.year + (m - 1) // 12; m = (m - 1) % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, monthrange(y, m)[1]))

def copy_field_value(val):
    if val is None: return None
    if isinstance(val, dict):
        if "id" in val: return {"id": val["id"]}
        if "accountId" in val: return {"accountId": val["accountId"]}
        if "value" in val: return {"value": val["value"]}
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, dict) and "id" in item: out.append({"id": item["id"]})
            elif isinstance(item, dict) and "accountId" in item: out.append({"accountId": item["accountId"]})
            elif isinstance(item, str): out.append(item)
        return out or None
    return val

def get_state_code(fields):
    val = fields.get(FIELD_STATE_CODE)
    if isinstance(val, dict): return (val.get("value") or val.get("name") or "").strip()
    return val.strip() if isinstance(val, str) else ""

def normalize_state_token(token):
    return STATE_ALIASES.get(token.strip().upper(), token.strip().upper())

def parse_exclude_states(raw):
    return {normalize_state_token(p) for p in raw.split(",") if p.strip()} if raw else set()

def is_excluded_state(fields, exclude_states):
    return bool(exclude_states) and normalize_state_token(get_state_code(fields)) in exclude_states

def get_parent_epics(jira, label):
    return jira.search_jql(f'project = {JIRA_PROJECT} AND issuetype = "Parent Epic" AND labels = "{label}"', ["summary", "key", "assignee", "labels"] + COPY_FIELDS)

def get_children(jira, parent_key, issue_type):
    return jira.search_jql(f'project = {JIRA_PROJECT} AND parent = {parent_key} AND issuetype = "{issue_type}" ORDER BY created DESC', ["summary", "duedate", "assignee", "labels", "priority", "issuetype"] + COPY_FIELDS)

def latest_per_unit(tickets):
    seen = {}
    for t in tickets:
        unit = t["fields"].get(FIELD_FILING_UNIT) or "unknown"
        if unit not in seen: seen[unit] = t
    return seen

def summary_contains_quarter_period(summary, quarter, year):
    """True if summary contains e.g. Q1 2026 (word boundary)."""
    return bool(re.search(rf"\b{re.escape(quarter)}\s+{year}\b", summary or "", re.I))

def latest_per_unit_with_source_quarter(tickets, source_quarter, source_year):
    """Latest Quarterly ticket per filing unit that has the prior quarter in summary."""
    marker = f"{source_quarter} {source_year}"
    eligible = [t for t in tickets if summary_contains_quarter_period(t["fields"].get("summary", ""), source_quarter, source_year)]
    if not eligible:
        return {}
    log.debug("Found %d tickets with %s for parent batch", len(eligible), marker)
    return latest_per_unit(eligible)

def unit_has_quarter_period(children, filing_unit, target_q, target_year):
    """True if this filing unit already has a Quarterly child for the target period."""
    year_str = str(target_year)
    return any(
        t["fields"].get(FIELD_FILING_UNIT) == filing_unit
        and summary_contains_quarter_period(t["fields"].get("summary", ""), target_q, year_str)
        for t in children
    )

def semi_monthly_epic_keys_by_state(jira):
    """Map normalized state code -> semi-monthly Parent Epic key."""
    out = {}
    for epic in get_parent_epics(jira, LABEL_SEMIM):
        state = normalize_state_token(get_state_code(epic["fields"]))
        if state:
            out[state] = epic["key"]
    return out

def migrate_semi_monthly_to_epics(jira, *, dry_run=False, exclude_states=None, errors=None):
    """Reparent Semi-Monthly tickets from monthly/quarterly parents to semi-monthly Parent Epics."""
    exclude_states = exclude_states or set()
    epic_by_state = semi_monthly_epic_keys_by_state(jira)
    if not epic_by_state:
        log.warning("No semi-monthly Parent Epics found; skipping migration")
        return []
    semi_parent_keys = set(epic_by_state.values())
    migrated = []
    jql = (
        f'project = {JIRA_PROJECT} AND issuetype = "Semi-Monthly" '
        f'AND parent NOT IN ({",".join(semi_parent_keys)})'
    )
    orphans = jira.search_jql(jql, ["summary", "parent", FIELD_STATE_CODE])
    for issue in orphans:
        key = issue["key"]
        tf = issue["fields"]
        state = normalize_state_token(get_state_code(tf))
        if state in exclude_states:
            continue
        target_parent = epic_by_state.get(state)
        if not target_parent:
            log.warning("No semi-monthly epic for state %s; skip %s", state, key)
            continue
        old_parent = (tf.get("parent") or {}).get("key", "?")
        if dry_run:
            migrated.append({"key": key, "summary": tf.get("summary"), "from": old_parent, "to": target_parent})
            continue
        try:
            jira.update_issue(key, {"parent": {"key": target_parent}})
            migrated.append({"key": key, "summary": tf.get("summary"), "from": old_parent, "to": target_parent})
            log.info("Reparented %s: %s -> %s", key, old_parent, target_parent)
        except Exception as e:
            log.error("Failed to reparent %s: %s", key, e)
            if errors is not None:
                errors.append({"type": "semi-monthly-migrate", "issue": key, "error": str(e)})
    return migrated

def build_fields(template, parent_key, new_summary, new_duedate):
    tf = template["fields"]
    fields = {"project": {"key": JIRA_PROJECT}, "issuetype": {"name": tf["issuetype"]["name"]}, "summary": new_summary, "parent": {"key": parent_key}, "duedate": new_duedate}
    if tf.get("assignee"): fields["assignee"] = {"accountId": tf["assignee"]["accountId"]}
    if tf.get("priority"): fields["priority"] = {"name": tf["priority"]["name"]}
    if tf.get("labels"): fields["labels"] = list(tf["labels"])
    for fid in COPY_FIELDS:
        val = copy_field_value(tf.get(fid))
        if val is not None: fields[fid] = val
    return fields

def replace_month_in_summary(summary, new_month, new_year):
    for m in MONTHS:
        if m in summary:
            updated = summary.replace(m, new_month)
            for offset in (-1, 1):
                old_yr = str(new_year + offset)
                if old_yr in updated: updated = updated.replace(old_yr, str(new_year))
            return updated
    return summary

def replace_quarter_in_summary(summary, new_quarter):
    return re.sub(r"Q\d\s+\d{4}", new_quarter, summary, count=1)

def replace_quarter_label(labels, new_label):
    cleaned = [l for l in labels if not re.match(r"^q\d\d\d-filings$", l)]
    if new_label not in cleaned: cleaned.append(new_label)
    return cleaned

def period_already_exists(jira, parent_key, issue_type, marker):
    return bool(jira.search_jql(f'project = {JIRA_PROJECT} AND parent = {parent_key} AND issuetype = "{issue_type}" AND summary ~ "\\"{marker}\\""', ["key"], max_results=1))

# Run month -> (target period name, label, source quarter, source year offset from run year)
QUARTER_RUN = {
    3: ("Q1", lambda y: f"q1{str(y)[2:]}-filings", "Q4", -1),
    6: ("Q2", lambda y: f"q2{str(y)[2:]}-filings", "Q1", 0),
    9: ("Q3", lambda y: f"q3{str(y)[2:]}-filings", "Q2", 0),
    12: ("Q4", lambda y: f"q4{str(y)[2:]}-filings", "Q3", 0),
}

def quarter_target_and_source(today):
    if today.month not in QUARTER_RUN:
        return None
    target_q, label_fn, source_q, year_delta = QUARTER_RUN[today.month]
    year = today.year
    target_name = f"{target_q} {year}"
    source_year = year + year_delta
    source_name = f"{source_q} {source_year}"
    return target_name, label_fn(year), source_name, source_q, source_year, target_q, year

def create_monthly_tickets(jira, today, *, dry_run=False, exclude_states=None, skip_existing=True, errors=None):
    exclude_states = exclude_states or set(); prior = advance_month(today, -1)
    month_name, year = MONTHS[prior.month - 1], prior.year; period_marker = f"{month_name} {year}"
    created = []
    for epic in get_parent_epics(jira, LABEL_MONTHLY):
        parent_key = epic["key"]; by_unit = latest_per_unit(get_children(jira, parent_key, "Monthly"))
        if not by_unit: continue
        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            if is_excluded_state(tf, exclude_states): continue
            if skip_existing and period_already_exists(jira, parent_key, "Monthly", period_marker): continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            if dry_run: created.append({"key": "DRY-RUN", "summary": new_summary}); continue
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"Failed monthly {parent_key}/{unit}: {e}")
                errors and errors.append({"type": "monthly", "parent": parent_key, "error": str(e)})
    return created

def create_quarterly_tickets(jira, today, *, dry_run=False, exclude_states=None, skip_existing=True, errors=None):
    exclude_states = exclude_states or set()
    spec = quarter_target_and_source(today)
    if not spec:
        return []
    quarter_name, quarter_label, source_name, source_q, source_year, target_q, target_year = spec
    created = []
    for epic in get_parent_epics(jira, LABEL_QUARTERLY):
        parent_key = epic["key"]
        children = get_children(jira, parent_key, "Quarterly")
        by_unit = latest_per_unit_with_source_quarter(children, source_q, source_year)
        if not by_unit:
            log.info("No Quarterly templates with %s under %s", source_name, parent_key)
            continue
        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            old_summary = tf.get("summary", "")
            if is_excluded_state(tf, exclude_states):
                continue
            if skip_existing and unit_has_quarter_period(children, unit, target_q, target_year):
                continue
            new_summary = replace_quarter_in_summary(old_summary, quarter_name)
            if new_summary == old_summary or not summary_contains_quarter_period(new_summary, target_q, str(target_year)):
                log.info("Skip quarterly %s/%s: summary would not contain %s", parent_key, unit, quarter_name)
                continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 3).isoformat() if prior_due else None
            fields = build_fields(tmpl, parent_key, new_summary, new_due)
            fields["labels"] = replace_quarter_label(fields.get("labels", []), quarter_label)
            if dry_run:
                created.append({"key": "DRY-RUN", "summary": new_summary})
                continue
            try:
                key = jira.create_issue(fields)["key"]
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"Failed quarterly {parent_key}/{unit}: {e}")
                errors and errors.append({"type": "quarterly", "parent": parent_key, "error": str(e)})
    return created

def create_semi_monthly_tickets(jira, today, *, dry_run=False, exclude_states=None, skip_existing=True, errors=None):
    exclude_states = exclude_states or set(); month_name, year = MONTHS[today.month - 1], today.year; created = []
    for epic in get_parent_epics(jira, LABEL_SEMIM):
        parent_key = epic["key"]; children = get_children(jira, parent_key, "Semi-Monthly")
        sm1 = next((t for t in children if re.search(r"SM.?1", t["fields"].get("summary", ""))), None)
        sm2 = next((t for t in children if re.search(r"SM.?2", t["fields"].get("summary", ""))), None)
        for label, tmpl in [("SM-1", sm1), ("SM-2", sm2)]:
            if not tmpl: continue
            tf = tmpl["fields"]
            if is_excluded_state(tf, exclude_states): continue
            marker = f"{month_name} {year}"
            if skip_existing and period_already_exists(jira, parent_key, "Semi-Monthly", marker): continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            if dry_run: created.append({"key": "DRY-RUN", "summary": new_summary}); continue
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                created.append({"key": key, "summary": new_summary})
            except Exception as e:
                errors and errors.append({"type": "semi-monthly", "parent": parent_key, "error": str(e)})
    return created

def write_run_summary(monthly, quarterly, semi_monthly, migrated, today, errors):
    prior = advance_month(today, -1); prior_str = f"{MONTHS[prior.month - 1]} {prior.year}"
    lines = [f"## Filing Ticket Automation — {today.isoformat()}", "", f"**Status:** {'failed' if errors else 'success'}"]
    if migrated:
        lines.append(f"\n### Semi-Monthly reparented: {len(migrated)}")
        for t in migrated[:20]:
            lines.append(f"- {t['key']}: {t.get('from')} → {t.get('to')} ({t.get('summary', '')[:60]})")
    if monthly:
        lines.append(f"\n### Monthly ({prior_str}): {len(monthly)}")
        for t in monthly[:20]: lines.append(f"- {t['key']}: {t['summary']}")
    if quarterly:
        lines.append(f"\n### Quarterly: {len(quarterly)}")
        for t in quarterly[:20]: lines.append(f"- {t['key']}: {t['summary']}")
    if semi_monthly:
        lines.append(f"\n### Semi-Monthly created: {len(semi_monthly)}")
        for t in semi_monthly: lines.append(f"- {t['key']}: {t['summary']}")
    lines.append(f"\n**Total created:** {len(monthly)+len(quarterly)+len(semi_monthly)}")
    if errors:
        lines.append("\n### Errors")
        for err in errors[:20]: lines.append(f"- {err}")
    summary = "\n".join(lines); log.info("\n%s", summary)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path: open(path, "a", encoding="utf-8").write(summary + "\n")

def parse_args():
    p = argparse.ArgumentParser(description="TaxOps filing ticket automation")
    p.add_argument("--as-of", type=date.fromisoformat, default=None)
    p.add_argument("--only", choices=("monthly", "quarterly", "semi-monthly", "all"), default="all")
    p.add_argument("--exclude-states", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-skip-existing", action="store_true")
    p.add_argument("--no-migrate-semi-monthly", action="store_true", help="Skip reparenting Semi-Monthly tickets to semi-monthly Parent Epics")
    return p.parse_args()

def main():
    args = parse_args(); today = args.as_of or date.today(); errors = []
    jira = JiraClient()
    opts = dict(dry_run=args.dry_run, exclude_states=parse_exclude_states(args.exclude_states), skip_existing=not args.no_skip_existing, errors=errors)
    migrated = []
    run_semim = args.only in ("semi-monthly", "all")
    if run_semim and not args.no_migrate_semi_monthly:
        migrated = migrate_semi_monthly_to_epics(
            jira,
            dry_run=opts["dry_run"],
            exclude_states=opts["exclude_states"],
            errors=opts["errors"],
        )
    monthly = create_monthly_tickets(jira, today, **opts) if args.only in ("monthly", "all") else []
    quarterly = create_quarterly_tickets(jira, today, **opts) if args.only in ("quarterly", "all") else []
    semi = create_semi_monthly_tickets(jira, today, **opts) if run_semim else []
    write_run_summary(monthly, quarterly, semi, migrated, today, errors)
    if errors and not args.dry_run: sys.exit(1)

if __name__ == "__main__": main()
