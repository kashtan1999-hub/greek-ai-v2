"""Durable lesson history, profile and spaced retention decisions."""
from datetime import datetime, timezone, timedelta
import json
from services.supabase_client import supabase


def rows(table, student_id):
    return supabase.table(table).select('*').eq('student_id', student_id).execute().data or []


def context(student_id):
    history = sorted(rows('learning_history', student_id), key=lambda r: r['created_at'])[-8:]
    paths = rows('learning_paths', student_id)
    profiles = rows('learner_profiles', student_id)
    return json.dumps({'profile': profiles[0] if profiles else {}, 'history': history,
                      'study_plan': paths}, ensure_ascii=False, default=str)


def retention(previous, score, hint_free, now=None):
    now = now or datetime.now(timezone.utc)
    previous = previous or {}
    stage = int(previous.get('stage') or 0)
    due = datetime.fromisoformat(previous['review_due_at']) if previous.get('review_due_at') else now
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    passed = score >= 80 and hint_free
    # A repeated test on the same day does not demonstrate retention.
    if passed and (stage == 0 or now >= due):
        stage += 1
        due = now + timedelta(days=[1, 3, 7, 14, 30][min(stage-1, 4)])
    elif not passed:
        stage = 0
        due = now + timedelta(days=1)
    return {'stage': stage, 'review_due_at': due.isoformat(), 'retained': stage >= 2}


def record_completion(student_id, block, topic, plan, percentage, next_lesson):
    previous = supabase.table('learning_paths').select('*').eq('student_id', student_id).eq('block', block).eq('topic', topic).limit(1).execute().data
    decision = retention(previous[0] if previous else {}, percentage, not plan.get('quiz_hint_used', False if plan.get('stages') else plan.get('hints_used',False)))
    mistakes = plan.get('mistakes', [])
    from services.lesson_stages import eligible_to_advance
    next_material = next_lesson if eligible_to_advance(plan,percentage) else {'block': block, 'topic': topic}
    action = 'Повторить трудные вопросы. Затем проверить знания без подсказок.' if mistakes else 'Короткое повторение по расписанию без подсказок.'
    payload = dict(student_id=student_id, block=block, topic=topic, **decision)
    supabase.table('learning_paths').upsert(payload, on_conflict='student_id,block,topic').execute()
    supabase.table('learning_history').insert(dict(student_id=student_id, block=block, topic=topic,
        completed='Урок, мини-практика, проверка понимания и тест' if plan.get('stages') else 'Урок и тест', stopped_at='Тест завершён', score=percentage, mistakes=mistakes,
        study_plan=action, next_material=next_material,
        review_due_at=decision['review_due_at'])).execute()
    return decision


def due_review(student_id, current_block, current_topic):
    now = datetime.now(timezone.utc)
    from services.course_sequence import BLOCK_ORDER
    from services.curriculum_service import get_lesson
    eligible = [r for r in rows('learning_paths', student_id) if r.get('block') in BLOCK_ORDER and get_lesson(r['block'], r.get('topic'))]
    for row in sorted(eligible, key=lambda r: r['review_due_at']):
        due = datetime.fromisoformat(row['review_due_at'])
        if due.tzinfo is None: due = due.replace(tzinfo=timezone.utc)
        if due <= now and (row['block'], row['topic']) != (current_block, current_topic):
            return row
    return None


def reinforce_mistake(student_id, exercise_id, hinted):
    if hinted: return
    found = supabase.table('learning_errors').select('*').eq('student_id', student_id).eq('exercise_id', exercise_id).eq('resolved', False).execute().data or []
    now = datetime.now(timezone.utc)
    for row in found:
        last = row.get('last_correct_at')
        if last:
            stamp = datetime.fromisoformat(last)
            if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=timezone.utc)
            if now - stamp < timedelta(days=1): continue
        count = int(row.get('retention_successes') or 0) + 1
        supabase.table('learning_errors').update({'last_correct_at': now.isoformat(),
            'retention_successes': count, 'resolved': count >= 2,
            'review_sessions_remaining': max(0, 2-count)}).eq('id', row['id']).eq('student_id', student_id).execute()


def record_mistake_review(student_id, plan, topic, percentage):
    destination = plan.get('return_to') or {}
    supabase.table('learning_history').insert(dict(student_id=student_id,block=plan['block'],topic=topic,
        completed='Практика ошибок и повторная проверка исходных вопросов',stopped_at='Проверка ошибок завершена',
        score=percentage,mistakes=plan.get('mistakes',[]),study_plan='Повторить трудные вопросы по расписанию. Продолжить сохранённый урок.',
        next_material={'block':destination.get('current_block'),'topic':destination.get('current_topic')},
        review_due_at=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat())).execute()
