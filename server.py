from flask import Flask, request, redirect, jsonify
import requests
import os

app = Flask(__name__)

# Загружаем параметры из переменных окружения
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")

# Твой домен Битрикс24
BITRIX_DOMAIN = "https://dom.mesopharm.ru"

# URL, куда Битрикс вернет code
REDIRECT_URI = "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback"


# 1️⃣ Маршрут для первоначальной установки
@app.route("/install")
def install():
    """
    Пользователь заходит на этот путь при установке приложения.
    Его нужно перенаправить на форму авторизации Битрикс24.
    """
    if not CLIENT_ID:
        return "Ошибка: переменная окружения BITRIX_CLIENT_ID не задана", 500

    auth_url = (
        f"{BITRIX_DOMAIN}/oauth/authorize/"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
    )

    return redirect(auth_url)


# 2️⃣ Callback — сюда Битрикс вернет временный код авторизации
@app.route("/oauth/bitrix/callback")
def oauth_callback():
    """
    После авторизации пользователь возвращается сюда с параметром ?code=...
    Обмениваем этот code на access_token и refresh_token.
    """
    code = request.args.get("code")

    if not code:
        return "Ошибка: отсутствует параметр code", 400

    token_url = f"{BITRIX_DOMAIN}/oauth/token/"

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    r = requests.post(token_url, data=data)
    result = r.json()

    # Для проверки выводим ответ сервера
    return jsonify(result)


# 3️⃣ Проверка доступности сервера
@app.route("/")
def index():
    return "✅ Bitrix Bot Server работает!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
