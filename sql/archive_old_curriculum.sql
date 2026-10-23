-- Run ONLY after importing all 35 new lessons. Leaves Exercises, profiles, history and payments intact.
begin;
do $$
begin
 if (select count(distinct block) from public."Curriculum" where content_type='lesson' and block in
 ('1.1','1.2','1.3','1.4','1.5','1.6','1.7','2.1','2.2','3.1','3.2','3.3','4.1','4.2','4.3','4.4','4.5','5.1','5.2','5.3','5.4','5.5','6.1','6.2','6.3','6.4','6.5','7.1','7.2','7.3','7.6','8.1','8.2','8.4','8.5') and length(trim(coalesce(content,'')))>0) <> 35 then
  raise exception 'Import all 35 nonempty new course lessons before archiving old material';
 end if;
end $$;
create table if not exists public.curriculum_legacy_archive as select * from public."Curriculum" where false;
alter table public.curriculum_legacy_archive enable row level security;
insert into public.curriculum_legacy_archive select c.* from public."Curriculum" c
 where (c.block ~* '^(0|[1-9]|[1-3][0-9]|4[0-4])[A-F]$' or c.block ~ '^[0-9]{1,2}$')
 and not exists (select 1 from public.curriculum_legacy_archive a where a.id=c.id);
delete from public."Curriculum" where block ~* '^(0|[1-9]|[1-3][0-9]|4[0-4])[A-F]$' or block ~ '^[0-9]{1,2}$';
commit;
