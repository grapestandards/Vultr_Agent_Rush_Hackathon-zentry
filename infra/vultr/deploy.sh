#!/usr/bin/env bash
# Deploy Zentry to one Vultr VM (Docker preinstalled by cloud-init): Supabase CLI stack + nats/api/worker/web
# + Caddy (HTTPS). Run from the repo root on your machine:  infra/vultr/deploy.sh <ip> [app-host] [sb-host]
# Hosts default to sslip.io names for the IP. Re-running syncs the code and rebuilds; data is kept.
set -euo pipefail
IP=$1
DASHED=${IP//./-}
APP_HOST=${2:-zentry.$DASHED.sslip.io}
SB_HOST=${3:-sb.$DASHED.sslip.io}
SSH_KEY=${SSH_KEY:-$HOME/.ssh/zentry_deploy}
SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=accept-new root@$IP"
cd "$(dirname "$0")/../.."

rsync -az --delete -e "ssh -i $SSH_KEY" \
  --exclude node_modules --exclude .venv --exclude .svelte-kit --exclude build --exclude .git \
  --exclude .env --exclude supabase/signing_keys.json --exclude 'models/runs' --exclude 'models/raw' --exclude 'supabase/.temp' \
  ./ root@"$IP":/opt/zentry/

# Server .env: local values minus the Supabase keys (regenerated there with a fresh signing key) and the
# Vultr account key (the VM never creates other VMs; training runs on the VM itself).
tmp=$(mktemp)
grep -vE '^(PUBLIC_SUPABASE_ANON_KEY|SUPABASE_SERVICE_ROLE_KEY|VULTR_API_KEY|TRAIN_RUNNER|APP_HOST|SB_HOST)=' .env > "$tmp"
printf 'PUBLIC_SUPABASE_ANON_KEY=\nSUPABASE_SERVICE_ROLE_KEY=\nVULTR_API_KEY=\nTRAIN_RUNNER=local\nAPP_HOST=%s\nSB_HOST=%s\n' \
  "$APP_HOST" "$SB_HOST" >> "$tmp"
$SSH 'test -f /opt/zentry/.env' || scp -q -i "$SSH_KEY" "$tmp" root@"$IP":/opt/zentry/.env
rm -f "$tmp"

$SSH APP_HOST="$APP_HOST" bash -s <<'EOF'
set -euo pipefail
cd /opt/zentry
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs; }
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH=$HOME/.local/bin:$PATH
# Asymmetric JWT signing key (the CLI's default HS256 secret is public knowledge)
[ -f supabase/signing_keys.json ] || npx -y supabase gen signing-key --algorithm ES256 2>/dev/null \
  | python3 -c 'import json,sys; k=json.load(sys.stdin); json.dump(k if isinstance(k, list) else [k], sys.stdout)' \
  > supabase/signing_keys.json
sed -i 's|^# signing_keys_path = .*|signing_keys_path = "./signing_keys.json"|' supabase/config.toml
sed -i "s|^site_url = .*|site_url = \"https://$APP_HOST\"|" supabase/config.toml
sed -i 's|^enable_signup = true|enable_signup = false|' supabase/config.toml
npx -y supabase start
./scripts/write_env.sh
uv sync -q --all-packages
docker compose -f infra/docker-compose.yml -f infra/docker-compose.prod.yml --env-file .env up -d --build
EOF
echo "https://$APP_HOST"
