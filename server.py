from flask import Flask, request, redirect, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

# Загружаем переменные окружения
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_DOMAIN = os.getenv("BITRIX_DOMAIN", "https://dom.mesopharm.ru")
REDIRECT_URI = os.getenv("BITRIX_OAUTH_REDIRECT_URI", "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

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

# Альтернативный путь для совместимости с документацией
@app.route("/oauth/install")
def oauth_install():
    return install()


# ----------------------
# Callback после OAuth
# ----------------------
@app.route("/oauth/bitrix/callback", methods=["GET", "POST"])
def oauth_callback():
    code = request.args.get("code") or request.form.get("code")
    cb_domain = request.args.get("domain")  # dom.mesopharm.ru
    member_id = request.args.get("member_id")

    if not code:
        return "❌ Ошибка: отсутствует параметр code", 400

    data = {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }

    # Сначала пробуем доменный эндпоинт портала
    portal_token_url = f"{BITRIX_DOMAIN}/oauth/token/"
    print(f"🔑 Пробуем получить токен у портала: {portal_token_url}")
    try:
        r = requests.post(portal_token_url, data=data, timeout=15)
        print("Ответ портала (raw):", r.text)
        if r.status_code == 200:
            result = r.json()
        else:
            result = None
    except Exception as e:
        print("⚠️ Ошибка портального эндпоинта:", e)
        result = None

    # Если не удалось — пробуем официальный облачный эндпоинт
    if result is None:
        global_token_url = "https://oauth.bitrix.info/oauth/token/"
        print(f"🔁 Портал не вернул токен. Пробуем: {global_token_url}")
        try:
            r2 = requests.post(global_token_url, data=data, timeout=15)
            print("Ответ oauth.bitrix.info (raw):", r2.text)
            if r2.status_code != 200:
                return jsonify({
                    "error": "token_exchange_failed",
                    "portal_status": getattr(r, 'status_code', None),
                    "portal_body": getattr(r, 'text', None),
                    "global_status": r2.status_code,
                    "global_body": r2.text,
                }), 502
            result = r2.json()
        except Exception as e:
            return jsonify({
                "error": "both_token_requests_failed",
                "portal_error": str(e),
            }), 502

    # Заполняем домен/участника, если не пришли
    if cb_domain and not result.get("domain"):
        result["domain"] = f"https://{cb_domain}"
    if member_id and not result.get("member_id"):
        result["member_id"] = member_id

    try:
        with open("token.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------
# Вспомогательные функции: чтение токена и вызовы Bitrix REST
# ----------------------

def load_oauth_tokens():
    try:
        with open("token.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        access_token = data.get("access_token")
        domain = data.get("domain") or BITRIX_DOMAIN
        return access_token, domain, data
    except Exception as e:
        print("⚠️ Не удалось загрузить token.json:", e)
        return None, None, None


def bitrix_call(method: str, payload: dict):
    access_token, domain, _ = load_oauth_tokens()
    if not access_token or not domain:
        return None, {"error": "missing_tokens", "error_description": "Нет OAuth токенов или домена"}
    url = f"{domain}/rest/{method}"
    try:
        r = requests.post(url, params={"auth": access_token}, json=payload, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return None, data
        return data.get("result", data), None
    except Exception as e:
        return None, {"error": "request_failed", "error_description": str(e)}


# ----------------------
# Статус OAuth: есть ли токен и какой домен
# ----------------------
@app.route("/oauth/status", methods=["GET"])
def oauth_status():
    access_token, domain, raw = load_oauth_tokens()
    return jsonify({
        "has_access_token": bool(access_token),
        "domain": domain or BITRIX_DOMAIN,
        "token_saved": bool(raw),
        "expires_in": (raw or {}).get("expires_in"),
        "member_id": (raw or {}).get("member_id"),
    })

# Безопасный дебаг, чтобы убедиться в корректных настройках (без секретов)
@app.route("/oauth/debug", methods=["GET"])
def oauth_debug():
    return jsonify({
        "bitrix_domain": BITRIX_DOMAIN,
        "redirect_uri": REDIRECT_URI,
        "has_client_id": bool(CLIENT_ID),
        "has_client_secret": bool(CLIENT_SECRET),
    })


# ----------------------
# Telegram webhook: принимает сообщения и создаёт задачу в Bitrix
# ----------------------
@app.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return jsonify({"ok": True})

    title = text or "Обращение из Telegram"
    description = f"Источник: Telegram chat_id={chat_id}\n\nТекст: {text}"

    result, err = bitrix_call("tasks.task.add", {
        "fields": {
            "TITLE": title,
            "DESCRIPTION": description,
        }
    })

    if TELEGRAM_BOT_TOKEN:
        reply_text = ""
        if err:
            reply_text = f"Не удалось создать задачу: {err.get('error_description', err)}"
        else:
            task_id = (result or {}).get("task", {}).get("id") if isinstance(result, dict) else result
            reply_text = f"Задача создана: {task_id}"
        try:
            requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": reply_text},
                timeout=10,
            )
        except Exception as e:
            print("⚠️ Ошибка отправки сообщения в Telegram:", e)

    return jsonify({"ok": True, "bitrix": result or err})


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
