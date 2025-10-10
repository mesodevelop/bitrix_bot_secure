from flask import Flask, request, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

# --- Конфигурация окружения ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BITRIX_IM_DIALOG_ID = os.getenv("BITRIX_IM_DIALOG_ID", "19508")
BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")  # например: https://dom.mesopharm.ru/rest/1/abc123xyz/
RENDER_URL = os.getenv("RENDER_URL", "https://bitrix-bot-537z.onrender.com")

# --- Глобальное состояние ---
_bot_state = {"bot_id": None}
_task_to_chat_map = {}
_chat_to_task_map = {}

# ===============================================================
# 🔧 Утилита: попытаться загрузить сохранённый BOT_ID
# ===============================================================
def load_bot_id():
    try:
        with open("bot_id.json", "r", encoding="utf-8") as f:
            saved = json.load(f)
            if "bot_id" in saved:
                _bot_state["bot_id"] = int(saved["bot_id"])
                print(f"♻️ Загружен сохранённый BOT_ID: {_bot_state['bot_id']}")
    except Exception:
        pass

# ===============================================================
# 🔧 Утилита: сохранить BOT_ID
# ===============================================================
def save_bot_id(bot_id):
    _bot_state["bot_id"] = int(bot_id)
    try:
        with open("bot_id.json", "w", encoding="utf-8") as f:
            json.dump({"bot_id": _bot_state["bot_id"]}, f)
        print(f"✅ Определён и сохранён BOT_ID: {_bot_state['bot_id']}")
    except Exception as e:
        print("⚠️ Не удалось сохранить bot_id.json:", e)

# ===============================================================
# 📥 Получение сообщений от Telegram
# ===============================================================
@app.route("/telegram/webhook", methods=["GET", "POST"])
def telegram_webhook():
    if request.method == "GET":
        return jsonify({"ok": True, "message": "Telegram webhook active"})

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return jsonify({"ok": True})

    # Загружаем BOT_ID при необходимости
    if not _bot_state.get("bot_id"):
        load_bot_id()

    # --- Пересылаем в Bitrix IM ---
    payload = {
        "BOT_ID": _bot_state.get("bot_id"),
        "DIALOG_ID": BITRIX_IM_DIALOG_ID,
        "MESSAGE": f"[Telegram {chat_id}] {text}",
    }

    if BITRIX_WEBHOOK_URL:
        try:
            r = requests.post(
                f"{BITRIX_WEBHOOK_URL}/imbot.message.add.json",
                json=payload,
                timeout=10,
            )
            print(f"➡️ Отправлено в Bitrix ({_bot_state.get('bot_id')}):", r.text)
        except Exception as e:
            print("⚠️ Ошибка отправки в Bitrix:", e)

    # Запоминаем связь между Telegram и Bitrix
    _chat_to_task_map[str(chat_id)] = str(BITRIX_IM_DIALOG_ID)
    _task_to_chat_map[str(BITRIX_IM_DIALOG_ID)] = str(chat_id)

    # Ответ пользователю Telegram
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": "✅ Отправлено в Bitrix"},
            timeout=10,
        )
    except Exception as e:
        print("⚠️ Ошибка ответа Telegram:", e)

    return jsonify({"ok": True})


# ===============================================================
# 📡 Получение событий от Bitrix (ONIMBOTMESSAGEADD и т.д.)
# ===============================================================
@app.route("/bot/events", methods=["POST", "GET"])
def bot_events():
    if request.method == "GET":
        return jsonify({
            "ok": True,
            "message": "bot events endpoint is up",
            "bot_id": _bot_state.get("bot_id")
        })

    body = request.get_json(silent=True) or {}
    if not body:
        try:
            body = request.form.to_dict(flat=False)
            body = {k: (v[0] if isinstance(v, list) else v) for k, v in body.items()}
        except Exception:
            body = {}

    # Попробуем распарсить data, если это строка
    if isinstance(body.get("data"), str):
        try:
            body["data"] = json.loads(body["data"])
        except Exception:
            pass

    print("\n====== 📥 ПРИШЛО СООБЩЕНИЕ ОТ BITRIX ======")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print("===========================================\n")

    event = body.get("event") or body.get("event_name")
    data = body.get("data") or {}

    # 🔍 Автоматическое определение BOT_ID
    possible_id = (
        data.get("BOT_ID")
        or (data.get("PARAMS") or {}).get("BOT_ID")
        or (data.get("MESSAGE") or {}).get("BOT_ID")
    )
    if possible_id and not _bot_state.get("bot_id"):
        save_bot_id(possible_id)

    # Если всё ещё не знаем BOT_ID — пробуем загрузить
    if not _bot_state.get("bot_id"):
        load_bot_id()

    # 🔁 Если это событие "сообщение добавлено"
    if event == "ONIMBOTMESSAGEADD":
        params = data.get("PARAMS") or data
        dialog_id = params.get("DIALOG_ID") or params.get("CHAT_ID")
        msg = params.get("MESSAGE") or data.get("MESSAGE")
        text = msg.get("TEXT") if isinstance(msg, dict) else str(msg or "")

        chat_id = _task_to_chat_map.get(str(dialog_id))
        if chat_id and TELEGRAM_BOT_TOKEN:
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": chat_id, "text": f"[Bitrix] {text}"},
                    timeout=10,
                )
                print(f"💬 Переслано в Telegram {chat_id}: {r.status_code}")
            except Exception as e:
                print("⚠️ Ошибка пересылки в Telegram:", e)

    return jsonify({"ok": True, "bot_id": _bot_state.get("bot_id")})


# ===============================================================
# 🧩 Вспомогательные роуты
# ===============================================================
@app.route("/", methods=["GET"])
def index():
    return f"""
    <h3>✅ Bitrix ↔ Telegram Bridge</h3>
    <ul>
        <li><a href="/telegram/webhook">/telegram/webhook</a></li>
        <li><a href="/bot/events">/bot/events</a></li>
        <li><a href="/debug/mappings">/debug/mappings</a></li>
    </ul>
    <p>BOT_ID: {_bot_state.get('bot_id')}</p>
    """


@app.route("/debug/mappings", methods=["GET"])
def debug_mappings():
    return jsonify({
        "task_to_chat": _task_to_chat_map,
        "chat_to_task": _chat_to_task_map,
        "bot_id": _bot_state.get("bot_id")
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
