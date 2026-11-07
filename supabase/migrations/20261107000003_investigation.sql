-- M3 investigation: richer cases, agent proposals (the agent's only write path), synthetic watchlist.

create extension if not exists pg_trgm with schema extensions;

alter table public.cases
  add column title            text,
  add column risk_level       text check (risk_level in ('low', 'medium', 'high', 'critical')),
  add column agent_report     jsonb,          -- structured output of the last investigation
  add column investigated_at  timestamptz,
  add column str_approved_by  uuid references auth.users(id),
  add column str_approved_at  timestamptz;

-- The investigator never changes data directly: it can only propose. A human accepts or rejects.
create table public.case_proposals (
  id           uuid primary key default gen_random_uuid(),
  case_id      uuid not null references public.cases(id) on delete cascade,
  action       text not null check (action in ('close', 'escalate', 'recommend_freeze', 'file_str')),
  rationale    text not null,
  evidence     jsonb not null default '[]',   -- transaction / account ids, validated before insert
  status       text not null default 'pending' check (status in ('pending', 'accepted', 'rejected')),
  decided_by   uuid references auth.users(id),
  decided_at   timestamptz,
  created_at   timestamptz not null default now()
);
create index on public.case_proposals (case_id);

-- Synthetic sanctions / internal watchlist for name screening. Not a real list.
create table public.watchlist (
  id       bigint generated always as identity primary key,
  name_en  text not null,
  name_th  text,
  list     text not null,          -- e.g. 'internal_mule_blacklist', 'synthetic_sanctions'
  reason   text not null
);
create index watchlist_name_trgm on public.watchlist using gin (name_en extensions.gin_trgm_ops);

alter table public.case_proposals enable row level security;
alter table public.watchlist enable row level security;
create policy staff_read on public.case_proposals for select to authenticated using (public.has_role('analyst', 'compliance_manager'));
create policy staff_read on public.watchlist for select to authenticated using (public.has_role('analyst', 'compliance_manager'));

alter publication supabase_realtime add table public.case_proposals;
