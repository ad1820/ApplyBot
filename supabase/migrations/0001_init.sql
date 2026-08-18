-- ============================================================================
-- Job Application Agent - Initial Schema (V1 + V2)
-- ============================================================================
-- Supabase/Postgres is the single source of truth for all persistent state.
-- Google Sheets is a reporting layer only and must never be relied upon here.
--
-- Notes on RLS: this project is accessed exclusively from a trusted backend
-- using the Supabase service role key, so Row Level Security is left
-- disabled by default. If this is ever exposed to untrusted clients, RLS
-- policies must be added before doing so.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ----------------------------------------------------------------------------
-- V1: Candidate profile & preferences
-- ----------------------------------------------------------------------------

create table if not exists candidate_profiles (
    id uuid primary key default gen_random_uuid(),
    name text not null,
    email text not null,
    phone text,
    location text,
    education jsonb default '[]'::jsonb,
    experience jsonb default '[]'::jsonb,
    skills text[] default array[]::text[],
    preferred_locations text[] default array[]::text[],
    preferred_roles text[] default array[]::text[],
    preferred_work_mode text,
    minimum_salary numeric,
    years_of_experience numeric,
    preferred_companies text[] default array[]::text[],
    excluded_companies text[] default array[]::text[],
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists job_preferences (
    id uuid primary key default gen_random_uuid(),
    profile_id uuid references candidate_profiles(id) on delete cascade,
    preferred_roles text[] default array[]::text[],
    preferred_technologies text[] default array[]::text[],
    preferred_locations text[] default array[]::text[],
    work_mode text check (work_mode in ('remote', 'hybrid', 'onsite', 'any')) default 'any',
    experience_min numeric,
    experience_max numeric,
    minimum_salary numeric,
    preferred_company_types text[] default array[]::text[],
    excluded_companies text[] default array[]::text[],
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- V1: Jobs, sources, deduplication
-- ----------------------------------------------------------------------------

create table if not exists jobs (
    id uuid primary key default gen_random_uuid(),
    external_id text,
    source text not null,
    company text not null,
    title text not null,
    location text,
    work_mode text check (work_mode in ('remote', 'hybrid', 'onsite', 'unknown')) default 'unknown',
    salary_min numeric,
    salary_max numeric,
    currency text,
    description text,
    requirements text,
    skills text[] default array[]::text[],
    url text,
    canonical_key text not null,
    posted_at timestamptz,
    discovered_at timestamptz not null default now(),
    match_score numeric,
    matching_skills text[] default array[]::text[],
    missing_skills text[] default array[]::text[],
    matching_reasons text[] default array[]::text[],
    concerns text[] default array[]::text[],
    status text not null default 'DISCOVERED' check (status in (
        'DISCOVERED', 'NOTIFIED', 'INTERESTED', 'SKIPPED', 'APPLIED',
        'INTERVIEW', 'REJECTED', 'OFFER', 'WITHDRAWN'
    )),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_jobs_canonical_key on jobs (canonical_key);
create index if not exists idx_jobs_status on jobs (status);

-- Preserves the fact that the same logical job was seen via multiple sources
-- instead of creating duplicate job rows.
create table if not exists job_sources (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    source text not null,
    external_id text,
    url text,
    discovered_at timestamptz not null default now(),
    unique (job_id, source, external_id)
);

-- ----------------------------------------------------------------------------
-- V1: Applications
-- ----------------------------------------------------------------------------

create table if not exists applications (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    status text not null default 'APPLIED' check (status in (
        'APPLIED', 'INTERVIEW', 'REJECTED', 'OFFER', 'WITHDRAWN'
    )),
    applied_at timestamptz not null default now(),
    resume_version text,
    notes text,
    last_updated timestamptz not null default now(),
    unique (job_id)
);

-- ----------------------------------------------------------------------------
-- V1: Agent run tracking (restart / recovery source of truth)
-- ----------------------------------------------------------------------------

create table if not exists agent_runs (
    id uuid primary key default gen_random_uuid(),
    started_at timestamptz not null default now(),
    finished_at timestamptz,
    status text not null default 'RUNNING' check (status in (
        'RUNNING', 'COMPLETED', 'FAILED', 'PARTIAL'
    )),
    source text,
    jobs_found integer default 0,
    jobs_new integer default 0,
    jobs_duplicate integer default 0,
    jobs_notified integer default 0,
    error_message text
);

-- ----------------------------------------------------------------------------
-- V1: Notification tracking (idempotency for Telegram sends)
-- ----------------------------------------------------------------------------

create table if not exists notifications (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    channel text not null default 'telegram',
    telegram_message_id text,
    status text not null default 'PENDING' check (status in ('PENDING', 'SENT', 'FAILED')),
    sent_at timestamptz,
    error_message text,
    created_at timestamptz not null default now(),
    unique (job_id, channel)
);


-- ----------------------------------------------------------------------------
-- V2: Master resume (versioned, never overwritten)
-- ----------------------------------------------------------------------------

create table if not exists master_resumes (
    id uuid primary key default gen_random_uuid(),
    version integer not null,
    content text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (version)
);

create table if not exists tailored_resumes (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    master_resume_version integer not null references master_resumes(version),
    content text not null,
    match_score numeric,
    strong_skills text[] default array[]::text[],
    missing_skills text[] default array[]::text[],
    suggested_changes text[] default array[]::text[],
    approved boolean not null default false,
    created_at timestamptz not null default now()
);

create table if not exists cover_letters (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    content text not null,
    approved boolean not null default false,
    created_at timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- V2: Referral assessment
-- ----------------------------------------------------------------------------

create table if not exists referral_assessments (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    potential text not null check (potential in ('HIGH', 'MEDIUM', 'LOW')),
    reasoning text,
    draft_message text,
    created_at timestamptz not null default now()
);

-- ----------------------------------------------------------------------------
-- V2: Application question / answer engine
-- ----------------------------------------------------------------------------

create table if not exists application_questions (
    id uuid primary key default gen_random_uuid(),
    job_id uuid not null references jobs(id) on delete cascade,
    platform text,
    question_text text not null,
    category text not null check (category in ('PROFILE_FACT', 'DERIVED_FACT', 'GENERATIVE', 'SENSITIVE')),
    created_at timestamptz not null default now()
);

create table if not exists application_answers (
    id uuid primary key default gen_random_uuid(),
    question_text text not null,
    normalized_question text not null,
    answer text not null,
    source text not null check (source in ('PROFILE', 'DERIVED', 'GENERATED', 'USER_APPROVED')),
    approved_at timestamptz,
    created_at timestamptz not null default now(),
    unique (normalized_question)
);

-- ----------------------------------------------------------------------------
-- V2: Analytics events (simple statistics, no ML)
-- ----------------------------------------------------------------------------

create table if not exists analytics_events (
    id uuid primary key default gen_random_uuid(),
    job_id uuid references jobs(id) on delete set null,
    event_type text not null check (event_type in (
        'DISCOVERED', 'VIEWED', 'SKIPPED', 'APPLIED', 'INTERVIEW', 'REJECTED', 'OFFER'
    )),
    occurred_at timestamptz not null default now(),
    metadata jsonb default '{}'::jsonb
);

create index if not exists idx_analytics_events_type on analytics_events (event_type);


