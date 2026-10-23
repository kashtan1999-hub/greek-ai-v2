-- Correct only the known duplicated-letter display label; lesson content is unchanged.
begin;
update public."Curriculum" set topic='Буквы α, ε, ι, κ, ο, τ'
 where block='1.1' and content_type='lesson' and topic='Буквы α, ι, κ, ο, τ и κ';
update public.student_state set current_topic='Буквы α, ε, ι, κ, ο, τ'
 where current_block='1.1' and current_topic='Буквы α, ι, κ, ο, τ и κ';
update public."Exercises" set topic='Буквы α, ε, ι, κ, ο, τ'
 where block='1.1' and topic='Буквы α, ι, κ, ο, τ и κ';
update public.learning_paths set topic='Буквы α, ε, ι, κ, ο, τ'
 where block='1.1' and topic='Буквы α, ι, κ, ο, τ и κ'
 and not exists (select 1 from public.learning_paths p where p.student_id=learning_paths.student_id and p.block='1.1' and p.topic='Буквы α, ε, ι, κ, ο, τ');
commit;
