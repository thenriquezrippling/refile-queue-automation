# Cursor Automation: Filing Ticket Slack Notifications

Slack notifications use a **Cursor Automation** on **CI completed** (not a webhook in Python).

## Slack targets

| Purpose | ID | Mention |
|---------|-----|--------|
| Channel | `C02UVQ7DFLZ` | All messages |
| Success | `S0A8N00FPEU` | `<!subteam^S0A8N00FPEU|@filing_team>` |
| Failure | `U026LRKHS1F` | `<@U026LRKHS1F>` |

## Machine-readable run result (for Cursor)

Each workflow run writes:

1. **Job summary** — JSON under `Cursor notification payload`
2. **Logs** — `CURSOR_AUTOMATION_PAYLOAD={...}`
3. **Artifact** — `filing-automation-result.json`

## Before July 1 — required steps

1. **Merge** branch `cursor/fix-july-cursor-automation-ae92` (Python + docs).
2. **Copy workflow** from `docs/filing_ticket_automation.workflow.yml` → `.github/workflows/filing_ticket_automation.yml` (GitHub token cannot update workflows via API).
3. **Update Cursor automation prompt**: open [Filing Jira Tickets Automation](https://cursor.com/automations), replace prompt with `docs/cursor-automation-prompt.txt`, save.
4. **One test run**: Actions → dry-run `as_of=2026-07-01` → confirm Cursor posts to Slack once (do not run multiple tests in the same minute).

## Cursor setup

1. [cursor.com/automations](https://cursor.com/automations) → **Filing Jira Tickets Automation**
2. Repository: `thenriquezrippling/refile-queue-automation`
3. Trigger: **CI completed** → **`Filing Ticket Automation - Monthly`**
4. Tool: **Send to Slack** → `C02UVQ7DFLZ`
5. Prompt: `docs/cursor-automation-prompt.txt`

### Why test runs failed (Jun 3)

Back-to-back tests can fail before Slack if the agent cannot parse logs. The new JSON payload + prompt requires **exactly one Slack post per workflow completion**.

## July 2026 cron

- **08:00 UTC on the 1st** — creates ~26 June monthly + ~4 July semi-monthly; 0 quarterly
- **Concurrency** — one run at a time after workflow copy

## Quarterly / semi-monthly rules

See previous sections in git history for quarterly template rules and semi-monthly migration.
