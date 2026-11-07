SHELL := /bin/bash
COMPOSE := $(shell docker compose version >/dev/null 2>&1 && echo "docker compose" || echo docker-compose) -f infra/docker-compose.yml
RUN := set -a && source .env && set +a && uv run

.PHONY: up down env db-reset seed check-m1 check-m2 check-m3 check-m4 check-m5 train-baseline reset replay demo-stream test logs web-dev

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

check-m3:
	$(RUN) python scripts/check_m3.py

check-m4:
	$(RUN) python scripts/check_m4.py

check-m5:
	$(RUN) python scripts/check_m5.py

check-m2:
	$(RUN) python scripts/check_m2.py

train-baseline: ## LightGBM baseline on a separate synthetic month, registered as champion
	$(RUN) python -m zt_trainer.baseline --register

reset: ## fresh demo state: reseed, clear streams, restart the worker (models stay registered)
	$(COMPOSE) stop worker
	$(RUN) python -m zt_generator
	$(RUN) python scripts/reset_streams.py
	$(COMPOSE) up -d worker

replay: ## push the whole sim feed through ingest → outbox → NATS → scoring, as fast as possible
	$(RUN) python -m zt_worker.simulator --rate 0

demo-stream: ## live demo speed (RATE tx/s)
	$(RUN) python -m zt_worker.simulator --rate $${RATE:-15}

test:
	uv run pytest libs data services -q

logs:
	$(COMPOSE) logs -f --tail=100

web-dev: ## SvelteKit dev server with HMR on :5173
	cd apps/web && pnpm dev
