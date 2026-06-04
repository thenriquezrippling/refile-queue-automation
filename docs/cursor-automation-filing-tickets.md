# Cursor Automation: Filing Ticket Slack Notifications

Slack notifications use a **Cursor Automation** on **CI completed** (not a webhook in Python).

## Slack targets

| Purpose | ID | Mention |
|---------|-----|--------|
| Channel | `C02UVQ7DFLZ` | All messages |
| Success | `S0A8N00FPEU` | `<!subteam^S0A8N00FPEU|@filing_team>` |
| Failure | `U026LRKHS1F` | `<@U026LRKHS1F>` |

## Cursor setup (one-time)

1. [cursor.com/automations](https://cursor.com/automations) → New
2. Repo: `thenriquezrippling/refile-queue-automation`
3. Trigger: **CI completed** → `Filing Ticket Automation - Monthly`
4. Tool: **Send to Slack** → `C02UVQ7DFLZ`
5. Paste the prompt from the section below.

## Automation prompt

```text
You run when the GitHub Actions workflow "Filing Ticket Automation - Monthly" finishes.

Always post to Slack channel C02UVQ7DFLZ.

Read the workflow run logs and job summary. Determine success vs failure from workflow conclusion and summary Status line.

IF SUCCEEDED:
- Confirmation that filing tickets were created.
- Run date, monthly/quarterly/semi-monthly counts, up to 10 Jira links https://rippling.atlassian.net/browse/KEY
- Tag filing team: <!subteam^S0A8N00FPEU|@filing_team>
- Do NOT mention <@U026LRKHS1F>

IF FAILED:
- Alert with errors and Actions run URL (GitHub also emails owner).
- Tag Tony: <@U026LRKHS1F>
- Do NOT tag <!subteam^S0A8N00FPEU|@filing_team>
```

## Backfill

Workflow dispatch: as_of `2026-06-01`, exclude_states `CO,OH`, only `monthly` then `quarterly`, dry_run true then false.
