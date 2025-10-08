from flask import Flask, request, redirect, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

# Загружаем переменные окружения
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_DOMAIN = "https://dom.mesopharm.ru"
REDIRECT_URI = "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback"

# ----------------------
# Лог всех входящих запросов
# ----------------------
@app.before_request
def log_request_info():
    print("\n--- 📩 Новый запрос ---")
    print(f"⏰ Время: {datetime.now()}")
    print(f"➡️ Метод: {request.method}")
    print(f"➡️ URL: {request.url}")
    if request.data:
        print(f"➡️ Тело запроса: {request.data.decode('utf-8', errors='ignore')}")
    print("----------------------\n")


# ----------------------
# Корневой маршрут — POST от Bitrix при установке
# ----------------------
@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "POST":
        domain = request.args.get("DOMAIN")
        app_sid = request.args.get("APP_SID")
        print(f"📦 Установка приложения с домена: {domain}, APP_SID={app_sid}")
        return "✅ Приложение получило POST-запрос от Bitrix", 200
    return "✅ Bitrix Bot Server работает!"


# ----------------------
# Ручная установка / OAuth-редирект
# ----------------------
@app.route("/install")
def install():
    if not CLIENT_ID:
        return "❌ Ошибка: переменная окружения BITRIX_CLIENT_ID не задана", 500

    auth_url = (
        f"{BITRIX_DOMAIN}/oauth/authorize/"
        f"?client_id={CLIENT_ID}"
        f"&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
    )
    print(f"🔗 Перенаправляем на авторизацию: {auth_url}")
    return redirect(auth_url)


# ----------------------
# Callback после OAuth
# ----------------------
@app.route("/oauth/bitrix/callback", methods=["GET", "POST"])
def oauth_callback():
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
    r = requests.post(token_url, data=data, timeout=10)
    print("Ответ сервера Bitrix (raw):", r.text)
    try:
        result = r.json()
    except json.JSONDecodeError:
        return {"error": "Не удалось распарсить JSON", "response": r.text}, 500


        # Сохраняем токен
        with open("token.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------
# Любые другие пути — для отладки
# ----------------------
@app.route("/<path:unknown>", methods=["GET", "POST"])
def catch_all(unknown):
    return f"❌ Путь '{unknown}' не обрабатывается этим сервером.", 404


# ----------------------
# Запуск
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
