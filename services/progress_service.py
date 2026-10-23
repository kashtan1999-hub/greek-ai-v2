"""Single source of truth for learner dashboard/progress statistics."""
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from services.supabase_client import supabase
from services.curriculum_service import BLOCK_ORDER


def _rows(table, student_id):
    result = []
    for start in range(0, 1000000, 1000):
        page = (supabase.table(table).select('*').eq('student_id', student_id)
                .order('id').range(start, start + 999).execute().data or [])
        result.extend(page)
        if len(page) < 1000:
            break
    return result


def _stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def save_session_result(student_id, topic, block, score, total, kind='exercise'):
    return supabase.table('learning_session_results').insert({
        'student_id': student_id, 'topic': topic, 'block': block,
        'score': int(score), 'total': int(total), 'kind': kind,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }).execute()


def _event_activity(activity_rows, attempts, now, tz):
    """Combine durable AI/activity events with answer submissions for the 7-day graph."""
    counts = {now.date() - timedelta(days=i): 0 for i in range(7)}
    for row in activity_rows:
        stamp = _stamp(row.get('created_at'))
        if stamp:
            day = stamp.astimezone(tz).date()
            if day in counts:
                counts[day] += 1
    # Answers are a distinct learner action and remain visible even if the old
    # attempts table is used by the legacy exercise flow.
    for row in attempts:
        stamp = _stamp(row.get('created_at'))
        if stamp:
            day = stamp.astimezone(tz).date()
            if day in counts:
                counts[day] += 1
    return [{'label': day.strftime('%d.%m'), 'count': counts[day]} for day in sorted(counts)]


def _correct_words(attempts):
    words = set()
    for row in attempts:
        if row.get('result') != 'correct':
            continue
        value = unicodedata.normalize('NFD', str(row.get('user_answer') or '').casefold())
        value = ''.join(c for c in value if not unicodedata.combining(c))
        words.update(w for w in re.findall(r'[α-ω]+', value) if len(w) > 1)
    return len(words)


async def get_student_progress(student_id):
    state_rows = _rows('student_state', student_id)
    state = state_rows[0] if state_rows else {}
    attempts = _rows('attempts', student_id)
    try:
        sessions = _rows('learning_session_results', student_id)
        history_available = True
    except Exception:
        sessions, history_available = [], False
    try:
        activity_rows = _rows('learning_activity', student_id)
    except Exception:
        activity_rows = []
    try:
        paths = _rows('learning_paths', student_id)
    except Exception:
        paths = []
    try:
        errors = _rows('learning_errors', student_id)
    except Exception:
        errors = []

    tz = ZoneInfo(os.getenv('LEARNING_TIMEZONE', os.getenv('PROGRESS_TIMEZONE', 'Europe/Athens')))
    now_utc = datetime.now(timezone.utc)
    today = now_utc.astimezone(tz).date()

    def is_today(row):
        stamp = _stamp(row.get('created_at'))
        return bool(stamp and stamp.astimezone(tz).date() == today)

    correct = sum(1 for row in attempts if row.get('result') == 'correct')
    answer_today = sum(1 for row in attempts if is_today(row))
    ai_today = sum(1 for row in activity_rows if row.get('event_type') == 'ai_conversation' and is_today(row))
    total_interactions_today = sum(1 for row in activity_rows if is_today(row)) + answer_today

    # Only assessment sessions count as tests. Exercise/lesson completions are
    # separate from testing and should never inflate the test counter.
    assessment_sessions = [s for s in sessions if str(s.get('kind') or '').lower() == 'assessment']
    passed_tests = [s for s in assessment_sessions if s.get('total') and float(s.get('score', 0)) / float(s['total']) >= 0.8]

    # A lesson is completed by a passed exercise session or an AI-confirmed
    # conversational lesson completion. Do not count a mere lesson view.
    completed_blocks = set()
    for row in sessions:
        kind = str(row.get('kind') or '').lower()
        if kind in {'exercise', 'lesson'} and row.get('block') in BLOCK_ORDER and row.get('total'):
            if float(row.get('score', 0)) / float(row['total']) >= 0.8:
                completed_blocks.add(row.get('block'))
    for row in paths:
        if row.get('block') in BLOCK_ORDER and int(row.get('stage') or 0) >= 1:
            completed_blocks.add(row.get('block'))

    total_lessons = len(BLOCK_ORDER)
    completed = len(completed_blocks)
    percent = round(completed / total_lessons * 100, 1) if total_lessons else 0
    retained = len({r.get('block') for r in paths if r.get('block') in BLOCK_ORDER and r.get('retained')})

    goal = max(1, int(os.getenv('DAILY_EXERCISE_GOAL', '10')))
    accuracy = round(correct / len(attempts) * 100) if attempts else 0
    sessions.sort(key=lambda r: str(r.get('created_at') or ''))
    recent_scores = [
        {'label': f"Тест {i + 1}", 'score': round(float(row['score']) / float(row['total']) * 100)}
        for i, row in enumerate(assessment_sessions[-5:]) if row.get('total')
    ]

    billing_end = None
    subscription_status = 'unknown'
    try:
        student_row = (supabase.table('Students').select('subscription_status')
                       .eq('id', student_id).limit(1).execute().data or [])
        if student_row:
            subscription_status = str(student_row[0].get('subscription_status') or 'free').lower()
        from services.stripe_service import profile
        billing_end = profile(student_id).get('current_period_end')
    except Exception:
        pass

    active_dates = set()
    for row in attempts + activity_rows:
        stamp = _stamp(row.get('created_at'))
        if stamp:
            active_dates.add(stamp.astimezone(tz).date())
    streak = 0
    cursor = today
    if cursor not in active_dates:
        cursor -= timedelta(days=1)
    while cursor in active_dates:
        streak += 1
        cursor -= timedelta(days=1)

    review_due = 0
    now_iso = now_utc.isoformat()
    for row in paths:
        due = _stamp(row.get('review_due_at'))
        if row.get('block') in BLOCK_ORDER and due and due <= now_utc:
            review_due += 1

    history = []
    try:
        history = _rows('learning_history', student_id)
        history.sort(key=lambda row: str(row.get('created_at') or ''))
    except Exception:
        pass

    return {
        'state': state,
        'words': _correct_words(attempts),
        'attempts': len(attempts),
        'accuracy': accuracy,
        'today': answer_today,
        'goal': goal,
        'completed': completed,
        'total_lessons': total_lessons,
        'tests': len(assessment_sessions),
        'passed': len(passed_tests),
        'percent': percent,
        'last_score': (round(float(assessment_sessions[-1]['score']) / float(assessment_sessions[-1]['total']) * 100)
                       if assessment_sessions and assessment_sessions[-1].get('total') else None),
        'history_available': history_available,
        'retained': retained,
        'retained_percent': round(retained / total_lessons * 100, 1) if total_lessons else 0,
        'daily_activity': _event_activity(activity_rows, attempts, now_utc.astimezone(tz), tz),
        'recent_scores': recent_scores,
        'date_label': now_utc.astimezone(tz).strftime('%d %b %Y'),
        'timezone': str(tz),
        'ai_turns_today': ai_today,
        'interactions_today': total_interactions_today,
        'subscription_status': subscription_status,
        'billing_period_end': billing_end,
        'open_mistakes': sum(not bool(row.get('resolved')) for row in errors),
        'review_due': review_due,
        'streak': streak,
        'recent_history': history[-4:][::-1],
    }


def format_progress(p):
    state = p.get('state') or {}
    goal = max(1, int(p.get('goal') or 10))
    filled = min(10, int(p.get('today', 0) / goal * 10))
    bar = '🟩' * filled + '⬜' * (10 - filled)
    billing = p.get('billing_period_end') or '—'
    return (
        '📊 Learning Progress\n\n'
        f"🔐 Access: {str(p.get('subscription_status') or 'unknown').upper()}\n"
        f"💳 Paid until: {billing}\n\n"
        f"📚 Current lesson: {state.get('current_block') or '1.1'}\n"
        f"Topic: {state.get('current_topic') or 'Not started'}\n"
        f"Lesson progress: {state.get('lesson_progress') or 0}%\n\n"
        f"🤖 AI conversations today: {p.get('ai_turns_today', 0)}\n"
        f"✍️ Answers today: {p.get('today', 0)}\n"
        f"🎯 Goal: {bar} {p.get('today', 0)}/{goal}\n\n"
        f"📖 Lessons completed: {p.get('completed', 0)}/{p.get('total_lessons', len(BLOCK_ORDER))}\n"
        f"📈 Course progress: {p.get('percent', 0)}%\n"
        f"🧪 Assessments: {p.get('tests', 0)} completed · {p.get('passed', 0)} passed\n"
        f"❌ Open mistakes: {p.get('open_mistakes', 0)} · 🔁 Reviews due: {p.get('review_due', 0)}\n"
    )

format_progress_message = format_progress
