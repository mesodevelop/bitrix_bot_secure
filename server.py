from flask import Flask, request, jsonify
import requests
import os
import json

app = Flask(__name__)

# === НАСТРОЙКИ ===
# URL вебхука Bitrix24 (созданного в разделе "Приложения → Вебхуки → Входящий вебхук")
BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK", "https://dom.mesopharm.ru/rest/1/ВАШ_ТОКЕН/")
# URL сервера (Render/Railway), например https://bitrix-bot-537z.onrender.com
RENDER_URL = os.getenv("RENDER_URL", "https://bitrix-bot-537z.onrender.com")
# Настройки Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "")

_bot_state = {"bot_id": None}

# === ОБЩАЯ ФУНКЦИЯ ВЫЗОВА Bitrix REST ===
def bitrix_call(method, params=None):
    try:
        url = f"{BITRIX_WEBHOOK}{method}"
        r = requests.post(url, json=params or {}, timeout=10)
        data = r.json()
        if "error" in data:
            print("❌ Bitrix error:", data)
            return None, data
        return data.get("result"), None
    except Exception as e:
        print("❌ Bitrix request failed:", e)
        return None, {"error": str(e)}

# === ПРИВЕТСТВИЕ ===
@app.route("/", methods=["GET"])
def home():
    return jsonify({"ok": True, "message": "Bitrix ↔ Telegram bridge active"})

# === РЕГИСТРАЦИЯ БОТА ===
@app.route("/bot/register", methods=["POST", "GET"])
def bot_register():
    payload = {
        "CODE": "telegram_bridge_bot",
        "TYPE": "HUMAN",
        "EVENT_MESSAGE_ADD": f"{RENDER_URL}/bot/events",
        "EVENT_BOT_DELETE": f"{RENDER_URL}/bot/events",
        "PROPERTIES": {
            "NAME": "Бот техподдержки (мост)",
            "COLOR": "GRAY",
        },
    }

    result, err = bitrix_call("imbot.register", payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    bot_id = None
    if isinstance(result, dict):
        bot_id = result.get("BOT_ID") or result.get("bot_id") or result.get("result")
    else:
        bot_id = result

    _bot_state["bot_id"] = str(bot_id)
    print(f"🤖 Bot registered with ID: {_bot_state['bot_id']}")
    return jsonify({"ok": True, "bot_id": _bot_state["bot_id"], "raw": result})

# === ОБРАБОТКА СОБЫТИЙ ОТ BITRIX ===
@app.route("/bot/events", methods=["POST", "GET"])
def bot_events():
    if request.method == "GET":
        return jsonify({"ok": True, "message": "bot events endpoint is up"})

    # Bitrix может прислать JSON или form-urlencoded
    body = request.get_json(silent=True) or {}
    if not body:
        form = request.form.to_dict(flat=False)
        body = {k: (v[0] if isinstance(v, list) else v) for k, v in form.items()}

    # Иногда поле data — строка JSON
    if isinstance(body.get("data"), str):
        try:
            body["data"] = json.loads(body["data"])
        except Exception:
            pass

    print("📩 Bitrix event body:", json.dumps(body, ensure_ascii=False, indent=2))

    event = body.get("event") or body.get("event_name")
    data = body.get("data") or {}

    if event == "ONIMBOTMESSAGEADD":
        params = data.get("PARAMS") or data
        raw_message = params.get("MESSAGE") or data.get("MESSAGE")
        if isinstance(raw_message, dict):
            dialog_id = raw_message.get("DIALOG_ID") or raw_message.get("CHAT_ID")
            text = raw_message.get("TEXT") or ""
            from_user = raw_message.get("FROM_USER_ID") or params.get("FROM_USER_ID")
        else:
            dialog_id = params.get("DIALOG_ID") or params.get("CHAT_ID")
            text = str(raw_message or "")
            from_user = params.get("FROM_USER_ID")

        # Отправляем в Telegram
        if TELEGRAM_BOT_TOKEN and TELEGRAM_NOTIFY_CHAT_ID:
            try:
                msg = f"[Bitrix IM] от {from_user} (dlg {dialog_id}):\n{text}"
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_NOTIFY_CHAT_ID, "text": msg},
                    timeout=10,
                )
            except Exception as e:
                print("⚠️ Telegram send error:", e)

        # Отвечаем пользователю в Bitrix
        try:
            if dialog_id:
                bitrix_call("imbot.message.add", {
                    "BOT_ID": int(_bot_state.get("bot_id") or 0),
                    "DIALOG_ID": dialog_id,
                    "MESSAGE": "✅ Принято в обработку",
                })
        except Exception as e:
            print("⚠️ Bitrix reply error:", e)

    return jsonify({"ok": True})

# === ПРОВЕРКА СТАТУСА ===
@app.route("/bot/status", methods=["GET"])
def bot_status():
    return jsonify({"ok": True, "bot_id": _bot_state.get("bot_id")})

# === ОТПРАВКА СООБЩЕНИЙ В BITRIX ИЗ TELEGRAM ===
@app.route("/bridge/send_to_bitrix", methods=["POST"])
def send_to_bitrix():
    data = request.get_json(force=True)
    chat_id = data.get("chat_id")
    text = data.get("text")

    result, err = bitrix_call("imbot.message.add", {
        "DIALOG_ID": chat_id,
        "MESSAGE": f"[Из Telegram] {text}"
    })
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "result": result})

# === ЗАПУСК ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
