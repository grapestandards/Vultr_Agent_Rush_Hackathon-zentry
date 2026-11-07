-- M2 detection: replay feed, alert fields, seed scenarios.

-- Transactions waiting to be replayed by the simulator. Same shape as transactions;
-- service-only (RLS on, no policies).
create table public.sim_feed (like public.transactions including all);
alter table public.sim_feed enable row level security;
revoke all on public.sim_feed from anon, authenticated;

alter table public.alerts
  add column status    text not null default 'new' check (status in ('new', 'in_case', 'closed')),
  add column rule_hits text[] not null default '{}',
  add column txn_ts    timestamptz,                      -- business time of the triggering transaction
  add constraint alerts_txn_account_key unique (transaction_id, account_id);  -- redelivery-safe
create index on public.alerts (status, priority, score desc);

-- The five launch scenarios. Thresholds live in dsl_json so Scenario Studio / tuning can change them.
insert into public.scenarios (name, dsl_json, status) values
  ('pass_through', '{"rule": "pass_through", "description": "Money out ≥ ratio of money in, within window after receiving", "params": {"window_min": 30, "ratio": 0.9, "min_in_baht": 10000}}', 'active'),
  ('fan_in_out', '{"rule": "fan_in_out", "description": "Many distinct senders or receivers in 24h", "params": {"min_senders": 5, "min_receivers": 4, "min_amount_baht": 20000}}', 'active'),
  ('dormant_reactivation', '{"rule": "dormant_reactivation", "description": "Quiet account suddenly receives a large amount", "params": {"quiet_days": 14, "min_in_baht": 20000}}', 'active'),
  ('structuring', '{"rule": "structuring", "description": "Several just-below-threshold transfers within an hour", "params": {"window_min": 60, "min_count": 3, "lower_baht": 45000, "upper_baht": 50000}}', 'active'),
  ('new_account_strangers', '{"rule": "new_account_strangers", "description": "Young account receiving from many first-time counterparties", "params": {"max_age_days": 30, "min_new_senders": 3, "min_in_baht": 20000}}', 'active');
