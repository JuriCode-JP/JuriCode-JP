#!/usr/bin/env bash
# approve-gates-lock.sh -- HUMAN-ONLY privileged re-hash for the locked pass lines.
#
# Why:
#   The locked retrieval pass lines (gates/pass-lines.json) are protected by a CI
#   checksum gate (tools/scripts/verify-gates-lock.py) whose expected digest lives in
#   a CI variable OUTSIDE the AI agent's write scope. That deliberately means the agent
#   cannot update the digest. To avoid a chicken-and-egg deadlock when a HUMAN wants to
#   change a pass line legitimately, this script re-computes the digest so the human can
#   paste it into the CI variable. It must be run only by a person who controls that
#   variable; it is intentionally NOT wired into any agent/automation flow. This mirrors
#   tools/scripts/approve-eval-set.sh.
#
# It does NOT write the digest anywhere in the repo (the whole point is that the
# expected value stays out of the agent's reach). It only prints it.
#
# Usage (human, from repo root):
#   bash tools/scripts/approve-gates-lock.sh
#   # then set the printed value as the GitHub Actions variable:
#   #   GATES_LOCK_SHA256=<printed digest>
set -euo pipefail

cd "$(dirname "$0")/../.."

echo "Recomputing locked pass-lines digest..."
DIGEST="$(python tools/scripts/verify-gates-lock.py 2>/dev/null | sed -n 's/^pass-lines combined SHA256: //p')"

if [ -z "${DIGEST}" ]; then
  echo "ERROR: failed to compute digest (is gates/pass-lines.json present?)" >&2
  exit 1
fi

cat <<EOF

==================================================================
Locked pass-lines combined SHA256:

  ${DIGEST}

To (re)activate the CI pass-line lock gate, set this as the
repository variable (Settings > Secrets and variables > Actions):

  GATES_LOCK_SHA256=${DIGEST}

Only do this if you have reviewed and INTEND the current pass lines
in gates/pass-lines.json. This is the human signature for a
legitimate pass-line update.
==================================================================
EOF
