import os
import sqlite3
from datetime import datetime
import pytz
from fastapi import FastAPI
from discord.ext import commands, tasks
import discord
from apscheduler.schedulers.background import BackgroundScheduler

# --- 設定エリア ---
TOKEN = os.getenv("DISCORD_TOKEN")  # Renderの環境変数に設定
CHANNEL_ID = int(os.getenv("CHANNEL_ID")) # リマインドを送るチャンネルID

# FastAPIの準備（Renderを叩き起こす窓口用）
app = FastAPI()

# Discord Botの準備
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

# データベース初期化（ON/OFF状態の保存用）
def init_db():
    conn = sqlite3.connect('settings.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS bot_status (id INTEGER PRIMARY KEY, is_on INTEGER)')
    c.execute('INSERT OR IGNORE INTO bot_status (id, is_on) VALUES (1, 1)') # 初期値はON
    conn.commit()
    conn.close()

def get_status():
    conn = sqlite3.connect('settings.db')
    res = conn.execute('SELECT is_on FROM bot_status WHERE id = 1').fetchone()
    conn.close()
    return res[0] == 1

def set_status(is_on):
    conn = sqlite3.connect('settings.db')
    conn.execute('UPDATE bot_status SET is_on = ? WHERE id = 1', (1 if is_on else 0,))
    conn.commit()
    conn.close()

# --- リマインド実行関数 ---
def send_reminder():
    if get_status():
        # Botのループを使ってメッセージを送る
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            bot.loop.create_task(channel.send("【毎日リマインド】18:50になりました！"))

# --- スケジューラの設定 ---
scheduler = BackgroundScheduler()
# 毎日18:50に実行（Asia/Tokyoを指定）
scheduler.add_job(send_reminder, 'cron', hour=23, minute=30, timezone='Asia/Tokyo')
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

@bot.event
async def on_ready():
    await bot.tree.sync() # スラッシュコマンドを同期
    print(f"Logged in as {bot.user.name}")

# --- Render 起こし用の窓口 ---
@app.get("/")
def read_root():
    return {"status": "active", "remind_on": get_status()}

# Botの起動処理（非同期で実行）
import asyncio
@app.on_event("startup")
async def startup_event():
    init_db()
    asyncio.create_task(bot.start(TOKEN))