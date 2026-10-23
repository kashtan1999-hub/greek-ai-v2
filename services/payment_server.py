import logging
import os
from aiohttp import web
from services.stripe_service import settings, payments_ready, verified_event, process_event
logger = logging.getLogger(__name__)


async def webhook(request):
    if not payments_ready():
        return web.Response(status=503, text='Payments not configured')
    _, secret, _ = settings()
    body = await request.read()
    try:
        event = verified_event(body, request.headers.get('Stripe-Signature', ''), secret)
    except (ValueError, TypeError):
        return web.Response(status=400, text='Invalid signature')
    try:
        await process_event(event)
    except Exception:
        logger.exception('Stripe webhook processing failed')
        # Non-2xx tells Stripe to retry after transient failures.
        return web.Response(status=500, text='Please retry')
    return web.Response(text='OK')


async def result_page(request):
    outcome = request.match_info.get('outcome')
    text = 'Платёж отправлен. Вернитесь в Telegram. Доступ обновится после подтверждения оплаты.' if outcome=='success' else 'Вернитесь в Telegram, чтобы продолжить обучение или управлять подпиской.'
    return web.Response(text='<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="font:20px sans-serif;padding:40px"><h1>Greek Tutor</h1><p>'+text+'</p></body></html>', content_type='text/html')


async def start_payment_server():
    # Start HTTP even before payment settings are ready, to obtain the hosting URL.
    # Checkout stays disabled and webhook fails closed until all settings are present.
    app = web.Application(client_max_size=1024*1024)
    app.router.add_get('/health', lambda request: web.Response(text='OK'))
    app.router.add_post('/stripe/webhook', webhook)
    app.router.add_get('/payment/{outcome:success|cancel|return}', result_page)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, os.getenv('PAYMENT_BIND_HOST','0.0.0.0'), int(os.getenv('PORT') or os.getenv('PAYMENT_PORT','8080'))).start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
