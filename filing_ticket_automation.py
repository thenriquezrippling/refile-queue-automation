#!/usr/bin/env python3
"""
filing_ticket_automation.py - TaxOps Filing Ticket Automation

Runs on the 1st of every month to:
  1. Create Monthly filing tickets for the prior month (all states with monthly-filings-epic label)
  2. On the 1st of Mar/Jun/Sep/Dec: create Quarterly tickets for current quarter
  3. Create Semi-Monthly SM-1 and SM-2 tickets for current month (OH, KY)
  4. Post a Slack summary of all tickets created

Secrets required:
  JIRA_EMAIL        - Jira account email
  JIRA_API_TOKEN    - Jira API token
  SLACK_WEBHOOK_URL - Slack incoming webhook URL
"""

import os
import re
import logging
from datetime import date
from calendar import monthrange
import requests
from requests.auth import HTTPBasicAuth

_env = os.environ.get

JIRA_BASE_URL  = _env("JIRA_BASE_URL", "https://rippling.atlassian.net")
JIRA_EMAIL     = _env("JIRA_EMAIL", "")
JIRA_API_TOKEN = _env("JIRA_API_TOKEN", "")
SLACK_WEBHOOK  = _env("SLACK_WEBHOOK_URL", "")

JIRA_PROJECT = "FILING"

# Labels identifying each Parent Epic type
LABEL_MONTHLY   = "monthly-filings-epic"
LABEL_QUARTERLY = "quarterly-filings-epic"
LABEL_SEMIM     = "semi-monthly-filings-epic"

# Custom field IDs
FIELD_FILING_UNIT = "customfield_21471"
FIELD_STATE_CODE  = "customfield_21080"
FIELD_TAX_TYPES   = "customfield_21075"
FIELD_REVIEWER    = "customfield_21472"
FIELD_PAYMENT     = "customfield_21079"
FIELD_FILING_MTH  = "customfield_21077"
FIELD_TEMPLATE    = "customfield_21076"
FIELD_NOTES       = "customfield_21476"
FIELD_APPROVAL    = "customfield_21479"
FIELD_SEMIM_TYPE  = "customfield_21650"

COPY_FIELDS = [
    FIELD_FILING_UNIT, FIELD_STATE_CODE, FIELD_TAX_TYPES, FIELD_REVIEWER,
    FIELD_PAYMENT, FIELD_FILING_MTH, FIELD_TEMPLATE, FIELD_NOTES,
    FIELD_APPROVAL, FIELD_SEMIM_TYPE,
    "customfield_21477", "customfield_21473", "customfield_21474",
    "customfield_21475", "customfield_21478",
]

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Jira Client (matches refile_queue.py pattern)
# ─────────────────────────────────────────────

class JiraClient:
    def __init__(self):
        self.base = JIRA_BASE_URL.rstrip("/") + "/rest/api/3"
        self.auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
        self.hdrs = {"Accept": "application/json", "Content-Type": "application/json"}

    def _get(self, path, params=None):
        r = requests.get(f"{self.base}{path}", auth=self.auth, headers=self.hdrs, params=params)
        r.raise_for_status()
        return r.json()

    def _post(self, path, body):
        r = requests.post(f"{self.base}{path}", auth=self.auth, headers=self.hdrs, json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def _put(self, path, body):
        r = requests.put(f"{self.base}{path}", auth=self.auth, headers=self.hdrs, json=body)
        r.raise_for_status()

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


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def advance_month(d: date, months: int) -> date:
    """Advance a date by N months, same day (capped at month end)."""
    m = d.month + months
    y = d.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return d.replace(year=y, month=m, day=min(d.day, monthrange(y, m)[1]))


def copy_field_value(val):
    """Safely copy a Jira field value for cloning into a new issue."""
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


def get_parent_epics(jira, label):
    """Return all FILING Parent Epics tagged with a given frequency label."""
    jql = f'project = {JIRA_PROJECT} AND issuetype = "Parent Epic" AND labels = "{label}"'
    return jira.search_jql(jql, ["summary", "key", "assignee", "labels"] + COPY_FIELDS)


def get_children(jira, parent_key, issue_type):
    """Return all child tickets of a given type under a parent, newest first."""
    jql = (
        f'project = {JIRA_PROJECT} AND parent = {parent_key} '
        f'AND issuetype = "{issue_type}" ORDER BY created DESC'
    )
    return jira.search_jql(
        jql, ["summary", "duedate", "assignee", "labels", "priority", "issuetype"] + COPY_FIELDS
    )


def latest_per_unit(tickets):
    """Return the most recent ticket per filing unit (customfield_21471)."""
    seen = {}
    for t in tickets:
        unit = t["fields"].get(FIELD_FILING_UNIT) or "unknown"
        if unit not in seen:
            seen[unit] = t
    return seen


def build_fields(template, parent_key, new_summary, new_duedate):
    """Build a new issue fields dict cloned from a template ticket."""
    tf = template["fields"]
    fields = {
        "project":   {"key": JIRA_PROJECT},
        "issuetype": {"name": tf["issuetype"]["name"]},
        "summary":   new_summary,
        "parent":    {"key": parent_key},
        "duedate":   new_duedate,
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
    """Replace the month name (and year if it changed) in a ticket summary."""
    for m in MONTHS:
        if m in summary:
            updated = summary.replace(m, new_month)
            # Correct year if month boundary crossed (e.g. December -> January)
            for offset in (-1, 1):
                old_yr = str(new_year + offset)
                if old_yr in updated:
                    updated = updated.replace(old_yr, str(new_year))
            return updated
    return summary


def replace_quarter_in_summary(summary, new_quarter):
    """Replace 'Q# YYYY' with the new quarter string in a summary."""
    return re.sub(r'Q\d\s+\d{4}', new_quarter, summary)


def replace_quarter_label(labels, new_label):
    """Swap the old qXXX-filings label for the new quarter label."""
    cleaned = [l for l in labels if not re.match(r'^q\d\d\d-filings$', l)]
    if new_label not in cleaned:
        cleaned.append(new_label)
    return cleaned


def jira_link(key):
    return f"<https://rippling.atlassian.net/browse/{key}|{key}>"


# ─────────────────────────────────────────────
# Monthly Ticket Creation
# ─────────────────────────────────────────────

def create_monthly_tickets(jira, today: date):
    prior = advance_month(today, -1)
    month_name = MONTHS[prior.month - 1]
    year = prior.year
    log.info(f"Creating Monthly tickets for {month_name} {year}")
    created = []

    for epic in get_parent_epics(jira, LABEL_MONTHLY):
        parent_key = epic["key"]
        by_unit = latest_per_unit(get_children(jira, parent_key, "Monthly"))
        if not by_unit:
            log.warning(f"{parent_key}: no Monthly children, skipping")
            continue

        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                log.info(f"  {key}: {new_summary} (due {new_due})")
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"  Failed monthly for unit={unit} parent={parent_key}: {e}")

    return created


# ─────────────────────────────────────────────
# Quarterly Ticket Creation
# ─────────────────────────────────────────────

# Map: month -> (quarter name, quarter label)
QUARTER_MAP = {
    3:  lambda y: (f"Q1 {y}", f"q1{str(y)[2:]}-filings"),
    6:  lambda y: (f"Q2 {y}", f"q2{str(y)[2:]}-filings"),
    9:  lambda y: (f"Q3 {y}", f"q3{str(y)[2:]}-filings"),
    12: lambda y: (f"Q4 {y}", f"q4{str(y)[2:]}-filings"),
}


def create_quarterly_tickets(jira, today: date):
    if today.month not in QUARTER_MAP:
        log.info(f"Month {today.month} is not a quarterly creation month, skipping.")
        return []

    quarter_name, quarter_label = QUARTER_MAP[today.month](today.year)
    log.info(f"Creating Quarterly tickets for {quarter_name}")
    created = []

    for epic in get_parent_epics(jira, LABEL_QUARTERLY):
        parent_key = epic["key"]
        by_unit = latest_per_unit(get_children(jira, parent_key, "Quarterly"))
        if not by_unit:
            log.warning(f"{parent_key}: no Quarterly children, skipping")
            continue

        for unit, tmpl in by_unit.items():
            tf = tmpl["fields"]
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 3).isoformat() if prior_due else None
            new_summary = replace_quarter_in_summary(tf.get("summary", ""), quarter_name)
            fields = build_fields(tmpl, parent_key, new_summary, new_due)
            fields["labels"] = replace_quarter_label(fields.get("labels", []), quarter_label)
            try:
                key = jira.create_issue(fields)["key"]
                log.info(f"  {key}: {new_summary} (due {new_due})")
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"  Failed quarterly for unit={unit} parent={parent_key}: {e}")

    return created


# ─────────────────────────────────────────────
# Semi-Monthly Ticket Creation
# ─────────────────────────────────────────────

def create_semi_monthly_tickets(jira, today: date):
    month_name = MONTHS[today.month - 1]
    year = today.year
    log.info(f"Creating Semi-Monthly tickets for {month_name} {year}")
    created = []

    for epic in get_parent_epics(jira, LABEL_SEMIM):
        parent_key = epic["key"]
        children = get_children(jira, parent_key, "Semi-Monthly")
        if not children:
            log.warning(f"{parent_key}: no Semi-Monthly children, skipping")
            continue

        # Find most recent SM-1 and SM-2 separately (they share the same filing unit)
        sm1_tmpl = next((t for t in children if re.search(r'SM.?1', t["fields"].get("summary", ""))), None)
        sm2_tmpl = next((t for t in children if re.search(r'SM.?2', t["fields"].get("summary", ""))), None)

        for label, tmpl in [("SM-1", sm1_tmpl), ("SM-2", sm2_tmpl)]:
            if not tmpl:
                log.warning(f"{parent_key}: no {label} template found, skipping")
                continue
            tf = tmpl["fields"]
            prior_due = tf.get("duedate")
            new_due = advance_month(date.fromisoformat(prior_due), 1).isoformat() if prior_due else None
            new_summary = replace_month_in_summary(tf.get("summary", ""), month_name, year)
            try:
                key = jira.create_issue(build_fields(tmpl, parent_key, new_summary, new_due))["key"]
                log.info(f"  {key}: {new_summary} (due {new_due})")
                created.append({"key": key, "summary": new_summary, "due": new_due})
            except Exception as e:
                log.error(f"  Failed {label} under {parent_key}: {e}")

    return created


# ─────────────────────────────────────────────
# Slack Notification
# ─────────────────────────────────────────────

def send_slack_notification(monthly, quarterly, semi_monthly, today: date):
    if not SLACK_WEBHOOK:
        log.warning("SLACK_WEBHOOK_URL not set — skipping Slack notification")
        return

    prior = advance_month(today, -1)
    prior_str = f"{MONTHS[prior.month - 1]} {prior.year}"

    lines = [f":white_check_mark: *Filing Ticket Automation — {today.isoformat()}*"]

    if monthly:
        lines.append(f"\n*Monthly tickets created ({prior_str}):* {len(monthly)}")
        for t in monthly[:15]:
            lines.append(f"  • {jira_link(t['key'])} — {t['summary']}")
        if len(monthly) > 15:
            lines.append(f"  _...and {len(monthly) - 15} more_")

    if quarterly:
        lines.append(f"\n*Quarterly tickets created:* {len(quarterly)}")
        for t in quarterly[:15]:
            lines.append(f"  • {jira_link(t['key'])} — {t['summary']}")
        if len(quarterly) > 15:
            lines.append(f"  _...and {len(quarterly) - 15} more_")

    if semi_monthly:
        lines.append(f"\n*Semi-Monthly tickets created:* {len(semi_monthly)}")
        for t in semi_monthly:
            lines.append(f"  • {jira_link(t['key'])} — {t['summary']}")

    total = len(monthly) + len(quarterly) + len(semi_monthly)
    lines.append(f"\n*Total tickets created: {total}*")

    r = requests.post(SLACK_WEBHOOK, json={"text": "\n".join(lines)})
    r.raise_for_status()
    log.info("Slack notification sent")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    today = date.today()
    log.info(f"=== Filing Ticket Automation — {today} ===")

    jira = JiraClient()

    monthly      = create_monthly_tickets(jira, today)
    quarterly    = create_quarterly_tickets(jira, today)
    semi_monthly = create_semi_monthly_tickets(jira, today)

    send_slack_notification(monthly, quarterly, semi_monthly, today)

    log.info("=== Summary ===")
    log.info(f"  Monthly created:      {len(monthly)}")
    log.info(f"  Quarterly created:    {len(quarterly)}")
    log.info(f"  Semi-Monthly created: {len(semi_monthly)}")
    log.info(f"  Total:                {len(monthly) + len(quarterly) + len(semi_monthly)}")
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
