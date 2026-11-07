-- PII masking: browsers only ever read masked person names ("Somying Sd****", "สมหญิง สุ****").
-- Business (merchant) names stay readable. Full names come only from the API's audited reveal.

create or replace function public.mask_name(full_name text) returns text
language sql immutable as $$
  select case
    when full_name is null or full_name = '' then full_name
    when position(' ' in full_name) = 0 then left(full_name, 2) || '****'
    else split_part(full_name, ' ', 1) || ' ' || left(substr(full_name, position(' ' in full_name) + 1), 2) || '****'
  end
$$;

alter table public.customers
  add column display_en text,
  add column display_th text;

create or replace function public.customers_mask() returns trigger
language plpgsql as $$
begin
  new.display_en := public.mask_name(new.name_en);
  new.display_th := public.mask_name(new.name_th);
  return new;
end $$;
create trigger customers_mask before insert or update of name_en, name_th on public.customers
  for each row execute function public.customers_mask();

-- merchants trade under a business name: show it in full
create or replace function public.accounts_unmask_merchant() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.type = 'merchant' then
    update public.customers set display_en = name_en, display_th = name_th where id = new.customer_id;
  end if;
  return new;
end $$;
create trigger accounts_unmask_merchant after insert on public.accounts
  for each row execute function public.accounts_unmask_merchant();

update public.customers set display_en = public.mask_name(name_en), display_th = public.mask_name(name_th);
update public.customers c set display_en = c.name_en, display_th = c.name_th
  where exists (select 1 from public.accounts a where a.customer_id = c.id and a.type = 'merchant');

-- column grants: no browser role can select the full names
revoke select on public.customers from anon, authenticated;
grant select (id, display_en, display_th, kyc_level, risk_score, created_at) on public.customers to authenticated;
