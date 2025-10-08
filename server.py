from flask import Flask, request
import os
import requests

app = Flask(__name__)

CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
REDIRECT_URI = "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback"
BITRIX_DOMAIN = "https://dom.mesopharm.ru"  # корпоративный портал

@app.route("/")
def index():
    return '<a href="/auth">Авторизоваться через Bitrix</a>'

@app.route("/auth")
def auth():
    url = (
        f"{BITRIX_DOMAIN}/oauth/authorize/"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
    )
    return f'<a href="{url}">Перейти к авторизации</a>'

@app.route("/oauth/bitrix/callback")
def callback():
    code = request.args.get("code")
    if not code:
        return "Ошибка: не получен параметр code", 400

    token_url = f"{BITRIX_DOMAIN}/oauth/token/"
    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    try:
        r = requests.post(token_url, data=data, timeout=10)

        # Отладка — выводим всю информацию о запросе
        debug_info = f"""
        <h3>Ответ Bitrix:</h3>
        <b>URL:</b> {token_url}<br>
        <b>Статус:</b> {r.status_code}<br>
        <b>Тело ответа:</b><br><pre>{r.text}</pre>
        """

        if r.status_code != 200:
            return f"<h3>Ошибка от портала Bitrix</h3>{debug_info}", 500

        return f"<h3>Access Token получен!</h3>{debug_info}"

    except Exception as e:
        return f"Ошибка при запросе токена: {str(e)}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
