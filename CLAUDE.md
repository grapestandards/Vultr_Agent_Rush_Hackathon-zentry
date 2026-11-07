# Zentry — notes for Claude Code

Financial-crime & payment-ops platform (mule detection, reconciliation, payment follow-ups,
model tuning) for the Vultr hackathon. Full spec: `docs/DESIGN.md` — read the "Handoff" section.

## Stack
- **Web** `apps/web`: SvelteKit (Svelte 5 runes, TS, adapter-node), Tailwind v4, shadcn-svelte,
  Cytoscape.js, supabase-js + @supabase/ssr. Package manager: **pnpm**.
- **API** `services/api`: FastAPI, Python 3.12, psycopg 3, pydantic v2.
- **Worker** `services/worker`: nats-py, LightGBM, scikit-learn, NetworkX, SHAP, openai SDK → Vultr Serverless Inference.
- **Trainer** `services/trainer`: LightGBM + Optuna, boto3 uploads via pre-signed URLs.
- **Shared** `libs/zt_core`: EventBus, money utils, scenario DSL, features.
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
- `make check-m1` — M1 acceptance checks
- Local runtime is Colima (`colima start`); Supabase CLI via `npx supabase`.

## Rules (non-negotiable)
- Synthetic data only. Never claim integration with AMLO (ปปง.) or real banks.
- Never commit secrets — only `.env.example`. `.env` is gitignored.
- Never create, resize or delete paid Vultr resources without asking the user first.
- Money is integer **satang** in `BIGINT` columns named `*_satang`. Never floats.
  Convert only at the UI edge (`zt_core.money`).
- Every agent claim must cite real transaction ids; validate ids exist before display.
- Agents: read-only tools except `propose_action`. Human approval for freezes, STRs,
  outbound messages and model promotion. Log prompt + output to `audit_log`.
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
