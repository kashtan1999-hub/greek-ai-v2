-- Run after learning_path.sql. Existing students remain ineligible for onboarding.
alter table public.learner_profiles add column if not exists intro_eligible boolean not null default false;
alter table public.learner_profiles add column if not exists preferred_name text not null default '';
alter table public.learner_profiles add column if not exists goal text not null default '';
alter table public.learner_profiles add column if not exists daily_minutes integer;
