"""Course access policy: the first curriculum block (1.1) is the free demo; every later block requires the active $19.90/month subscription."""
from services.curriculum_service import BLOCK_ORDER, get_lesson

SUBSCRIPTION_AMOUNT = "19.90 USD/month"
FREE_DEMO_BLOCK = "1.1"


def first_free_lesson():
    lesson = get_lesson(FREE_DEMO_BLOCK)
    return lesson


def has_access(student, block, topic=None):
    """Server-authoritative access rule: 1.1 is always the free demo; all later
    curriculum blocks require an active subscription. Topic labels never affect
    access and are never used as a source of truth."""
    if str(student.get("subscription_status") or "").lower() == "active":
        return True
    return str(block or "").strip() == FREE_DEMO_BLOCK


def subscription_required(student, block, topic=None):
    return not has_access(student, block, topic)
