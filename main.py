import os
import asyncio
from datetime import datetime
import pytz
from fastapi import FastAPI
from discord.ext import commands
import discord
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client, Client

# --- 設定エリア ---
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# --- Supabase 操作関数 ---

def get_status_info():
    """設定値(is_on)と最終送信日(last_sent_at)を同時に取得する"""
    try:
        # id=1 の行から is_on と last_sent_at を取得
        response = supabase.table("bot_status").select("is_on, last_sent_at").eq("id", 1).execute()
        if response.data:
            return response.data[0]
        # データがない場合のデフォルト値
        return {"is_on": True, "last_sent_at": None}
    except Exception as e:
        print(f"Supabase Get Error: {e}")
        return {"is_on": True, "last_sent_at": None}

def set_status(is_on: bool):
    """リマインドのON/OFFを切り替える"""
    try:
        supabase.table("bot_status").upsert({"id": 1, "is_on": is_on}).execute()
    except Exception as e:
        print(f"Supabase Set Error: {e}")

# --- リマインド実行関数 (二重送信防止付き) ---
def send_reminder():
    jst = pytz.timezone('Asia/Tokyo')
    today_date = datetime.now(jst).date().isoformat()
    
    # Supabaseの関数を呼び出す
    # この関数の中で「今日送ったかチェック」と「今日の日付を書き込み」を同時に行う
    result = supabase.rpc("check_and_lock_reminder", {"today_date": today_date}).execute()
    
    # Trueが返ってきた場合のみ、実際に送信する
    if result.data == True:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            bot.loop.create_task(channel.send("クロス取引開始の時間です！🎉"))
            print(f"Reminder sent and locked via RPC: {today_date}")
    else:
        print(f"Reminder skipped by RPC lock (Already sent or OFF)")

# --- スケジューラの設定 ---
scheduler = BackgroundScheduler()
# 毎日 18:50 に実行
scheduler.add_job(send_reminder, 'cron', hour=18, minute=50, timezone='Asia/Tokyo')
scheduler.start()

# --- Discord スラッシュコマンド ---

@bot.tree.command(name="remind-on", description="リマインドをONにします")
async def remind_on(interaction: discord.Interaction):
    set_status(True)
    await interaction.response.send_message("リマインドをONに設定しました！")

@bot.tree.command(name="remind-off", description="リマインドをOFFにします")
async def remind_off(interaction: discord.Interaction):
    set_status(False)
    await interaction.response.send_message("リマインドをOFFに設定しました！")

@bot.tree.command(name="remind-status", description="現在のリマインド設定を確認します")
async def remind_status(interaction: discord.Interaction):
    info = get_status_info()
    status_text = "【ON】" if info["is_on"] else "【OFF】"
    last_sent = info.get("last_sent_at") or "なし"
    
    embed = discord.Embed(
        title="リマインド設定確認",
        description=f"現在の設定：**{status_text}**\n最終送信日：`{last_sent}`",
        color=discord.Color.green() if info["is_on"] else discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user.name}")

# --- Koyeb/死活監視用の窓口 ---
@app.get("/")
@app.head("/")
def read_root():
    return {"status": "active", "info": get_status_info()}

# --- Botの起動処理 ---
@app.on_event("startup")
async def startup_event():
    # 起動時の競合を避けるため少し待機
    await asyncio.sleep(5)
    asyncio.create_task(bot.start(TOKEN))