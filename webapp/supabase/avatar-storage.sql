-- Profile avatar storage setup.
-- Run this in the Supabase SQL editor if profile photo upload fails.

create table if not exists public.profiles (
  user_id uuid primary key references auth.users(id) on delete cascade,
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

alter table public.profiles add column if not exists avatar_url text;
alter table public.profiles add column if not exists account_balance numeric;
alter table public.profiles add column if not exists preferred_currency text not null default 'EUR';
alter table public.profiles add column if not exists usd_to_eur_rate numeric;
alter table public.profiles add column if not exists ftmo_account_size numeric;
alter table public.profiles add column if not exists daily_loss_limit numeric;
alter table public.profiles add column if not exists max_loss_limit numeric;
alter table public.profiles add column if not exists max_trades_per_day integer;
alter table public.profiles add column if not exists max_risk_per_day numeric;
alter table public.profiles add column if not exists daily_profit_target numeric;

update public.profiles
set preferred_currency = currency
where preferred_currency is null;

alter table public.profiles enable row level security;

drop policy if exists "profiles_select_own" on public.profiles;
create policy "profiles_select_own" on public.profiles
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "profiles_insert_own" on public.profiles;
create policy "profiles_insert_own" on public.profiles
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "profiles_update_own" on public.profiles;
create policy "profiles_update_own" on public.profiles
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

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
