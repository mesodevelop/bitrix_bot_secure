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
_did_bootstrap = False

# Загружаем переменные окружения
CLIENT_ID = os.getenv("BITRIX_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITRIX_CLIENT_SECRET")
BITRIX_DOMAIN = os.getenv("BITRIX_DOMAIN", "https://dom.mesopharm.ru")
REDIRECT_URI = os.getenv("BITRIX_OAUTH_REDIRECT_URI", "https://bitrix-bot-537z.onrender.com/oauth/bitrix/callback")
RENDER_URL = "https://bitrix-bot-537z.onrender.com"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID")  # куда слать входящие из Bitrix IM
FORWARD_TELEGRAM_TO_IM = os.getenv("FORWARD_TELEGRAM_TO_IM", "1")  # "1" to forward Telegram -> Bitrix IM
BITRIX_IM_DIALOG_ID = os.getenv("BITRIX_IM_DIALOG_ID", "19508")  # куда слать из Telegram в Bitrix IM
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
    # If Bitrix returned here with OAuth params (code, domain, etc.), forward to the proper callback
    if request.method == "GET" and (request.args.get("code") or request.args.get("DOMAIN") or request.args.get("domain")):
        # Preserve the full original query string
        qs = request.query_string.decode("utf-8") if request.query_string else ""
        target = "/oauth/bitrix/callback"
        if qs:
            target = f"{target}?{qs}"
        return redirect(target, code=302)

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
            .status {{ color: #28a745; font-size: 24px; margin-bottom: 10px; }}
            .links a {{ display: inline-block; margin-right: 12px; color: #007bff; text-decoration: none; }}
            .links a:hover {{ text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class=\"container\">
            <div class=\"status\">✅ Bitrix Bot Server работает!</div>
            <div class=\"links\">
                <a href=\"/oauth/status\">/oauth/status</a>
                <a href=\"/oauth/introspect\">/oauth/introspect</a>
                <a href=\"/oauth/install\">/oauth/install</a>
                <a href=\"/bot/status\">/bot/status</a>
                <a href=\"/debug/mappings\">/debug/mappings</a>
            </div>
        </div>
    </body>
    </html>
    """


# ----------------------
# Ручная установка / OAuth-редирект
# ----------------------
@app.route("/install", methods=["GET", "POST"])
def install():
    """
    Bitrix вызывает этот маршрут при установке приложения.
    Здесь мы регистрируем бота через REST-вебхук.
    """
    print("\n⚙️ Установка приложения из Bitrix...")
    print("Параметры запроса:", request.args.to_dict())

    # Попробуем зарегистрировать бота
    new_id = register_bot()
    if new_id:
        return jsonify({
            "ok": True,
            "message": "Бот успешно зарегистрирован",
            "bot_id": new_id
        })
    else:
        return jsonify({
            "ok": False,
            "message": "Не удалось зарегистрировать бота"
        }), 500

# Альтернативный путь для совместимости с документацией
@app.route("/oauth/install", methods=["GET", "POST"]) 
@app.route("/oauth/install/", methods=["GET", "POST"]) 
def oauth_install():
    """Bitrix calls this path on initial install check. Always return 200 OK."""
    # Optionally log incoming params for troubleshooting
    try:
        print("🔔 /oauth/install called", {"args": request.args.to_dict(), "method": request.method})
    except Exception:
        pass
    return jsonify({"ok": True, "message": "Install endpoint is up"})

# Redirect common typo to the correct endpoint
@app.route("/oauth/introspe", methods=["GET"]) 
def oauth_introspe_alias():
    return redirect("/oauth/introspect", code=302)


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

    # Кэшируем в памяти вместо записи в файл
    _memory_token_cache["access_token"] = result.get("access_token")
    _memory_token_cache["raw"] = result

    # Проверим scopes и при наличии imbot/im — автозарегистрируем бота
    try:
        info, err = bitrix_call("app.info", {})
        scopes = []
        if not err and isinstance(info, dict):
            # app.info возвращает список scope в разных форматах; пробуем извлечь
            scopes = info.get("scope") or info.get("SCOPE") or []
            if isinstance(scopes, str):
                scopes = scopes.split(",")
            scopes = [s.strip().lower() for s in scopes]
        if "imbot" in scopes and "im" in scopes:
            print("🔧 Найдены нужные права (imbot, im) — регистрируем бота...")
            register_bot()
        else:
            print("ℹ️ Права imbot/im не обнаружены, пропускаем авто-регистрацию.")
    except Exception as e:
        print("⚠️ Ошибка при проверке прав/авторегистрации:", e)

    return jsonify({"ok": True})


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
        # 2) Environment fallback
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
    except Exception as e:
        print("⚠️ Ошибка при загрузке токена:", e)
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
            err_text = r.text or ""
            content_type = r.headers.get("content-type", "")
            try:
                err_body = r.json() if content_type.startswith("application/json") else {}
            except Exception:
                err_body = {}
            # Normalize error reason text
            err_descr = (err_body.get("error_description") or err_text or "").lower()
            err_code = (err_body.get("error") or "").upper()
            # Trigger refresh on known signals
            token_problem = (
                err_code in {"EXPIRED_TOKEN", "INVALID_TOKEN", "NO_AUTH_FOUND", "INVALID_AUTH"}
                or "access token" in err_descr and "expire" in err_descr
                or "token" in err_descr and "expired" in err_descr
            )
            if token_problem:
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
            # Not a token error — return as Bitrix error (JSON if available)
            if err_body:
                return None, err_body
            return None, {"error": "HTTP_ERROR", "error_description": err_text, "status": r.status_code}
        # Success path
        try:
            data = r.json()
        except Exception:
            data = {}
        if "error" in data:
            # Secondary JSON error handling
            err_descr2 = (data.get("error_description") or "").lower()
            if data.get("error") in {"expired_token", "invalid_token", "NO_AUTH_FOUND", "INVALID_TOKEN"} or ("access token" in err_descr2 and "expire" in err_descr2):
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
# Регистрация бота (helper)
# ----------------------

def register_bot() -> str | None:
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
        print("⚠️ Ошибка регистрации бота:", err)
        return None
    bot_id = None
    if isinstance(result, dict):
        bot_id = result.get("BOT_ID") or result.get("bot_id") or result.get("result")
    else:
        bot_id = result
    _bot_state["bot_id"] = str(bot_id) if bot_id is not None else None
    return _bot_state["bot_id"]


# ----------------------
# Статус OAuth: есть ли токен и какой домен
# ----------------------
@app.route("/oauth/status", methods=["GET"])
def oauth_status():
    access_token, rest_base, raw = load_oauth_tokens()
    source = "memory" if _memory_token_cache.get("access_token") else ("env" if os.getenv("BITRIX_ACCESS_TOKEN") else "none")
    return jsonify({
        "has_access_token": bool(access_token),
        "domain": raw.get("domain") if isinstance(raw, dict) else None,
        "rest_base": rest_base,
        "token_saved": bool(raw),
        "expires_in": (raw or {}).get("expires_in"),
        "member_id": (raw or {}).get("member_id"),
        "source": source,
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

@app.route("/oauth/token", methods=["GET"]) 
def oauth_token_view():
    """Show masked access token. Pass full=1 to return full token (use cautiously)."""
    token = _memory_token_cache.get("access_token") or os.getenv("BITRIX_ACCESS_TOKEN")
    if not token:
        return jsonify({"has_access_token": False}), 404
    show_full = str(request.args.get("full", "0")).lower() in {"1", "true", "yes"}
    masked = token if show_full else (token[:6] + "..." + token[-6:])
    return jsonify({"has_access_token": True, "access_token": masked, "full": show_full})

@app.route("/oauth/refresh_token", methods=["GET"]) 
def oauth_refresh_token_view():
    """Show masked refresh token. Pass full=1 to return full token (use cautiously)."""
    raw = _memory_token_cache.get("raw") or {}
    token = raw.get("refresh_token") or os.getenv("BITRIX_REFRESH_TOKEN")
    if not token:
        return jsonify({"has_refresh_token": False}), 404
    show_full = str(request.args.get("full", "0")).lower() in {"1", "true", "yes"}
    masked = token if show_full else (token[:6] + "..." + token[-6:])
    return jsonify({"has_refresh_token": True, "refresh_token": masked, "full": show_full})

@app.route("/oauth/introspect", methods=["GET"]) 
def oauth_introspect():
    """Call app.info with current token to verify validity and scopes (without showing the token)."""
    token = _memory_token_cache.get("access_token") or os.getenv("BITRIX_ACCESS_TOKEN")
    if not token:
        return jsonify({"ok": False, "error": "no_token"}), 404
    # Use REST base from current status
    access_token, rest_base, _ = load_oauth_tokens()
    if not rest_base:
        rest_base = (os.getenv("BITRIX_REST_BASE") or (os.getenv("BITRIX_DOMAIN") or "").rstrip("/") + "/rest/")
    try:
        r = requests.get(f"{rest_base}app.info", params={"auth": token}, timeout=10)
        body = {}
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        return jsonify({
            "ok": r.ok,
            "status": r.status_code,
            "response": body,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----------------------
# Telegram webhook: принимает сообщения и создаёт/комментирует задачу в Bitrix
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

    # Дополнительно: пересылаем текст из Telegram в Bitrix IM (двусторонний мост)
    try:
        if FORWARD_TELEGRAM_TO_IM in {"1", "true", "TRUE", "yes", "on"} and text:
            target_dialog = BITRIX_IM_DIALOG_ID
            try:
                target_dialog_int = int(str(target_dialog))
            except Exception:
                target_dialog_int = None
            payload = {
                "BOT_ID": int((_bot_state.get("bot_id") or 19510)),
                "DIALOG_ID": target_dialog_int if target_dialog_int is not None else str(target_dialog),
                "MESSAGE": text,
            }
            _res, _err = bitrix_call("imbot.message.add", payload)
            if _err:
                print("⚠️ Ошибка пересылки в Bitrix IM:", _err)
    except Exception as e:
        print("⚠️ Исключение при пересылке в Bitrix IM:", e)

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
        return jsonify({"ok": False, "error": "chat mapping not found for task", "task_id": task_id}), 404

    if TELEGRAM_BOT_TOKEN:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": f"Комментарий к задаче #{task_id}:\n{text}"},
                timeout=10,
            )
            print("🔔 Telegram send status:", r.status_code, r.text)
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
    new_id = register_bot()
    if not new_id:
        return jsonify({"ok": False, "error": "bot_register_failed"}), 400
    return jsonify({"ok": True, "bot_id": new_id})

@app.route("/bot/update", methods=["POST", "GET"]) 
def bot_update():
    # Автообновление существующего бота (по умолчанию BOT_ID=19508) на наш /bot/events
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        bot_id = int(body.get("BOT_ID") or body.get("bot_id") or 19508)
    else:
        bot_id = int(request.args.get("BOT_ID") or request.args.get("bot_id") or 19508)

    fields = {
        "EVENT_MESSAGE_ADD": f"{RENDER_URL}/bot/events",
        "EVENT_WELCOME_MESSAGE": f"{RENDER_URL}/bot/events",
        "EVENT_BOT_DELETE": f"{RENDER_URL}/bot/events",
        "OPENLINE": "N",
        "PROPERTIES": {
            "NAME": "Бот техподдержки",
            "COLOR": "GRAY",
        },
    }
    payload = {
        "BOT_ID": bot_id,
        "FIELDS": fields,
    }
    result, err = bitrix_call("imbot.update", payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "result": result, "bot_id": bot_id})

@app.route("/bot/reinstall", methods=["POST", "GET"]) 
def bot_reinstall():
    # Принудительная переустановка бота: unregister + register
    try:
        # 1) Определить текущий/указанный BOT_ID
        provided_id = request.args.get("BOT_ID") or request.args.get("bot_id")
        current_id = _bot_state.get("bot_id")
        bot_id_to_remove = provided_id or current_id

        # 2) Попробовать удалить старого бота (если есть)
        if bot_id_to_remove:
            _res, _err = bitrix_call("imbot.unregister", {"BOT_ID": int(bot_id_to_remove)})
            # Игнорируем ошибку удаления — возможно, бот уже отсутствует

        # 3) Зарегистрировать нового бота с корректными обработчиками
        new_id = register_bot()
        if not new_id:
            return jsonify({"ok": False, "error": "bot_register_failed"}), 400
        return jsonify({"ok": True, "old_bot_id": bot_id_to_remove, "bot_id": new_id})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/bot/events", methods=["POST", "GET"]) 
def bot_events():
    if request.method == "GET":
        return jsonify({"ok": True, "message": "bot events endpoint is up"})

    # Пробуем получить JSON или форму (Bitrix может прислать form-urlencoded)
    body = request.get_json(silent=True) or {}
    if not body:
        try:
            body = request.form.to_dict(flat=False)
        except Exception:
            body = {}

    # Если внутри есть строка JSON — тоже парсим
    if isinstance(body.get("data"), str):
        try:
            body["data"] = json.loads(body["data"])
        except Exception:
            pass

    print("\n====== 📥 ПРИШЛО СООБЩЕНИЕ ОТ BITRIX ======")
    print(json.dumps(body, ensure_ascii=False, indent=2))
    print("===========================================\n")

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
# Helpers: find existing bot by CODE
# ----------------------

def find_bot_id_by_code(code: str) -> str | None:
    listing, err = bitrix_call("imbot.bot.list", {})
    if err or not isinstance(listing, list):
        return None
    for b in listing:
        bcode = (b or {}).get("CODE") or (b or {}).get("code")
        if str(bcode).lower() == str(code).lower():
            return str((b or {}).get("BOT_ID") or (b or {}).get("ID"))
    return None


# ----------------------
# Automatic bootstrap (run once on first incoming request)
# ----------------------

def _auto_bootstrap():
    try:
        print("⚙️ Bootstrap: validating token and bot configuration...")
        access_token, rest_base, raw = load_oauth_tokens()
        if not access_token or not rest_base:
            print("⚠️ Bootstrap: no access token/rest base; set BITRIX_ACCESS_TOKEN/BITRIX_REST_BASE or complete OAuth.")
            return
        # Introspect token
        try:
            r = requests.get(f"{rest_base}app.info", params={"auth": access_token}, timeout=10)
            info = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if not r.ok:
                print("⚠️ Bootstrap: app.info not ok:", r.status_code, info)
                return
        except Exception as e:
            print("⚠️ Bootstrap: app.info request failed:", e)
            return
        # Ensure scopes
        scopes = []
        try:
            res = info.get("result") or {}
            scopes = res.get("scope") or res.get("SCOPE") or []
            if isinstance(scopes, str):
                scopes = [s.strip() for s in scopes.split(",") if s.strip()]
            scopes = [s.lower() for s in scopes]
        except Exception:
            scopes = []
        if not ("imbot" in scopes and "im" in scopes):
            print("⚠️ Bootstrap: required scopes imbot/im are missing; grant scopes in app and re-auth.")
            return
        # Ensure bot
        desired_code = "support_bridge_bot"
        current_id = _bot_state.get("bot_id")
        if not current_id:
            found = find_bot_id_by_code(desired_code)
            if found:
                _bot_state["bot_id"] = found
                print("✅ Bootstrap: found existing bot_id:", found)
        # Register if still missing
        if not _bot_state.get("bot_id"):
            new_id = register_bot()
            if new_id:
                print("✅ Bootstrap: bot registered:", new_id)
            else:
                print("⚠️ Bootstrap: bot registration failed; try manual /bot/register after fixing scopes.")
                return
        # Update events to point to our /bot/events
        try:
            bot_id_int = int(str(_bot_state.get("bot_id")))
        except Exception:
            bot_id_int = None
        if bot_id_int is not None:
            fields = {
                "EVENT_MESSAGE_ADD": f"{RENDER_URL}/bot/events",
                "EVENT_WELCOME_MESSAGE": f"{RENDER_URL}/bot/events",
                "EVENT_BOT_DELETE": f"{RENDER_URL}/bot/events",
            }
            _upd, upd_err = bitrix_call("imbot.update", {"BOT_ID": bot_id_int, "FIELDS": fields})
            if upd_err:
                print("⚠️ Bootstrap: imbot.update failed:", upd_err)
            else:
                print("✅ Bootstrap: bot events updated")
    except Exception as e:
        print("⚠️ Bootstrap exception:", e)

@app.before_request
def _maybe_run_bootstrap_once():
    global _did_bootstrap
    if not _did_bootstrap:
        _did_bootstrap = True
        _auto_bootstrap()

# ----------------------
# Любые другие пути — для отладки
# ----------------------
@app.route("/<path:unknown>", methods=["GET", "POST"]) 
def catch_all(unknown):
    return f"❌ Путь '{unknown}' не обрабатывается этим сервером.", 404

# Debug: list routes
@app.route("/routes", methods=["GET"]) 
def list_routes():
    try:
        rules = []
        for r in app.url_map.iter_rules():
            rules.append({"rule": str(r), "methods": sorted(list(r.methods or []))})
        return jsonify({"ok": True, "routes": rules})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# Ensure /bot/send exists
@app.route("/bot/send", methods=["POST", "GET"]) 
def bot_send_route():
    # Delegate to existing logic (same as earlier bot_send)
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        dialog_id = body.get("DIALOG_ID") or body.get("dialog_id")
        message = body.get("MESSAGE") or body.get("message")
        bot_id = body.get("BOT_ID") or body.get("bot_id") or _bot_state.get("bot_id") or 19510
    else:
        dialog_id = request.args.get("DIALOG_ID") or request.args.get("dialog_id")
        message = request.args.get("MESSAGE") or request.args.get("message")
        bot_id = request.args.get("BOT_ID") or request.args.get("bot_id") or _bot_state.get("bot_id") or 19510

    if not dialog_id or not message:
        return jsonify({"ok": False, "error": "dialog_id and message are required"}), 400

    payload = {
        "BOT_ID": int(bot_id),
        "DIALOG_ID": dialog_id if isinstance(dialog_id, int) or (isinstance(dialog_id, str) and dialog_id.isdigit()) else str(dialog_id),
        "MESSAGE": message,
    }
    result, err = bitrix_call("imbot.message.add", payload)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "result": result, "bot_id": str(bot_id), "dialog_id": str(dialog_id)})


# ----------------------
# Запуск
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
