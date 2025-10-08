from flask import Flask, request
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import os
import threading

app = Flask(__name__)

# 🔐 Настройки
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")  # токен Telegram бота
WEBHOOK_URL = "https://dom.mesopharm.ru/rest/19508/4mi5yvzezp02hiit/"  # твой вебхук Bitrix

# ---------- Telegram-бот ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Привет! Я бот Bitrix.\n"
        "Команды:\n"
        "/me — мой профиль\n"
        "/leads — список лидов"
    )

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get(WEBHOOK_URL + "user.current.json")
    data = r.json()
    if "result" in data:
        user = data["result"]
        msg = f"👤 {user.get('NAME', '')} {user.get('LAST_NAME', '')}\nEmail: {user.get('EMAIL', '')}\nID: {user.get('ID')}"
    else:
        msg = f"Ошибка: {data}"
    await update.message.reply_text(msg)

async def leads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    r = requests.get(WEBHOOK_URL + "crm.lead.list.json")
    data = r.json()
    if "result" in data:
        leads = data["result"]
        if not leads:
            await update.message.reply_text("Нет лидов в CRM.")
            return
        msg = "📋 Лиды:\n" + "\n".join([f"{l['ID']}: {l['TITLE']}" for l in leads[:10]])
    else:
        msg = f"Ошибка: {data}"
    await update.message.reply_text(msg)

# ---------- Flask + Telegram в одном ----------

def start_bot():
    app_tg = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("me", me))      # ✅ вместо "я"
    app_tg.add_handler(CommandHandler("leads", leads))  # ✅ вместо "лиды"
    app_tg.run_polling()

@app.route("/")
def index():
    return "🤖 Telegram–Bitrix бот работает!"

if __name__ == "__main__":
    threading.Thread(target=start_bot).start()  # запускаем Telegram-бота в отдельном потоке
    app.run(host="0.0.0.0", port=10000)
