"""Small durable learner memory used by the conversational AI mentor."""
import json
from datetime import datetime, timezone
from services.supabase_client import supabase


def _clean_list(value, limit=12):
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        item = str(item or '').strip()
        if item and item not in out:
            out.append(item)
    return out[:limit]


def get_memory(student_id: int) -> dict:
    try:
        rows = (supabase.table('ai_learning_memory').select('*')
                .eq('student_id', student_id).limit(1).execute().data or [])
        if not rows:
            return {'recurring_mistakes': [], 'topics_to_review': [], 'weak_areas': [],
                    'learning_plan': [], 'last_summary': ''}
        row = rows[0]
        return {
            'recurring_mistakes': _clean_list(row.get('recurring_mistakes')),
            'topics_to_review': _clean_list(row.get('topics_to_review')),
            'weak_areas': _clean_list(row.get('weak_areas')),
            'learning_plan': _clean_list(row.get('learning_plan')),
            'last_summary': str(row.get('last_summary') or '').strip(),
        }
    except Exception as error:
        print('AI MEMORY READ ERROR:', repr(error))
        return {'recurring_mistakes': [], 'topics_to_review': [], 'weak_areas': [],
                'learning_plan': [], 'last_summary': ''}


def apply_update(student_id: int, update: dict | None) -> None:
    if not isinstance(update, dict):
        return
    current = get_memory(student_id)
    def merged(key):
        incoming = update.get(key)
        if incoming is None:
            return current[key]
        return _clean_list(current[key] + (incoming if isinstance(incoming, list) else []))

    payload = {
        'student_id': student_id,
        'recurring_mistakes': merged('recurring_mistakes'),
        'topics_to_review': merged('topics_to_review'),
        'weak_areas': merged('weak_areas'),
        'learning_plan': merged('learning_plan'),
        'last_summary': str(update.get('last_summary', current['last_summary']) or '').strip()[:1000],
        'updated_at': datetime.now(timezone.utc).isoformat(),
    }
    try:
        supabase.table('ai_learning_memory').upsert(payload, on_conflict='student_id').execute()
    except Exception as error:
        # The bot remains usable if the migration has not been run yet.
        print('AI MEMORY SAVE ERROR:', repr(error))


def format_memory(student_id: int) -> str:
    return json.dumps(get_memory(student_id), ensure_ascii=False)
