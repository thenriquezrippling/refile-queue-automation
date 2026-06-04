# Retry status (2026-06-04)

MCP can write repo files but gets **404** on any path under `.github/workflows/` (new or updated).

## You need to add this file once (about 2 minutes)

1. Open: https://github.com/thenriquezrippling/refile-queue-automation/new/main?filename=.github%2Fworkflows%2Ffiling_ticket_automation.yml
2. Paste contents of `filing_ticket_automation.workflow.yml` from the repo root.
3. Commit to `main`.

Then run backfill via Actions → **Filing Ticket Automation - Monthly** (four dispatch runs documented in `docs/workflow-install.md`).
