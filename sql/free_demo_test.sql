-- Greek Tutor: FREE DEMO TEST / DIAGNOSTIC
-- This does not touch Stripe or payment records.
-- Replace 8947101896 with the test student's Telegram user ID.
-- It verifies the student state and resets only the learning pointer to Curriculum 1.1.

SELECT
    s.id,
    s.telegram_user_id,
    s.first_name,
    s.subscription_status,
    st.current_block,
    st.current_topic,
    st.current_step,
    st.lesson_progress,
    st.block_progress
FROM public."Students" s
LEFT JOIN public.student_state st ON st.student_id = s.id
WHERE s.telegram_user_id = 8947101896;

-- Optional test reset: use only when you want to test the FREE 1.1 flow again.
UPDATE public.student_state
SET
    current_block = '1.1',
    current_topic = (
        SELECT c.topic
        FROM public."Curriculum" c
        WHERE c.block = '1.1'
          AND c.content_type = 'lesson'
        ORDER BY c.lesson_order
        LIMIT 1
    ),
    current_step = 1,
    interaction_number = 1,
    next_action = 'continue_learning',
    active_plan = NULL,
    lesson_progress = 0,
    block_progress = 0,
    updated_at = now(),
    last_activity_at = now()
WHERE student_id = (
    SELECT id FROM public."Students"
    WHERE telegram_user_id = 8947101896
    LIMIT 1
);
