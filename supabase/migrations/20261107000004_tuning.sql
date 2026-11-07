-- M5 model tuning: richer model registry (card, shadow stats, promotion history) and train runs.

alter table public.model_versions
  add column name          text,
  add column card_json     jsonb not null default '{}',   -- holdout curves, champion comparison, gained/lost accounts
  add column shadow_json   jsonb,                         -- live shadow stats written by the scorer
  add column train_run_id  uuid references public.train_runs(id) on delete set null,
  add column promoted_at   timestamptz,
  add column promoted_by   uuid references auth.users(id);

update public.model_versions set name = 'lgbm-baseline', promoted_at = created_at where stage = 'champion' and name is null;

alter table public.train_runs
  add column runner      text not null default 'local' check (runner in ('local', 'vultr')),
  add column started_at  timestamptz,
  add column error       text;

-- at most one champion and one shadow per kind
create unique index model_versions_one_champion on public.model_versions (kind) where stage = 'champion';
create unique index model_versions_one_shadow on public.model_versions (kind) where stage = 'shadow';

drop policy staff_read on public.train_runs;
create policy staff_read on public.train_runs for select to authenticated using (public.has_role('analyst', 'compliance_manager'));

alter publication supabase_realtime add table public.model_versions;
