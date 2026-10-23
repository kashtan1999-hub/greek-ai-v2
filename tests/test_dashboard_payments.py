import os
import sys
import types
import json
import hmac
import hashlib
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
if 'services.supabase_client' not in sys.modules:
    db=types.ModuleType('services.supabase_client');db.supabase=Mock();sys.modules['services.supabase_client']=db
from services import stripe_service as stripe
from services.dashboard_image import render_dashboard

SETTINGS={'STRIPE_SECRET_KEY':'sk_test_offline','STRIPE_WEBHOOK_SECRET':'whsec_offline','PAYMENT_PUBLIC_BASE_URL':'https://example.com'}


def subscription(status='active',paid=True):
    return {'id':'sub_1','status':status,'customer':'cus_1','metadata':{'app':'greek_tutor','student_id':'1'},
        'latest_invoice':{'paid':paid},'items':{'data':[{'quantity':1,'price':{'unit_amount':1990,'currency':'usd','recurring':{'interval':'month','interval_count':1}}}]}}


class PaymentTests(unittest.IsolatedAsyncioTestCase):
    def test_monthly_amount_and_student_binding(self):
        with patch.dict(os.environ,SETTINGS):data=stripe.checkout_data(5,10)
        self.assertEqual(data['line_items[0][price_data][unit_amount]'],'1990')
        self.assertEqual(data['line_items[0][price_data][currency]'],'usd')
        self.assertEqual(data['line_items[0][price_data][recurring][interval]'],'month')
        self.assertEqual(data['subscription_data[metadata][student_id]'],'5')
        self.assertEqual(data['mode'],'subscription')

    def test_signature_and_tamper_and_replay(self):
        body=b'{"type":"invoice.paid"}'
        sig=hmac.new(b'whsec_offline',b'1000.'+body,hashlib.sha256).hexdigest()
        header='t=1000,v1='+sig
        self.assertEqual(stripe.verified_event(body,header,'whsec_offline',1000)['type'],'invoice.paid')
        with self.assertRaises(ValueError):stripe.verified_event(body+b' ',header,'whsec_offline',1000)
        with self.assertRaises(ValueError):stripe.verified_event(body,header,'whsec_offline',1400)
        with self.assertRaises(ValueError):stripe.verified_event(body,header,'wrong',1000)

    def test_access_requires_paid_expected_plan(self):
        self.assertTrue(stripe.paid_access(subscription()))
        self.assertFalse(stripe.paid_access(subscription(paid=False)))
        self.assertFalse(stripe.paid_access(subscription(status='canceled')))
        s=subscription();s['items']['data'][0]['price']['unit_amount']=100
        self.assertFalse(stripe.paid_access(s))
        s=subscription();s['items']['data'][0]['price']['recurring']['interval']='year'
        self.assertFalse(stripe.paid_access(s))

    async def test_repeated_checkout_reuses_existing_link(self):
        with patch.object(stripe,'profile',return_value={'checkout_session_id':'cs_1'}),patch.object(stripe,'stripe_request',AsyncMock(return_value={'status':'open','url':'https://checkout.stripe.com/test'})) as req:
            url=await stripe.create_checkout(1,10)
        self.assertEqual(url,'https://checkout.stripe.com/test')
        self.assertEqual(req.call_args.args[0],'GET')

    async def test_checkout_create_has_idempotency(self):
        with patch.dict(os.environ,SETTINGS),patch.object(stripe,'ensure_monthly_price',AsyncMock(return_value='price_1990')),patch.object(stripe,'profile',return_value={'checkout_request_id':'request1'}),patch.object(stripe,'save_profile') as save,patch.object(stripe,'stripe_request',AsyncMock(return_value={'id':'cs_1','url':'https://checkout.stripe.com/test'})) as req:
            await stripe.create_checkout(1,10)
        self.assertEqual(req.call_args.kwargs['idempotency'],'checkout-request1')
        self.assertEqual(save.call_args.args[1]['checkout_session_id'],'cs_1')

    async def test_unpaid_webhook_revokes_access(self):
        query=Mock();query.update.return_value=query;query.eq.return_value=query
        with patch.object(stripe,'stripe_request',AsyncMock(return_value=subscription(status='past_due',paid=False))),patch.object(stripe,'profile',return_value={}),patch.object(stripe,'save_profile'),patch.object(stripe.supabase,'table',return_value=query):
            await stripe.sync_subscription('sub_1')
        self.assertEqual(query.update.call_args.args[0]['subscription_status'],'past_due')

    async def test_paid_webhook_activates_access(self):
        query=Mock();query.update.return_value=query;query.eq.return_value=query
        with patch.object(stripe,'stripe_request',AsyncMock(return_value=subscription())),patch.object(stripe,'profile',return_value={}),patch.object(stripe,'save_profile'),patch.object(stripe.supabase,'table',return_value=query):
            await stripe.sync_subscription('sub_1')
        self.assertEqual(query.update.call_args.args[0]['subscription_status'],'active')

    async def test_old_subscription_cannot_revoke_new_active(self):
        with patch.object(stripe,'stripe_request',AsyncMock(side_effect=[subscription(status='canceled'),subscription()])),patch.object(stripe,'profile',return_value={'subscription_id':'sub_new'}),patch.object(stripe,'save_profile') as save:
            await stripe.sync_subscription('sub_old')
        save.assert_not_called()

    async def test_current_invoice_schema(self):
        event={'type':'invoice.paid','data':{'object':{'parent':{'subscription_details':{'subscription':'sub_1'}}}}}
        with patch.object(stripe,'sync_subscription',AsyncMock()) as sync:
            await stripe.process_event(event)
        sync.assert_awaited_once_with('sub_1')

    def test_profile_updates_preserve_customer_and_subscription(self):
        query=Mock();query.upsert.return_value=query
        with patch.object(stripe,'profile',return_value={'student_id':1,'customer_id':'cus_keep','subscription_id':'sub_keep'}),patch.object(stripe.supabase,'table',return_value=query):
            stripe.save_profile(1,{'checkout_session_id':'cs_new'})
        data=query.upsert.call_args.args[0]
        self.assertEqual(data['customer_id'],'cus_keep')
        self.assertEqual(data['subscription_id'],'sub_keep')

    async def test_webhook_invalid_signature_returns_400(self):
        from services.payment_server import webhook
        request=types.SimpleNamespace(read=AsyncMock(return_value=b'{}'),headers={'Stripe-Signature':'invalid'})
        with patch.dict(os.environ,SETTINGS): response=await webhook(request)
        self.assertEqual(response.status,400)

    async def test_other_stripe_product_is_ignored(self):
        s=subscription();s['metadata']['app']='different_app'
        with patch.object(stripe,'stripe_request',AsyncMock(return_value=s)),patch.object(stripe,'save_profile') as save:
            await stripe.sync_subscription('sub_1')
        save.assert_not_called()

class DashboardTests(unittest.TestCase):
    def test_real_image_and_empty_state(self):
        p={'state':{'current_block':'1.1','current_topic':'Alphabet'},'words':0,'completed':0,'history_available':True,'today':0,'goal':10,'accuracy':0,'attempts':0,'percent':0,'daily_activity':[{'label':str(i),'count':0} for i in range(7)],'recent_scores':[]}
        image=Image.open(BytesIO(render_dashboard(p)))
        self.assertEqual(image.size,(1200,1760))
        self.assertEqual(image.format,'PNG')
        p.update(words=24,today=17,accuracy=85,attempts=40,percent=100,completed=3,history_available=False,recent_scores=[{'label':f'Test {i}','score':90} for i in range(5)])
        self.assertGreater(len(render_dashboard(p)),20000)

if __name__=='__main__':unittest.main()
