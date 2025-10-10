import os
import json
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# === Настройки ===
WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL")  # Например: https://dom.mesopharm.ru/rest/19508/ogky24oh9ijc2e31/
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID")

# === Вспомогательная функция для отправки сообщений в Bitrix через вебхук ===
def send_bitrix_message(dialog_id, text):
    if not WEBHOOK_URL or not dialog_id or not text:
        return
    try:
        payload = {
            "DIALOG_ID": dialog_id,
            "MESSAGE": text
        }
        r = requests.post(WEBHOOK_URL + "imbot.message.add", json=payload, timeout=10)
        print("Bitrix response:", r.text)
    except Exception as e:
        print("Error sending message to Bitrix:", e)

# === Endpoint для событий бота ===
@app.route("/bot/events", methods=["POST", "GET"])
def bot_events():
    if request.method == "GET":
        return jsonify({"ok": True, "message": "Bot events endpoint is up"})

    body = request.get_json(silent=True) or {}
    # Fallback: Bitrix может прислать form-urlencoded
    if not body:
        try:
            form = request.form.to_dict(flat=False)
            body = {k: (v[0] if isinstance(v, list) and v else v) for k, v in form.items()}
        except Exception:
            body = {}

    print("📩 Bitrix event body:", body)

    event = body.get("event") or body.get("event_name") or request.values.get("event") or request.values.get("event_name")
    data = body.get("data") or {}

    if event == "ONIMBOTMESSAGEADD":
        params = data.get("PARAMS") or data
        raw_message = params.get("MESSAGE") or data.get("MESSAGE") or request.values.get("MESSAGE")

        if isinstance(raw_message, dict):
            dialog_id = raw_message.get("DIALOG_ID") or raw_message.get("CHAT_ID") or params.get("DIALOG_ID") or params.get("CHAT_ID")
            text = raw_message.get("TEXT") or ""
            from_user = raw_message.get("FROM_USER_ID") or params.get("FROM_USER_ID") or (data.get("USER") or {}).get("ID")
        else:
            dialog_id = params.get("DIALOG_ID") or params.get("CHAT_ID") or request.values.get("DIALOG_ID") or request.values.get("CHAT_ID")
            text = str(raw_message or "")
            from_user = params.get("FROM_USER_ID") or request.values.get("FROM_USER_ID") or (data.get("USER") or {}).get("ID")

        # Пересылаем в Telegram
        if TELEGRAM_BOT_TOKEN and TELEGRAM_NOTIFY_CHAT_ID:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_NOTIFY_CHAT_ID, "text": f"[Bitrix IM] от {from_user} (dlg {dialog_id}):\n{text}"},
                    timeout=10,
                )
            except Exception as e:
                print("Error sending to Telegram:", e)

        # Отправляем мгновенный ответ в Bitrix
        send_bitrix_message(dialog_id, "Принято")

    return jsonify({"ok": True})

# === Healthcheck endpoints ===
@app.route("/bot/status", methods=["GET"])
def bot_status():
    return jsonify({"ok": True, "message": "Bot is running"})

@app.route("/debug/mappings", methods=["GET"])
def debug_mappings():
    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
