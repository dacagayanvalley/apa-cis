-- APA-CIS Supabase/PostgreSQL/PostGIS starter schema
-- Run in Supabase SQL editor after enabling the PostGIS extension.

create extension if not exists postgis;

create table if not exists data_sources (
  id bigserial primary key,
  source_code text unique not null,
  source_name text not null,
  source_url text,
  source_type text not null check (source_type in ('official', 'satellite', 'reanalysis', 'manual', 'internal')),
  update_frequency text,
  lag_days integer,
  notes text,
  created_at timestamptz default now()
);

create table if not exists municipalities (
  psgc text primary key,
  name text not null,
  province text not null,
  province_code text,
  climate_type text,
  elevation_m numeric,
  irrigation_status text check (irrigation_status in ('rainfed', 'partial', 'irrigated')),
  geom geometry(MultiPolygon, 4326),
  centroid geometry(Point, 4326),
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table if not exists apa_sites (
  id bigserial primary key,
  site_code text unique not null,
  site_name text not null,
  psgc text references municipalities(psgc),
  site_type text check (site_type in ('APA', 'AMIA', 'demo_farm', 'seed_buffer', 'postharvest', 'irrigation')),
  lead_office text,
  dominant_crop text,
  notes text,
  geom geometry(Point, 4326),
  created_at timestamptz default now()
);

create table if not exists amia_villages (
  id bigserial primary key,
  village_code text unique not null,
  village_name text not null,
  psgc text references municipalities(psgc),
  barangay_name text,
  dominant_crop text,
  water_source text,
  geom geometry(Point, 4326),
  created_at timestamptz default now()
);

create table if not exists weather_observations (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  source_id bigint references data_sources(id),
  observed_date date not null,
  rainfall_mm numeric,
  tmax_c numeric,
  tmin_c numeric,
  tmean_c numeric,
  humidity_pct numeric,
  wind_speed_ms numeric,
  wind_dir_deg numeric,
  solar_mj_m2 numeric,
  soil_moisture numeric,
  quality_flag text default 'unchecked',
  raw_payload jsonb,
  created_at timestamptz default now(),
  unique (psgc, source_id, observed_date)
);

create table if not exists weather_forecasts (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  source_id bigint references data_sources(id),
  issue_time timestamptz not null,
  valid_date date not null,
  lead_day integer,
  rainfall_mm numeric,
  rainfall_class text,
  tmax_c numeric,
  tmin_c numeric,
  humidity_pct numeric,
  wind_speed_ms numeric,
  thunderstorm_risk text,
  confidence text,
  advisory_text text,
  raw_payload jsonb,
  created_at timestamptz default now(),
  unique (psgc, source_id, issue_time, valid_date)
);

create table if not exists climate_normals (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  source_id bigint references data_sources(id),
  baseline_start_year integer not null,
  baseline_end_year integer not null,
  month integer not null check (month between 1 and 12),
  rainfall_normal_mm numeric,
  tmax_normal_c numeric,
  tmin_normal_c numeric,
  humidity_normal_pct numeric,
  created_at timestamptz default now(),
  unique (psgc, source_id, baseline_start_year, baseline_end_year, month)
);

create table if not exists rainfall_anomalies (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  period_start date not null,
  period_end date not null,
  observed_rainfall_mm numeric,
  normal_rainfall_mm numeric,
  anomaly_mm numeric,
  pct_of_normal numeric,
  anomaly_class text,
  source_id bigint references data_sources(id),
  created_at timestamptz default now(),
  unique (psgc, period_start, period_end, source_id)
);

create table if not exists seasonal_outlooks (
  id bigserial primary key,
  source_id bigint references data_sources(id),
  issue_date date not null,
  valid_start date not null,
  valid_end date not null,
  enso_status text,
  rainfall_outlook text,
  temperature_outlook text,
  region_text text,
  source_document_url text,
  raw_payload jsonb,
  created_at timestamptz default now()
);

create table if not exists municipal_climate_profiles (
  psgc text primary key references municipalities(psgc),
  climate_type text,
  mean_annual_rainfall_mm numeric,
  wettest_months integer[],
  driest_months integer[],
  typical_onset_month integer,
  typical_cessation_month integer,
  dominant_hazards text[],
  recommended_adaptations text[],
  updated_at timestamptz default now()
);

create table if not exists crop_calendars (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  crop text not null,
  season text not null,
  planting_start date,
  planting_end date,
  expected_harvest_start date,
  expected_harvest_end date,
  irrigation_status text,
  source text,
  created_at timestamptz default now()
);

create table if not exists crop_stage_risks (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  crop text not null,
  crop_stage text not null,
  risk_date date not null,
  drought_score numeric,
  flood_score numeric,
  heat_score numeric,
  disease_score numeric,
  composite_score numeric,
  risk_class text,
  explanation jsonb,
  created_at timestamptz default now(),
  unique (psgc, crop, crop_stage, risk_date)
);

create table if not exists agri_advisories (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  issue_time timestamptz not null,
  valid_start timestamptz,
  valid_end timestamptz,
  rule_id text not null,
  severity text not null check (severity in ('info', 'advisory', 'warning', 'danger')),
  affected_crops text[],
  affected_stages text[],
  operation text,
  trigger_values jsonb,
  bulletin_text text,
  sms_text text,
  lgu_text text,
  facebook_text text,
  responsible_office text,
  status text default 'draft' check (status in ('draft', 'reviewed', 'approved', 'archived')),
  reviewer text,
  created_at timestamptz default now()
);

create table if not exists hazard_events (
  id bigserial primary key,
  source_id bigint references data_sources(id),
  event_type text not null check (event_type in ('tropical_cyclone', 'thunderstorm', 'flood', 'drought', 'heat', 'landslide', 'other')),
  event_name text,
  issue_time timestamptz,
  valid_start timestamptz,
  valid_end timestamptz,
  severity text,
  description text,
  affected_psgcs text[],
  geom geometry(Geometry, 4326),
  raw_payload jsonb,
  created_at timestamptz default now()
);

create table if not exists farmer_exposure (
  id bigserial primary key,
  psgc text references municipalities(psgc),
  barangay_name text,
  crop text,
  season text,
  farmer_count integer,
  area_ha numeric,
  rainfed_area_ha numeric,
  irrigated_area_ha numeric,
  smallholder_count integer,
  source text,
  data_year integer,
  created_at timestamptz default now(),
  unique (psgc, barangay_name, crop, season, source, data_year)
);

create table if not exists etl_logs (
  id bigserial primary key,
  run_id uuid default gen_random_uuid(),
  source_code text,
  step_name text not null,
  run_started_at timestamptz default now(),
  run_finished_at timestamptz,
  status text not null check (status in ('running', 'success', 'warning', 'failed')),
  records_fetched integer default 0,
  records_valid integer default 0,
  records_rejected integer default 0,
  message text,
  details jsonb
);

create index if not exists weather_observations_psgc_date_idx
  on weather_observations (psgc, observed_date desc);

create index if not exists weather_forecasts_psgc_valid_idx
  on weather_forecasts (psgc, valid_date);

create index if not exists agri_advisories_psgc_issue_idx
  on agri_advisories (psgc, issue_time desc);

create index if not exists hazard_events_geom_idx
  on hazard_events using gist (geom);

create index if not exists municipalities_geom_idx
  on municipalities using gist (geom);

create or replace view public_current_weather as
select distinct on (wo.psgc)
  wo.psgc,
  m.name as municipality,
  m.province,
  wo.observed_date,
  wo.rainfall_mm,
  wo.tmax_c,
  wo.tmin_c,
  wo.humidity_pct,
  wo.wind_speed_ms,
  ds.source_name
from weather_observations wo
join municipalities m on m.psgc = wo.psgc
left join data_sources ds on ds.id = wo.source_id
order by wo.psgc, wo.observed_date desc;

create or replace view public_active_advisories as
select
  aa.id,
  aa.psgc,
  m.name as municipality,
  m.province,
  aa.issue_time,
  aa.valid_start,
  aa.valid_end,
  aa.rule_id,
  aa.severity,
  aa.operation,
  aa.bulletin_text,
  aa.sms_text,
  aa.lgu_text,
  aa.facebook_text,
  aa.trigger_values
from agri_advisories aa
join municipalities m on m.psgc = aa.psgc
where aa.status in ('reviewed', 'approved')
  and (aa.valid_end is null or aa.valid_end >= now());
