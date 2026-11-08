# Zentry

**AI that follows the money.** Zentry is a financial-crime and payment-ops desk for Thai e-wallets.
It scores every transfer live, AI agents investigate mule rings and cite real transaction ids,
it reconciles settlement files, and it drafts payment follow-ups in Thai and English. People
approve every freeze, report, outbound message and model change.

Built for the Vultr *Agent Rush* hackathon, challenge "Powering the Future of Work".
**All data is synthetic.** Zentry is not connected to any bank or regulator.

- Live app: https://zentry.45-76-180-150.sslip.io
- Demo access: four role accounts (`analyst`, `finance_ops`, `collections`, `compliance_manager`
  `@demo.zentry.local`). The password is in the lablab submission.

## What it does

| Area | Who | What happens |
| --- | --- | --- |
| Alert Queue | Fraud analyst | Live risk scores from five rules plus a gradient-boosted model, each alert with its reasons |
| Cases | Fraud analyst | Graph analysis groups a mule ring into one case; an AI agent writes a report where every claim cites a transaction id that a validator checked |
| Graph Explorer | Fraud analyst | Money-flow network with time replay and "trace from victim" |
| Decisions | Fraud analyst | Approve a freeze and a suspicious-transaction report; written to the audit log and kept as a training label |
| Reconciliation | Finance ops | Three-pass matching of ledger vs bank and gateway files; the agent explains each break and drafts a balanced journal entry |
| Follow-ups | Collections | The agent drafts reminders and refund notices in Thai and English; nothing is sent until a person approves |
| Model Tuning | Compliance manager | Train a challenger on analyst decisions, compare it with the champion on a held-out month, then promote or roll back |

Each role sees only its own sections. Names are masked everywhere (`Somying Sd****`); a full
name needs a stated reason and is audited.

## How it uses Vultr

| Vultr service | Used for |
| --- | --- |
| **Cloud Compute** (Singapore) | Runs the whole stack: web app, API, event stream, scorer, AI agents, Postgres |
| **Serverless Inference** | The three AI agents (investigator, reconciliation, follow-up) call an OpenAI-compatible endpoint with tool calling |
| **Firewall** | Only 80/443 are public; SSH is limited to one admin address |
| **Vultr API** (optional) | With `TRAIN_RUNNER=vultr`, each training run gets its own short-lived VM tagged `zentry-train`; a watchdog deletes any such VM after 30 minutes |

Terraform for a larger multi-VM layout (VPC, app/worker/data VMs, firewall groups) is in
[`infra/vultr/terraform`](infra/vultr/terraform).

## Architecture

```
Users ──HTTPS──▶ Caddy ──▶ SvelteKit web ──▶ FastAPI (role checks)
                    │                              │
                    └──▶ Supabase Auth / REST ──▶ Postgres (row-level security, audit log)
                                                   ▲
Wallet events ──▶ outbox ──▶ NATS JetStream ──▶ worker: scorer · 3 AI agents · trainer
                                                   │
                                                   └──▶ Vultr Serverless Inference
```

- **Web**: SvelteKit (Svelte 5), Tailwind, Cytoscape.js
- **API**: FastAPI, psycopg 3, pydantic v2
- **Worker**: NATS consumers for scoring, investigation, reconciliation, follow-ups and training
- **Data**: Supabase (Postgres, Auth, Realtime), NATS JetStream
- Money is stored as integer satang (`*_satang BIGINT`), never floats

## Security

- Only HTTPS is exposed; the database, NATS, API and Supabase internals bind to localhost
- The production Supabase uses its own signing key, and public sign-up is off
- Roles are enforced twice: in the API and by row-level security in Postgres
- AI agents read inside read-only transactions; `propose_action` is their only write, and a
  person approves every action
- Training jobs get a short-lived job token, never database credentials
- Prompts, outputs, decisions and PII reveals are written to `audit_log`

## Run it locally

Needs Docker (Colima works), Node 22 + pnpm, and [uv](https://docs.astral.sh/uv/).

```bash
make up               # Supabase (CLI) + NATS, API, worker, web
make seed             # 10k customers, ~200k transactions, mule rings, settlement files with breaks
make train-baseline   # baseline model (champion)
make replay           # stream the transactions through scoring and investigation (~4 min)
```

Then open http://localhost:3000. Demo logins are `<role>@demo.zentry.local`, and the password
is `DEMO_PASSWORD` in `.env` (generated on first `make up`).

Without `VULTR_INFERENCE_API_KEY` the agents run in an offline mode with a deterministic planner
and the same tools. Acceptance checks: `make check-m1` … `make check-m6`.

Deploy to a single VM: `infra/vultr/deploy.sh <ip>` (Caddy + Supabase + Docker Compose).

## Repository layout

```
apps/web            SvelteKit UI
services/api        FastAPI
services/worker     scoring, AI agents, reconciliation, follow-ups, training jobs
services/trainer    model training job
libs/zt_core        shared: event bus, features, rules, money
data/generator      synthetic data
supabase/           config and migrations (schema, RLS)
infra/              Docker Compose, Caddy, Vultr deploy script and Terraform
scripts/            acceptance checks, UI smoke test, video recorders
docs/               design notes
```

## License

MIT
