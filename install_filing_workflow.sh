#!/usr/bin/env bash
# Run once locally or in CI to place the workflow where GitHub Actions expects it.
set -euo pipefail
SRC=".github/workflows/.github/workflows/filing_ticket_automation.yml"
DEST=".github/workflows/filing_ticket_automation.yml"
if [[ ! -f "$SRC" ]]; then
  echo "Source workflow not found: $SRC" >&2
  exit 1
fi
mkdir -p "$(dirname "$DEST")"
cp "$SRC" "$DEST"
echo "Installed $DEST — commit and push this file."
