#!/usr/bin/env python3
"""
filing_ticket_automation.py - TaxOps Filing Ticket Automation

Runs on the 1st of every month to:
  1. Create Monthly filing tickets for the prior month (monthly-filings-epic)
  2. On Mar/Jun/Sep/Dec 1st: create Quarterly tickets for the current quarter
  3. Create Semi-Monthly SM-1 and SM-2 tickets for the current month (OH, KY)
  4. Write a run summary to logs and $GITHUB_STEP_SUMMARY for Cursor Automations

Secrets required:
  JIRA_EMAIL        - Jira account email
  JIRA_API_TOKEN    - Jira API token

Slack notifications are handled by a Cursor Automation on CI completion (see
docs/cursor-automation-filing-tickets.md).
"""

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

COPY_FIELDS = [
    FIELD_FILING_UNIT,
    FIELD_STATE_CODE,
    FIELD_TAX_TYPES,
    FIELD_REVIEWER,
    FIELD_PAYMENT,
    FIELD_FILING_MTH,
    FIELD_TEMPLATE,
    FIELD_NOTES,
    FIELD_APPROVAL,
    FIELD_SEMIM_TYPE,
    "customfield_21477",
    "customfield_21473",
    "customfield_21474",
    "customfield_21475",
    "customfield_21478",
]

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

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

    def search_jql(self, jql, fields, max_results=100):
        issues, next_token = [], None
        while True:
            body = {"jql": jql, "fields": fields, "maxResults": max_results}
            if next_token:
                body["nextPageToken"] = next_token
            resp = self._post("/search/jql", body)
            chunk = resp.get("issues", [])
            issues.extend(chunk)
            next_token = resp.get("nextPageToken")
            if not chunk or not next_token:
                break
        return issues

    def create_issue(self, fields):
        return self._post("/issue", {"fields": fields})


def advance_month(d: date, months: int) -> date:
    m = d.month + months
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, monthrange(y, m)[1]))


def copy_field_value(val):
    if val is None:
        return None
    if isinstance(val, dict):
        if "id" in val:
            return {"id": val["id"]}
        if "accountId" in val:
            return {"accountId": val["accountId"]}
        if "value" in val:
            return {"value": val["value"]}
    if isinstance(val, list):
        out = []
        for item in val:
            if isinstance(item, dict) and "id" in item:
                out.append({"id": item["id"]})
            elif isinstance(item, dict) and "accountId" in item:
                out.append({"accountId": item["accountId"]})
            elif isinstance(item, str):
                out.append(item)
        return out or None
    return val


def get_state_code(fields) -> str:
    val = fields.get(FIELD_STATE_CODE)
    if isinstance(val, dict):
        return (val.get("value") or val.get("name") or "").strip()
    if isinstance(val, str):
        return val.strip()
    return ""


def normalize_state_token(token: str) -> str:
    return STATE_ALIASES.get(token.strip().upper(), token.strip().upper())


def parse_exclude_states(raw: str) -> set[str]:
    if not raw:
        return set()
    return {normalize_state_token(part) for part in raw.split(",") if part.strip()}


def is_excluded_state(fields, exclude_states: set[str]) -> bool:
    return bool(exclude_states) and normalize_state_token(get_state_code(fields)) in exclude_states


def get_parent_epics(jira, label):
    jql = f'project = {JIRA_PROJECT} AND issuetype = "Parent Epic" AND labels = "{label}"'
    return jira.search_jql(jql, ["summary", "key", "assignee", "labels"] + COPY_FIELDS)


def get_children(jira, parent_key, issue_type):
    jql = f'project = {JIRA_PROJECT} AND parent = {parent_key} AND issuetype = "{issue_type}" ORDER BY created DESC'
    return jira.search_jql(jql, ["summary", "duedate", "assignee", "labels", "priority", "issuetype"] + COPY_FIELDS)


def latest_per_unit(tickets):
    seen = {}
    for t in tickets:
        unit = t["fields"].get(FIELD_FILING_UNIT) or "unknown"
        if unit not in seen:
            seen[unit] = t
    return seen


def build_fields(template, parent_key, new_summary, new_duedate):
    tf = template["fields"]
    fields = {
        "project": {"key": JIRA_PROJECT},
        "issuetype": {"name": tf["issuetype"]["name"]},
        "summary": new_summary,
        "parent": {"key": parent_key},
        "duedate": new_duedate,
    }
    if tf.get("assignee"):
        fields["assignee"] = {"accountId": tf["assignee"]["accountId"]}
    if tf.get("priority"):
        fields["priority"] = {"name": tf["priority"]["name"]}
    if tf.get("labels"):
        fields["labels"] = list(tf["labels"])
    for fid in COPY_FIELDS:
        val = copy_field_value(tf.get(fid))
        if val is not None:
            fields[fid] = val
    return fields


def replace_month_in_summary(summary, new_month, new_year):
    for m in MONTHS:
        if m in summary:
            updated = summary.replace(m, new_month)
            for offset in (-1, 1):
                old_yr = str(new_year + offset)
                if old_yr in updated:
                    updated = updated.replace(old_yr, str(new_year))
            return updated
    return summary


def replace_quarter_in_summary(summary, new_quarter):
    return re.sub(r"Q\d\s+\d{4}", new_quarter, summary)


def replace_quarter_label(labels, new_label):
    cleaned = [l for l in labels if not re.match(r"^q\d\d\d-filings$", l)]
    if new_label not in cleaned:
        cleaned.append(new_label)
    return cleaned


def period_already_exists(jira, parent_key, issue_type, marker: str) -> bool:
    jql = f'project = {JIRA_PROJECT} AND parent = {parent_key} AND issuetype = "{issue_type}" AND summary ~ "\\"{marker}\\""'
    return bool(jira.search_jql(jql, ["key"], max_results=1))


QUARTER_MAP = {
    3: lambda y: (f"Q1 {y}", f"q1{str(y)[2:]}-filings"),
    6: lambda y: (f"Q2 {y}", f"q2{str(y)[2:]}-filings"),
    9: lambda y: (f"Q3 {y}", f"q3{str(y)[2:]}-filings"),
    12: lambda y: (f"Q4 {y}", f"q4{str(y)[2:]}-filings"),
}


def create_monthly_tickets(jira, today, *, dry_run=False, exclude_states=None, skip_existing=True, errors=None):
    exclude_states = exclude_states or set()
    prior = advance_month(today, -1)
    month_name, year = MONTHS[prior.month - 1], prior.year
    period_marker = f"{month_name} {year}"
    log.info(f"Creating Monthly tickets for {period_marker}")
    created = []
    for epic in get_parent_epics(jira, LABEL_MONTHLY):
        parent_key = epic["key"]
        by_unit = latest_per_unit(get_children(jira, parent_key, "Monthly"))
        if not by_unit:
            continue
        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            if is_excluded_state(tf, exclude_states):
                continue
            if skip_existing and period_already_exists(jira, parent_key, "Monthly", period_marker):
                continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            if dry_run:
                created.append({"key": "DRY-RUN", "summary": new_summary})
                continue
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"Failed monthly {parent_key}/{unit}: {e}")
                errors and errors.append({"type": "monthly", "parent": parent_key, "error": str(e)})
    return created


def create_quarterly_tickets(jira, today, *, dry_run=False, exclude_states=None, skip_existing=True, errors=None):
    exclude_states = exclude_states or set()
    if today.month not in QUARTER_MAP:
        return []
    quarter_name, quarter_label = QUARTER_MAP[today.month](today.year)
    created = []
    for epic in get_parent_epics(jira, LABEL_QUARTERLY):
        parent_key = epic["key"]
        by_unit = latest_per_unit(get_children(jira, parent_key, "Quarterly"))
        if not by_unit:
            continue
        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            if is_excluded_state(tf, exclude_states):
                continue
            if skip_existing and period_already_exists(jira, parent_key, "Quarterly", quarter_name):
                continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 3).isoformat() if prior_due else None
            new_summary = replace_quarter_in_summary(tf.get("summary", ""), quarter_name)
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
    exclude_states = exclude_states or set()
    month_name, year = MONTHS[today.month - 1], today.year
    created = []
    for epic in get_parent_epics(jira, LABEL_SEMIM):
        parent_key = epic["key"]
        children = get_children(jira, parent_key, "Semi-Monthly")
        sm1 = next((t for t in children if re.search(r"SM.?1", t["fields"].get("summary", ""))), None)
        sm2 = next((t for t in children if re.search(r"SM.?2", t["fields"].get("summary", ""))), None)
        for label, tmpl in [("SM-1", sm1), ("SM-2", sm2)]:
            if not tmpl:
                continue
            tf = tmpl["fields"]
            if is_excluded_state(tf, exclude_states):
                continue
            marker = f"{month_name} {year}"
            if skip_existing and period_already_exists(jira, parent_key, "Semi-Monthly", marker):
                continue
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            if dry_run:
                created.append({"key": "DRY-RUN", "summary": new_summary})
                continue
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                created.append({"key": key, "summary": new_summary})
            except Exception as e:
                errors and errors.append({"type": "semi-monthly", "parent": parent_key, "error": str(e)})
    return created


def write_run_summary(monthly, quarterly, semi_monthly, today, errors):
    prior = advance_month(today, -1)
    prior_str = f"{MONTHS[prior.month - 1]} {prior.year}"
    lines = [f"## Filing Ticket Automation — {today.isoformat()}", ""]
    lines.append(f"**Status:** {'failed' if errors else 'success'}")
    if monthly:
        lines.append(f"\n### Monthly ({prior_str}): {len(monthly)}")
        for t in monthly[:20]:
            lines.append(f"- {t['key']}: {t['summary']}")
    if quarterly:
        lines.append(f"\n### Quarterly: {len(quarterly)}")
        for t in quarterly[:20]:
            lines.append(f"- {t['key']}: {t['summary']}")
    if semi_monthly:
        lines.append(f"\n### Semi-Monthly: {len(semi_monthly)}")
        for t in semi_monthly:
            lines.append(f"- {t['key']}: {t['summary']}")
    lines.append(f"\n**Total:** {len(monthly)+len(quarterly)+len(semi_monthly)}")
    if errors:
        lines.append("\n### Errors")
        for err in errors[:20]:
            lines.append(f"- {err}")
    summary = "\n".join(lines)
    log.info("\n%s", summary)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        open(path, "a", encoding="utf-8").write(summary + "\n")


def parse_args():
    p = argparse.ArgumentParser(description="TaxOps filing ticket automation")
    p.add_argument("--as-of", type=date.fromisoformat, default=None)
    p.add_argument("--only", choices=("monthly", "quarterly", "semi-monthly", "all"), default="all")
    p.add_argument("--exclude-states", default="")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-skip-existing", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    today = args.as_of or date.today()
    errors = []
    jira = JiraClient()
    opts = dict(dry_run=args.dry_run, exclude_states=parse_exclude_states(args.exclude_states), skip_existing=not args.no_skip_existing, errors=errors)
    monthly = create_monthly_tickets(jira, today, **opts) if args.only in ("monthly", "all") else []
    quarterly = create_quarterly_tickets(jira, today, **opts) if args.only in ("quarterly", "all") else []
    semi = create_semi_monthly_tickets(jira, today, **opts) if args.only in ("semi-monthly", "all") else []
    write_run_summary(monthly, quarterly, semi, today, errors)
    if errors and not args.dry_run:
        sys.exit(1)


if __name__ == "__main__":
    main()
