-- Zentry core schema. Money is always integer satang (BIGINT, *_satang).
-- Columns prefixed gt_ are synthetic ground truth for evaluation only.

create extension if not exists vector with schema extensions;

-- ---------------------------------------------------------------- roles
create or replace function public.app_role() returns text
language sql stable
as $$
  select coalesce(auth.jwt() -> 'app_metadata' ->> 'role', '')
$$;

create or replace function public.has_role(variadic roles text[]) returns boolean
language sql stable
as $$
  select public.app_role() = any(roles) or public.app_role() = 'admin'
$$;

-- ---------------------------------------------------- customers & accounts
create table public.customers (
  id          text primary key,
  name_th     text not null,
  name_en     text not null,
  kyc_level   smallint not null check (kyc_level between 0 and 3),
  risk_score  smallint not null default 0 check (risk_score between 0 and 100),
  created_at  timestamptz not null default now()
);

create table public.accounts (
  id           text primary key,
  customer_id  text not null references public.customers(id),
  type         text not null check (type in ('wallet', 'bank', 'merchant')),
  bank_code    text,
  opened_at    timestamptz not null,
  status       text not null default 'active' check (status in ('active', 'frozen', 'closed')),
  gt_role      text check (gt_role in ('victim', 'mule')),
  gt_ring      smallint,
  gt_layer     smallint check (gt_layer between 1 and 3)
);
create index on public.accounts (customer_id);
create index on public.accounts (gt_ring) where gt_ring is not null;

-- ----------------------------------------------------------- transactions
create table public.transactions (
  id             text primary key,
  from_account   text not null references public.accounts(id),
  to_account     text not null references public.accounts(id),
  amount_satang  bigint not null check (amount_satang > 0),
  channel        text not null check (channel in ('promptpay', 'transfer', 'qr')),
  ref_no         text not null,
  ts             timestamptz not null,
  device_id      text,
  gt_is_fraud    boolean not null default false,
  gt_ring        smallint
);
create index on public.transactions (from_account, ts);
create index on public.transactions (to_account, ts);
create index on public.transactions (ts);
create index on public.transactions (ref_no);

create table public.settlements (
  id                 text primary key,
  source             text not null check (source in ('gateway', 'bank')),
  ref_no             text,
  counterparty_name  text,
  amount_satang      bigint not null,
  fee_satang         bigint not null default 0 check (fee_satang >= 0),
  value_date         date not null,
  raw_file_key       text not null,
  gt_break_type      text check (gt_break_type in ('timing', 'fee', 'amount_mismatch', 'duplicate', 'missing_in_bank', 'missing_in_ledger'))
);
create index on public.settlements (ref_no);
create index on public.settlements (value_date);

-- -------------------------------------------------------------- detection
create table public.scenarios (
  id          uuid primary key default gen_random_uuid(),
  name        text not null,
  dsl_json    jsonb not null,
  version     int not null default 1,
  status      text not null default 'draft' check (status in ('draft', 'active', 'retired')),
  created_by  uuid references auth.users(id),
  created_at  timestamptz not null default now(),
  unique (name, version)
);

create table public.model_versions (
  id            uuid primary key default gen_random_uuid(),
  kind          text not null check (kind in ('lgbm', 'prompt', 'scenario')),
  params_json   jsonb not null default '{}',
  metrics_json  jsonb not null default '{}',
  artifact_key  text,
  stage         text not null default 'challenger' check (stage in ('challenger', 'shadow', 'champion', 'retired')),
  created_at    timestamptz not null default now()
);

create table public.alerts (
  id                 uuid primary key default gen_random_uuid(),
  transaction_id     text references public.transactions(id),
  account_id         text not null references public.accounts(id),
  scenario_id        uuid references public.scenarios(id),
  model_version      uuid references public.model_versions(id),
  score              smallint not null check (score between 0 and 100),
  top_features_json  jsonb not null default '[]',
  reason             text,
  priority           smallint not null default 3 check (priority between 1 and 5),
  created_at         timestamptz not null default now()
);
create index on public.alerts (account_id);
create index on public.alerts (created_at desc);

-- ------------------------------------------------------------------ cases
create table public.cases (
  id           uuid primary key default gen_random_uuid(),
  type         text not null check (type in ('mule', 'recon_break', 'follow_up')),
  status       text not null default 'open' check (status in ('open', 'in_review', 'escalated', 'closed')),
  assignee     uuid references auth.users(id),
  disposition  text check (disposition in ('fraud', 'false_positive', 'resolved', 'inconclusive')),
  ai_summary   text,
  str_draft    text,
  embedding    extensions.vector,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create table public.case_links (
  id              bigint generated always as identity primary key,
  case_id         uuid not null references public.cases(id) on delete cascade,
  alert_id        uuid references public.alerts(id),
  account_id      text references public.accounts(id),
  transaction_id  text references public.transactions(id),
  check (num_nonnulls(alert_id, account_id, transaction_id) = 1)
);
create index on public.case_links (case_id);

-- --------------------------------------------------------- reconciliation
create table public.recon_runs (
  id             uuid primary key default gen_random_uuid(),
  period         daterange not null,
  matched_count  int not null default 0,
  break_count    int not null default 0,
  status         text not null default 'running' check (status in ('running', 'review', 'done', 'failed')),
  created_at     timestamptz not null default now()
);

create table public.recon_matches (
  id              bigint generated always as identity primary key,
  run_id          uuid not null references public.recon_runs(id) on delete cascade,
  transaction_id  text references public.transactions(id),
  settlement_id   text references public.settlements(id),
  match_rule      text check (match_rule in ('ref_exact', 'amount_time_fuzzy', 'many_to_one')),
  confidence      real check (confidence between 0 and 1),
  break_type      text check (break_type in ('timing', 'fee', 'amount_mismatch', 'duplicate', 'missing_in_bank', 'missing_in_ledger'))
);
create index on public.recon_matches (run_id);

-- ------------------------------------------------------------- follow-ups
create table public.follow_ups (
  id                 uuid primary key default gen_random_uuid(),
  case_id            uuid references public.cases(id),
  counterparty       text not null,
  amount_due_satang  bigint not null check (amount_due_satang >= 0),
  due_date           date,
  stage              text not null default 'new' check (stage in ('new', 'reminded', 'promised', 'escalated', 'closed')),
  promise_date       date,
  next_action_at     timestamptz
);
create index on public.follow_ups (next_action_at) where stage <> 'closed';

create table public.messages (
  id            uuid primary key default gen_random_uuid(),
  follow_up_id  uuid not null references public.follow_ups(id) on delete cascade,
  channel       text not null check (channel in ('email', 'sms', 'line')),
  draft         text not null,
  approved_by   uuid references auth.users(id),
  sent_at       timestamptz
);

-- ---------------------------------------------------------- tuning runs
create table public.train_runs (
  id                uuid primary key default gen_random_uuid(),
  requested_by      uuid references auth.users(id),
  params_json       jsonb not null default '{}',
  status            text not null default 'queued' check (status in ('queued', 'provisioning', 'running', 'succeeded', 'failed', 'cancelled')),
  vultr_instance_id text,
  model_version_id  uuid references public.model_versions(id),
  log_tail          text,
  created_at        timestamptz not null default now(),
  finished_at       timestamptz
);

-- ------------------------------------------------------- audit & outbox
create table public.audit_log (
  id           bigint generated always as identity primary key,
  actor        text not null,                      -- 'user:<uuid>' or 'agent:<name>'
  action       text not null,
  object_ref   text,
  before_json  jsonb,
  after_json   jsonb,
  ts           timestamptz not null default now()
);
create index on public.audit_log (ts desc);

create table public.outbox (
  id            bigint generated always as identity primary key,
  subject       text not null,
  msg_id        text not null unique,              -- becomes Nats-Msg-Id
  payload       jsonb not null,
  created_at    timestamptz not null default now(),
  published_at  timestamptz
);
create index on public.outbox (id) where published_at is null;

-- -------------------------------------------------------------------- RLS
-- Browser clients only read. Every write goes through the API/worker with the
-- service role (which bypasses RLS) so it can be validated and audited.
do $$
declare t text;
begin
  foreach t in array array[
    'customers','accounts','transactions','settlements','scenarios','model_versions',
    'alerts','cases','case_links','recon_runs','recon_matches','follow_ups','messages',
    'train_runs','audit_log','outbox'
  ] loop
    execute format('alter table public.%I enable row level security', t);
  end loop;
end $$;

create policy staff_read on public.customers     for select to authenticated using (public.has_role('analyst','compliance_manager','finance_ops','collections'));
create policy staff_read on public.accounts      for select to authenticated using (public.has_role('analyst','compliance_manager','finance_ops','collections'));
create policy staff_read on public.transactions  for select to authenticated using (public.has_role('analyst','compliance_manager','finance_ops','collections'));
create policy staff_read on public.scenarios     for select to authenticated using (public.has_role('analyst','compliance_manager'));
create policy staff_read on public.alerts        for select to authenticated using (public.has_role('analyst','compliance_manager'));
create policy staff_read on public.model_versions for select to authenticated using (public.has_role('analyst','compliance_manager'));
create policy staff_read on public.train_runs    for select to authenticated using (public.has_role('compliance_manager'));
create policy staff_read on public.settlements   for select to authenticated using (public.has_role('finance_ops','compliance_manager'));
create policy staff_read on public.recon_runs    for select to authenticated using (public.has_role('finance_ops','compliance_manager'));
create policy staff_read on public.recon_matches for select to authenticated using (public.has_role('finance_ops','compliance_manager'));
create policy staff_read on public.follow_ups    for select to authenticated using (public.has_role('collections','finance_ops','compliance_manager'));
create policy staff_read on public.messages      for select to authenticated using (public.has_role('collections','compliance_manager'));
create policy staff_read on public.audit_log     for select to authenticated using (public.has_role('compliance_manager'));

-- Cases are shared by every module; each role sees the case types it works on.
create policy staff_read on public.cases for select to authenticated using (
  public.has_role('analyst','compliance_manager')
  or (type = 'recon_break' and public.app_role() = 'finance_ops')
  or (type = 'follow_up'   and public.app_role() = 'collections')
);
create policy staff_read on public.case_links for select to authenticated using (
  exists (select 1 from public.cases c where c.id = case_id)
);
-- outbox: no policies → invisible to browsers.

-- Hide ground-truth columns from browser roles (column grants replace table grants).
revoke select on public.accounts, public.transactions, public.settlements from anon, authenticated;
grant select (id, customer_id, type, bank_code, opened_at, status) on public.accounts to authenticated;
grant select (id, from_account, to_account, amount_satang, channel, ref_no, ts, device_id) on public.transactions to authenticated;
grant select (id, source, ref_no, counterparty_name, amount_satang, fee_satang, value_date, raw_file_key) on public.settlements to authenticated;

-- --------------------------------------------------------------- realtime
alter publication supabase_realtime add table public.alerts, public.cases, public.train_runs, public.follow_ups;
