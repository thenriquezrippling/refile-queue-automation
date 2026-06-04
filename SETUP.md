# One-step workflow install (use Cursor Git UI)

GitHub API tokens cannot create files under `.github/workflows/` without the **workflow** OAuth scope.

## In Cursor (now that you are logged in as GitHub)

1. Open `filing_ticket_automation.workflow.yml` in this repo.
2. Copy all contents.
3. Create new file: `.github/workflows/filing_ticket_automation.yml`
4. Paste and **Commit to main** using Cursor Source Control.

Then run **Actions → Filing Ticket Automation - Monthly** for backfill.

See `docs/cursor-automation-filing-tickets.md` for Cursor Automation + Slack setup.
