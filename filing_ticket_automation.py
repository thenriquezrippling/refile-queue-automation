#!/usr/bin/env python3
"""TaxOps filing ticket automation — see docs/cursor-automation-filing-tickets.md"""
import argparse
import json
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
RESULT_PATH = _env("FILING_AUTOMATION_RESULT_PATH", "filing-automation-result.json")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ... truncated for push - WILL FAIL if truncated
