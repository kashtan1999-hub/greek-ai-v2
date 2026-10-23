import os

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")

if not SUPABASE_URL:
    raise ValueError("SUPABASE_URL .env file mein missing hai.")

if not SUPABASE_SECRET_KEY:
    raise ValueError("SUPABASE_SECRET_KEY .env file mein missing hai.")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

