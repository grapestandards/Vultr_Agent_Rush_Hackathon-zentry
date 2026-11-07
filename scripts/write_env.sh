#!/usr/bin/env bash
# Create .env from .env.example and fill in the local Supabase keys. Keeps existing values.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
eval "$(npx supabase status -o env 2>/dev/null | grep -E '^(ANON_KEY|SERVICE_ROLE_KEY)=')"
set_var() { # only fill empty values
  if grep -qE "^$1=$" .env; then sed -i.bak "s|^$1=$|$1=$2|" .env && rm -f .env.bak; fi
}
set_var PUBLIC_SUPABASE_ANON_KEY "$ANON_KEY"
set_var SUPABASE_SERVICE_ROLE_KEY "$SERVICE_ROLE_KEY"
if grep -q '^DEMO_PASSWORD=change-me-demo-password$' .env; then
  sed -i.bak "s|^DEMO_PASSWORD=.*|DEMO_PASSWORD=$(openssl rand -base64 12 | tr -d '/+=')|" .env && rm -f .env.bak
fi
echo ".env ready"
