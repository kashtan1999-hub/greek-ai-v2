import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class FinalFlowRequirementTests(unittest.TestCase):
    def read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_all_python_files_compile(self):
        for path in ROOT.rglob("*.py"):
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_first_topic_is_free_and_next_learning_has_payment_gate(self):
        access = self.read("services/access_service.py")
        learning = self.read("handlers/learning.py")
        self.assertIn("def first_free_lesson", access)
        self.assertIn('FREE_DEMO_BLOCK = "1.1"', access)
        self.assertIn('return str(block or "").strip() == FREE_DEMO_BLOCK', access)
        self.assertIn("Первый урок — бесплатное демо", learning)
        self.assertIn("19,90 USD в месяц", learning)
        self.assertIn('callback_data="subscription"', learning)
        self.assertIn("not has_access(student", self.read("handlers/tutor.py"))
        self.assertIn("not has_access(student", self.read("handlers/voice.py"))

    def test_monthly_payment_confirmation_and_period_are_persisted(self):
        stripe = self.read("services/stripe_service.py")
        sql = self.read("sql/client_updates.sql")
        self.assertIn("'current_period_end'", stripe)
        self.assertIn("'last_payment_id'", stripe)
        self.assertIn("_send_payment_alert", stripe)
        self.assertIn("last_payment_id", sql)
        self.assertIn("current_period_end", sql)
        self.assertIn("Следующее списание", stripe)

    def test_teaching_starts_with_explanation_before_practice(self):
        agent = self.read("services/ai_agent.py")
        policy = self.read("services/teaching_policy.py")
        self.assertIn("Teach before testing", agent)
        self.assertIn("teach a small useful piece before asking", policy)
        self.assertIn("Do not start with a bare quiz question", agent)
        self.assertIn("public.Curriculum.content", agent)
        self.assertIn("The field named CURRICULUM CONTENT", agent)

if __name__ == "__main__":
    unittest.main()
