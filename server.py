from flask import Flask, request, redirect, jsonify
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)
_memory_token_cache = {
    "access_token": None,
    "raw": None,
}
_task_to_chat_map: dict[str, str] = {}
_chat_to_task_map: dict[str, str] = {}
_bot_state: dict[str, str | None] = {"bot_id": None}

# Загружаем переменные окружения
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_DOMAIN = os.getenv("BITRIX_DOMAIN", "https://dom.mesopharm.ru")
REDIRECT_URI = os.getenv("BITRIX_OAUTH_REDIRECT_URI", "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback")
RENDER_URL = "https://bitrix-bot-537z.onrender.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID")  # куда слать входящие из Bitrix IM
BITRIX_ENV_ACCESS_TOKEN = os.getenv("BITRIX_ACCESS_TOKEN")
BITRIX_ENV_REFRESH_TOKEN = os.getenv("BITRIX_REFRESH_TOKEN")
BITRIX_ENV_REST_BASE = os.getenv("BITRIX_REST_BASE")  # e.g. https://dom.mesopharm.ru/rest/

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
    
    return f"""
    <html>
    <head>
        <title>Bitrix Bot Server</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            .status {{ color: #28a745; font-size: 24px; margin-bottom: 20px; }}
            .info {{ background: #e7f3ff; padding: 15px; border-radius: 5px; margin: 10px 0; }}
            .endpoint {{ background: #f8f9fa; padding: 10px; margin: 5px 0; border-left: 4px solid #007bff; }}
            a {{ color: #007bff; text-decoration: none; }}
            a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="status">✅ Bitrix Bot Server работает!</div>
            
            <div class="info">
                <h3>🔗 Интеграция с Telegram и Bitrix24</h3>
                <p><strong>Bitrix24:</strong> {BITRIX_DOMAIN}</p>
                <p><strong>Сервер:</strong> {RENDER_URL}</p>
                <p><strong>Пользователь бота:</strong> Бот Техподдержки (techsupp)</p>
            </div>
            
            <h3>📋 Доступные эндпоинты:</h3>
            
            <div class="endpoint">
                <strong>OAuth авторизация:</strong><br>
                <a href="/install">/install</a> - Начать OAuth авторизацию<br>
                <a href="/oauth/status">/oauth/status</a> - Статус авторизации
            </div>
            
            <div class="endpoint">
                <strong>Пользователи Bitrix24:</strong><br>
                <a href="/users/html">/users/html</a> - HTML таблица пользователей<br>
                <a href="/users">/users</a> - JSON список пользователей<br>
                <a href="/user/techsupport-bot">/user/techsupport-bot</a> - Поиск бота техподдержки
            </div>
            
            <div class="endpoint">
                <strong>Telegram webhook:</strong><br>
                <a href="/telegram/webhook">/telegram/webhook</a> - Прием сообщений от Telegram
            </div>
            
            <div class="info">
                <h4>🔧 Настройка:</h4>
                <p>1. Выполните OAuth авторизацию через <a href="/install">/install</a></p>
                <p>2. Настройте Telegram webhook на <code>{RENDER_URL}/telegram/webhook</code></p>
                <p>3. Проверьте статус через <a href="/oauth/status">/oauth/status</a></p>
            </div>
        </div>
    </body>
    </html>
    """


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
        # also cache in memory
        _memory_token_cache["access_token"] = result.get("access_token")
        _memory_token_cache["raw"] = result
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ----------------------
# Вспомогательные функции: чтение токена и вызовы Bitrix REST
# ----------------------

def _normalize_rest_base(token_data: dict) -> str:
    # 1) Если есть client_endpoint (обычно вида https://portal/rest/), используем его
    client_endpoint = token_data.get("client_endpoint")
    if client_endpoint:
        base = client_endpoint.rstrip('/')
        if not base.endswith('/rest'):
            base = f"{base}/rest"
        return f"{base}/"  # гарантируем хвостовой слэш
    # 2) Иначе пробуем domain
    domain = token_data.get("domain")
    if domain:
        if not domain.startswith("http://") and not domain.startswith("https://"):
            domain = f"https://{domain}"
        return f"{domain.rstrip('/')}/rest/"
    # 3) Фолбэк на BITRIX_DOMAIN
    return f"{BITRIX_DOMAIN.rstrip('/')}/rest/"


def _refresh_oauth_token() -> tuple[str | None, str | None, dict | None]:
    refresh_token = None
    raw = _memory_token_cache.get("raw") or {}
    # prefer memory, then ENV
    if raw:
        refresh_token = raw.get("refresh_token")
    if not refresh_token:
        refresh_token = BITRIX_ENV_REFRESH_TOKEN
    if not refresh_token or not CLIENT_ID or not CLIENT_SECRET:
        return None, None, None

    # token endpoint: prefer domain-based, fallback to oauth.bitrix.info
    rest_base = _normalize_rest_base(raw or {"domain": BITRIX_DOMAIN, "client_endpoint": BITRIX_ENV_REST_BASE})
    domain = (raw or {}).get("domain") or BITRIX_DOMAIN
    portal_token_url = f"{domain.rstrip('/')}/oauth/token/"
    payload = {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }
    try:
        r = requests.post(portal_token_url, data=payload, timeout=15)
        if r.status_code == 200:
            result = r.json()
        else:
            result = None
    except Exception:
        result = None
    if result is None:
        try:
            r2 = requests.post("https://oauth.bitrix.info/oauth/token/", data=payload, timeout=15)
            if r2.status_code == 200:
                result = r2.json()
        except Exception:
            result = None
    if not result or not result.get("access_token"):
        return None, None, None
    # cache in memory
    _memory_token_cache["access_token"] = result.get("access_token")
    # merge minimal info to keep domain/rest base
    merged = {**(raw or {}), **result}
    _memory_token_cache["raw"] = merged
    return _memory_token_cache["access_token"], _normalize_rest_base(merged), merged


def load_oauth_tokens():
    try:
        # 1) Memory cache first
        if _memory_token_cache.get("access_token") and _memory_token_cache.get("raw"):
            data = _memory_token_cache["raw"]
            access_token = _memory_token_cache["access_token"]
            rest_base = _normalize_rest_base(data)
            return access_token, rest_base, data

        # 2) token.json on disk
        with open("token.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        access_token = data.get("access_token")
        rest_base = _normalize_rest_base(data)
        # populate memory cache
        _memory_token_cache["access_token"] = access_token
        _memory_token_cache["raw"] = data
        return access_token, rest_base, data
    except Exception as e:
        print("⚠️ Не удалось загрузить token.json:", e)
        # 3) Environment fallback
        env_access_token = BITRIX_ENV_ACCESS_TOKEN
        env_rest_base = BITRIX_ENV_REST_BASE  # e.g. https://dom.mesopharm.ru/rest/
        env_domain = BITRIX_DOMAIN
        if env_access_token and (env_rest_base or env_domain):
            data = {
                "access_token": env_access_token,
                "domain": env_domain,
                "client_endpoint": env_rest_base,
            }
            access_token = env_access_token
            rest_base = _normalize_rest_base(data)
            # cache in memory
            _memory_token_cache["access_token"] = access_token
            _memory_token_cache["raw"] = data
            print("✅ Загрузка OAuth токена из ENV")
            return access_token, rest_base, data
        return None, None, None


def bitrix_call(method: str, payload: dict):
    access_token, rest_base, _ = load_oauth_tokens()
    if not access_token or not rest_base:
        return None, {"error": "missing_tokens", "error_description": "Нет OAuth токенов или REST базы"}
    url = f"{rest_base}{method}"
    try:
        r = requests.post(url, params={"auth": access_token}, json=payload, timeout=15)
        # Try to parse error body even on non-2xx to detect expired_token
        if r.status_code >= 400:
            try:
                err_body = r.json()
            except Exception:
                err_body = {"error": "HTTP_ERROR", "error_description": r.text}
            # Refresh on token problems
            if (err_body or {}).get("error") in {"expired_token", "invalid_token", "NO_AUTH_FOUND", "INVALID_TOKEN"}:
                new_access, new_rest, _raw = _refresh_oauth_token()
                if new_access and new_rest:
                    rr = requests.post(f"{new_rest}{method}", params={"auth": new_access}, json=payload, timeout=15)
                    if rr.status_code >= 400:
                        try:
                            return None, rr.json()
                        except Exception:
                            return None, {"error": "HTTP_ERROR", "error_description": rr.text}
                    try:
                        dd = rr.json()
                    except Exception:
                        dd = {}
                    if "error" in dd:
                        return None, dd
                    return dd.get("result", dd), None
            # Not a token error — return as Bitrix error
            return None, err_body
        # Success path
        try:
            data = r.json()
        except Exception:
            data = {}
        if "error" in data:
            # Secondary JSON error handling
            if data.get("error") in {"expired_token", "invalid_token", "NO_AUTH_FOUND", "INVALID_TOKEN"}:
                new_access, new_rest, _raw = _refresh_oauth_token()
                if new_access and new_rest:
                    rr = requests.post(f"{new_rest}{method}", params={"auth": new_access}, json=payload, timeout=15)
                    if rr.status_code >= 400:
                        try:
                            return None, rr.json()
                        except Exception:
                            return None, {"error": "HTTP_ERROR", "error_description": rr.text}
                    try:
                        dd = rr.json()
                    except Exception:
                        dd = {}
                    if "error" in dd:
                        return None, dd
                    return dd.get("result", dd), None
            return None, data
        return data.get("result", data), None
    except Exception as e:
        return None, {"error": "request_failed", "error_description": str(e)}


# ----------------------
# Статус OAuth: есть ли токен и какой домен
# ----------------------
@app.route("/oauth/status", methods=["GET"])
def oauth_status():
    access_token, rest_base, raw = load_oauth_tokens()
    source = "memory" if _memory_token_cache.get("access_token") else ("file" if os.path.exists("token.json") else ("env" if os.getenv("BITRIX_ACCESS_TOKEN") else "none"))
    return jsonify({
        "has_access_token": bool(access_token),
        "domain": raw.get("domain") if isinstance(raw, dict) else None,
        "rest_base": rest_base,
        "token_saved": bool(raw),
        "expires_in": (raw or {}).get("expires_in"),
        "member_id": (raw or {}).get("member_id"),
        "source": source,
    })

# ----------------------
# Получение списка пользователей Bitrix24
# ----------------------
@app.route("/users", methods=["GET"])
def get_users():
    """Получает список пользователей Bitrix24 (пагинация и фильтры)."""
    # query params
    try:
        start = int(request.args.get("start", "0"))
    except Exception:
        start = 0
    try:
        limit = int(request.args.get("limit", "50"))
    except Exception:
        limit = 50
    limit = max(1, min(limit, 200))
    fetch_all = str(request.args.get("all", "false")).lower() in {"1", "true", "yes"}
    login = request.args.get("login")
    name = request.args.get("name")

    accumulated = []
    next_start = start

    while True:
        payload = {
            "ACTIVE": "Y",
            "SELECT": ["ID", "NAME", "LAST_NAME", "EMAIL", "LOGIN"],
            "start": next_start,
        }
        if login:
            payload["LOGIN"] = login
        if name:
            payload["NAME"] = name

        page_result, err = bitrix_call("user.get", payload)
        if err:
            return jsonify({"error": "failed_to_get_users", "details": err}), 500
        page = page_result or []
        accumulated.extend(page)

        if not fetch_all:
            break
        if len(page) < limit:
            break
        next_start += limit
        if next_start - start > 5000:
            break

    return jsonify({
        "users": accumulated,
        "count": len(accumulated),
        "params": {"start": start, "limit": limit, "all": fetch_all, "login": login, "name": name},
        "note": "Используйте ?start, ?limit, ?all=true, ?login=, ?name=",
    })

# ----------------------
# Получение информации о текущем пользователе
# ----------------------
@app.route("/user/current", methods=["GET"])
def get_current_user():
    """Получает информацию о текущем пользователе (владельце токена)"""
    result, err = bitrix_call("user.current", {})
    
    if err:
        return jsonify({
            "error": "failed_to_get_current_user",
            "details": err
        }), 500
    
    return jsonify({
        "current_user": result,
        "note": "Это пользователь, от имени которого работает приложение"
    })

# ----------------------
# Поиск пользователя "Бот Техподдержки"
# ----------------------
@app.route("/user/techsupport-bot", methods=["GET"])
def get_techsupport_bot():
    """Ищет пользователя 'Бот Техподдержки' с логином 'techsupp'"""
    
    # Сначала ищем по логину
    result, err = bitrix_call("user.get", {
        "ACTIVE": "Y",
        "LOGIN": "techsupp",
        "SELECT": ["ID", "NAME", "LAST_NAME", "LOGIN", "EMAIL"]
    })
    
    if err:
        return jsonify({
            "error": "failed_to_search_user",
            "details": err
        }), 500
    
    if result and len(result) > 0:
        bot_user = result[0]
        return jsonify({
            "found": True,
            "user": bot_user,
            "search_method": "by_login",
            "note": f"Найден пользователь: {bot_user.get('NAME')} {bot_user.get('LAST_NAME')} (ID: {bot_user.get('ID')})"
        })
    
    # Если не найден по логину, ищем по имени
    result, err = bitrix_call("user.get", {
        "ACTIVE": "Y",
        "NAME": "Бот",
        "SELECT": ["ID", "NAME", "LAST_NAME", "LOGIN", "EMAIL"]
    })
    
    if err:
        return jsonify({
            "error": "failed_to_search_user_by_name",
            "details": err
        }), 500
    
    if result:
        for user in result:
            if "техподдержки" in user.get("LAST_NAME", "").lower() or "техподдержки" in user.get("NAME", "").lower():
                return jsonify({
                    "found": True,
                    "user": user,
                    "search_method": "by_name",
                    "note": f"Найден пользователь: {user.get('NAME')} {user.get('LAST_NAME')} (ID: {user.get('ID')})"
                })
    
    return jsonify({
        "found": False,
        "user": None,
        "search_method": "both",
        "note": "Пользователь 'Бот Техподдержки' с логином 'techsupp' не найден"
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
@app.route("/telegram/webhook", methods=["GET", "POST"]) 
def telegram_webhook():
    # GET — healthcheck/webhook verification convenience
    if request.method == "GET":
        return jsonify({"ok": True, "message": "Telegram webhook is up"})
    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not chat_id:
        return jsonify({"ok": True})

    title = text or "Обращение из Telegram"
    description = f"Источник: Telegram chat_id={chat_id}\n\nТекст: {text}"

    # Фиксированный ответственный (Бот Техподдержки)
    responsible_id = 19508

    # Если уже есть связанная задача для этого чата — добавляем комментарий
    existing_task_id = _chat_to_task_map.get(str(chat_id))
    if existing_task_id:
        # Try modern method first
        result, err = bitrix_call("task.commentitem.add", {
            "taskId": int(existing_task_id),
            "fields": {
                "POST_MESSAGE": text or "Сообщение из Telegram",
            }
        })
        # Fallback to legacy tasks.* method if needed
        if err and err.get("error") in {"ERROR_CORE", "ERROR_ARGUMENT"}:
            result, err = bitrix_call("tasks.task.comment.add", {
                "TASK_ID": int(existing_task_id),
                "TEXT": text or "Сообщение из Telegram",
            })
        task_id = existing_task_id
    else:
        # Создаём новую задачу
        result, err = bitrix_call("tasks.task.add", {
            "fields": {
                "TITLE": title,
                "DESCRIPTION": description,
                "RESPONSIBLE_ID": responsible_id,
            }
        })
        task_id = None

    # Save mapping task_id -> chat_id for reverse direction
    if not err and not existing_task_id:
        task_id = (result or {}).get("task", {}).get("id") if isinstance(result, dict) else result
        if task_id:
            _task_to_chat_map[str(task_id)] = str(chat_id)
            _chat_to_task_map[str(chat_id)] = str(task_id)

    if TELEGRAM_BOT_TOKEN:
        reply_text = ""
        if err:
            reply_text = f"Не удалось обновить задачу: {err.get('error_description', err)}"
        else:
            if existing_task_id:
                reply_text = f"Комментарий добавлен в задачу: {task_id}"
            else:
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
# Bitrix → Telegram: события (комментарии по задачам)
# ----------------------
@app.route("/bitrix/events", methods=["POST"]) 
def bitrix_events():
    data = request.get_json(silent=True) or {}
    task_id = str(data.get("taskId") or data.get("TASK_ID") or "")
    text = data.get("text") or data.get("COMMENT_TEXT") or ""
    author_id = data.get("authorId") or data.get("AUTHOR_ID")

    if not task_id or not text:
        return jsonify({"ok": False, "error": "taskId and text are required"}), 400

    chat_id = _task_to_chat_map.get(task_id)
    if not chat_id:
        # Try to enrich mapping via REST (load last 1 comment and infer?) — skip for now
        return jsonify({"ok": False, "error": "chat mapping not found for task", "task_id": task_id}), 404

    if TELEGRAM_BOT_TOKEN:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": f"Комментарий к задаче #{task_id}:\n{text}"},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})


# ----------------------
# Telegram: helper to set webhook to this server
# ----------------------
@app.route("/telegram/set_webhook", methods=["POST", "GET"]) 
def telegram_set_webhook():
    if not TELEGRAM_BOT_TOKEN:
        return jsonify({"ok": False, "error": "TELEGRAM_BOT_TOKEN is not set"}), 500
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    webhook_url = f"{RENDER_URL}/telegram/webhook"
    try:
        r = requests.post(url, json={"url": webhook_url}, timeout=10)
        return jsonify({
            "ok": r.ok,
            "status_code": r.status_code,
            "request": {"url": url, "webhook": webhook_url},
            "response": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----------------------
# Bitrix IM Bot: register, status, events
# ----------------------
@app.route("/bot/status", methods=["GET"]) 
def bot_status():
    access_token, rest_base, raw = load_oauth_tokens()
    return jsonify({
        "has_access_token": bool(access_token),
        "rest_base": rest_base,
        "bot_id": _bot_state.get("bot_id"),
        "events_url": f"{RENDER_URL}/bot/events",
    })

@app.route("/bot/register", methods=["POST", "GET"]) 
def bot_register():
    # Регистрируем IM бота, чтобы получать ONIMBOTMESSAGEADD на /bot/events
    payload = {
        "CODE": "support_bridge_bot",
        "TYPE": "HUMAN",
        "EVENT_MESSAGE_ADD": f"{RENDER_URL}/bot/events",
        "EVENT_WELCOME_MESSAGE": f"{RENDER_URL}/bot/events",
        "EVENT_BOT_DELETE": f"{RENDER_URL}/bot/events",
        "OPENLINE": "N",
        "PROPERTIES": {
            "NAME": "Бот техподдержки (мост)",
            "COLOR": "GRAY",
        },
    }
    result, err = bitrix_call("imbot.register", payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    # Bitrix may return plain ID or object with BOT_ID
    bot_id = None
    if isinstance(result, dict):
        bot_id = result.get("BOT_ID") or result.get("bot_id") or result.get("result")
    else:
        bot_id = result
    _bot_state["bot_id"] = str(bot_id) if bot_id is not None else None
    return jsonify({"ok": True, "bot_id": _bot_state["bot_id"], "raw": result})

@app.route("/bot/events", methods=["POST", "GET"]) 
def bot_events():
    # GET — healthcheck/проверка доступности
    if request.method == "GET":
        return jsonify({"ok": True, "message": "bot events endpoint is up"})

    # POST — обработка событий из Bitrix IM (например, ONIMBOTMESSAGEADD)
    body = request.get_json(silent=True) or {}
    event = body.get("event") or body.get("event_name")
    data = body.get("data") or {}
    # Поддержка форматов Bitrix
    if event == "ONIMBOTMESSAGEADD":
        msg = (data.get("PARAMS") or {}).get("MESSAGE") or data.get("MESSAGE") or {}
        dialog_id = msg.get("DIALOG_ID") or msg.get("CHAT_ID")
        text = msg.get("TEXT") or ""
        from_user = msg.get("FROM_USER_ID") or (data.get("USER") or {}).get("ID")
        # Пересылаем в Telegram (в один заданный чат) — простой мост
        if TELEGRAM_BOT_TOKEN and TELEGRAM_NOTIFY_CHAT_ID:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                    json={"chat_id": TELEGRAM_NOTIFY_CHAT_ID, "text": f"[Bitrix IM] от {from_user} (dlg {dialog_id}):\n{text}"},
                    timeout=10,
                )
            except Exception:
                pass
    return jsonify({"ok": True})

# ----------------------
# Diagnostics: view and manage chat↔task mappings
# ----------------------
@app.route("/debug/mappings", methods=["GET"]) 
def debug_mappings():
    return jsonify({
        "task_to_chat": _task_to_chat_map,
        "chat_to_task": _chat_to_task_map,
        "note": "Для сброса используйте /chat/reset?chat_id=...; для привязки /chat/bind?chat_id=...&task_id=..."
    })

@app.route("/chat/reset", methods=["GET"]) 
def chat_reset():
    chat_id = request.args.get("chat_id")
    if not chat_id:
        return jsonify({"ok": False, "error": "chat_id is required"}), 400
    task_id = _chat_to_task_map.pop(str(chat_id), None)
    if task_id:
        _task_to_chat_map.pop(str(task_id), None)
    return jsonify({"ok": True, "cleared": {"chat_id": chat_id, "task_id": task_id}})

@app.route("/chat/bind", methods=["GET", "POST"]) 
def chat_bind():
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        chat_id = str(data.get("chat_id") or "")
        task_id = str(data.get("task_id") or "")
    else:
        chat_id = request.args.get("chat_id") or ""
        task_id = request.args.get("task_id") or ""
    if not chat_id or not task_id:
        return jsonify({"ok": False, "error": "chat_id and task_id are required"}), 400
    _chat_to_task_map[str(chat_id)] = str(task_id)
    _task_to_chat_map[str(task_id)] = str(chat_id)
    return jsonify({"ok": True, "bound": {"chat_id": chat_id, "task_id": task_id}})

# ----------------------
# HTML страница для просмотра пользователей
# ----------------------
@app.route("/users/html", methods=["GET"])
def users_html():
    """HTML страница для просмотра пользователей Bitrix24 (пагинация/фильтры)"""
    # параметры
    try:
        start = int(request.args.get("start", "0"))
    except Exception:
        start = 0
    try:
        limit = int(request.args.get("limit", "50"))
    except Exception:
        limit = 50
    limit = max(1, min(limit, 200))
    login = request.args.get("login", "")
    name = request.args.get("name", "")
    fetch_all = str(request.args.get("all", "false")).lower() in {"1", "true", "yes"}

    # сбор данных (та же логика, что и в /users)
    accumulated = []
    next_start = start
    while True:
        payload = {
            "ACTIVE": "Y",
            "SELECT": ["ID", "NAME", "LAST_NAME", "EMAIL", "LOGIN"],
            "start": next_start,
        }
        if login:
            payload["LOGIN"] = login
        if name:
            payload["NAME"] = name
        page_result, err = bitrix_call("user.get", payload)
        if err:
            return f"""
            <html><body>
            <h1>❌ Ошибка получения пользователей</h1>
            <pre>{err}</pre>
            <p><a href='/oauth/status'>Проверить статус OAuth</a></p>
            </body></html>
            """, 500
        page = page_result or []
        accumulated.extend(page)
        if not fetch_all:
            break
        if len(page) < limit:
            break
        next_start += limit
        if next_start - start > 5000:
            break

    # рендер
    html = """
    <html>
    <head>
        <title>Пользователи Bitrix24</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 20px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            .id { background-color: #e7f3ff; font-weight: bold; }
            .controls { margin: 10px 0; }
            .controls input { padding: 6px; }
            .controls button { padding: 6px 10px; }
            .pager a { margin-right: 10px; }
        </style>
        <script>
            function applyFilters() {
                const params = new URLSearchParams();
                const login = document.getElementById('login').value;
                const name = document.getElementById('name').value;
                const limit = document.getElementById('limit').value || 50;
                const all = document.getElementById('all').checked ? 'true' : 'false';
                if (login) params.set('login', login);
                if (name) params.set('name', name);
                if (limit) params.set('limit', limit);
                if (all) params.set('all', all);
                window.location.search = '?' + params.toString();
            }
        </script>
    </head>
    <body>
        <h1>👥 Пользователи Bitrix24</h1>
        <div class="controls">
            <label>Логин: <input id="login" value="" placeholder="techsupp" /></label>
            <label>Имя: <input id="name" value="" placeholder="Бот" /></label>
            <label>Лимит: <input id="limit" type="number" min="1" max="200" value="50" /></label>
            <label><input id="all" type="checkbox" /> Показать все</label>
            <button onclick="applyFilters()">Применить</button>
        </div>
        <p>Используйте <strong>ID</strong> из таблицы для настройки RESPONSIBLE_ID</p>
        <table>
            <tr>
                <th>ID</th>
                <th>Имя</th>
                <th>Фамилия</th>
                <th>Email</th>
                <th>Логин</th>
            </tr>
    """

    for user in accumulated:
        html += f"""
            <tr>
                <td class=\"id\">{user.get('ID', 'N/A')}</td>
                <td>{user.get('NAME', 'N/A')}</td>
                <td>{user.get('LAST_NAME', 'N/A')}</td>
                <td>{user.get('EMAIL', 'N/A')}</td>
                <td>{user.get('LOGIN', 'N/A')}</td>
            </tr>
        """

    prev_start = max(0, start - limit)
    next_start_link = start + limit
    qs_base = []
    if login:
        qs_base.append(f"login={login}")
    if name:
        qs_base.append(f"name={name}")
    qs_base.append(f"limit={limit}")
    qs_base_str = "&".join(qs_base)

    html += f"""
        </table>
        <div class=\"pager\">
            <p>
                <a href=\"/users/html?start={prev_start}&{qs_base_str}\">&larr; Предыдущие</a>
                <a href=\"/users/html?start={next_start_link}&{qs_base_str}\">Следующие &rarr;</a>
            </p>
        </div>
        <hr>
        <p><a href=\"/oauth/status\">Статус OAuth</a> | <a href=\"/users?{qs_base_str}\">JSON API</a></p>
    </body>
    </html>
    """

    return html

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
