"""Durable learning events. Run sql/client_updates.sql before using these counters."""
import logging
from services.supabase_client import supabase
from services.student_service import utc_now

logger = logging.getLogger(__name__)

def record_activity(student_id, event_type, block=None, topic=None, details=None):
    try:
        supabase.table('learning_activity').insert({
            'student_id': student_id, 'event_type': event_type,
            'block': block, 'topic': topic, 'details': details or {}, 'created_at': utc_now(),
        }).execute()
        return True
    except Exception:
        # Activity tracking failure must not invalidate a delivered lesson/test.
        logger.exception('Learning activity could not be saved; check client_updates.sql')
        return False
