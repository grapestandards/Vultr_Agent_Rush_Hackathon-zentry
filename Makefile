SHELL := /bin/bash
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose) -f infra/docker-compose.yml
RUN := set -a && source .env && set +a && uv run

.PHONY: up down env db-reset seed check-m1 test logs web-dev

up: ## start Supabase + nats/api/worker/web
	npx supabase start
	./scripts/write_env.sh
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down
	npx supabase stop

env:
	./scripts/write_env.sh

db-reset: ## re-apply all migrations (wipes data)
	npx supabase db reset

seed: ## synthetic data + demo users
	$(RUN) python -m zt_generator

check-m1:
	$(RUN) python scripts/check_m1.py

test:
	uv run pytest libs data services -q

logs:
	$(COMPOSE) logs -f --tail=100

web-dev: ## SvelteKit dev server with HMR on :5173
	cd apps/web && pnpm dev
