import hashlib
import logging

from services.supabase_client import supabase


from services.course_sequence import BLOCK_ORDER


def get_lesson(block: str, topic: str | None = None):
    query = (
        supabase.table("Curriculum")
        .select("block,topic,content_type,content,metadata,lesson_order")
        .eq("block", block)
        .eq("content_type", "lesson")
    )
    # Curriculum.content is the authoritative teaching source. Topic is only a
    # display label and is never used to generate the lesson or identify content.
    data = query.order("lesson_order").limit(2).execute().data or []
    if len(data) > 1:
        raise ValueError(f'Duplicate Curriculum lesson rows for block {block}; remove duplicate imports')
    return data[0] if data else None


def _get_block_lessons(block: str):
    data = (
        supabase.table("Curriculum")
        .select("block,topic,content_type,content,metadata,lesson_order")
        .eq("block", block)
        .eq("content_type", "lesson")
        .order("lesson_order")
        .execute()
        .data or []
    )
    return data


def get_next_lesson(block: str, current_topic: str | None = None):
    """
    Returns only the next curriculum lesson.
    Never falls back to the first lesson of the same block.
    """

    rows = _get_block_lessons(block)

    if not current_topic and rows:
        return rows[0]

    if current_topic:
        for index, row in enumerate(rows):
            if row.get("topic") == current_topic:
                if index + 1 < len(rows):
                    return rows[index + 1]
                break

    # move to next block when current block finishes
    try:
        index = BLOCK_ORDER.index(block)
    except ValueError:
        raise ValueError("Legacy course block: select a new curriculum lesson before continuing.")

    if index + 1 < len(BLOCK_ORDER):
        next_block = BLOCK_ORDER[index + 1]
        next_rows = _get_block_lessons(next_block)
        if next_rows:
            return next_rows[0]

    # first lesson only for a brand new student
    if not current_topic and rows:
        return rows[0]

    return None


def lesson_context(block: str, topic: str | None = None, limit: int | None = None):
    lesson = get_lesson(block, topic)
    if not lesson:
        return ""
    content, _ = require_content(lesson)
    return content if limit is None else content[:limit]


def split_message(text: str, max_length: int = 3800):
    text = text.strip()
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, max_length)
        if cut < max_length // 2:
            cut = max(text.rfind(" ", 0, max_length), max_length)
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    return chunks


def require_content(lesson):
    if not lesson or lesson.get('block') not in BLOCK_ORDER:
        raise ValueError("Нет урока в текущем Curriculum.")
    content = lesson.get('content')
    if not isinstance(content, str) or not content.strip():
        raise ValueError("В Curriculum пустой content. Сначала добавьте материал урока.")
    digest = hashlib.sha256(content.encode('utf-8')).hexdigest()
    logging.getLogger(__name__).info("Curriculum source lesson_order=%s block=%s content_chars=%s sha256=%s", lesson.get('lesson_order'), lesson['block'], len(content), digest)
    return content, digest
