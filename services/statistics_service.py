"""Compatibility wrapper: dashboard statistics are now owned by progress_service."""
from services.progress_service import get_student_progress

async def build_student_statistics(student_id: int):
    return await get_student_progress(student_id)

