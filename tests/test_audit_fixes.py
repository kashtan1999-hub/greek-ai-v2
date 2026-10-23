import os, sys, types, unittest, asyncio, tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('OPENAI_API_KEY','offline-test')
if 'services.supabase_client' not in sys.modules:
    m=types.ModuleType('services.supabase_client');m.supabase=Mock();sys.modules['services.supabase_client']=m
from handlers import learning, voice_lesson, profile
from services import progress_service, stripe_service as stripe
from services.lesson_stages import eligible_to_advance, build_stages

class AuditFixes(unittest.IsolatedAsyncioTestCase):
    def callback(self,data='voice_lesson'):
        msg=types.SimpleNamespace(chat=types.SimpleNamespace(id=10,type='private'),answer=AsyncMock(),answer_voice=AsyncMock())
        wait=types.SimpleNamespace(edit_text=AsyncMock(),delete=AsyncMock())
        msg.answer.return_value=wait
        return types.SimpleNamespace(data=data,from_user=types.SimpleNamespace(id=10),message=msg,answer=AsyncMock()),wait
    async def test_audio_has_actions_and_cleans_file(self):
        cb,wait=self.callback();f=tempfile.NamedTemporaryFile(delete=False);f.close()
        with patch.object(voice_lesson,'get_student',return_value={'id':20}),patch.object(voice_lesson,'get_student_state',return_value={'current_block':'1.1'}),patch.object(voice_lesson,'has_access',return_value=True),patch.object(voice_lesson,'create_voice_lesson',AsyncMock(return_value=(f.name,{'topic':'Буквы'}))):
            await voice_lesson.voice_lesson(cb)
        markup=cb.message.answer_voice.call_args.kwargs['reply_markup']
        self.assertIn('start_exercises',[b.callback_data for row in markup.inline_keyboard for b in row])
        self.assertFalse(Path(f.name).exists())
    async def test_audio_denied_before_generation(self):
        cb,wait=self.callback()
        with patch.object(voice_lesson,'get_student',return_value={'id':20}),patch.object(voice_lesson,'get_student_state',return_value={'current_block':'1.2'}),patch.object(voice_lesson,'has_access',return_value=False),patch.object(voice_lesson,'create_voice_lesson',AsyncMock()) as generate:
            await voice_lesson.voice_lesson(cb)
        generate.assert_not_awaited();cb.message.answer_voice.assert_not_awaited()
        self.assertIn('🔒',wait.edit_text.call_args.args[0])
    async def test_audio_send_failure_keeps_error_message_and_cleans_file(self):
        cb,wait=self.callback();f=tempfile.NamedTemporaryFile(delete=False);f.close();cb.message.answer_voice.side_effect=RuntimeError('send failed')
        with patch.object(voice_lesson,'get_student',return_value={'id':20}),patch.object(voice_lesson,'get_student_state',return_value={}),patch.object(voice_lesson,'has_access',return_value=True),patch.object(voice_lesson,'create_voice_lesson',AsyncMock(return_value=(f.name,{'topic':'Буквы'}))):
            await voice_lesson.voice_lesson(cb)
        self.assertFalse(Path(f.name).exists());wait.edit_text.assert_awaited_once();wait.delete.assert_not_awaited()
    async def test_concurrent_duplicate_option_only_graded_once(self):
        cb,_=self.callback('exercise_option:0:0')
        plan={'mode':'exercise','index':0,'exercise_ids':[1,2]}
        async def grade(*args,**kwargs):
            await asyncio.sleep(0)
            plan['index']=1
        with patch.object(learning,'_context',return_value=({'id':20},{'active_plan':plan})),patch.object(learning,'get_exercise',return_value={'question':'Какая буква?\nA) α\nB) β'}),patch.object(learning,'_extract_options',return_value=['α','β']),patch.object(learning,'_grade_and_advance',AsyncMock(side_effect=grade)) as check:
            await asyncio.gather(learning.exercise_option(cb),learning.exercise_option(cb))
        self.assertEqual(check.await_count,1)
        self.assertEqual(check.call_args.kwargs['telegram_user_id'],10)
    async def test_course_selection_cannot_skip_locked_block(self):
        cb,_=self.callback('course_select:1.3')
        with patch('services.curriculum_service.get_lesson',return_value={'block':'1.3','topic':'Letters'}),patch.object(profile,'get_student',return_value={'id':20}),patch('services.access_service.has_access',return_value=True),patch.object(progress_service,'get_student_progress',AsyncMock(return_value={'completed_blocks':[]})),patch('services.student_service.get_student_state',return_value={'current_block':'1.1'}),patch('services.student_service.update_state') as update:
            await profile.select_course(cb)
        update.assert_not_called();self.assertIn('🔒',cb.message.answer.call_args.args[0])
    async def test_course_next_selection_allowed_after_saved_pass(self):
        cb,_=self.callback('course_select:1.2')
        with patch('services.curriculum_service.get_lesson',return_value={'block':'1.2','topic':'Letters'}),patch.object(profile,'get_student',return_value={'id':20}),patch('services.access_service.has_access',return_value=True),patch.object(progress_service,'get_student_progress',AsyncMock(return_value={'completed_blocks':['1.1']})),patch('services.student_service.get_student_state',return_value={'current_block':'1.1'}),patch('services.student_service.update_state') as update:
            await profile.select_course(cb)
        self.assertEqual(update.call_args.args[1]['current_block'],'1.2')
    def test_hint_free_quiz_pass_not_blocked_by_practice_errors(self):
        plan={'stages':build_stages(10),'stage_scores':{'mini':1,'understanding':1},'quiz_hint_used':False}
        self.assertTrue(eligible_to_advance(plan,80));self.assertFalse(eligible_to_advance(plan,79))
        plan['quiz_hint_used']=True;self.assertFalse(eligible_to_advance(plan,100))
    async def test_completed_checkout_with_missing_subscription_recovers(self):
        settings={'STRIPE_SECRET_KEY':'offline','STRIPE_WEBHOOK_SECRET':'offline','PAYMENT_PUBLIC_BASE_URL':'https://example.com'}
        responses=[{'status':'complete','subscription':'sub_old'},{'id':'cus_good'},{'id':'cs_new','url':'https://checkout.stripe.com/new'}]
        with patch.dict(os.environ,settings),patch.object(stripe,'profile',return_value={'checkout_session_id':'cs_old','customer_id':'cus_good'}),patch.object(stripe,'sync_subscription',AsyncMock(side_effect=stripe.StripeRequestError(404,'resource_missing'))),patch.object(stripe,'save_profile'),patch.object(stripe,'ensure_monthly_price',AsyncMock(return_value='price_1990')),patch.object(stripe,'stripe_request',AsyncMock(side_effect=responses)):
            self.assertEqual(await stripe.create_checkout(20,10),'https://checkout.stripe.com/new')

class DeliveryRecovery(unittest.IsolatedAsyncioTestCase):
    async def test_loading_indicator_failure_does_not_block_handler(self):
        from services.loading import LoadingMiddleware
        from aiogram.types import CallbackQuery, Message, Chat, User
        cb=CallbackQuery(id='callback',from_user=User(id=10,is_bot=False,first_name='Test'),chat_instance='chat',data='next_lesson',message=Message(message_id=1,date=0,chat=Chat(id=10,type='private')))
        handler=AsyncMock(return_value='handled')
        with patch.object(CallbackQuery,'answer',AsyncMock(side_effect=RuntimeError('expired'))):
            result=await LoadingMiddleware()(handler,cb,{})
        self.assertEqual(result,'handled');handler.assert_awaited_once()
    async def test_feedback_send_failure_still_advances_saved_answer(self):
        message=types.SimpleNamespace(from_user=types.SimpleNamespace(id=10),answer=AsyncMock(side_effect=RuntimeError('delivery failed')))
        plan={'mode':'exercise','index':0,'exercise_ids':[1]}
        query=Mock();query.insert.return_value=query;query.update.return_value=query;query.eq.return_value=query;query.execute.return_value=types.SimpleNamespace(data=[{'id':1}])
        with patch.object(learning,'_has_access',return_value=True),patch.object(learning,'get_exercise',return_value={'id':1,'block':'1.1','question':'Q','correct_answer':'A'}),patch.object(learning,'evaluate',AsyncMock(return_value={'result':'correct','feedback':'Верно','score':1})),patch.object(learning,'save_attempt'),patch.object(learning,'log_turn'),patch('services.learning_history.reinforce_mistake'),patch('services.supabase_client.supabase.table',return_value=query),patch.object(learning,'_finish_or_advance',AsyncMock()) as finish:
            await learning._grade_and_advance(message,{'id':20},{'current_topic':'Letters'},plan,'A')
        finish.assert_awaited_once();self.assertEqual(plan['total_score'],1)
