import os
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['OPENAI_API_KEY'] = 'offline-test-key'
for key in ('ALL_PROXY','HTTPS_PROXY','HTTP_PROXY','all_proxy','https_proxy','http_proxy'):
    os.environ.pop(key, None)
db = types.ModuleType('services.supabase_client')
db.supabase = Mock()
sys.modules['services.supabase_client'] = db
from services import exercise_service as es, curriculum_service as cs, ai_service as ai
from services.progress_service import summarize, format_progress
from services import ui_manager as ui
from handlers import learning

class Updates(unittest.IsolatedAsyncioTestCase):
    async def test_database_questions_and_nonnull_topic(self):
        stored = [{'id':1,'question':'Existing question','topic':'Reading','block':'0C','correct_answer':'α'}]
        query = Mock()
        query.insert.side_effect = lambda payload: types.SimpleNamespace(execute=lambda: types.SimpleNamespace(data=[{'id':payload['question'],**payload}]))
        generated=[dict(question=f'New {i}',correct_answer='β',type='practice') for i in range(9)]
        with patch.object(es,'get_lesson',return_value=dict(block='0C',topic='Reading',content='Greek letters')), patch.object(es,'list_exercises',return_value=stored), patch.object(es,'generate_exercises',AsyncMock(return_value=generated)) as gen, patch.object(es.supabase,'table',return_value=query):
            result=await es.ensure_exercises('0C',None)
        self.assertEqual(result[0]['id'],1)
        self.assertEqual(len(result),10)
        self.assertTrue(all(r['topic']=='Reading' for r in result))
        self.assertEqual(gen.call_args.kwargs['count'],9)
        self.assertEqual(gen.call_args.kwargs['existing_questions'],['Existing question'])

    async def test_missing_topic_rejected_before_insert(self):
        with patch.object(es,'get_lesson',return_value=dict(content='letters',topic=None)), patch.object(es.supabase,'table') as table:
            with self.assertRaises(ValueError): await es.ensure_exercises('0C',None)
            table.assert_not_called()

    async def test_no_callback_content_deleted(self):
        callback=types.SimpleNamespace(message=types.SimpleNamespace(chat=types.SimpleNamespace(id=1),delete=AsyncMock()),bot=types.SimpleNamespace(send_message=AsyncMock(return_value=types.SimpleNamespace(message_id=1))))
        with patch.object(ui,'magic_transition',AsyncMock()), patch.object(ui,'clear_previous_ui',AsyncMock()):
            await ui.replace_callback_ui(callback,'Menu')
        callback.message.delete.assert_not_awaited()

    def test_next_curriculum_and_new_student(self):
        rows={'0A':[dict(block='0A',topic='Alphabet')],'0B':[dict(block='0B',topic='Pronunciation')],'0C':[dict(block='0C',topic='Reading')]}
        with patch.object(cs,'_get_block_lessons',side_effect=lambda b: rows.get(b,[])):
            self.assertEqual(cs.get_next_lesson('0B','Pronunciation')['block'],'0C')
            self.assertEqual(cs.get_next_lesson('0A',None)['block'],'0A')

    async def test_continue_does_not_skip_ready_lesson(self):
        state=dict(current_block='0B',current_topic='Pronunciation',next_action='start_block_0B')
        callback=types.SimpleNamespace(answer=AsyncMock(),from_user=types.SimpleNamespace(id=10),message=types.SimpleNamespace(answer=AsyncMock()))
        with patch.object(learning,'_context',return_value=({'id':1},state)),patch.object(learning,'update_state') as update,patch.object(learning,'get_lesson',return_value=dict(block='0B',topic='Pronunciation')),patch.object(learning,'generate_lesson',AsyncMock(return_value='Lesson')):
            await learning.continue_learning(callback)
        self.assertEqual(update.call_args.args[1]['current_block'],'0B')

    async def test_completed_test_unlocks_actual_next_topic(self):
        plan=dict(block='0B',exercise_ids=list(range(10)),index=9,total_score=9)
        message=types.SimpleNamespace(answer=AsyncMock())
        with patch.object(learning,'get_next_lesson',return_value=dict(block='0C',topic='Reading')),patch.object(learning,'update_state') as update,patch('services.progress_service.save_session_result'):
            await learning._finish_or_advance(message,{'id':1},{'current_topic':'Pronunciation'},plan)
        self.assertEqual(update.call_args.args[1]['current_topic'],'Reading')
        self.assertEqual(update.call_args.args[1]['current_block'],'0C')

    def test_statistics_timezones_and_distinct_words(self):
        attempts=[dict(result='correct',user_answer='καλημέρα',created_at='2026-09-30T23:00:00Z'),dict(result='correct',user_answer='Καλημερα',created_at='2026-10-01T08:00:00Z')]
        sessions=[dict(score=9,total=10,kind='exercise',block='0A',topic='Alphabet')]
        p=summarize({'current_block':'0B'},attempts,sessions,date(2026,10,1),ZoneInfo('Europe/Prague'))
        p['history_available']=True
        self.assertEqual(p['words'],1)
        self.assertEqual(p['today'],2)
        self.assertEqual(p['completed'],1)
        self.assertEqual(p['accuracy'],100)
        self.assertIn('Today’s goal',format_progress(p))

    async def test_semantic_grading_policy_sent_to_ai(self):
        response=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"result":"correct","feedback":"Good"}'))])
        with patch.object(ai.client.chat.completions,'create',AsyncMock(return_value=response)) as create:
            result=await ai.grade_answer('Say hello','γεια σου','γεια σου','hello')
        self.assertEqual(result['result'],'correct')
        self.assertIn('missing accents',create.call_args.kwargs['messages'][1]['content'])

    async def test_grading_failure_not_counted_incorrect(self):
        with patch.object(es,'grade_answer',AsyncMock(side_effect=RuntimeError('offline'))),patch.object(es,'lesson_context',return_value='letters'):
            with self.assertRaises(RuntimeError): await es.evaluate(dict(question='Q',correct_answer='α'),'β')

    async def test_voice_help_transcribes_auto_and_replies_audio(self):
        from handlers import voice
        message=types.SimpleNamespace(voice=object(),from_user=types.SimpleNamespace(id=12),
            bot=object(),chat=types.SimpleNamespace(id=12),answer=AsyncMock())
        with patch.object(voice,'get_session',return_value={'mode':'tutor_chat','voice_russian':True}),patch.object(voice,'transcribe_greek_voice',AsyncMock(return_value='Что значит γεια σου?')) as transcribe,patch.object(voice,'get_student',return_value=None),patch.object(voice,'process_user_request',AsyncMock(return_value='γεια σου означает привет.')),patch.object(voice,'classify_tutor_topic',AsyncMock(return_value={'has_topic':False})),patch.object(voice,'_send_voice',AsyncMock()) as send:
            await voice.voice_message_handler(message)
        self.assertIsNone(transcribe.call_args.kwargs['language'])
        send.assert_awaited_once()
        self.assertIn('γεια σου',send.call_args.args[2])

    async def test_tutor_prompt_requires_russian_and_greek_script(self):
        from services import ai_agent as agent
        response=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='Привет'))])
        with patch.object(agent,'get_student_id_by_telegram',AsyncMock(return_value=1)),patch.object(agent.client.chat.completions,'create',AsyncMock(return_value=response)) as create:
            await agent.process_user_request(987,'Что значит γεια σου?', response_language='Russian')
        system=create.call_args.kwargs['messages'][0]['content']
        self.assertIn('all explanations must be in Russian',system)
        self.assertIn('Keep them in Greek script',system)

    async def test_text_tutor_keeps_english_default(self):
        from services import ai_agent as agent
        response=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='Hello'))])
        with patch.object(agent,'get_student_id_by_telegram',AsyncMock(return_value=1)),patch.object(agent.client.chat.completions,'create',AsyncMock(return_value=response)) as create:
            await agent.process_user_request(987,'Explain this word')
        system=create.call_args.kwargs['messages'][0]['content']
        self.assertIn('explanations must be in English, regardless of earlier conversation language',system)
        self.assertNotIn('For this AI Help voice question',system)

    def test_all_handlers_import(self):
        import handlers.menu, handlers.tutor, handlers.voice, handlers.game_menu

if __name__=='__main__': unittest.main()
