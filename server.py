from flask import Flask, request, jsonify
import os
import requests

app = Flask(__name__)

# ----------------------
# Настройки
# ----------------------
BITRIX_DOMAIN = "https://dom.mesopharm.ru"  # твой портал
ACCESS_TOKEN = os.getenv("BITRIX_ACCESS_TOKEN")  # токен техподдержки или админский
APP_SID = os.getenv("BITRIX_APP_SID")  # APP_SID локального приложения
APP_SECRET = os.getenv("BITRIX_APP_SECRET")  # client_secret локального приложения
# ----------------------

@app.route("/", methods=["POST"])
def index():
    """Главный обработчик POST-запросов от Bitrix"""
    data = request.form.to_dict() or request.json
    print("POST от Bitrix:", data)

    # Проверка App SID
    if data.get("APP_SID") != APP_SID:
        return jsonify({"error": "WRONG_APPLICATION_CLIENT"}), 400

    # Пример: отвечаем на тестовый webhook
    return jsonify({"result": "OK"}), 200


@app.route("/api/message", methods=["POST"])
def send_message():
    """
    Пример отправки сообщения через IM API коробочного Bitrix
    """
    data = request.json
    user_id = data.get("USER_ID")
    message = data.get("MESSAGE")

    if not user_id or not message:
        return jsonify({"error": "USER_ID and MESSAGE required"}), 400

    url = f"{BITRIX_DOMAIN}/rest/im.message.add.json"
    payload = {
        "USER_ID": user_id,
        "MESSAGE": message,
        "AUTH": ACCESS_TOKEN
    }

    r = requests.post(url, data=payload)
    return jsonify({"response": r.json()}), r.status_code


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
