
import ast
import html
import json
import math
import os
import random
import re
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid

# ---------------------------------------------------------------- إعدادات
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")          # توكن بوت تليجرام
DEEPAI_API_KEY = os.environ.get("DEEPAI_API_KEY", "")  # مفتاح DeepAI Pro (اختياري)
DEEP_CHAT_URL = "https://api.deepai.org/hacking_is_a_serious_crime"
DEEP_IMG_URL = "https://api.deepai.org/api/text2img"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".deepai_bot_state.json")
TG_API = "https://api.telegram.org/bot"


GIGA_BASE = "https://giga.chat"
GIGA_APP = "gigachat-b2c-web-neo"
GIGA_VERSION = "0.15.13"
GIGA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
GIGA_SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".giga_bot_session.json")
# (id, الاسم المعروض, وصف)
GIGA_MODES = [
    ("reasoning", "🧠 تفكير عميق", "GigaChat-3.5-432B-A28B — رياضيات ومنطق خطوة بخطوة"),
    ("giga", "💬 جيجا", "رد سريع عام"),
    ("deep-research", "🔍 بحث عميق", "بحث عميق بخطوات LOG — بياخد دقايق"),
    ("education", "🎓 تعليم", "شرح وتعليم"),
]
GIGA_BY_ID = {m[0]: m for m in GIGA_MODES}
GIGA_AGENTS = {
    "giga": {"guest": "cc540466-dc61-403f-8836-ab4c630ad228",
             "authed": "019a5d95-ab99-7c86-a31c-610dad03b054"},
    "reasoning": {"guest": "cc540466-dc61-403f-8836-ab4c630ad228",
                  "authed": "019a5d95-ab99-7c86-a31c-610dad03b054"},
    "deep-research": {"guest": "019e20bb-666d-753a-a91c-6375e175e7e7",
                      "authed": "9384a8fd-39e0-4da9-9bc4-da143487449f"},
    "education": {"guest": "019e9310-695a-7cd2-8f90-3c06bda7722d",
                  "authed": "019df879-c311-708b-a82c-04d73566fe02"},
}

def _giga_bytes_from_uuid(s):
    h = s.replace("-", "")
    return bytearray(int(h[i:i + 2], 16) for i in range(0, 32, 2))

def _giga_sum_except(b, skip=None):
    return sum(v for i, v in enumerate(b) if i != skip)

def derive_auth_session_id(device_id):
    """نفس معادلة الجافاسكربت (6819.js module 90560) بالظبط."""
    r = _giga_bytes_from_uuid(str(uuid.uuid4()))
    i = random.randrange(9)
    r[6] = (0xF0 & r[6]) | i
    a = 7 + i
    n = (_giga_sum_except(_giga_bytes_from_uuid(device_id)) + _giga_sum_except(r, a)) % 256
    r[a] = n
    o = "".join(f"{b:02x}" for b in r)
    return f"{o[0:8]}-{o[8:12]}-{o[12:16]}-{o[16:20]}-{o[20:]}"

def _load_giga_session():
    if os.path.exists(GIGA_SESSION_FILE):
        try:
            with open(GIGA_SESSION_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"device_id": str(uuid.uuid4()), "cookies": {}}

def _save_giga_session(data):
    try:
        with open(GIGA_SESSION_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

class GigaChat:
    def __init__(self, sm_sess=None):
        self.state = _load_giga_session()
        self.device_id = self.state.get("device_id") or str(uuid.uuid4())
        self.state["device_id"] = self.device_id
        self.cookies = dict(self.state.get("cookies") or {})
        self.sm_sess = sm_sess or os.environ.get("GIGA_SM_SESS") or ""
        self.authed = bool(self.sm_sess)
        self.sd_user_id = self.cookies.get("_sd_user_id", "")

    def _headers(self, stream=False):
        h = {
            "User-Agent": GIGA_UA,
            "Accept": "text/event-stream, application/json" if stream else "application/json",
            "Content-Type": "application/json",
            "X-Application-Name": GIGA_APP,
            "X-Application-Version": GIGA_VERSION,
            "X-Request-Id": str(uuid.uuid4()),
            "X-User-Timezone": "Africa/Cairo",
        }
        if not self.authed:
            h["x-device-id"] = self.device_id
            h["x-sm-user-id"] = self.sd_user_id or self.device_id
            if self.sd_user_id:
                h["x-project-id"] = self.sd_user_id
        return h

    def _cookie_header(self):
        parts = []
        if self.sm_sess:
            parts.append(f"_sm_sess={self.sm_sess}")
        for k, v in self.cookies.items():
            if k == "_sm_sess":
                continue
            parts.append(f"{k}={v}")
        return "; ".join(parts)

    def _request(self, method, url, body=None, stream=False, timeout=60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method,
                                     headers=self._headers(stream=stream))
        ck = self._cookie_header()
        if ck:
            req.add_header("Cookie", ck)
        try:
            resp = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")
            raise RuntimeError(f"HTTP {e.code} on {method} {url}\n{raw[:800]}")
        for c in resp.headers.get_all("Set-Cookie") or []:
            kv = c.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                self.cookies[k.strip()] = v.strip()
                if k.strip() == "_sd_user_id":
                    self.sd_user_id = v.strip()
        _save_giga_session({"device_id": self.device_id, "cookies": self.cookies})
        return resp

    def _api_base(self):
        return (f"{GIGA_BASE}/api/giga-back-web" if self.authed
                else f"{GIGA_BASE}/api/smartproxy/api/prelogin")

    def guest_login(self):
        auth_session = derive_auth_session_id(self.device_id)
        url = f"{GIGA_BASE}/api/smartproxy/api/prelogin/api/v0/prelogin/login"
        headers = self._headers()
        headers["X-Auth-Session-Id"] = auth_session
        headers["X-Prelogin-User-Id"] = self.device_id
        req = urllib.request.Request(url, data=None, method="POST", headers=headers)
        ck = self._cookie_header()
        if ck:
            req.add_header("Cookie", ck)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"guest login HTTP {e.code}: "
                               f"{e.read().decode('utf-8', 'ignore')[:500]}")
        for c in resp.headers.get_all("Set-Cookie") or []:
            kv = c.split(";", 1)[0]
            if "=" in kv:
                k, v = kv.split("=", 1)
                self.cookies[k.strip()] = v.strip()
                if k.strip() == "_sd_user_id":
                    self.sd_user_id = v.strip()
        _save_giga_session({"device_id": self.device_id, "cookies": self.cookies})
        return json.loads(resp.read().decode("utf-8", "ignore") or "{}")

    def ensure_guest(self):
        if self.authed:
            return
        if not self.sd_user_id:
            r = self.guest_login()
            if r.get("status") != "ok":
                raise RuntimeError(f"guest login failed: {r}")

    def chat(self, prompt, mode="reasoning", session_id=None, timeout=300):
        """بيرجع dict: session_id, answer, thinking, logs, model, events"""
        self.ensure_guest()
        mode = mode if mode in GIGA_AGENTS else "reasoning"
        agent = GIGA_AGENTS[mode]["authed" if self.authed else "guest"]
        body = {"text": prompt, "agent": agent}
        if mode == "reasoning":
            body["featureFlags"] = ["REASONING"]
        if session_id:
            url = f"{self._api_base()}/api/v0/sessions/{session_id}/request"
        else:
            url = f"{self._api_base()}/api/v0/sessions/request"
        resp = self._request("POST", url, body=body, stream=True, timeout=timeout)
        answer, thinking, logs = "", "", []
        model, sid, events = None, session_id, 0
        buf = ""
        while True:
            line = resp.readline()
            if not line:
                break
            line = line.decode("utf-8", "ignore")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                buf += line[5:].strip() + "\n"
                continue
            if line.strip() == "" and buf.strip():
                events += 1
                try:
                    ev = json.loads(buf)
                except json.JSONDecodeError:
                    buf = ""
                    continue
                buf = ""
                sid = ev.get("sessionId") or sid
                status = ev.get("status")
                if status == "ERROR":
                    raise RuntimeError(f"stream ERROR: {json.dumps(ev, ensure_ascii=False)[:800]}")
                for block in ev.get("contentDelta", []) or []:
                    role = block.get("role")
                    txt = block.get("delta") or block.get("value") or ""
                    if role == "REASONING":
                        thinking += txt
                    elif role == "LOG":
                        logs.append(txt)
                    elif role in ("ASSISTANT", "AI"):
                        answer += txt
                if ev.get("model"):
                    model = ev["model"]
                if status == "READY":
                    msg = ev.get("message") or {}
                    model = msg.get("model") or model
                    if not answer:
                        for block in msg.get("content", []) or []:
                            if block.get("role") in ("ASSISTANT", "AI"):
                                answer += block.get("value") or ""
                    break
        return {"session_id": sid, "answer": answer, "thinking": thinking,
                "logs": logs, "model": model, "events": events}

# كائن واحد مشترك (هوية الضيف بتاعت البوت) — جلسة الشات لكل مستخدم لوحده
GIGA = GigaChat()


MODELS = [
    # --- مجانية (10) ---
    ("glm-5.3-flash", "GLM 5.3 Flash", True, True, True, "سريع، كود ومهام وكيل، سياق 1M — اللي في الصورة 🧠"),
    ("standard", "Standard", True, False, True, "النموذج الافتراضي العام"),
    ("claude-haiku-5-5", "Claude Haiku 5.5", True, False, True, "خفيف وحديث من Anthropic"),
    ("qwen3.8-flash", "Qwen 3.8 Flash", True, False, True, "سريع"),
    ("deepseek-v4.1-flash", "DeepSeek V4.1 Flash", True, False, True, "سريع وحديث"),
    ("gpt-6-luna", "GPT-6 Luna", True, False, True, "سريع وخفيف"),
    ("tencent-hy3", "Tencent Hy3", True, False, True, "عام"),
    ("gemma-4", "Gemma 4", True, False, True, "من Google"),
    ("llama-3.3-70b-instruct", "Llama 3.3 70B", True, False, True, "قوي ومفتوح"),
    ("llama-3.1-8b-instant", "Llama 3.1 8B Instant", True, False, False, "فوري وخفيف (من غير وضع وكيل)"),
]
BY_ID = {m[0]: m for m in MODELS}
FREE_MODELS = [m for m in MODELS if m[2]]
THINKING_MODELS = [m for m in MODELS if m[3]]

CHAT_STYLE = "chat"

# ---------------------------------------------------------------- حالة المستخدمين
def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(st):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=1)
    except Exception:
        pass

def user_state(st, uid):
    u = st.setdefault(str(uid), {
        "model": "glm-5.3-flash", "history": [], "memory": [],
        "web": False, "agent": True, "memory_on": False,
        "awaiting": None, "page": 0, "tab": "free",
        "provider": "deepai", "giga_mode": "reasoning", "giga_session": None,
        "rich": True,
    })
    return u

# ---------------------------------------------------------------- تليجرام
def tg(method, data=None, files=None, timeout=60):
    url = TG_API + BOT_TOKEN + "/" + method
    if files:
        import uuid
        boundary = "----tg" + uuid.uuid4().hex
        body = b""
        for k, v in (data or {}).items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                     % (boundary, k, v)).encode()
        for k, (fname, content, ctype) in files.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                     "Content-Type: %s\r\n\r\n" % (boundary, k, fname, ctype)).encode() + content + b"\r\n"
        body += ("--%s--\r\n" % boundary).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(data or {}).encode(),
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}

def tg_json(method, payload, timeout=60):
    """POST بصيغة JSON — لازم لـ sendRichMessage لأن rich_message كائن مش نص."""
    url = TG_API + BOT_TOKEN + "/" + method
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode())
        except Exception:
            return {"ok": False, "description": str(e)}
    except Exception as e:
        return {"ok": False, "description": str(e)}

def send(chat_id, text, reply_markup=None, parse_mode="HTML"):
    d = {"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode,
         "disable_web_page_preview": True}
    if reply_markup:
        d["reply_markup"] = json.dumps(reply_markup)
    return tg("sendMessage", d)

def send_long(chat_id, text, reply_markup=None):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 4000:
            parts.append(cur); cur = line
        else:
            cur += ("\n" if cur else "") + line
    if cur:
        parts.append(cur)
    for i, p in enumerate(parts):
        send(chat_id, p, reply_markup if i == len(parts) - 1 else None)


RICH_LIMIT = 30000

def _rich_units(text):
    """قسّم الماركداون لوحدات (فقرات / جداول / بلوكات كود) من غير ما نكسر جدول أو كود."""
    lines = text.split("\n")
    units, cur, in_fence = [], [], False

    def flush():
        nonlocal cur
        if cur:
            units.append("\n".join(cur).strip("\n"))
            cur = []

    for ln in lines:
        s = ln.strip()
        if s.startswith("```"):
            if not in_fence:
                flush()
                in_fence = True
                cur = [ln]
            else:
                cur.append(ln)
                in_fence = False
                flush()
            continue
        if in_fence:
            cur.append(ln)
            continue
        if s.startswith("|"):
            if cur and not cur[-1].strip().startswith("|"):
                flush()
            cur.append(ln)
            continue
        if cur and cur[-1].strip().startswith("|"):
            flush()
        if s == "":
            flush()
        else:
            cur.append(ln)
    flush()
    return [u for u in units if u.strip()]

def split_rich(text, limit=RICH_LIMIT):
    """قسّم رد طويل لأجزاء Rich من غير ما نكسر جدول أو بلوك كود في النص."""
    chunks, cur = [], ""
    for u in _rich_units(text):
        if len(u) > limit:  # وحدة واحدة ضخمة — قصّها قسراً
            if cur:
                chunks.append(cur); cur = ""
            for i in range(0, len(u), limit):
                chunks.append(u[i:i + limit])
            continue
        if cur and len(cur) + len(u) + 2 > limit:
            chunks.append(cur); cur = u
        else:
            cur = (cur + "\n\n" + u) if cur else u
    if cur:
        chunks.append(cur)
    return chunks or [""]

def send_rich(chat_id, markdown_text, reply_markup=None):
    """ابعت رد النموذج كـ Rich Message (جداول حقيقية، عناوين، كود...).
       ولو فشل لأي سبب (ماركداون مكسور، عميل قديم...) ارجع للرسالة العادية."""
    for chunk in split_rich(markdown_text):
        payload = {"chat_id": chat_id, "rich_message": {"markdown": chunk}}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = tg_json("sendRichMessage", payload)
        if not r.get("ok"):
            send_long(chat_id, html.escape(chunk))

def edit(chat_id, msg_id, text, reply_markup=None):
    d = {"chat_id": chat_id, "message_id": msg_id, "text": text[:4096],
         "parse_mode": "HTML", "disable_web_page_preview": True}
    if reply_markup:
        d["reply_markup"] = json.dumps(reply_markup)
    return tg("editMessageText", d)

def answer_callback(cb_id, text=""):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text[:200]})

def typing(chat_id):
    tg("sendChatAction", {"chat_id": chat_id, "action": "typing"})

def kb(rows):
    return {"inline_keyboard": rows}

def btn(text, data):
    return {"text": text, "callback_data": data[:64]}

# ---------------------------------------------------------------- DeepAI
def deepai_chat(model_id, history, session_uuid=None, thinking=False,
                  web=False, sandbox=False, memory=False):
    """الريكوست الأساسي — نفس ريكوست شات الموقع بالظبط (FormData).
    بيرجع (ok, text). من غير كوكيز/جلسة متصفح السيرفر بيرد بالإجابة نص على طول
    (حتى مع thinking_support=1) — الـ task_id + polling بيشتغلوا بس مع جلسة متصفح."""
    import uuid as _uuid
    data = {
        "model": model_id,
        "chat_style": CHAT_STYLE,
        "language": "en",
        "chatHistory": json.dumps(history, ensure_ascii=False),
        "session_uuid": session_uuid or str(_uuid.uuid4()),
        "sensitivity_request_id": str(_uuid.uuid4()),
        "tool_activity_support": "1",
        "thinking_image_tool_support": "1",
        "enabled_tools": '["image_generator","image_editor"]',
        "web_access_enabled": "true" if web else "false",
        "sandbox_enabled": "true" if sandbox else "false",
        "memory_enabled": "true" if memory else "false",
        "hacker_is_stinky": "very_stinky",
    }
    if thinking:
        data["thinking_support"] = "1"
    if sandbox:
        data["sandbox_turn_id"] = str(_uuid.uuid4())
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(DEEP_CHAT_URL, data=body, method="POST",
                                 headers={"User-Agent": "Mozilla/5.0"})
    if DEEPAI_API_KEY:
        req.add_header("api-key", DEEPAI_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return True, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        if "Only paid accounts can use genius" in raw or "only available to paid users" in raw:
            return False, "PAID"
        if "try it exceeded" in raw or "try-it quota exceeded" in raw:
            return False, "QUOTA"
        return False, "HTTP %s: %s" % (e.code, raw[:300])
    except Exception as e:
        return False, str(e)

def deepai_image(prompt):
    """توليد صورة — محتاج DEEPAI_API_KEY. بيرجع (ok, url_or_error)."""
    if not DEEPAI_API_KEY:
        return False, "NO_KEY"
    data = urllib.parse.urlencode({"text": prompt}).encode()
    req = urllib.request.Request(DEEP_IMG_URL, data=data, method="POST",
                                 headers={"api-key": DEEPAI_API_KEY,
                                          "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            j = json.loads(r.read().decode())
            return True, j.get("output_url") or str(j)
    except urllib.error.HTTPError as e:
        return False, "HTTP %s: %s" % (e.code, e.read().decode()[:300])
    except Exception as e:
        return False, str(e)

def web_search(query, n=5):
    """بحث ويب حقيقي من غير مفتاح (DuckDuckGo lite)."""
    try:
        q = urllib.parse.urlencode({"q": query})
        req = urllib.request.Request("https://html.duckduckgo.com/html/?" + q,
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", "replace")
        out = []
        for m in re.finditer(r'class="result__a"[^>]*>(.*?)</a>.*?(?:class="result__snippet"[^>]*>(.*?)</a>)?',
                             page, re.S):
            title = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            snip = re.sub(r"<[^>]+>", "", m.group(2) or "").strip()
            if title:
                out.append("• %s%s" % (title, (" — " + snip) if snip else ""))
            if len(out) >= n:
                break
        return "\n".join(out) if out else ""
    except Exception:
        return ""

# ---------------------------------------------------------------- الوكيل
def safe_calc(expr):
    """آلة حاسبة آمنة (من غير eval على كود عشوائي)."""
    expr = expr.replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", ".")
    if not re.fullmatch(r"[0-9\s\.\+\-\*/\%\(\)]+", expr):
        return None
    try:
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Num,
                                     ast.Constant, ast.Add, ast.Sub, ast.Mult, ast.Div,
                                     ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Load)):
                return None
        return eval(compile(tree, "<calc>", "eval"), {"__builtins__": {}}, {})
    except Exception:
        return None

MATH_RE = re.compile(r"(?:احسب|حساب|كام يساوي|=)\s*([0-9\.\+\-\*/\%\(\)\s×÷\^,]+)|^([0-9\.\+\-\*/\%\(\)\s×÷\^]{3,})$")

# أمر إرسال رسالة: "ابعت رسالة لـ 123456: النص" أو "send to 123456: text"
SEND_RE = re.compile(r"(?:ابعت(?:ي)?|ارسل|أرسل|send)\s+(?:رسالة\s+)?(?:لـ|ل|الى|إلى|to)?\s*(\d{5,})\s*[:：\-]?\s*(.+)", re.S)

def do_send(target_id, text):
    """أداة الوكيل: إرسال رسالة تليجرام لمستخدم برقمه. بترجع (ok, message_id_or_error)."""
    r = tg("sendMessage", {"chat_id": target_id, "text": text[:4096]})
    if r.get("ok"):
        return True, r["result"]["message_id"]
    return False, r.get("description", "خطأ غير معروف")


def agent_tools(text, u):
    """أدوات الوكيل قبل ما نوصل للنموذج. بيرجع (handled, reply_text)."""
    t = text.strip()
    sm = SEND_RE.search(t)
    if sm:
        return True, "SENDTO:%s:%s" % (sm.group(1), sm.group(2).strip())
    m = MATH_RE.search(t)
    if m:
        expr = (m.group(1) or m.group(2) or "").strip()
        val = safe_calc(expr)
        if val is not None:
            return True, "🧮 <b>الحاسبة:</b>\n<code>%s</code> = <b>%s</b>" % (html.escape(expr), val)
    low = t.lower()
    if any(w in low for w in ("احفظ", "اعمل ملف", "حفظ", "save", "ملف txt", "نزل")) and len(t) > 12:
        return True, "FILE:" + t
    return False, ""

# ---------------------------------------------------------------- القوائم
PAGE_SIZE = 10

def models_tab(u):
    return u.get("tab", "free")

def tab_models(u):
    tab = models_tab(u)
    if tab == "free":
        return [m for m in MODELS if m[2]]
    if tab == "thinking":
        return [m for m in MODELS if m[3]]
    if tab == "paid":
        return [m for m in MODELS if not m[2]]
    return MODELS

def model_menu(u):
    ms = tab_models(u)
    page = u.get("page", 0)
    pages = max(1, (len(ms) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    u["page"] = page
    chunk = ms[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
    rows = []
    for mid, name, free, think, agent_ok, desc in chunk:
        mark = "✅ " if u.get("model") == mid else ""
        lock = "" if free else "🔒 "
        rows.append([btn("%s%s%s" % (mark, lock, name), "m:" + mid)])
    # زرار التنقل بين الصفحات بيظهر بس لو فيه أكتر من صفحة (دلوقتي صفحة واحدة بس)
    # وزرار التبويبات (مجانية / تفكير عميق / الكل) اتشال بطلب محمود — القايمة
    # بقت النماذج المجانية بس على طول من غير تبويبات.
    nav = []
    if page > 0:
        nav.append(btn("◀ السابق", "pg:-1"))
    if page < pages - 1:
        nav.append(btn("التالي ▶", "pg:1"))
    if nav:
        rows.append(nav)
    rows.append([btn("🤖 GigaChat", "giga_menu")])
    rows.append([btn("🛠️ أدوات الوكيل", "tools")])
    cur = BY_ID.get(u.get("model"), MODELS[0])
    head = ("🤖 <b>اختار النموذج</b>\n"
            "النموذج الحالي: <b>%s</b> %s\n\n"
            "دوس على أي نموذج عشان تختاره ✅ — بعدها ابعت رسالتك على طول.\n"
            "كل النماذج هنا مجانية وشغالة دلوقتي 🆓\n"
            "أو دوس <b>🤖 GigaChat</b> عشان تبدأ محادثة جيجا شات على طول." % (
                html.escape(current_name(u)),
                "🧠 تفكير عميق" if u.get("provider", "deepai") == "deepai" and cur[3] else ""))
    return head, kb(rows)

def current_name(u):
    """اسم الاختيار الحالي (نموذج DeepAI أو مود GigaChat)."""
    if u.get("provider", "deepai") == "giga":
        return GIGA_BY_ID.get(u.get("giga_mode", "reasoning"), GIGA_MODES[0])[1]
    return BY_ID.get(u.get("model"), MODELS[0])[1]

def tools_menu(u):
    def onoff(v):
        return "✅ شغال" if v else "❌ مطفي"
    txt = ("🛠️ <b>أدوات الوكيل</b>\n\n"
           "🌐 بحث الويب: %s\n"
           "🤖 وضع الوكيل: %s\n"
           "🧠 الذاكرة: %s\n"
           "💬 شكل الردود: %s\n\n"
           "النموذج الحالي: <b>%s</b>" % (
               onoff(u.get("web")), onoff(u.get("agent")), onoff(u.get("memory_on")),
               "🆕 جديدة" if u.get("rich", True) else "📄 قديمة",
               html.escape(current_name(u))))
    cur_model = BY_ID.get(u.get("model"), MODELS[0])
    agent_note = "" if cur_model[4] else " (غير متاح مع النموذج ده — زي الموقع)"
    rows = [
        [btn("🌐 بحث الويب: %s" % onoff(u.get("web")), "tgl:web")],
        [btn("🤖 وضع الوكيل: %s%s" % (onoff(u.get("agent")), agent_note), "tgl:agent")],
        [btn("🧠 الذاكرة: %s" % onoff(u.get("memory_on")), "tgl:memory_on")],
        [btn("💬 شكل الردود: %s" % ("🆕 جديدة" if u.get("rich", True) else "📄 قديمة"), "tgl:rich")],
        [btn("⬅️ رجوع للنماذج", "back")],
    ]
    return txt, kb(rows)

# ---------------------------------------------------------------- المعالجة
def do_giga_chat(chat_id, u, text, st):
    """ابعت رسالة المستخدم لـ GigaChat ورد عليه (فرع جيجا من do_chat)."""
    typing(chat_id)
    sys_notes = []
    if u.get("agent"):
        sys_notes.append("أنت وكيل ذكي: قسّم المهمة لخطوات، اشرح خطواتك باختصار، ثم أعطِ النتيجة النهائية.")
        sys_notes.append("أداة إرسال رسائل تليجرام: لو المستخدم طلب منك تبعت رسالة لمستخدم معين، "
                         "رد بسطر واحد بالصيغة دي بالظبط ومن غير أي كلام زيادة: SEND|user_id|نص الرسالة "
                         "(مثال: SEND|7602919067|أهلاً بيك). لا تشرح ولا تعتذر — نفّذ بالصيغة دي.")
    if u.get("memory_on") and u.get("memory"):
        sys_notes.append("معلومات تتذكرها عن المستخدم:\n" + "\n".join("- " + x for x in u["memory"][-10:]))
    if u.get("web"):
        res = web_search(text)
        if res:
            sys_notes.append("نتائج بحث من الويب عن سؤال المستخدم (استخدمها في إجابتك واذكر أنها من الويب):\n" + res)
        else:
            sys_notes.append("بحث الويب لم يجد نتائج — أجب من معرفتك ووضّح ذلك.")
    prompt = ("\n\n".join(sys_notes) + "\n\nسؤال المستخدم: " + text) if sys_notes else text
    mode = u.get("giga_mode", "reasoning")
    try:
        r = GIGA.chat(prompt, mode=mode, session_id=u.get("giga_session"),
                      timeout=300 if mode == "deep-research" else 120)
    except Exception as e:
        send(chat_id, "⚠️ حصل خطأ من GigaChat:\n<code>%s</code>" % html.escape(str(e)[:500]))
        return
    if r.get("session_id"):
        u["giga_session"] = r["session_id"]
    ans = (r.get("answer") or "").strip()
    if ans.startswith("SEND|"):
        try:
            _, tid, body = ans.split("|", 2)
            tid, body = tid.strip(), body.strip()
            if tid.isdigit() and body:
                ok2, res2 = do_send(tid, body)
                if ok2:
                    send(chat_id, "✅ <b>النموذج بعت الرسالة</b> للمستخدم <code>%s</code> (رسالة رقم %s)." % (tid, res2))
                else:
                    send(chat_id, "⚠️ النموذج طلب يبعت، بس الإرسال فشل:\n<code>%s</code>" % html.escape(str(res2)[:300]))
                save_state(st)
                return
        except Exception:
            pass
    if not ans:
        ans = "(مفيش إجابة — جرّب تبعت السؤال تاني.)"
    if u.get("memory_on"):
        m = re.search(r"افتكر (?:ان|أن|اني|إني)?\s*(.+)", text)
        if m:
            u["memory"].append(m.group(1).strip()[:300])
    save_state(st)
    out = ""
    plain = ""
    if r.get("thinking"):
        out += "**🧠 التفكير:**\n\n%s\n\n" % r["thinking"][:1500]
        plain += "🧠 التفكير:\n%s\n\n" % r["thinking"][:1500]
    if r.get("logs"):
        out += "**🔍 خطوات البحث:**\n\n%s\n\n" % "\n".join("- " + x for x in r["logs"])[:1500]
        plain += "🔍 خطوات البحث:\n%s\n\n" % "\n".join(r["logs"])[:1500]
    out += ans
    plain += ans
    mode_name = GIGA_BY_ID.get(mode, GIGA_MODES[0])[1]
    model = r.get("model")
    out += "\n\n— *%s%s*" % (mode_name, (" • " + str(model)) if model else "")
    plain += "\n\n— %s%s" % (mode_name, (" • " + str(model)) if model else "")
    if u.get("rich", True):
        send_rich(chat_id, out)
    else:
        send_long(chat_id, html.escape(plain))

def do_chat(chat_id, u, text, st):
    """ابعت رسالة المستخدم للنموذج ورد عليه."""
    typing(chat_id)
    if u.get("provider", "deepai") == "giga":
        do_giga_chat(chat_id, u, text, st)
        return
    hist = list(u.get("history", []))
    sys_notes = []
    if u.get("agent"):
        sys_notes.append("أنت وكيل ذكي: قسّم المهمة لخطوات، اشرح خطواتك باختصار، ثم أعطِ النتيجة النهائية.")
        sys_notes.append("أداة إرسال رسائل تليجرام: لو المستخدم طلب منك تبعت رسالة لمستخدم معين، "
                         "رد بسطر واحد بالصيغة دي بالظبط ومن غير أي كلام زيادة: SEND|user_id|نص الرسالة "
                         "(مثال: SEND|7602919067|أهلاً بيك). لا تشرح ولا تعتذر — نفّذ بالصيغة دي.")
    if u.get("memory_on") and u.get("memory"):
        sys_notes.append("معلومات تتذكرها عن المستخدم:\n" + "\n".join("- " + x for x in u["memory"][-10:]))
    if u.get("web"):
        res = web_search(text)
        if res:
            sys_notes.append("نتائج بحث من الويب عن سؤال المستخدم (استخدمها في إجابتك واذكر أنها من الويب):\n" + res)
        else:
            sys_notes.append("بحث الويب لم يجد نتائج — أجب من معرفتك ووضّح ذلك.")
    call_hist = ([{"role": "user", "content": "\n\n".join(sys_notes)}] if sys_notes else []) + hist + \
                [{"role": "user", "content": text}]
    model_id = u.get("model", "glm-5.3-flash")
    info = BY_ID.get(model_id, MODELS[0])
    if not u.get("session_uuid"):
        import uuid as _uuid
        u["session_uuid"] = str(_uuid.uuid4())
    ok, ans = deepai_chat(model_id, call_hist,
                          session_uuid=u["session_uuid"],
                          thinking=bool(info[3]),
                          web=bool(u.get("web")),
                          sandbox=bool(u.get("agent") and info[4]),
                          memory=bool(u.get("memory_on")))
    if not ok and ans == "PAID":
        send(chat_id, "🔒 النموذج ده مدفوع (Genius) ومحتاج حساب Pro.\n"
                      "اختار نموذج مجاني من /models — أو حط مفتاح Pro في "
                      "متغير البيئة وشغّل البوت تاني.")
        return
    if not ok and ans == "QUOTA":
        send(chat_id, "⏳ الاستخدام المجاني خلص مؤقتاً (الموقع بيحدد عدد "
                      "الرسايل من غير حساب). جرّب تاني بعد شوية، أو سجّل دخول "
                      "بحساب Pro.")
        return
    if not ok:
        send(chat_id, "⚠️ حصل خطأ:\n<code>%s</code>" % html.escape(str(ans)[:500]))
        return
    ans = ans.strip()
    # النموذج طلب إرسال رسالة (صيغة الوكيل SEND|id|text) — نفّذها من الكود
    if ans.startswith("SEND|"):
        try:
            _, tid, body = ans.split("|", 2)
            tid, body = tid.strip(), body.strip()
            if tid.isdigit() and body:
                ok2, res2 = do_send(tid, body)
                if ok2:
                    send(chat_id, "✅ <b>النموذج بعت الرسالة</b> للمستخدم <code>%s</code> (رسالة رقم %s)." % (tid, res2))
                else:
                    send(chat_id, "⚠️ النموذج طلب يبعت، بس الإرسال فشل:\n<code>%s</code>" % html.escape(str(res2)[:300]))
                hist.append({"role": "user", "content": text})
                hist.append({"role": "assistant", "content": "تم إرسال الرسالة للمستخدم %s." % tid})
                u["history"] = hist[-20:]
                save_state(st)
                return
        except Exception:
            pass
    if u.get("memory_on"):
        m = re.search(r"افتكر (?:ان|أن|اني|إني)?\s*(.+)", text)
        if m:
            u["memory"].append(m.group(1).strip()[:300]); save_state(st)
    hist.append({"role": "user", "content": text})
    hist.append({"role": "assistant", "content": ans})
    u["history"] = hist[-20:]
    save_state(st)
    model_name = BY_ID.get(u.get("model"), MODELS[0])[1]
    if u.get("rich", True):
        send_rich(chat_id, "%s\n\n— *%s*" % (ans, model_name))
    else:
        send_long(chat_id, "%s\n\n— <i>%s</i>" % (html.escape(ans), html.escape(model_name)))

def handle_update(upd, st):
    msg = upd.get("message") or upd.get("edited_message")
    cb = upd.get("callback_query")
    if cb:
        uid = cb["from"]["id"]
        chat_id = cb["message"]["chat"]["id"]
        mid = cb["message"]["message_id"]
        u = user_state(st, uid)
        data = cb.get("data", "")
        answer_callback(cb["id"])
        if data.startswith("m:"):
            model_id = data[2:]
            info = BY_ID.get(model_id)
            if not info:
                return
            if not info[2]:
                edit(chat_id, mid,
                     "🔒 <b>%s</b> نموذج مدفوع (Genius).\n\n"
                     "النماذج المدفوعة محتاجة حساب Pro — السيرفر بيرجع:\n"
                     "<code>401 Only paid accounts can use genius</code>\n\n"
                     "لو عندك اشتراك Pro، حط مفتاح الـ API في متغير البيئة "
                     "وشغّل البوت تاني، أو اختار نموذج مجاني 🆓."
                     % html.escape(info[1]), kb([[btn("⬅️ رجوع للنماذج", "back")]]))
                return
            u["model"] = model_id
            u["provider"] = "deepai"
            u["history"] = []
            save_state(st)
            # ✅ علامة صح + بدء الشات
            txt = ("✅ <b>تم اختيار النموذج:</b> %s\n%s\n\n"
                   "💬 <b>ابعت رسالتك دلوقتي — الشات بدأ!</b>\n"
                   "اكتب أي سؤال أو ابعت ملف، وأنا هرد عليك بالنموذج ده.\n\n"
                   "أوامر: /models لتغيير النموذج • /tools للأدوات • /new لمحادثة جديدة" % (
                       html.escape(info[1]),
                       ("🧠 <i>وضع التفكير العميق — الإجابة هتيجي خطوة بخطوة.</i>" if info[3]
                        else "📝 <i>%s</i>" % html.escape(info[5]))))
            rows = [[btn("🔄 تغيير النموذج", "back"), btn("🛠️ أدوات الوكيل", "tools")]]
            edit(chat_id, mid, txt, kb(rows))
        elif data == "giga_menu":
            # زر GigaChat بيبدأ المحادثة على طول — من غير ما يظهر باقي الأزرار
            u["provider"] = "giga"
            u["giga_session"] = None
            save_state(st)
            info = GIGA_BY_ID.get(u.get("giga_mode", "reasoning"), GIGA_MODES[0])
            edit(chat_id, mid,
                 "✅ <b>تم اختيار GigaChat:</b> %s\n%s\n\n"
                 "💬 <b>ابعت رسالتك دلوقتي — الشات بدأ!</b>\n"
                 "اكتب أي سؤال أو ابعت ملف، وهرد عليك بالمود ده." % (
                     html.escape(info[1]), html.escape(info[2])))
        elif data.startswith("tab:"):
            u["tab"] = data[4:]; u["page"] = 0; save_state(st)
            txt, markup = model_menu(u)
            edit(chat_id, mid, txt, markup)
        elif data.startswith("pg:"):
            u["page"] = u.get("page", 0) + int(data[3:]); save_state(st)
            txt, markup = model_menu(u)
            edit(chat_id, mid, txt, markup)
        elif data == "tools":
            txt, markup = tools_menu(u)
            edit(chat_id, mid, txt, markup)
        elif data == "back":
            txt, markup = model_menu(u)
            edit(chat_id, mid, txt, markup)
        elif data == "new":
            u["history"] = []; u["giga_session"] = None; save_state(st)
            txt, markup = model_menu(u)
            edit(chat_id, mid, "🆕 محادثة جديدة — اختار النموذج:", markup)
        elif data.startswith("tgl:"):
            key = data[4:]
            if key == "rich":
                u["rich"] = not u.get("rich", True)
            else:
                u[key] = not u.get(key)
            save_state(st)
            txt, markup = tools_menu(u)
            edit(chat_id, mid, txt, markup)
        return
    if not msg:
        return
    uid = msg["from"]["id"]
    chat_id = msg["chat"]["id"]
    u = user_state(st, uid)
    text = msg.get("text", "") or ""
    if text.startswith("/"):
        cmd = text.split()[0].lower()
        if cmd == "/start":
            _, markup = model_menu(u)
            name = html.escape(msg.get("from", {}).get("first_name", "") or "")
            hello = "اهلا %s♥" % (name + " " if name else "")
            send(chat_id, "%s\n\nالتحدث مع نماذج الAI المتاحه هنا غير محدود\n\n"
                          "اختار زر النموذج الي يعجبك واتكلم معاه براحتك" % hello,
                 markup)
        elif cmd in ("/models", "/model"):
            txt, markup = model_menu(u)
            send(chat_id, txt, markup)
        elif cmd == "/tools":
            txt, markup = tools_menu(u)
            send(chat_id, txt, markup)
        elif cmd == "/new":
            u["history"] = []; u["giga_session"] = None; save_state(st)
            txt, markup = model_menu(u)
            send(chat_id, "🆕 محادثة جديدة — اختار النموذج:", markup)
        elif cmd == "/help":
            send(chat_id, "🤖 <b>أوامر البوت</b>\n\n"
                          "/models — قايمة النماذج (كل نموذج زر)\n"
                          "🤖 GigaChat — من القايمة: 4 مودات (تفكير عميق / جيجا / بحث عميق / تعليم)\n"
                          "/tools — أدوات الوكيل (ويب / وكيل / ذاكرة / شكل الردود)\n"
                          "/new — محادثة جديدة\n\n"
                          "• اختار النموذج أو مود جيجا من الأزرار ✅ وبعدها ابعت رسالتك.\n"
                          "• ابعت ملف نصي/كود والبوت يقراه ويجاوب عنه.\n"
                          "• اكتب «احسب 15*8+3» والحاسبة ترد فوراً.\n"
                          "• اكتب «افتكر اني ...» والذاكرة تحفظها (لما تكون شغالة).\n"
                          "• اكتب «ابعت رسالة لـ 7602919067: نص الرسالة» والبوت يبعتها فوراً.")
        return
    # ملفات مرفقة (مستند/صورة)
    doc = msg.get("document") or (msg.get("photo")[-1] if msg.get("photo") else None)
    if doc:
        fid = doc.get("file_id")
        fname = doc.get("file_name") or "image.jpg"
        r = tg("getFile", {"file_id": fid})
        if r.get("ok"):
            path = r["result"]["file_path"]
            url = "https://api.telegram.org/file/bot%s/%s" % (BOT_TOKEN, path)
            try:
                with urllib.request.urlopen(url, timeout=60) as resp:
                    content = resp.read()
                if fname.lower().endswith((".txt", ".py", ".js", ".md", ".json", ".csv", ".html", ".log")):
                    txt = content.decode("utf-8", "replace")
                    u["history"] = u.get("history", [])[-10:]
                    do_chat(chat_id, u, "ده محتوى الملف %s:\n```\n%s\n```\nاشرحه / جاوب عنه باختصار." % (
                        fname, txt[:6000]), st)
                else:
                    send(chat_id, "📎 استلمت الملف <b>%s</b> (%d بايت).\n"
                                  "البوت بيقرأ الملفات النصية والكود — ابعت ملف .txt أو .py "
                                  "عشان أقراه وأجاوب عنه." % (html.escape(fname), len(content)))
            except Exception as e:
                send(chat_id, "⚠️ مقدرتش أنزّل الملف: %s" % html.escape(str(e)[:200]))
        return
    if not text:
        return
    # أدوات الوكيل (حاسبة / ملف)
    if u.get("agent"):
        handled, reply = agent_tools(text, u)
        if handled:
            if reply.startswith("SENDTO:"):
                _, tid, body = reply.split(":", 2)
                ok, res = do_send(tid, body)
                if ok:
                    send(chat_id, "✅ <b>بعت الرسالة</b> للمستخدم <code>%s</code> (رسالة رقم %s)." % (tid, res))
                else:
                    send(chat_id, "⚠️ مقدرتش أبعت للمستخدم <code>%s</code>:\n<code>%s</code>\n(لازم المستخدم يكون بدأ محادثة مع البوت الأول.)" % (tid, html.escape(str(res)[:300])))
                return
            if reply.startswith("FILE:"):
                body = reply[5:]
                fn = "deepai_reply_%d.txt" % int(time.time())
                send(chat_id, "📄 جهّزت لك الملف — دي نسخة من طلبك مع الرد:",
                     kb([[btn("⬅️ النماذج", "back")]]))
                tg("sendDocument", {"chat_id": chat_id, "caption": "📄 ملف من وكيل %s" % (
                    "GigaChat" if u.get("provider", "deepai") == "giga" else "الوكيل")},
                   files={"document": (fn, body.encode(), "text/plain")})
                return
            send(chat_id, reply)
            return
    do_chat(chat_id, u, text, st)

def main():
    if not BOT_TOKEN:
        print("❌ مفيش توكن! شغّل كده:\n   export BOT_TOKEN=\"توكن_البوت\"\n   python3 deepai_bot.py")
        return
    me = tg("getMe")
    print("🤖 البوت:", me.get("result", {}).get("username"), "| النماذج:", len(MODELS),
          "| مجاني:", len(FREE_MODELS), "| مدفوع:", len(MODELS) - len(FREE_MODELS),
          "| GigaChat:", len(GIGA_MODES), "مود")
    st = load_state()
    offset = 0
    while True:
        try:
            r = tg("getUpdates", {"offset": offset, "timeout": 50}, timeout=60)
            if not r.get("ok"):
                print("getUpdates:", r); time.sleep(3); continue
            for upd in r.get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                try:
                    handle_update(upd, st)
                except Exception as e:
                    print("خطأ في update:", e)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("خطأ:", e); time.sleep(3)

if __name__ == "__main__":
    main()
