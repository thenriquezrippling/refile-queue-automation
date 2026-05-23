#!/usr/bin/env python3
"""
refile_queue.py - TaxOps Re-File Queue Automation

Runs daily at 6am PST (or on demand) to:
  1. Find unprocessed DNF tickets in filter 47966
  2. Apply 3-case decision tree (create/link/label Re-File tickets)
  3. Record Date Added to Re-File Queue on DNF tickets
  4. Monitor FILED Re-File tickets -> update linked DNF Completion Date
  5. Log all activity to Google Sheets (Daily Log + Run Summary tabs)
"""

import os
import json
import logging
from datetime import date, datetime
from typing import Optional
import requests
from requests.auth import HTTPBasicAuth
import gspread
from google.oauth2.service_account import Credentials

# Configuration
JIRA_BASE_URL     = os.environ["JIRA_BASE_URL"]
JIRA_EMAIL        = os.environ["JIRA_EMAIL"]
JIRA_API_TOKEN    = ********["JIRA_API_TOKEN"]
GOOGLE_SHEET_ID   = os.environ["GOOGLE_SHEET_ID"]
GOOGLE_CREDS_JSON = os.environ["GOOGLE_CREDENTIALS_JSON"]

JIRA_PROJECT = "REFILE"
REFILE_TYPE  = "Re-File"
FILTER_ID    = "47966"

# Custom field IDs
FIELD_CLIENT_ID         = "customfield_18946"
FIELD_AGENCY            = "customfield_18931"
FIELD_YEAR              = "customfield_18932"
FIELD_PERIOD            = "customfield_18933"
FIELD_SEMI_MONTHLY      = "customfield_18935"
FIELD_CLIENT_SEGMENT    = "customfield_18939"
FIELD_FILING_TYPE       = "customfield_18942"
FIELD_PRIORITY_LEVEL    = "customfield_18940"
FIELD_FREQUENCY         = "customfield_18943"
FIELD_REJECTION_REASON  = "customfield_21367"
FIELD_STATE             = "customfield_21334"
FIELD_FILING_PERIOD_CMB = "customfield_20922"
FIELD_DATE_ADDED        = "customfield_19002"
FIELD_COMPLETION_DATE   = "customfield_18941"

LABEL_CREATED   = "refile-ticket-created"
LABEL_COMPLETED = "refile-completed"
STATUS_FILED    = "FILED"

COPY_FIELDS = [
    FIELD_CLIENT_ID, FIELD_AGENCY, FIELD_YEAR, FIELD_PERIOD,
    FIELD_SEMI_MONTHLY, FIELD_CLIENT_SEGMENT, FIELD_FILING_TYPE,
    FIELD_PRIORITY_LEVEL, FIELD_FREQUENCY, FIELD_REJECTION_REASON,
    FIELD_STATE, FIELD_FILING_PERIOD_CMB,
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


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

    def search_all(self, jql, fields, batch=50):
        issues, start = [], 0
        while True:
            resp = self._post("/search", {"jql": jql, "fields": fields,
                                          "startAt": start, "maxResults": batch})
            chunk = resp.get("issues", [])
            issues.extend(chunk)
            start += len(chunk)
            if start >= resp.get("total", 0) or not chunk:
                break
        return issues

    def get_issue(self, key):
        return self._get(f"/issue/{key}")

    def create_issue(self, fields):
        return self._post("/issue", {"fields": fields})

    def update_issue(self, key, fields):
        self._put(f"/issue/{key}", {"fields": fields})

    def add_link(self, key_a, key_b, link_type="Relates"):
        self._post("/issueLink", {
            "type": {"name": link_type},
            "inwardIssue":  {"key": key_a},
            "outwardIssue": {"key": key_b},
        })

    def add_comment(self, key, text):
        self._post(f"/issue/{key}/comment", {
            "body": {
                "type": "doc", "version": 1,
                "content": [{"type": "paragraph",
                              "content": [{"type": "text", "text": text}]}],
            }
        })

    @staticmethod
    def is_linked(issue, other_key):
        for lnk in issue.get("fields", {}).get("issuelinks", []):
            linked = lnk.get("inwardIssue") or lnk.get("outwardIssue")
            if linked and linked.get("key") == other_key:
                return True
        return False

    @staticmethod
    def is_done(issue):
        return (issue.get("fields", {})
                     .get("status", {})
                     .get("statusCategory", {})
                     .get("key") == "done")


def _copy_value(val):
    if val is None:
        return None
    if isinstance(val, dict):
        if "id" in val:
            return {"id": val["id"]}
        if "accountId" in val:
            return {"accountId": val["accountId"]}
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


def find_existing_refile(jira, client_id, agency, year, period):
    if not all([client_id, agency, year]):
        return None
    terms = f'summary ~ "{client_id}" AND summary ~ "{agency}" AND summary ~ "{year}"'
    if period:
        terms += f' AND summary ~ "{period}"'
    jql = f'project = {JIRA_PROJECT} AND issuetype = "{REFILE_TYPE}" AND {terms}'
    results = jira.search_all(jql, ["summary", "status", "issuelinks", "labels"], batch=25)
    for issue in results:
        s = issue["fields"].get("summary", "")
        if client_id in s and agency in s and year in s and (not period or period in s):
            return issue
    for issue in results:
        s = issue["fields"].get("summary", "")
        if client_id in s and agency in s and year in s:
            return issue
    return None


def _add_label(jira, key, current_labels, new_label):
    if new_label not in current_labels:
        jira.update_issue(key, {"labels": list(current_labels) + [new_label]})


def _str(val):
    if isinstance(val, dict):
        return val.get("value") or val.get("name") or ""
    return str(val) if val else ""


def process_dnf_tickets(jira):
    jql = (f'filter={FILTER_ID} AND '
           f'labels not in ("{LABEL_CREATED}", "{LABEL_COMPLETED}")')
    tickets = jira.search_all(jql, [
        "summary", "labels", "status", "issuelinks",
        FIELD_CLIENT_ID, FIELD_AGENCY, FIELD_YEAR, FIELD_PERIOD,
    ])
    log.info(f"Found {len(tickets)} unprocessed DNF tickets")
    results = []

    for ticket in tickets:
        key = ticket["key"]
        f   = ticket["fields"]
        client_id = f.get(FIELD_CLIENT_ID) or ""
        agency    = f.get(FIELD_AGENCY) or ""
        year      = f.get(FIELD_YEAR) or ""
        period    = _str(f.get(FIELD_PERIOD))
        labels    = list(f.get("labels") or [])

        try:
            existing = find_existing_refile(jira, client_id, agency, year, period)

            if existing is None:
                # Case A: no Re-File exists -> create one
                full = jira.get_issue(key)
                ff   = full["fields"]
                new_fields = {
                    "project":     {"key": JIRA_PROJECT},
                    "issuetype":   {"name": REFILE_TYPE},
                    "summary":     ff.get("summary", ""),
                    "description": ff.get("description"),
                }
                if ff.get("priority"):
                    new_fields["priority"] = {"name": ff["priority"]["name"]}
                if ff.get("assignee"):
                    new_fields["assignee"] = {"accountId": ff["assignee"]["accountId"]}
                if ff.get("labels"):
                    new_fields["labels"] = list(ff["labels"])
                for fid in COPY_FIELDS:
                    v = _copy_value(ff.get(fid))
                    if v is not None:
                        new_fields[fid] = v
                new_fields[FIELD_DATE_ADDED] = date.today().isoformat()
                new_fields = {k: v for k, v in new_fields.items() if v is not None}
                refile_key = jira.create_issue(new_fields)["key"]
                jira.add_link(key, refile_key)
                jira.update_issue(key, {FIELD_DATE_ADDED: date.today().isoformat()})
                _add_label(jira, key, labels, LABEL_CREATED)
                log.info(f"{key} -> Case A: created {refile_key}")
                results.append({"ticket": key, "case": "A", "refile": refile_key,
                                 "action": f"Created {refile_key}", "status": "success"})

            elif not jira.is_done(existing):
                # Case B: Re-File exists, not resolved
                refile_key = existing["key"]
                if not jira.is_linked(ticket, refile_key):
                    jira.add_link(key, refile_key)
                _add_label(jira, key, labels, LABEL_CREATED)
                log.info(f"{key} -> Case B: linked to open {refile_key}")
                results.append({"ticket": key, "case": "B", "refile": refile_key,
                                 "action": f"Linked to open {refile_key}", "status": "success"})

            else:
                # Case C: Re-File exists and is resolved
                refile_key = existing["key"]
                if not jira.is_linked(ticket, refile_key):
                    jira.add_link(key, refile_key)
                _add_label(jira, key, labels, LABEL_COMPLETED)
                jira.add_comment(key, (
                    f"A Re-File ticket ({refile_key} - "
                    f"https://rippling.atlassian.net/browse/{refile_key}) "
                    f"was previously created and has been completed."
                ))
                log.info(f"{key} -> Case C: linked to resolved {refile_key}")
                results.append({"ticket": key, "case": "C", "refile": refile_key,
                                 "action": f"Linked to resolved {refile_key}", "status": "success"})

        except Exception as e:
            log.error(f"{key} -> ERROR: {e}")
            results.append({"ticket": key, "case": "ERR", "refile": "",
                             "action": str(e), "status": "error"})

    return results


def process_filed_tickets(jira):
    """For every FILED Re-File ticket, stamp Completion Date + label on linked DNF tickets."""
    jql = f'project = {JIRA_PROJECT} AND issuetype = "{REFILE_TYPE}" AND status = "{STATUS_FILED}"'
    filed = jira.search_all(jql, ["summary", "status", "issuelinks", "resolutiondate"])
    log.info(f"Found {len(filed)} FILED Re-File tickets to check")
    results = []

    for refile in filed:
        refile_key = refile["key"]
        raw_date   = refile["fields"].get("resolutiondate") or ""
        comp_date  = raw_date[:10] if raw_date else date.today().isoformat()

        for lnk in refile["fields"].get("issuelinks", []):
            linked = lnk.get("inwardIssue") or lnk.get("outwardIssue")
            if not linked:
                continue
            dnf_key = linked["key"]
            try:
                dnf   = jira.get_issue(dnf_key)
                dlbls = list(dnf["fields"].get("labels") or [])
                if LABEL_COMPLETED not in dlbls:
                    jira.update_issue(dnf_key, {FIELD_COMPLETION_DATE: comp_date})
                    _add_label(jira, dnf_key, dlbls, LABEL_COMPLETED)
                    log.info(f"{refile_key} FILED -> {dnf_key} completion date set to {comp_date}")
                    results.append({"ticket": dnf_key, "refile": refile_key,
                                    "action": f"Completion date {comp_date} set + refile-completed",
                                    "status": "success"})
            except Exception as e:
                log.error(f"Error updating {dnf_key} from filed {refile_key}: {e}")
                results.append({"ticket": dnf_key, "refile": refile_key,
                                 "action": str(e), "status": "error"})
    return results


def log_to_sheets(dnf_results, filed_results):
    creds = Credentials.from_service_account_info(
        json.loads(GOOGLE_CREDS_JSON),
        scopes=["https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"],
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(GOOGLE_SHEET_ID)
    now = datetime.now().strftime("%Y-%m-%d %H:%M PST")

    def jira_url(key):
        return f"https://rippling.atlassian.net/browse/{key}" if key else ""

    try:
        log_ws = sh.worksheet("Daily Log")
    except gspread.WorksheetNotFound:
        log_ws = sh.add_worksheet("Daily Log", rows=5000, cols=6)
        log_ws.append_row(["Run Date", "DNF Ticket", "Case", "Action Taken",
                           "Re-File Ticket", "Status"])

    for r in dnf_results + [
        {"ticket": r["ticket"], "case": "FILED", "refile": r["refile"],
         "action": r["action"], "status": r["status"]} for r in filed_results
    ]:
        log_ws.append_row([
            now,
            jira_url(r["ticket"]),
            r.get("case", "?"),
            r["action"],
            jira_url(r.get("refile", "")),
            r["status"],
        ])

    try:
        sum_ws = sh.worksheet("Run Summary")
    except gspread.WorksheetNotFound:
        sum_ws = sh.add_worksheet("Run Summary", rows=500, cols=7)
        sum_ws.append_row(["Run Date", "Total Processed", "New Re-Files Created",
                           "Linked (Open)", "Linked (Completed)", "Filed & Closed", "Errors"])

    all_results = dnf_results + filed_results
    sum_ws.append_row([
        now,
        len(all_results),
        sum(1 for r in dnf_results if r.get("case") == "A"),
        sum(1 for r in dnf_results if r.get("case") == "B"),
        sum(1 for r in dnf_results if r.get("case") == "C"),
        len(filed_results),
        sum(1 for r in all_results if r["status"] == "error"),
    ])
    log.info("Google Sheet updated.")


def main():
    log.info("=== Re-File Queue Automation - Run Started ===")
    jira = JiraClient()
    dnf_results   = process_dnf_tickets(jira)
    filed_results = process_filed_tickets(jira)
    log_to_sheets(dnf_results, filed_results)
    a = sum(1 for r in dnf_results if r.get("case") == "A")
    b = sum(1 for r in dnf_results if r.get("case") == "B")
    c = sum(1 for r in dnf_results if r.get("case") == "C")
    e = sum(1 for r in dnf_results + filed_results if r["status"] == "error")
    log.info("=== Run Summary ===")
    log.info(f"  Total processed      : {len(dnf_results) + len(filed_results)}")
    log.info(f"  New Re-Files created : {a}")
    log.info(f"  Linked (open)        : {b}")
    log.info(f"  Linked (completed)   : {c}")
    log.info(f"  Filed & closed       : {len(filed_results)}")
    log.info(f"  Errors               : {e}")
    log.info("=== End ===")


if __name__ == "__main__":
    main()
