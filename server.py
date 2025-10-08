from flask import Flask
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import asyncio, threading, os

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
WEBHOOK_URL = "https://dom.mesopharm.ru/rest/19508/4mi5yvzezp02hiit/"

# ---------- Telegram handlers ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот Bitrix.\n"
        "/me — мой профиль\n"
        "/leads — список лидов"
    )

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get(WEBHOOK_URL + "user.current.json")
    data = r.json()
    if "result" in data:
        u = data["result"]
        msg = f"👤 {u.get('NAME','')} {u.get('LAST_NAME','')}\nEmail: {u.get('EMAIL','')}"
    else:
        msg = f"Ошибка: {data}"
    await update.message.reply_text(msg)

async def leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get(WEBHOOK_URL + "crm.lead.list.json")
    data = r.json()
    if "result" in data:
        leads = data["result"]
        if not leads:
            await update.message.reply_text("Нет лидов.")
            return
        msg = "📋 Лиды:\n" + "\n".join([f"{l['ID']}: {l['TITLE']}" for l in leads[:10]])
    else:
        msg = f"Ошибка: {data}"
    await update.message.reply_text(msg)

# ---------- Flask routes ----------

@app.route("/")
def index():
    return "🤖 Telegram–Bitrix бот работает!"

# ---------- Telegram bot launcher ----------

def start_bot():
    asyncio.set_event_loop(asyncio.new_event_loop())  # отдельный loop для потока
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("me", me))
    app_tg.add_handler(CommandHandler("leads", leads))
    # ✅ ключевое: не ловим сигналы в потоке
    app_tg.run_polling(stop_signals=None)

# ---------- Main ----------

if __name__ == "__main__":
    threading.Thread(target=start_bot, daemon=True).start()
    app.run(host="0.0.0.0", port=10000)
