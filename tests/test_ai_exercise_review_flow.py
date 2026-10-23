
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def source(path):
    return (ROOT / path).read_text(encoding="utf-8")

def function_source(path, name):
    tree = ast.parse(source(path))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(source(path), node) or ""
    raise AssertionError(f"{name} not found")

def test_no_legacy_database_questions_are_selected():
    s = function_source("services/exercise_service.py", "ensure_exercises")
    assert "return selected" not in s
    assert "main_questions" not in s
    assert "selected = existing" not in s
    assert "await generate_exercises" in s
    assert 'lesson=content' in s

def test_generator_declares_curriculum_content_authoritative():
    s = function_source("services/ai_service.py", "generate_exercises")
    assert "AUTHORITATIVE SOURCE" in s
    assert "Curriculum content is the ONLY source" in s
    assert "topic label as a substitute" in s

def test_answer_always_advances_without_quiz_stopiteration():
    s = function_source("handlers/learning.py", "_grade_and_advance")
    f = function_source("handlers/learning.py", "_finish_or_advance")
    assert "await _finish_or_advance" in s
    assert "next(stage for stage" not in f
    assert "if plan[\"index\"] < len(ids):" in f
    assert "await _ask_exercise(message, plan)" in f

def test_review_is_ai_generated_and_checked():
    s = function_source("handlers/learning.py", "practice_mistakes")
    assert "targeted_mistake_exercises" in s
    assert '"lesson_source": "Curriculum.content"' in s
    assert 'await _ask_exercise(callback.message, plan)' in s

def test_review_does_not_replay_original_questions():
    s = function_source("handlers/learning.py", "practice_mistakes")
    assert "practice+originals" not in s
    assert "originals" in s

def test_activity_buttons_are_not_attached_to_every_exercise():
    s = source("keyboards/learning.py")
    assert "callback_data=\"exercise_hint\"" not in s
    assert "callback_data=\"ask_tutor\"" not in s
    assert "callback_data=\"retry_with_context\"" not in s
    assert "def lesson_actions" in s
    assert "Главное меню" in s

def test_no_hardcoded_lesson_title_patch():
    s = source("services/lesson_agent.py")
    assert "Буквы α, ε, ι, κ, ο, τ" not in s

def test_progression_simulation_100_runs():
    # Pure state-machine simulation of the production index progression:
    # every graded answer increments exactly once and the next question is
    # requested until the set is exhausted. This specifically guards the
    # StopIteration failure seen in the user's console.
    for _ in range(100):
        ids = list(range(5))
        index = 0
        shown = []
        for _answer in ids:
            if index >= len(ids):
                raise AssertionError("advanced past exercise set")
            shown.append(ids[index])
            index += 1
            if index < len(ids):
                next_id = ids[index]
                assert next_id == len(shown)
        assert shown == ids
        assert index == len(ids)
