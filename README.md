# Zentry

Financial-crime & payment-ops platform for Thai e-wallets: flags mule accounts, investigates with
an AI agent, reconciles settlements, chases payment follow-ups, and lets the team retrain its
detection model on demand — all running on Vultr. **All data is synthetic.**

Design: [`docs/DESIGN.md`](docs/DESIGN.md)

## Local setup

Requires Docker (Colima works), Node 22 + pnpm, and [uv](https://docs.astral.sh/uv/).

```bash
make up        # Supabase (CLI) + NATS, API, worker, web
make seed      # 10k customers, ~200k transactions, 5 mule rings, settlement files with breaks
make check-m1  # acceptance checks
```

- Web: http://localhost:3000 — demo logins `<role>@demo.zentry.local` for `analyst`, `finance_ops`,
  `collections`, `compliance_manager`; the password is `DEMO_PASSWORD` in `.env`.
- API: http://localhost:8000/healthz · Supabase Studio: http://127.0.0.1:55423 · Mailpit: http://127.0.0.1:55424

## License

MIT
