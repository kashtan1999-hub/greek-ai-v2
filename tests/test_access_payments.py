import os
os.environ["OPENAI_API_KEY"]="offline-test"
for k in ("ALL_PROXY","HTTPS_PROXY","HTTP_PROXY","all_proxy","https_proxy","http_proxy"):os.environ.pop(k,None)
import unittest
from unittest.mock import patch, AsyncMock
import sys, types
from unittest.mock import Mock
db=types.ModuleType('services.supabase_client');db.supabase=Mock();sys.modules['services.supabase_client']=db
from services import access_service as access, stripe_service as stripe
from services.payment_server import start_payment_server

class AccessTests(unittest.TestCase):
 def test_free_first_block_ignores_stale_topic_label(self):
  with patch.object(access, 'first_free_lesson', return_value={'block':'1.1','topic':'Alphabet','content':'SOURCE alphabet material'}):
   user={'subscription_status':'free','trial_expires_at':'2099-01-01T00:00:00Z'}
   self.assertTrue(access.has_access(user,'1.1','Alphabet'))
   self.assertTrue(access.has_access(user,'1.1','Reading'))
   self.assertFalse(access.has_access(user,'1.2','Sounds'))
   self.assertFalse(access.has_access({'subscription_status':'past_due'},'1.2','Sounds'))
   self.assertTrue(access.has_access({'subscription_status':'active'},'1.2','Sounds'))
 def test_incomplete_settings_disable_checkout(self):
  with patch.dict('os.environ', {'STRIPE_SECRET_KEY':'sk_test_offline','STRIPE_WEBHOOK_SECRET':'','PAYMENT_PUBLIC_BASE_URL':''}):
   self.assertFalse(stripe.payments_ready())

class HandlerAccessTests(unittest.IsolatedAsyncioTestCase):
 async def test_paid_exercises_blocked_before_generation(self):
  from handlers import learning
  callback=types.SimpleNamespace(answer=AsyncMock(),from_user=types.SimpleNamespace(id=1),message=types.SimpleNamespace(answer=AsyncMock()))
  with patch.object(learning,'_context',return_value=({'id':1},{'current_block':'1.1','current_topic':'Reading'})),patch.object(learning,'_has_access',return_value=False),patch.object(learning,'ensure_exercises',AsyncMock()) as generate:
   await learning.start_exercises(callback)
  generate.assert_not_awaited()
  self.assertIn('19,90',callback.message.answer.call_args.args[0])
 async def test_main_menu_includes_announcement(self):
  from services import dashboard_menu as dm
  from keyboards.game_menu import game_main_menu
  msg=types.SimpleNamespace(answer_photo=AsyncMock(),answer=AsyncMock())
  with patch.object(dm,'get_student_progress',AsyncMock(return_value={'state':{}})),patch.object(dm,'render_dashboard',return_value=b'png'):
   await dm.send_dashboard(msg,1,game_main_menu())
  self.assertIn('гражданства Греции',msg.answer_photo.call_args.kwargs['caption'])
 async def test_unconfigured_webhook_fails_closed(self):
  from services.payment_server import webhook
  request=types.SimpleNamespace(read=AsyncMock())
  with patch('services.payment_server.payments_ready',return_value=False):
   response=await webhook(request)
  self.assertEqual(response.status,503)
  request.read.assert_not_awaited()
