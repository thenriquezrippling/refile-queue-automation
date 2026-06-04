#!/usr/bin/env python3
"""TaxOps filing ticket automation. See docs/cursor-automation-filing-tickets.md."""
import argparse
import os
import sys
from datetime import date

# Full implementation: run `git pull` after merging PR cursor/filing-automation-cursor-notify-ae92
# or copy from branch prepared by Cursor Cloud Agent.

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=date.fromisoformat, default=None)
    parser.add_argument("--only", default="all")
    parser.add_argument("--exclude-states", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print("ERROR: deploy full filing_ticket_automation.py from PR branch", file=sys.stderr)
    sys.exit(2)

if __name__ == "__main__":
    main()
