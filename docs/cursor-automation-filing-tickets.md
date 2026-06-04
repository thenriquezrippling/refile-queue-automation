# Cursor Automation: Filing Ticket Slack Notifications

Slack notifications use a **Cursor Automation** on **CI completed** (not a webhook in Python).

## Slack targets

| Purpose | ID | Mention |
|---------|-----|--------|
| Channel | `C02UVQ7DFLZ` | All messages |
| Success | `S0A8N00FPEU` | `<!subteam^S0A8N00FPEU|@filing_team>` |
| Failure | `U026LRKHS1F` | `<@U026LRKHS1F>` |

## Cursor setup (one-time, ~3 min)

1. [cursor.com/automations](https://cursor.com/automations) → **New automation**
2. Repository: `thenriquezrippling/refile-queue-automation`
3. Trigger: **CI completed** → workflow **`Filing Ticket Automation - Monthly`**
4. Tool: **Send to Slack** → channel **`C02UVQ7DFLZ`**
5. Paste the prompt below and save.

### Automation prompt

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

## Workflow file location

The workflow must live at **`.github/workflows/filing_ticket_automation.yml`**. If yours is still under `.github/workflows/.github/workflows/`, move it to the correct path in the repo root.

## Quarterly ticket rules

On quarter-boundary months (Mar/Jun/Sep/Dec), new **Quarterly** tickets are created only when:

1. The parent epic has label `quarterly-filings-epic`.
2. An existing **Quarterly** child summary contains the **source** period (e.g. `Q1 2026` when creating `Q2 2026` in June).
3. The newest such ticket per filing unit is the template (not the newest Quarterly child overall).
4. Summaries without `Q{n} YYYY` are ignored (ACA-only, error tickets, etc.).
5. Creation is skipped if the new summary would not contain the target period.

## Semi-monthly epic migration

When running `only=semi-monthly` or `all`, the script **first** reparents Semi-Monthly tickets under monthly/quarterly parents to the semi-monthly Parent Epic for that state (by state code). Example: Kentucky children under `FILING-2706` → `FILING-6212`. Use `--no-migrate-semi-monthly` to skip. Honors `--dry-run`.

## Backfill May 2026 + Q2 2026

Actions → **Filing Ticket Automation - Monthly** → **Run workflow**:

| Step | as_of | only | exclude_states | dry_run |
|------|--------|------|----------------|---------|
| 1 | 2026-06-01 | monthly | CO,OH | true |
| 2 | 2026-06-01 | quarterly | CO,OH | true |
| 3 | 2026-06-01 | semi-monthly | CO,OH | true |
| 4 | 2026-06-01 | monthly | CO,OH | false |
| 5 | 2026-06-01 | quarterly | CO,OH | false |
| 6 | 2026-06-01 | semi-monthly | CO,OH | false |

After merging this fix, quarterly live runs should create far fewer tickets (only units with `Q1 2026` templates). `skip-existing` still applies for summaries already containing `Q2 2026`.

### Cleanup incorrect quarterly creates (Jun 2026)

Review/cancel tickets without `Q2 2026` in summary:

`project = FILING AND created >= "2026-06-03" AND issuetype = Quarterly AND summary !~ "Q2 2026"`

Examples: `FILING-6291`, `FILING-6281`, `FILING-6308`, `FILING-6315`.
