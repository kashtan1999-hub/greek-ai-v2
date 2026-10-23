"""Apply assessment estimates without inventing curriculum CEFR mappings."""
from services.supabase_client import supabase
from services.mentor_memory import record_plan
from services.student_service import update_state
from services.access_service import has_access


def apply_placement(student, result):
    level = result['level']
    plan = {
        'estimated_level': level,
        'assessment_summary': result.get('summary', ''),
        'weak_topics': result.get('weak_topics') or [],
        'review_topics': result.get('review_topics') or [],
        'next_step': result.get('next_step') or 'Adapt the next conversation to the assessed ability and review demonstrated weaknesses.',
    }
    lessons = (supabase.table('Curriculum').select('block,topic,metadata,lesson_order')
               .eq('content_type', 'lesson').order('lesson_order').execute().data or [])
    candidates = []
    for lesson in lessons:
        metadata = lesson.get('metadata') or {}
        if not isinstance(metadata, dict):
            continue
        mapped = str(metadata.get('cefr_level') or metadata.get('level') or '').upper()
        if mapped == level:
            candidates.append(lesson)
    # The content owner must explicitly map lessons; numeric block IDs are not CEFR levels.
    target = candidates[0] if candidates else None
    update_state(student['id'], {'level': level})
    if target and has_access(student, target['block'], target.get('topic')):
        update_state(student['id'], {'current_block': target['block'], 'current_topic': target.get('topic'),
            'current_step': 1, 'interaction_number': 1, 'active_plan': None,
            'lesson_progress': 0, 'block_progress': 0, 'next_action': 'continue_learning'})
        plan['placement_note'] = f"Selected verified {level} curriculum lesson {target['block']}; earlier lessons were not marked complete."
    elif target:
        plan['placement_note'] = 'Suitable mapped lesson requires subscription; retain current accessible lesson.'
    else:
        plan['placement_note'] = ('No explicit CEFR curriculum mapping exists. Keep the saved lesson pointer, '
            'but adapt conversational difficulty to demonstrated ability; do not restart alphabet practice '
            'for a learner who demonstrated it. Select relevant material with the learner as needed.')
    record_plan(student['id'], plan)
    return plan
