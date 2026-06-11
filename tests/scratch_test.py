import os
from supabase import create_client

supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
supabase_key = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")

client = create_client(supabase_url, supabase_key)

try:
    print("Fetching users table content...")
    res = client.table("users").select("*").limit(1).execute()
    print("Success! Data:", res.data)
except Exception as e:
    print("Error querying users table:", e)
