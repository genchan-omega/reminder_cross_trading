import os
import asyncio
import re
from datetime import date, datetime, timedelta
import pytz
import requests
from bs4 import BeautifulSoup
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
CALENDAR_URL = "https://gokigen-life.tokyo/calendar/"
REMINDER_WINDOW_ROW_ID = 2
JST = pytz.timezone('Asia/Tokyo')

app = FastAPI()
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="/", intents=intents)

DATE_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日")


def today_jst() -> date:
    return datetime.now(JST).date()


def parse_iso_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None

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


def get_reminder_window_end():
    """自動リマインド期間の終了日を取得する。id=2 の last_sent_at を期間終了日として使う。"""
    try:
        response = supabase.table("bot_status").select("last_sent_at").eq("id", REMINDER_WINDOW_ROW_ID).execute()
        if response.data:
            return parse_iso_date(response.data[0].get("last_sent_at"))
    except Exception as e:
        print(f"Supabase Window Get Error: {e}")
    return None


def set_reminder_window_end(end_date: date):
    """自動リマインド期間の終了日を保存する。"""
    try:
        supabase.table("bot_status").upsert({
            "id": REMINDER_WINDOW_ROW_ID,
            "is_on": True,
            "last_sent_at": end_date.isoformat(),
        }).execute()
    except Exception as e:
        print(f"Supabase Window Set Error: {e}")


# --- SBIフライング日程判定 ---

def fetch_calendar_html():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; reminder-cross-trading/1.0)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    response = requests.get(CALENDAR_URL, headers=headers, timeout=(10, 30))
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def extract_weekly_calendar_rows(html: str, reference_date: date):
    soup = BeautifulSoup(html, "html.parser")
    start_heading = None
    for heading in soup.find_all(["h2", "h3"]):
        if "週間優待クロスイベントカレンダー" in heading.get_text(strip=True):
            start_heading = heading
            break

    if not start_heading:
        return []

    lines = []
    for node in start_heading.next_siblings:
        if getattr(node, "name", None) in ["h2", "h3"]:
            next_heading = node.get_text(strip=True)
            if "直近優待月イベントカレンダー" in next_heading:
                break
        if getattr(node, "get_text", None):
            text = node.get_text("\n", strip=True)
            if text:
                lines.extend(line.strip() for line in text.splitlines() if line.strip())

    rows = []
    current_date = None
    current_events = []

    def infer_year(month: int) -> int:
        if reference_date.month == 12 and month == 1:
            return reference_date.year + 1
        if reference_date.month == 1 and month == 12:
            return reference_date.year - 1
        return reference_date.year

    def flush():
        nonlocal current_date, current_events
        if current_date is not None:
            rows.append({"date": current_date, "events": current_events[:]})
        current_date = None
        current_events = []

    for line in lines:
        if line.upper().replace(" ", "") == "DATEEVENT":
            continue

        line = re.sub(r"\bToday\b", "", line, flags=re.IGNORECASE).strip()
        if not line:
            continue

        match = DATE_RE.match(line)
        if match:
            flush()
            month = int(match.group(1))
            day = int(match.group(2))
            current_date = date(infer_year(month), month, day)
            rest = line[match.end():].strip()
            if rest:
                current_events.append(rest)
            continue

        if current_date is not None:
            current_events.append(line)

    flush()
    return rows


def fetch_sbi_flying_dates(reference_date: date):
    html = fetch_calendar_html()
    rows = extract_weekly_calendar_rows(html, reference_date)
    return [
        row["date"]
        for row in rows
        if any("SBI" in event and "フライング" in event for event in row["events"])
    ]


def calculate_reminder_window_end(start_date: date):
    """開始日から見て次の週末直前の金曜日までを送信期間にする。"""
    days_until_friday = (4 - start_date.weekday()) % 7
    end_date = start_date + timedelta(days=days_until_friday)
    if (end_date - start_date).days < 7:
        end_date += timedelta(days=7)
    return end_date


def is_weekday(target_date: date):
    return target_date.weekday() < 5


def should_send_reminder_today(target_date: date):
    try:
        flying_dates = fetch_sbi_flying_dates(target_date)
        if target_date in flying_dates:
            end_date = calculate_reminder_window_end(target_date)
            set_reminder_window_end(end_date)
            print(f"SBI flying date detected: {target_date}, reminder window until {end_date}")
    except Exception as e:
        print(f"Calendar Fetch/Parse Error: {e}")

    window_end = get_reminder_window_end()
    if window_end is None:
        return False, "no active reminder window"
    if target_date > window_end:
        return False, f"reminder window ended at {window_end}"
    if not is_weekday(target_date):
        return False, "weekend"
    return True, f"active until {window_end}"


# --- リマインド実行関数 (二重送信防止付き) ---
def send_reminder():
    current_date = today_jst()
    should_send, reason = should_send_reminder_today(current_date)
    if not should_send:
        print(f"Reminder skipped by schedule: {current_date} ({reason})")
        return

    today_date = current_date.isoformat()
    
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
    window_end = get_reminder_window_end()
    window_text = f"`{window_end.isoformat()}` まで" if window_end else "対象期間外"
    
    embed = discord.Embed(
        title="リマインド設定確認",
        description=f"現在の設定：**{status_text}**\n最終送信日：`{last_sent}`\n自動送信期間：{window_text}",
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
    return {
        "status": "active",
        "info": get_status_info(),
        "reminder_window_end": get_reminder_window_end(),
    }

# --- Botの起動処理 ---
@app.on_event("startup")
async def startup_event():
    # 起動時の競合を避けるため少し待機
    await asyncio.sleep(5)
    asyncio.create_task(bot.start(TOKEN))
