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
    # 今日の日付を文字列(YYYY-MM-DD)で取得
    today_date = datetime.now(jst).date().isoformat()
    
    # 状態と最終送信日をチェック
    info = get_status_info()
    is_on = info.get("is_on", True)
    last_sent = info.get("last_sent_at")

    # 条件：リマインド設定がON 且つ 最後に送った日が今日ではない
    if is_on and last_sent != today_date:
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            # 非同期でメッセージ送信タスクを投げる
            bot.loop.create_task(channel.send("クロス取引開始の時間です！🎉"))
            
            # 送信後、Supabaseの last_sent_at を今日の日付に更新
            try:
                supabase.table("bot_status").update({"last_sent_at": today_date}).eq("id", 1).execute()
                print(f"Reminder sent and database updated: {today_date}")
            except Exception as e:
                print(f"Supabase update error: {e}")
    else:
        # スキップ理由をログに出す（デバッグ用）
        reason = "OFF設定のため" if not is_on else f"本日({today_date})送信済みのため"
        print(f"Reminder skipped: {reason}")

# --- スケジューラの設定 ---
scheduler = BackgroundScheduler()
# 毎日 18:50 に実行
scheduler.add_job(send_reminder, 'cron', hour=1, minute=10, timezone='Asia/Tokyo')
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