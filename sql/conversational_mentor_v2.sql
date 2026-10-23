-- Run after the existing project migrations, including conversation_history.sql.
-- New tables are backend-only. Do not expose a service-role key to clients.
begin;
create table if not exists public.mentor_memory (
 student_id bigint primary key references public."Students"(id) on delete cascade,
 summary text not null default '', summary_through_id bigint not null default 0,
 learning_plan jsonb not null default '{}', evidence jsonb not null default '[]',
 updated_at timestamptz not null default now()
);
create table if not exists public.mentor_sessions (
 telegram_user_id bigint primary key,
 payload jsonb not null default '{}'
);
alter table public.learning_errors add column if not exists concept_key text;
alter table public.mentor_memory enable row level security;
alter table public.mentor_sessions enable row level security;
revoke all on public.mentor_memory, public.mentor_sessions from anon, authenticated;
grant all on public.mentor_memory, public.mentor_sessions to service_role;
create index if not exists conversation_history_student_id_cursor_idx
 on public.conversation_history(student_id, id);
-- Keep the existing reset transaction and extend it to the new memory.
-- Wrapper stays idempotent when this migration is run again.
do $$ begin
 if to_regprocedure('public.reset_learning_history_v1(bigint,text,text)') is null
    and to_regprocedure('public.reset_learning_history(bigint,text,text)') is not null then
  alter function public.reset_learning_history(bigint,text,text) rename to reset_learning_history_v1;
 end if;
end $$;
create or replace function public.reset_learning_history(p_student_id bigint, p_block text, p_topic text)
returns void language plpgsql security invoker set search_path=public as $$
begin
 perform public.reset_learning_history_v1(p_student_id,p_block,p_topic);
 delete from public.mentor_memory where student_id=p_student_id;
 delete from public.conversation_history where student_id=p_student_id;
 delete from public.mentor_sessions where telegram_user_id in (
  select telegram_user_id from public."Students" where id=p_student_id
 );
end; $$;
revoke all on function public.reset_learning_history(bigint,text,text) from public, anon, authenticated;
grant execute on function public.reset_learning_history(bigint,text,text) to service_role;
commit;
