-- Adds related/transferable skills tracking (semantic-ish skill matching)
-- to the jobs table, and a fresher-friendly preference flag to
-- job_preferences.

alter table jobs
    add column if not exists related_skills text[] default array[]::text[];

alter table job_preferences
    add column if not exists fresher_friendly_only boolean not null default true;
