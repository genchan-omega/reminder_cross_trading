# main.py
import os
from datetime import datetime
import pytz
import httpx
from fastapi import FastAPI, HTTPException
from supabase import create_client, Client

# ---- env ----
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not all([DISCORD_TOKEN, CHANNEL_ID, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY]):
    raise RuntimeError("Missing env vars: DISCORD_TOKEN, CHANNEL_ID, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY")

CHANNEL_ID = int(CHANNEL_ID)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

app = FastAPI()

JST = pytz.timezone("Asia/Tokyo")

def get_status() -> bool:
    """Supabaseから is_on を取得（id=1）"""
    try:
        resp = supabase.table("bot_status").select("is_on").eq("id", 1).execute()
        if resp.data:
            return bool(resp.data[0]["is_on"])
        return True
    except Exception as e:
        print(f"Supabase Get Error: {e}")
        return True

def get_last_sent_date() -> str | None:
    """重複送信防止用（bot_status.last_sent_date を推奨）"""
    try:
        resp = supabase.table("bot_status").select("last_sent_date").eq("id", 1).execute()
        if resp.data:
            return resp.data[0].get("last_sent_date")
        return None
    except Exception as e:
        print(f"Supabase Get last_sent_date Error: {e}")
        return None

def set_last_sent_date(date_ymd: str) -> None:
    try:
        supabase.table("bot_status").upsert({"id": 1, "last_sent_date": date_ymd}).execute()
    except Exception as e:
        print(f"Supabase Set last_sent_date Error: {e}")

async def post_discord_message(content: str) -> None:
    url = f"https://discord.com/api/v10/channels/{CHANNEL_ID}/messages"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(url, headers=headers, json={"content": content})
        if r.status_code // 100 != 2:
            raise HTTPException(status_code=502, detail=f"Discord API error {r.status_code}: {r.text}")

@app.get("/")
@app.head("/")
def health():
    return {"status": "active", "remind_on": get_status()}

@app.post("/tick")
async def tick():
    """
    Cloud Schedulerが叩くエンドポイント。
    - SupabaseでONなら送信
    - last_sent_dateで重複防止（推奨）
    """
    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")

    if not get_status():
        return {"ok": True, "sent": False, "reason": "off"}

    last = get_last_sent_date()
    if last == today:
        return {"ok": True, "sent": False, "reason": "already_sent_today"}

    await post_discord_message("クロス取引開始の時間です！🎉")
    set_last_sent_date(today)
    print(f"Reminder sent at {now.isoformat()}")
    return {"ok": True, "sent": True}
