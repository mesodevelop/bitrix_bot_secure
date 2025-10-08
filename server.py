from flask import Flask
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import asyncio

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
        user = data["result"]
        msg = f"👤 {user.get('NAME', '')} {user.get('LAST_NAME', '')}\nEmail: {user.get('EMAIL', '')}"
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

# ---------- Flask ----------

@app.route("/")
def index():
    return "🤖 Telegram–Bitrix бот работает!"

# ---------- Main ----------

async def main():
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("me", me))
    app_tg.add_handler(CommandHandler("leads", leads))

    # Запускаем Flask в отдельном потоке событий
    loop = asyncio.get_event_loop()
    from threading import Thread
    Thread(target=lambda: app.run(host="0.0.0.0", port=10000)).start()

    # Запускаем Telegram polling (основной asyncio loop)
    await app_tg.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
