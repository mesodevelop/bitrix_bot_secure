from flask import Flask, request, redirect, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_DOMAIN = "https://dom.mesopharm.ru"
REDIRECT_URI = "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback"


# 🧠 Универсальный логгер всех входящих запросов
@app.before_request
def log_request_info():
    print("\n--- 📩 Новый запрос ---")
    print(f"⏰ Время: {datetime.now()}")
    print(f"➡️ Метод: {request.method}")
    print(f"➡️ URL: {request.url}")
    print(f"➡️ Заголовки: {dict(request.headers)}")
    if request.data:
        print(f"➡️ Тело запроса: {request.data.decode('utf-8', errors='ignore')}")
    print("----------------------\n")


# 🟢 Проверка сервера
@app.route("/")
def index():
    return "✅ Bitrix Bot Server работает!"


# 🚀 Маршрут установки
@app.route("/install", methods=["GET", "POST"])
def install():
    """
    При установке приложения Битрикс направляет пользователя сюда.
    """
    if not CLIENT_ID:
        return "Ошибка: переменная окружения BITRIX_CLIENT_ID не задана", 500

    auth_url = (
        f"{BITRIX_DOMAIN}/oauth/authorize/"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
    )
    print(f"🔗 Перенаправляем на авторизацию: {auth_url}")
    return redirect(auth_url)


# 🔄 Callback от Битрикс (GET или POST)
@app.route("/oauth/bitrix/callback", methods=["GET", "POST"])
def oauth_callback():
    """
    Битрикс возвращает code сюда.
    """
    code = request.args.get("code") or request.form.get("code")

    if not code:
        return "❌ Ошибка: отсутствует параметр code", 400

    token_url = f"{BITRIX_DOMAIN}/oauth/token/"

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    print(f"🔑 Отправляем запрос на получение токена: {token_url}")
    try:
        r = requests.post(token_url, data=data, timeout=10)
        print(f"📨 Ответ Bitrix: {r.text}")
        result = r.json()

        # 💾 Сохраняем токен в файл
        with open("token.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# 🔍 Фолбэк на все неожиданные пути (для отладки)
@app.route("/<path:unknown>", methods=["GET", "POST"])
def catch_all(unknown):
    return f"Путь '{unknown}' не обрабатывается этим сервером.", 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
