# Filing automation retry (2026-06-04)

## What works via Cursor / GitHub MCP

- Updates to `filing_ticket_automation.py`, docs, `SETUP.md`, etc.
- Authenticated as **thenriquezrippling**

## What is still blocked

Any commit that adds or changes files under **`.github/workflows/`** returns **404** from the GitHub API (new workflow file or edits). This is a GitHub OAuth app restriction, not a repo permission issue.

## One manual step (about 2 minutes)

Create the workflow file in the GitHub UI:

**https://github.com/thenriquezrippling/refile-queue-automation/new/main?filename=.github%2Fworkflows%2Ffiling_ticket_automation.yml**

Paste the full contents of **`filing_ticket_automation.workflow.yml`** from the repo root, then commit to `main`.

## Backfill after the workflow exists

In Actions → **Filing Ticket Automation - Monthly** → **Run workflow**, run four times:

| # | as_of | only | exclude_states | dry_run |
|---|--------|------|----------------|---------|
| 1 | 2026-06-01 | monthly | CO,OH | true |
| 2 | 2026-06-01 | quarterly | CO,OH | true |
| 3 | 2026-06-01 | monthly | CO,OH | false |
| 4 | 2026-06-01 | quarterly | CO,OH | false |

## Cursor Automation (Slack)

Configure at [cursor.com/automations](https://cursor.com/automations): trigger on **CI completed** for workflow **Filing Ticket Automation - Monthly**, channel **C02UVQ7DFLZ**. Prompt template in `docs/cursor-automation-filing-tickets.md`.

## Optional: merge filing into existing workflow

If you prefer a single workflow file, you can instead extend `.github/workflows/refile_queue.yml` with a second job (see `docs/workflow-install.md`). That file must be edited in the GitHub UI or via local `git push` with your personal credentials.
