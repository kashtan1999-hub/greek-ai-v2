import unittest
from services.content_lesson import validate_sections

class SectionIdentifiers(unittest.TestCase):
    def test_string_identifier(self):
        self.assertEqual(validate_sections([{'id':2,'source':'α'}], {'sections':[{'id':'2','russian':'Буква α'}]}), ['Буква α'])
    def test_order_restored(self):
        self.assertEqual(validate_sections([{'id':1,'source':'α'},{'id':2,'source':'β'}], {'sections':[{'id':2,'russian':'Буква β'},{'id':1,'russian':'Буква α'}]}), ['Буква α','Буква β'])
    def test_missing_greek_rejected(self):
        with self.assertRaises(ValueError):
            validate_sections([{'id':1,'source':'α'}], {'sections':[{'id':1,'russian':'Буква'}]})
    def test_duplicate_rejected(self):
        with self.assertRaises(ValueError):
            validate_sections([{'id':1,'source':'α'},{'id':2,'source':'β'}], {'sections':[{'id':1,'russian':'α'},{'id':1,'russian':'β'}]})

class ResultMenu(unittest.IsolatedAsyncioTestCase):
    async def test_pass_has_one_navigation_button_and_main_menu_kept(self):
        import test_menu_progression as setup
        from unittest.mock import patch, AsyncMock
        from keyboards.main_menu import get_main_menu
        message = setup.types.SimpleNamespace(answer=AsyncMock())
        plan = dict(block='1.1', index=9, exercise_ids=list(range(10)), total_score=9)
        with patch('services.learning_history.record_completion', return_value={'review_due_at':'2026-10-06'}), patch.object(setup.learning,'save_session_result'), patch.object(setup.learning,'get_next_lesson',return_value={'block':'1.2','topic':'Next'}), patch.object(setup.learning,'update_state'):
            await setup.learning._finish_or_advance(message,{'id':1},{'current_topic':'Alphabet'},plan)
        data = [b.callback_data for row in message.answer.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
        self.assertEqual(data.count('next_lesson'),1)
        self.assertNotIn('continue_learning',data)
        self.assertIn('continue_learning',[b.callback_data for row in get_main_menu().inline_keyboard for b in row])
    def test_tutor_has_exact_two_actions(self):
        import test_menu_progression
        from handlers.tutor import tutor_topic_actions
        self.assertEqual([b.callback_data for row in tutor_topic_actions().inline_keyboard for b in row],['tutor_more_info','main_menu'])
