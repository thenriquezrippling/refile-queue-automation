# /refile-queue Skill

Trigger when user types /refile-queue or asks to run the refile queue,
process DNF tickets, or check the re-file queue.

Use Jira MCP tools (prefix: mcp__046051b7-341b-4854-96b3-7e7647533bf6__)
with cloudId: 969226a5-2105-49eb-a9f7-e3852660973e

## Step 1 - Find unprocessed DNF tickets
JQL: filter=47966 AND labels not in ("refile-ticket-created", "refile-completed")
Fields: ["summary", "labels", "status", "issuelinks", "customfield_18946",
         "customfield_18931", "customfield_18932", "customfield_18933"]

## Step 2 - Decision tree per ticket
Search for existing Re-File:
  project = REFILE AND issuetype = "Re-File"
  AND summary ~ "<client>" AND summary ~ "<agency>"
  AND summary ~ "<period>" AND summary ~ "<year>"

Values from: client=customfield_18946, agency=customfield_18931,
             year=customfield_18932, period=customfield_18933

**Case A - No Re-File exists:**
1. Fetch full ticket, create Re-File copying all fields
2. Set customfield_19002 (Date Added to Re-File Queue) = today on both tickets
3. Link as Relates
4. Add refile-ticket-created label to DNF ticket (preserve existing labels)

**Case B - Re-File exists, not done:**
1. Link if not already linked
2. Add refile-ticket-created label

**Case C - Re-File exists, done:**
1. Link if not already linked
2. Add refile-completed label
3. Add comment: "A Re-File ticket (REFILE-XXXXX -
   https://rippling.atlassian.net/browse/REFILE-XXXXX)
   was previously created and has been completed."

## Step 3 - Check FILED Re-File tickets
JQL: project = REFILE AND issuetype = "Re-File" AND status = "FILED"
For each: find linked DNF tickets without refile-completed label,
update customfield_18941 (Completion Date) = resolution date,
add refile-completed label.

## Step 4 - Post summary
Report counts for each case and errors with ticket hyperlinks.

## Rules
- Always preserve existing labels when adding new ones
- Check issuelinks before creating duplicate links
- Process in batches of 25

## Field IDs
- customfield_18946: Client ID
- customfield_18931: Agency
- customfield_18932: Year
- customfield_18933: Period (Q1-Q4, monthly, SM1/SM2)
- customfield_19002: Date Added to Re-File Queue
- customfield_18941: Completion Date
