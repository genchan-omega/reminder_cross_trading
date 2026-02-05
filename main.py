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

# Supabaseの設定
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# FastAPIの準備
app = FastAPI()

# Discord Botの準備
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# --- Supabase 操作関数 ---
def get_status():
    """Supabaseから設定を読み込む"""
    try:
        response = supabase.table("bot_status").select("is_on").eq("id", 1).execute()
        if response.data:
            return response.data[0]["is_on"]
        return True  # データがない場合はデフォルトON
    except Exception as e:
        print(f"Supabase Get Error: {e}")
        return True

def set_status(is_on: bool):
    """Supabaseへ設定を書き込む"""
    try:
        # id=1のデータを更新。データがない場合は作成する
        supabase.table("bot_status").upsert({"id": 1, "is_on": is_on}).execute()
    except Exception as e:
        print(f"Supabase Set Error: {e}")

# --- リマインド実行関数 ---
def send_reminder():
    if get_status():
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            # 非同期でメッセージ送信
            bot.loop.create_task(channel.send("クロス取引開始の時間です！🎉"))
            print(f"Reminder sent at {datetime.now(pytz.timezone('Asia/Tokyo'))}")

# --- スケジューラの設定 ---
scheduler = BackgroundScheduler()
# 毎日18:50に実行（JST）
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
    is_on = get_status()
    status_text = "【ON】（18:50に送信されます）" if is_on else "【OFF】（現在は停止中です）"
    
    embed = discord.Embed(
        title="リマインド設定確認",
        description=f"現在の設定は **{status_text}** です。",
        color=discord.Color.green() if is_on else discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user.name}")

# --- Render 起こし用の窓口 ---
@app.get("/")
@app.head("/")
def read_root():
    return {"status": "active", "remind_on": get_status()}

# --- Botの起動処理 ---
@app.on_event("startup")
async def startup_event():
    # 起動時のIP制限を回避するため少し待機
    await asyncio.sleep(5)
    asyncio.create_task(bot.start(TOKEN))