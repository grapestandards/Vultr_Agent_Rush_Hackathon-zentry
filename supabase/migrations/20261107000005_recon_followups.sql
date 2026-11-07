-- M6 reconciliation + payment follow-ups.

-- ------------------------------------------------------------ reconciliation
alter table public.recon_runs
  add column requested_by  uuid references auth.users(id),
  add column stats_json    jsonb not null default '{}',   -- counts per match rule / break type, match rate
  add column error         text,
  add column finished_at   timestamptz;
alter table public.recon_runs drop constraint recon_runs_status_check;
alter table public.recon_runs add constraint recon_runs_status_check
  check (status in ('queued', 'running', 'review', 'done', 'failed'));

-- recon_matches holds both matches (break_type null) and breaks. Breaks carry the agent's
-- explanation and a drafted journal entry that Finance Ops confirms or dismisses.
alter table public.recon_matches
  add column diff_satang     bigint,                      -- settlement minus ledger (or the unmatched amount)
  add column explanation     text,
  add column journal_json    jsonb,                       -- {"memo", "lines": [{"account", "debit_satang", "credit_satang"}]}
  add column follow_up_json  jsonb,                       -- suggested follow-up when the break is money owed to us
  add column resolution      text check (resolution in ('confirmed', 'dismissed', 'auto_cleared')),
  add column resolved_by     uuid references auth.users(id),
  add column resolved_at     timestamptz,
  add column note            text;
create index on public.recon_matches (run_id) where break_type is not null;
create index on public.recon_matches (settlement_id);

-- ---------------------------------------------------------------- follow-ups
alter table public.follow_ups
  add column kind          text not null default 'recon' check (kind in ('recon', 'victim_refund', 'chargeback')),
  add column title         text not null default '',
  add column source_ref    text,                          -- settlement / transaction / victim account it came from
  add column contact       text,                          -- synthetic address in the demo inbox
  add column level         int not null default 0,        -- reminder ladder: 1 friendly, 2 firm, 3 escalation
  add column created_at    timestamptz not null default now(),
  add column updated_at    timestamptz not null default now(),
  add column closed_reason text;
create unique index follow_ups_one_open_per_source on public.follow_ups (kind, source_ref) where stage <> 'closed';

alter table public.messages
  add column direction   text not null default 'out' check (direction in ('out', 'in')),
  add column level       int,
  add column status      text not null default 'draft' check (status in ('draft', 'approved', 'sent', 'rejected', 'received')),
  add column subject     text,
  add column author      text,                            -- agent:followup:<offline|model> or user:<id>
  add column created_at  timestamptz not null default now();
create index on public.messages (follow_up_id, created_at);

drop policy staff_read on public.messages;
create policy staff_read on public.messages for select to authenticated using (public.has_role('collections', 'finance_ops', 'compliance_manager'));

alter publication supabase_realtime add table public.recon_runs, public.messages;
