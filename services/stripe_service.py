"""Stripe-hosted Checkout: $19.90 USD/month. No card data touches this bot."""
import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from datetime import datetime, timezone
from collections import defaultdict
from urllib.parse import urlencode
import aiohttp
from services.supabase_client import supabase

AMOUNT = 1990
CURRENCY = 'usd'
INTERVAL = 'month'
APP = 'greek_tutor'
_locks = defaultdict(asyncio.Lock)


def payments_ready():
    try:
        settings()
        return True
    except RuntimeError:
        return False


def settings():
    key = os.getenv('STRIPE_SECRET_KEY', '').strip()
    secret = os.getenv('STRIPE_WEBHOOK_SECRET', '').strip()
    base = os.getenv('PAYMENT_PUBLIC_BASE_URL', '').strip().rstrip('/')
    if not key or not secret or not base.startswith('https://'):
        raise RuntimeError('Configure STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET and HTTPS PAYMENT_PUBLIC_BASE_URL')
    return key, secret, base


class StripeRequestError(RuntimeError):
    def __init__(self,status,code,param=None):
        super().__init__(f'Stripe request failed ({status}): {code}')
        self.status=status; self.code=code; self.param=param


def _missing_resource(error):
    return isinstance(error,StripeRequestError) and error.status==404 and error.code=='resource_missing'


async def stripe_request(method, path, data=None, idempotency=None):
    key = os.getenv('STRIPE_SECRET_KEY','').strip()
    if not key: raise RuntimeError('STRIPE_SECRET_KEY is missing')
    headers = {'Authorization': f'Bearer {key}'}
    if idempotency: headers['Idempotency-Key'] = idempotency
    # Form encoding is Stripe's documented REST format.
    body = urlencode(data or {}, doseq=True) if method == 'POST' else None
    if body is not None: headers['Content-Type'] = 'application/x-www-form-urlencoded'
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as http:
        async with http.request(method, 'https://api.stripe.com/v1/'+path,
                                data=body, params=data if method=='GET' else None, headers=headers) as response:
            result = await response.json()
            if response.status >= 400:
                raise StripeRequestError(response.status,result.get('error',{}).get('code','request_error'),result.get('error',{}).get('param'))
            return result


def profile(student_id):
    rows = supabase.table('stripe_payment_profiles').select('*').eq('student_id', student_id).limit(1).execute().data or []
    value=dict(rows[0]) if rows else {}
    for key in ('customer_id','subscription_id','checkout_session_id','checkout_request_id'):
        if str(value.get(key) or '').strip().lower() in {'','null','none'}: value[key]=None
    return value


def save_profile(student_id, values):
    supabase.table('stripe_payment_profiles').upsert({**profile(student_id), 'student_id': student_id, **values}, on_conflict='student_id').execute()


def checkout_data(student_id, telegram_user_id, customer=None, price_id=None):
    _, _, base = settings()
    data = {
        'mode': 'subscription',
        'client_reference_id': str(student_id),
        'metadata[app]': APP,
        'metadata[student_id]': str(student_id),
        'subscription_data[metadata][app]': APP,
        'subscription_data[metadata][student_id]': str(student_id),
        'subscription_data[metadata][telegram_user_id]': str(telegram_user_id),
        'line_items[0][price_data][currency]': CURRENCY,
        'line_items[0][price_data][unit_amount]': str(AMOUNT),
        'line_items[0][price_data][recurring][interval]': INTERVAL,
        'line_items[0][price_data][product_data][name]': 'Греческий язык — ежемесячная подписка',
        'line_items[0][quantity]': '1',
        'success_url': base+'/payment/success',
        'cancel_url': base+'/payment/cancel',
    }
    data['locale'] = 'ru'
    if price_id:
        data={k:v for k,v in data.items() if not k.startswith('line_items[0][price_data]')}
        data['line_items[0][price]']=price_id
    if customer: data['customer'] = customer
    return data


async def create_checkout(student_id, telegram_user_id):
    async with _locks[student_id]:
        p = profile(student_id)
        if p.get('subscription_id'):
            try:
                status = await sync_subscription(p['subscription_id'])
            except StripeRequestError as error:
                if not _missing_resource(error): raise
                status=None
                p['subscription_id']=None
                p['checkout_request_id']=None
                save_profile(student_id, {'subscription_id':None,'checkout_request_id':None})
            if status in {'active', 'past_due', 'unpaid', 'trialing', 'paused', 'incomplete'}:
                return await create_portal(student_id)
        if p.get('checkout_session_id'):
            try:
                session = await stripe_request('GET', 'checkout/sessions/'+p['checkout_session_id'])
            except StripeRequestError as error:
                if not _missing_resource(error): raise
                # Missing session must not make the payment button unusable.
                session={}
                save_profile(student_id, {'checkout_session_id':None,'checkout_request_id':None})
            if session.get('status') == 'open' and session.get('url'):
                return session['url']
            if session.get('status') == 'complete' and session.get('subscription'):
                status = await sync_subscription(session['subscription'])
                if status in {'active','past_due','unpaid','trialing','paused','incomplete'}:
                    return await create_portal(student_id)
            p['checkout_request_id'] = None
        if p.get('customer_id'):
            try:
                existing=await stripe_request('GET','customers/'+p['customer_id'])
                missing=bool(existing.get('deleted'))
            except StripeRequestError as error:
                if not _missing_resource(error): raise
                missing=True
            if missing:
                p['customer_id']=None
                p['checkout_request_id']=None
                save_profile(student_id, {'customer_id':None,'checkout_request_id':None})
        request_id = p.get('checkout_request_id') or uuid.uuid4().hex
        save_profile(student_id, {'checkout_request_id': request_id})
        if not p.get('customer_id'):
            customer = await stripe_request('POST', 'customers',
                {'metadata[app]': APP, 'metadata[student_id]': str(student_id)},
                idempotency='greek-tutor-customer-'+str(student_id)+'-'+request_id)
            save_profile(student_id, {'customer_id': customer['id']})
            p['customer_id'] = customer['id']
        session = await stripe_request('POST', 'checkout/sessions',
            checkout_data(student_id, telegram_user_id, p.get('customer_id'), await ensure_monthly_price()),
            idempotency='checkout-'+request_id)
        save_profile(student_id, {'checkout_session_id': session['id']})
        return session['url']


async def create_portal(student_id):
    p = profile(student_id)
    if not p.get('customer_id'): raise RuntimeError('No billing customer is available yet')
    _, _, base = settings()
    result = await stripe_request('POST', 'billing_portal/sessions',
        {'customer': p['customer_id'], 'return_url': base+'/payment/return'})
    return result['url']


def verified_event(payload, signature, secret, now=None):
    fields = defaultdict(list)
    for part in signature.split(','):
        key, sep, value = part.partition('=')
        if sep: fields[key].append(value)
    try:
        stamp = int(fields['t'][0])
    except (ValueError, IndexError):
        raise ValueError('Invalid signature timestamp')
    if abs((time.time() if now is None else now) - stamp) > 300:
        raise ValueError('Expired webhook signature')
    expected = hmac.new(secret.encode(), str(stamp).encode()+b'.'+payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, sig) for sig in fields['v1']):
        raise ValueError('Invalid webhook signature')
    return json.loads(payload)


def paid_access(subscription):
    items = subscription.get('items', {}).get('data', [])
    if len(items) != 1: return False
    item = items[0]
    price = item.get('price') or {}
    recurring = price.get('recurring') or {}
    invoice = subscription.get('latest_invoice') or {}
    return bool(subscription.get('status') == 'active'
        and isinstance(invoice, dict) and (invoice.get('paid') or invoice.get('status') == 'paid')
        and price.get('unit_amount') == AMOUNT and price.get('currency') == CURRENCY
        and recurring.get('interval') == INTERVAL and recurring.get('interval_count', 1) == 1
        and item.get('quantity', 1) == 1)


async def _send_payment_alert(student_id, text):
    """Best-effort Telegram payment notification; billing state remains authoritative."""
    try:
        token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        if not token:
            return
        rows = supabase.table('Students').select('chat_id').eq('id', student_id).limit(1).execute().data or []
        chat_id = rows[0].get('chat_id') if rows else None
        if not chat_id:
            return
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as http:
            await http.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': text},
            )
    except Exception:
        # Payment activation must not fail because a notification could not be delivered.
        import logging
        logging.getLogger(__name__).exception('Payment Telegram notification failed')


async def sync_subscription(subscription_id):
    subscription = await stripe_request('GET', 'subscriptions/'+subscription_id,
                                        {'expand[]': 'latest_invoice'})
    metadata = subscription.get('metadata') or {}
    if metadata.get('app') != APP: return None
    student_id = int(metadata['student_id'])
    # Fetch authoritative current state rather than trusting out-of-order event snapshots.
    p = profile(student_id)
    other = p.get('subscription_id')
    if other and other != subscription_id:
        # Ignore old canceled subscriptions after a replacement has been attached.
        other_sub = await stripe_request('GET', 'subscriptions/'+other)
        if other_sub.get('status') not in {'canceled','incomplete_expired'}: return None
    active = paid_access(subscription)
    status = subscription.get('status') or 'incomplete'
    invoice = subscription.get('latest_invoice') or {}
    invoice_id = invoice.get('id') if isinstance(invoice, dict) else None
    paid_at = None
    if isinstance(invoice, dict):
        paid_ts = (invoice.get('status_transitions') or {}).get('paid_at') or invoice.get('created')
        if paid_ts:
            try:
                paid_at = datetime.fromtimestamp(int(paid_ts), timezone.utc).isoformat()
            except (TypeError, ValueError, OSError):
                paid_at = None

    old_profile = profile(student_id)
    previous_status = old_profile.get('status')
    status_changed_at = old_profile.get('status_changed_at')
    if str(previous_status or '') != str(status or ''):
        status_changed_at = datetime.now(timezone.utc).isoformat()
    save_profile(student_id, {
        'subscription_id': subscription_id,
        'customer_id': subscription.get('customer'),
        'status': status,
        'previous_status': previous_status,
        'status_changed_at': status_changed_at,
        'current_period_end': (
            datetime.fromtimestamp(int(subscription['current_period_end']), timezone.utc).isoformat()
            if subscription.get('current_period_end') else None
        ),
    })
    values = {'subscription_status': 'active' if active else ('past_due' if status=='active' else status)}
    if active:
        values['trial_expires_at'] = None
    supabase.table('Students').update(values).eq('id', student_id).execute()

    # One notification per successfully paid invoice. This gives the learner a
    # clear confirmation of the monthly (30-day-class) billing cycle.
    if active and invoice_id and (invoice.get('paid') or invoice.get('status') == 'paid'):
        if old_profile.get('last_payment_id') != invoice_id:
            save_profile(student_id, {
                'last_payment_id': invoice_id,
                'last_paid_at': paid_at,
            })
            next_end = subscription.get('current_period_end')
            next_date = ''
            if next_end:
                next_date = datetime.fromtimestamp(int(next_end), timezone.utc).strftime('%d.%m.%Y')
            text = (
                '✅ Оплата получена. Ваша подписка на Greek Tutor активна на следующий ежемесячный период.\n\n'
                + (f'Следующее списание: {next_date}.' if next_date else 'Следующее списание будет выполнено автоматически.')
            )
            await _send_payment_alert(student_id, text)
    return status


async def process_event(event):
    kind = event.get('type', '')
    obj = event.get('data', {}).get('object', {})
    subscription_id = None
    if kind.startswith('customer.subscription.'):
        subscription_id = obj.get('id')
    elif kind.startswith('invoice.'):
        subscription_id = obj.get('subscription') or ((obj.get('parent') or {}).get('subscription_details') or {}).get('subscription')
    elif kind in {'checkout.session.completed', 'checkout.session.async_payment_succeeded'}:
        if obj.get('mode') == 'subscription': subscription_id = obj.get('subscription')
    if subscription_id:
        async with _locks['webhook-events']:
            await sync_subscription(subscription_id)


PRICE_LOOKUP = 'greek_tutor_usd_1990_month_v1'

def valid_monthly_price(price):
    recurring=price.get('recurring') or {}
    return (price.get('active') is True and price.get('unit_amount')==AMOUNT
        and price.get('currency')==CURRENCY and recurring.get('interval')==INTERVAL
        and recurring.get('interval_count',1)==1 and recurring.get('usage_type','licensed')=='licensed')

async def ensure_monthly_price():
    """Create/reuse one recurring product price, without enrolling any customer."""
    async with _locks['monthly-price']:
        configured=os.getenv('STRIPE_PRICE_ID','').strip()
        if configured:
            price=await stripe_request('GET','prices/'+configured)
        else:
            found=await stripe_request('GET','prices',{'lookup_keys[]':PRICE_LOOKUP,'active':'true','limit':'1'})
            existing=found.get('data') or []
            price=existing[0] if existing else await stripe_request('POST','prices',{
                'currency':CURRENCY,'unit_amount':str(AMOUNT),'recurring[interval]':INTERVAL,
                'lookup_key':PRICE_LOOKUP,'product_data[name]':'Греческий язык — ежемесячная подписка',
                'metadata[app]':APP},idempotency=PRICE_LOOKUP)
        if not valid_monthly_price(price): raise RuntimeError('Stripe price must be active, USD 19.90, monthly, quantity one')
        return price['id']
