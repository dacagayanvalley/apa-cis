-- APA-CIS Supabase authentication + access monitoring module
-- Run this in the Supabase SQL editor after creating a Supabase project.
-- It is safe to rerun; tables, columns, indexes, and policies are idempotent.

create extension if not exists pgcrypto;

create table if not exists access_sessions (
  session_id uuid primary key,
  visitor_id uuid not null,
  auth_user_id uuid,
  email text,
  identity_source text default 'self_declared',
  name text,
  agency text,
  role text,
  office_location text,
  latitude numeric(9, 6),
  longitude numeric(9, 6),
  location_accuracy_m integer,
  location_consented boolean default false,
  device text,
  user_agent text,
  language text,
  module_name text,
  last_seen_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create table if not exists access_events (
  event_id uuid primary key default gen_random_uuid(),
  session_id uuid references access_sessions(session_id) on delete cascade,
  visitor_id uuid not null,
  auth_user_id uuid,
  event_type text not null,
  module_name text,
  path text,
  details jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists user_profiles (
  auth_user_id uuid primary key references auth.users(id) on delete cascade,
  email text,
  name text,
  agency text,
  role text,
  office_location text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table access_sessions add column if not exists auth_user_id uuid;
alter table access_sessions add column if not exists email text;
alter table access_sessions add column if not exists identity_source text default 'self_declared';
alter table access_events add column if not exists auth_user_id uuid;

alter table access_sessions drop constraint if exists access_sessions_identity_source_check;
alter table access_sessions add constraint access_sessions_identity_source_check
  check (identity_source in ('self_declared', 'supabase_auth', 'supabase_auth_pending'));

alter table access_events drop constraint if exists access_events_event_type_check;
alter table access_events add constraint access_events_event_type_check
  check (event_type in ('page_view', 'module_view', 'profile_saved', 'location_enabled', 'location_denied', 'export_csv', 'auth_link_requested', 'auth_signed_in', 'auth_signed_out'));

create index if not exists user_profiles_agency_idx
  on user_profiles (agency);

create index if not exists access_sessions_auth_user_idx
  on access_sessions (auth_user_id, last_seen_at desc);

create index if not exists access_sessions_last_seen_idx
  on access_sessions (last_seen_at desc);

create index if not exists access_sessions_agency_idx
  on access_sessions (agency);

create index if not exists access_events_session_created_idx
  on access_events (session_id, created_at desc);

create index if not exists access_events_module_idx
  on access_events (module_name, created_at desc);

alter table user_profiles enable row level security;
alter table access_sessions enable row level security;
alter table access_events enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'user_profiles' and policyname = 'user_profiles_select_authenticated') then
    create policy user_profiles_select_authenticated
      on user_profiles for select
      to authenticated
      using (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'user_profiles' and policyname = 'user_profiles_upsert_own') then
    create policy user_profiles_upsert_own
      on user_profiles for all
      to authenticated
      using (auth.uid() = auth_user_id)
      with check (auth.uid() = auth_user_id);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_sessions' and policyname = 'access_sessions_insert_anon') then
    create policy access_sessions_insert_anon
      on access_sessions for insert
      to anon
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_sessions' and policyname = 'access_sessions_update_own_anon') then
    create policy access_sessions_update_own_anon
      on access_sessions for update
      to anon
      using (true)
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_events' and policyname = 'access_events_insert_anon') then
    create policy access_events_insert_anon
      on access_events for insert
      to anon
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_sessions' and policyname = 'access_sessions_insert_authenticated') then
    create policy access_sessions_insert_authenticated
      on access_sessions for insert
      to authenticated
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_sessions' and policyname = 'access_sessions_update_authenticated') then
    create policy access_sessions_update_authenticated
      on access_sessions for update
      to authenticated
      using (true)
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_events' and policyname = 'access_events_insert_authenticated') then
    create policy access_events_insert_authenticated
      on access_events for insert
      to authenticated
      with check (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_sessions' and policyname = 'access_sessions_select_authenticated') then
    create policy access_sessions_select_authenticated
      on access_sessions for select
      to authenticated
      using (true);
  end if;

  if not exists (select 1 from pg_policies where schemaname = 'public' and tablename = 'access_events' and policyname = 'access_events_select_authenticated') then
    create policy access_events_select_authenticated
      on access_events for select
      to authenticated
      using (true);
  end if;
end
$$;

create or replace view access_monitoring_summary as
select
  count(distinct visitor_id) as known_visitors,
  count(*) as sessions_logged,
  count(*) filter (where location_consented) as sessions_with_location,
  max(last_seen_at) as latest_access_at
from access_sessions;