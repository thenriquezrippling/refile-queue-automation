# Install filing workflow manually

GitHub blocks the Cursor MCP token from **creating** new files under `.github/workflows/` (404). It may only **update** existing workflow files in some cases.

## Steps

1. In GitHub: **Add file** → paste contents of `filing_ticket_automation.workflow.yml` as `.github/workflows/filing_ticket_automation.yml`
2. Or run locally: `./install_filing_workflow.sh` and `git push`
3. Configure Cursor Automation per `docs/cursor-automation-filing-tickets.md`

## Backfill (May 2026 + Q2 2026)

Run workflow dispatch four times with `as_of=2026-06-01`, `exclude_states=CO,OH`:

| Step | only | dry_run |
|------|------|---------|
| 1 | monthly | true |
| 2 | quarterly | true |
| 3 | monthly | false |
| 4 | quarterly | false |
