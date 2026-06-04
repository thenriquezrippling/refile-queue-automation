# Cursor Automation: Filing Ticket Slack Notifications

Slack notifications are handled by a **Cursor Automation** on **CI completed** (not a webhook in Python). The script writes a summary to logs and `$GITHUB_STEP_SUMMARY`; the automation reads the CI result and posts to Slack.

## Slack targets

| Purpose | ID | Mention in message |
|---------|-----|------------------|
| Channel | `C02UVQ7DFLZ` | Post all messages here |
| Filing team (success) | `S0A8N00FPEU` | `<!subteam^S0A8N00FPEU\|@filing_team>` |
| Tony (failure only) | `U026LRKHS1F` | `<@U026LRKHS1F>` |

In the automation UI, set **Send to Slack** to channel `C02UVQ7DFLZ`.

## Create the automation

1. Open [cursor.com/automations](https://cursor.com/automations) → **New automation**
2. **Repository:** `thenriquezrippling/refile-queue-automation`
3. **Trigger:** **CI completed** → workflow `Filing Ticket Automation - Monthly`
4. **Tools:** **Send to Slack** → channel **`C02UVQ7DFLZ`**
5. **Prompt** — paste exactly:

```text
You run when the GitHub Actions workflow "Filing Ticket Automation - Monthly" finishes.

Always post to Slack channel C02UVQ7DFLZ.

Read the workflow run logs and the GitHub Actions job summary. Determine success vs failure from the workflow conclusion and the summary Status line.

IF THE RUN SUCCEEDED:
- Post a confirmation that filing tickets were created on schedule.
- Include run date, counts of monthly / quarterly / semi-monthly tickets, up to 10 Jira links (https://rippling.atlassian.net/browse/KEY).
- Notify the filing team with exactly: <!subteam^S0A8N00FPEU|@filing_team>
- Do NOT mention <@U026LRKHS1F> on success.

IF THE RUN FAILED:
- Post an alert in C02UVQ7DFLZ (GitHub also emails the workflow owner).
- Summarize errors and link to the Actions run URL.
- Notify Tony with exactly: <@U026LRKHS1F>
- Do NOT mention <!subteam^S0A8N00FPEU|@filing_team> on failure.
```

6. Save and test via workflow_dispatch (dry_run=true first).

## Behavior summary

| Outcome | Channel | Mention |
|---------|---------|---------|
| Success | `C02UVQ7DFLZ` | `@filing_team` (`S0A8N00FPEU`) |
| Failure | `C02UVQ7DFLZ` | `@Tony` (`U026LRKHS1F`) + GitHub email |
