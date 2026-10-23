from test_menu_progression import *
from services import lesson_agent as agent
from services.curriculum_service import require_content
from handlers import profile
from services import ai_agent

class ContentProfile(unittest.IsolatedAsyncioTestCase):
 def tearDown(self):
  from services.user_session import clear_session
  clear_session(5)
 def test_empty_content_cannot_generate(self):
  with self.assertRaises(ValueError): require_content({'block':'1.1','topic':'Alphabet','content':''})
 async def test_exact_content_reaches_lesson_model(self):
  source={'id':93,'block':'1.1','topic':'TOPIC_ONLY','content':'UNIQUE_DATABASE_CONTENT_Αβ'}
  response=types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=__import__('json').dumps({'sections':[{'id':1,'russian':'Урок Αβ'}]},ensure_ascii=False)))])
  with patch.object(agent,'get_student_id_by_telegram',AsyncMock(return_value=7)),patch.object(agent,'get_current_lesson',AsyncMock()) as fetch,patch.object(agent,'get_student_progress',AsyncMock(return_value={})),patch.object(agent,'get_weak_topics',AsyncMock(return_value=[])),patch('services.learning_history.context',return_value='{"preferred_name":"Анна","goal":"Поездка","daily_minutes":15}'),patch.object(agent.client.chat.completions,'create',AsyncMock(side_effect=[response,types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{\"approved\":true,\"issues\":[]}'))])])) as model:
   self.assertEqual(await agent.generate_lesson(4,lesson_row=source),'📚 1.1 · TOPIC_ONLY\n\nУрок Αβ')
  fetch.assert_not_awaited()
  messages=model.call_args.kwargs['messages']
  payload=__import__('json').loads(messages[-1]['content'])
  self.assertEqual(source['content'],payload['curriculum_content'])
  self.assertNotIn('TOPIC_ONLY',messages[-1]['content'])
  self.assertIn('Анна',messages[-1]['content'])
 async def test_topic_only_route_rejected(self):
  with self.assertRaises(ValueError): await ai_agent.generate_topic_lesson('Alphabet')
 async def test_old_student_no_profile_is_not_asked(self):
  message=types.SimpleNamespace(from_user=types.SimpleNamespace(id=5),answer=AsyncMock())
  with patch('services.student_service.get_student_state',return_value={'current_block':'1.1'}),patch.object(profile.supabase,'table') as table:
   table.return_value.select.return_value.eq.return_value.execute.return_value.data=[]
   await profile.welcome(message,7,is_new_student=False)
  message.answer.assert_not_awaited()
 async def test_new_student_outside_first_block_is_not_asked(self):
  message=types.SimpleNamespace(from_user=types.SimpleNamespace(id=5),answer=AsyncMock())
  with patch('services.student_service.get_student_state',return_value={'current_block':'2.1'}),patch.object(profile.supabase,'table') as table:
   table.return_value.select.return_value.eq.return_value.execute.return_value.data=[]
   await profile.welcome(message,7,is_new_student=True)
  message.answer.assert_not_awaited()
 async def test_new_first_student_gets_one_optional_intro(self):
  message=types.SimpleNamespace(from_user=types.SimpleNamespace(id=5),answer=AsyncMock())
  with patch('services.student_service.get_student_state',return_value={'current_block':'1.1'}),patch.object(profile.supabase,'table') as table:
   table.return_value.select.return_value.eq.return_value.execute.return_value.data=[]
   await profile.welcome(message,7,is_new_student=True)
  message.answer.assert_awaited_once()
  self.assertEqual(message.answer.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data,'skip_introduction')

class RowLookup(unittest.TestCase):
 def test_uses_six_columns_and_lesson_order_not_title(self):
  from services import curriculum_service as service
  db = Mock()
  query = db.table.return_value.select.return_value.eq.return_value.eq.return_value
  query.order.return_value.limit.return_value.execute.return_value.data=[{'block':'1.1','topic':'new title','content':'actual material','lesson_order':1}]
  with patch.object(service,'supabase',db):
   row=service.get_lesson('1.1','old title')
  self.assertEqual(row['content'],'actual material')
  db.table.return_value.select.assert_called_once_with('block,topic,content_type,content,metadata,lesson_order')
  query.order.assert_called_once_with('lesson_order')
  self.assertFalse(any(c.args and c.args[0]=='topic' for c in query.eq.call_args_list))
