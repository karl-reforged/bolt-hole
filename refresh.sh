#!/bin/bash
# Refresh the Bolt Hole pipeline safely: only rebuild shortlist when source coverage is healthy.
set -euo pipefail
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Missing virtualenv Python at $PY" >&2
  exit 1
fi
exec "$PY" run_guarded_domain_refresh.py   --min-domain "${BOLT_MIN_DOMAIN:-240}"   --min-passed "${BOLT_MIN_PASSED:-110}"   --min-domain-desc "${BOLT_MIN_DOMAIN_DESC:-90}"   --cooldown "${BOLT_RETRY_COOLDOWN:-1800}"   --max-attempts "${BOLT_MAX_ATTEMPTS:-3}"   --shortlist
