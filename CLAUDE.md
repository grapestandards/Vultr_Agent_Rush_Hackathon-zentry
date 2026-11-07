# Zentry — notes for Claude Code

Financial-crime & payment-ops platform (mule detection, reconciliation, payment follow-ups,
model tuning) for the Vultr hackathon. Full spec: `docs/DESIGN.md` — read the "Handoff" section.

## Stack
- **Web** `apps/web`: SvelteKit (Svelte 5 runes, TS, adapter-node), Tailwind v4, shadcn-svelte,
  Cytoscape.js, supabase-js + @supabase/ssr. Package manager: **pnpm**.
- **API** `services/api`: FastAPI, Python 3.12, psycopg 3, pydantic v2.
- **Worker** `services/worker`: nats-py, LightGBM, scikit-learn, NetworkX, SHAP, openai SDK → Vultr Serverless Inference.
- **Trainer** `services/trainer`: LightGBM + Optuna, boto3 uploads via pre-signed URLs.
- **Shared** `libs/zt_core`: EventBus (NATS impl), outbox ingest, FeatureEngine (same code for
  training and live scoring), the 5 rules (`rules.py`, thresholds from `scenarios.dsl_json`), money.
- **Data**: Supabase (Postgres + pgvector, Auth, Realtime) via Supabase CLI locally; NATS JetStream.
- Python is managed with **uv** (workspace at repo root).

## Layout
```
apps/web  services/{api,worker,trainer}  libs/zt_core  data/generator
supabase/{config.toml,migrations}  infra/{docker-compose.yml,coolify,vultr}  scripts/  docs/
```

## Commands
- `make up` — `supabase start` + `docker compose up` (nats, api, worker, web)
- `make down` — stop everything
- `make db-reset` — re-apply migrations from scratch
- `make seed` — synthetic data + 4 demo users (idempotent: truncates first)
- `make train-baseline` — LightGBM on a separate synthetic month (seed 7), registered as champion
- `make reset` — reseed + delete JetStream streams + restart worker (needed before re-replaying:
  txn ids are deterministic and would hit the 2h dedup window)
- `make replay` — push all of sim_feed through ingest → outbox → NATS → scorer (~4 min)
- `make demo-stream RATE=15` — live-speed replay for the demo
- `make check-m1` … `check-m6` — acceptance checks (m2–m6 need `make reset && make replay` first; m5 trains a challenger, ~2.5 min)
- Local runtime is Colima (`colima start`); Supabase CLI via `npx supabase`.

## Rules (non-negotiable)
- Synthetic data only. Never claim integration with AMLO (ปปง.) or real banks.
- Never commit secrets — only `.env.example`. `.env` is gitignored.
- Never create, resize or delete paid Vultr resources without asking the user first.
- Money is integer **satang** in `BIGINT` columns named `*_satang`. Never floats.
  Convert only at the UI edge (`zt_core.money`).
- Every agent claim must cite real transaction ids; validate ids exist before display.
- Investigator (`services/worker/src/zt_worker/agent/`): read tools run in READ ONLY transactions;
  `propose_action` is the only writer; `validator.py` rejects reports citing ids that don't exist or
  weren't returned by a tool. Runs as `llm` (Vultr Inference, needs VULTR_INFERENCE_API_KEY + LLM_MODEL)
  or `offline` (deterministic planner, same tools) when no key is set.
- Agents: read-only tools except `propose_action`. Human approval for freezes, STRs,
  outbound messages and model promotion. Log prompt + output to `audit_log`.
- Training (`services/trainer/src/zt_trainer/job.py`): runs locally (worker subprocess) unless
  `TRAIN_RUNNER=vultr` + `VULTR_API_KEY`; then the worker creates a `zentry-train` VM (paid — ask
  the user first), which gets only a short-lived job token. Watchdog deletes those VMs after 30 min.
- PII: browsers can only select masked names (`customers.display_en/display_th`, "Somying Sd****";
  merchants keep business names). APIs and agents return the masked columns too. Full names only via
  `POST /pii/reveal` with a reason (analyst / compliance_manager / collections), audited as `pii:reveal`.
- Ground-truth columns prefixed `gt_` exist for evaluation only — never use them as model features
  or show them in analyst UI.
- Work milestone by milestone (M1→M7); run acceptance checks and stop for review after each.

## Roles
`app_metadata.role` in the Supabase JWT, one of `analyst`, `finance_ops`, `collections`,
`compliance_manager` (+ `admin`). RLS uses `public.app_role()`.
Demo users: `<role>@demo.zentry.local`, password from `DEMO_PASSWORD` in `.env`.

## UI style
Soft lavender gradient (`#ECF0F8`→`#9CA7DE`), glassy white panels `rounded-3xl`, white cards with
soft shadow, thin left icon rail, dark pill buttons/chips (`#05060B`), muted text `#4D506E`,
accent `#6C72AC`, risk/alert orange `#EC630D`. See "UI style guide" in DESIGN.md. No dark mode.
