#!/usr/bin/env bash
set -euo pipefail
# Copies workflow template to the path GitHub Actions requires.
SRC="${1:-filing_ticket_automation.workflow.yml}"
DEST=".github/workflows/filing_ticket_automation.yml"
if [[ ! -f "$SRC" ]]; then echo "Missing $SRC" >&2; exit 1; fi
mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
echo "Wrote $DEST — commit and push in Cursor Source Control."
