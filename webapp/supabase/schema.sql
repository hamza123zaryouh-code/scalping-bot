-- Trading Journal schema for server-mediated Supabase persistence.
-- Run this file in the Supabase SQL editor.
-- The Next.js API writes with the service-role key after validating the
-- backend JWT, so these tables use app_users instead of auth.users.

create extension if not exists "pgcrypto";

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.app_users (
  id uuid primary key,
  username text not null unique,
  email text,
  role text not null default 'admin',
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.profiles (
  user_id uuid primary key,
  display_name text,
  language text not null default 'nl' check (language in ('nl', 'en', 'ar')),
  currency text not null default 'EUR',
  preferred_currency text not null default 'EUR',
  usd_to_eur_rate numeric,
  avatar_url text,
  account_balance numeric,
  ftmo_account_size numeric,
  daily_loss_limit numeric,
  max_loss_limit numeric,
  max_trades_per_day integer,
  max_risk_per_day numeric,
  daily_profit_target numeric,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.trades (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  symbol text not null default 'XAUUSD',
  trade_type text not null,
  date date not null,
  entry_price numeric not null,
  current_price numeric,
  lot_size numeric not null,
  entry_zone_from numeric not null,
  entry_zone_to numeric not null,
  entry_zone_pips integer not null default 30,
  total_stop_loss_pips integer not null default 60,
  stop_loss numeric not null,
  tp1 numeric not null,
  tp2 numeric not null,
  tp3 numeric not null,
  tp4 numeric not null,
  feeling text,
  reason_for_entry text,
  satisfaction_emoji text,
  satisfaction_reason text,
  setup_tag text,
  is_favorite boolean not null default false,
  is_mistake boolean not null default false,
  status text not null default 'open',
  profit_loss numeric not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.reviews (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  week_start date not null,
  went_well text,
  went_wrong text,
  improve_next_week text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles add column if not exists preferred_currency text not null default 'EUR';
alter table public.profiles add column if not exists usd_to_eur_rate numeric;
alter table public.profiles add column if not exists avatar_url text;
alter table public.profiles add column if not exists account_balance numeric;
alter table public.profiles add column if not exists ftmo_account_size numeric;
alter table public.profiles add column if not exists daily_loss_limit numeric;
alter table public.profiles add column if not exists max_loss_limit numeric;
alter table public.profiles add column if not exists max_trades_per_day integer;
alter table public.profiles add column if not exists max_risk_per_day numeric;
alter table public.profiles add column if not exists daily_profit_target numeric;

alter table public.trades add column if not exists current_price numeric;
alter table public.trades add column if not exists entry_zone_from numeric;
alter table public.trades add column if not exists entry_zone_to numeric;
alter table public.trades add column if not exists entry_zone_pips integer not null default 30;
alter table public.trades add column if not exists total_stop_loss_pips integer not null default 60;
alter table public.trades add column if not exists stop_loss numeric;
alter table public.trades add column if not exists tp1 numeric;
alter table public.trades add column if not exists tp2 numeric;
alter table public.trades add column if not exists tp3 numeric;
alter table public.trades add column if not exists tp4 numeric;
alter table public.trades add column if not exists feeling text;
alter table public.trades add column if not exists reason_for_entry text;
alter table public.trades add column if not exists satisfaction_emoji text;
alter table public.trades add column if not exists satisfaction_reason text;
alter table public.trades add column if not exists setup_tag text;
alter table public.trades add column if not exists is_favorite boolean not null default false;
alter table public.trades add column if not exists is_mistake boolean not null default false;
alter table public.trades add column if not exists status text not null default 'open';
alter table public.trades add column if not exists profit_loss numeric not null default 0;
alter table public.trades add column if not exists created_at timestamptz not null default now();
alter table public.trades add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'trades'
      and column_name = 'reason'
  ) then
    execute $sql$
      update public.trades
      set reason_for_entry = reason
      where reason_for_entry is null
        and reason is not null
    $sql$;
  end if;
end
$$;

update public.profiles
set preferred_currency = currency
where preferred_currency is null;

update public.trades set status = 'open' where status is null;
update public.trades set status = 'closed profit' where status in ('closed_profit');
update public.trades set status = 'closed loss' where status in ('closed_loss');
update public.trades set status = 'SL hit' where status in ('sl_hit', 'hit_sl');
update public.trades set status = 'TP hit' where status in ('tp_hit', 'hit_tp');
update public.trades set status = 'manually closed' where status in ('closed', 'manually_closed');

alter table public.trades drop constraint if exists trades_status_check;
alter table public.trades add constraint trades_status_check
check (status in ('open', 'closed profit', 'closed loss', 'SL hit', 'TP hit', 'manually closed'));

alter table public.trades drop constraint if exists trades_trade_type_check;
alter table public.trades add constraint trades_trade_type_check
check (trade_type in ('Buy', 'Sell'));

alter table public.trades drop constraint if exists trades_setup_tag_check;
alter table public.trades add constraint trades_setup_tag_check
check (
  setup_tag is null or setup_tag in (
    'Breakout', 'Retest', 'Support/Resistance', 'EMA', 'RSI', 'Liquidity', 'Other'
  )
);

drop trigger if exists on_auth_user_created on auth.users;
drop function if exists public.handle_new_user_profile();

alter table public.profiles drop constraint if exists profiles_user_id_fkey;
alter table public.trades drop constraint if exists trades_user_id_fkey;
alter table public.reviews drop constraint if exists reviews_user_id_fkey;

alter table public.profiles
  add constraint profiles_user_id_fkey
  foreign key (user_id) references public.app_users(id) on delete cascade;

alter table public.trades
  add constraint trades_user_id_fkey
  foreign key (user_id) references public.app_users(id) on delete cascade;

alter table public.reviews
  add constraint reviews_user_id_fkey
  foreign key (user_id) references public.app_users(id) on delete cascade;

create unique index if not exists reviews_user_week_unique_idx on public.reviews(user_id, week_start);
create index if not exists app_users_username_idx on public.app_users(username);
create index if not exists trades_user_id_idx on public.trades(user_id);
create index if not exists trades_date_idx on public.trades(date);
create index if not exists reviews_user_id_idx on public.reviews(user_id);
create index if not exists reviews_week_start_idx on public.reviews(week_start);

alter table public.app_users enable row level security;
alter table public.profiles enable row level security;
alter table public.trades enable row level security;
alter table public.reviews enable row level security;

drop trigger if exists set_app_users_updated_at on public.app_users;
create trigger set_app_users_updated_at
before update on public.app_users
for each row execute function public.set_updated_at();

drop trigger if exists set_profiles_updated_at on public.profiles;
create trigger set_profiles_updated_at
before update on public.profiles
for each row execute function public.set_updated_at();

drop trigger if exists set_trades_updated_at on public.trades;
create trigger set_trades_updated_at
before update on public.trades
for each row execute function public.set_updated_at();

drop trigger if exists set_reviews_updated_at on public.reviews;
create trigger set_reviews_updated_at
before update on public.reviews
for each row execute function public.set_updated_at();

insert into storage.buckets (id, name, public)
values ('avatars', 'avatars', true)
on conflict (id) do update set public = true;

drop policy if exists "avatars_public_read" on storage.objects;
create policy "avatars_public_read" on storage.objects
for select
to public
using (bucket_id = 'avatars');

drop policy if exists "avatars_user_insert" on storage.objects;
create policy "avatars_user_insert" on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "avatars_user_update" on storage.objects;
create policy "avatars_user_update" on storage.objects
for update
to authenticated
using (
  bucket_id = 'avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);

drop policy if exists "avatars_user_delete" on storage.objects;
create policy "avatars_user_delete" on storage.objects
for delete
to authenticated
using (
  bucket_id = 'avatars'
  and (storage.foldername(name))[1] = auth.uid()::text
);
