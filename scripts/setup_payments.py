"""Check deployed payment prerequisites; explicitly create/reuse Stripe price with --create-plan."""
import argparse,asyncio,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv,set_key
load_dotenv(ROOT/'.env')

async def run(create):
    required=['STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','PAYMENT_PUBLIC_BASE_URL','SUPABASE_URL','SUPABASE_SECRET_KEY']
    # Supabase deployment may use either supported key variable.
    for key in required:
        value=os.getenv(key,'').strip()
        print(key+': '+('configured' if value else 'MISSING'))
    if not create: return
    if not os.getenv('STRIPE_SECRET_KEY','').strip(): raise RuntimeError('Add STRIPE_SECRET_KEY to .env first')
    from services.stripe_service import ensure_monthly_price
    price=await ensure_monthly_price()
    set_key(str(ROOT/'.env'),'STRIPE_PRICE_ID',price)
    print('Monthly USD 19.90 price ready: '+price)
    print('Next: configure HTTPS /stripe/webhook, signing secret and Billing customer portal; restart the bot.')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--create-plan',action='store_true')
    args=parser.parse_args()
    try:asyncio.run(run(args.create_plan))
    except Exception as exc:
        print('Setup failed: '+str(exc),file=sys.stderr);raise SystemExit(1)
