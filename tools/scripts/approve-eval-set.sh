#!/usr/bin/env bash
# approve-eval-set.sh -- HUMAN-ONLY privileged re-hash for locked eval-set golden.
#
# Why (lock plan fu-515-db-golden-lock-plan-2026-06-20.md AC-12):
#   The locked G1-local / G3-sp golden answer keys are protected by a CI checksum
#   gate (tools/scripts/verify-eval-set-checksum.py) whose expected digest lives in
#   a CI secret OUTSIDE the AI agent's write scope. That deliberately means the agent
#   cannot update the digest. To avoid a chicken-and-egg deadlock when a HUMAN wants
#   to change the golden legitimately, this script re-computes the digest so the human
#   can paste it into the CI secret. It must be run only by a person who controls the
#   CI secret; it is intentionally NOT wired into any agent/automation flow.
#
# It does NOT write the digest anywhere in the repo (the whole point is that the
# expected value stays out of the agent's reach). It only prints it.
#
# Usage (human, from repo root):
#   bash tools/scripts/approve-eval-set.sh
#   # then set the printed value as the GitHub Actions secret/variable:
#   #   EVALSET_GOLDEN_SHA256=<printed digest>
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Recomputing locked eval-set golden digest..."
DIGEST="$(python tools/scripts/verify-eval-set-checksum.py 2>/dev/null | sed -n 's/^eval-set golden combined SHA256: //p')"

if [ -z "${DIGEST}" ]; then
  echo "ERROR: failed to compute digest (are the golden files present?)" >&2
  exit 1
fi

cat <<EOF

==================================================================
Locked eval-set golden combined SHA256:

  ${DIGEST}

To (re)activate the CI checksum gate, set this as the repository
secret/variable (Settings > Secrets and variables > Actions):

  EVALSET_GOLDEN_SHA256=${DIGEST}

Only do this if you have reviewed and INTEND the current golden in
data/eval-set/tax-honbun-local/ and data/eval-set/tax-supplproviso-probe/.
This is the human L3 signature for a legitimate golden update.
==================================================================
EOF
