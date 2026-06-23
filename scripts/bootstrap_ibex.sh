#!/usr/bin/env bash
set -euo pipefail

IBEX_DIR="${IBEX_DIR:-third_party/ibex}"
IBEX_REF="${IBEX_REF:-master}"

if [[ -e "$IBEX_DIR" ]]; then
  echo "$IBEX_DIR already exists; refusing to overwrite." >&2
  exit 2
fi

mkdir -p "$(dirname "$IBEX_DIR")"
git clone https://github.com/lowRISC/ibex.git "$IBEX_DIR"
git -C "$IBEX_DIR" checkout "$IBEX_REF"

echo "Ibex cloned at revision: $(git -C "$IBEX_DIR" rev-parse HEAD)"
echo "Record this revision in every evidence bundle."
