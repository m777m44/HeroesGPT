import urllib.request
import json
import ssl
import os
import re
import tempfile
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime, timezone
import threading
import time
import random

ssl._create_default_https_context = ssl._create_unverified_context

BOT_TOKEN = "توكن"
AUTH_TOKEN = "3YBo86VxlMjjVgy6ncFetHucWKT966+n6K9E+cYEAB3K4PTTnziw+klG5zjHiO5w"
POW_PROXY = "http://107.172.78.104:8800"
CHANNEL_USERNAME = "@editortrue"

STREAM_INTERVAL = 0.5
CODE_FILE_THRESHOLD = 300
MAX_HISTORY = 200  # أقصى عدد للرسائل المخزنة (زوج رسالة+رد)

POW_URL = f"{POW_PROXY}/get_pow?authorization={urllib.request.quote(AUTH_TOKEN)}"
CHAT_URL = "https://chat.deepseek.com/api/v0/chat/completion"
CREATE_SESSION_URL = "https://chat.deepseek.com/api/v0/chat_session/create"
LIST_SESSIONS_URL = "https://chat.deepseek.com/api/v0/chat_session/list"
DELETE_SESSION_URL = "https://chat.deepseek.com/api/v0/chat_session/delete"

LANG_EXT = {
    "python": "py", "py": "py",
    "javascript": "js", "js": "js", "typescript": "ts", "ts": "ts",
    "java": "java", "kotlin": "kt", "swift": "swift",
    "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "c#": "cs",
    "go": "go", "golang": "go", "rust": "rs",
    "php": "php", "ruby": "rb", "rb": "rb",
    "bash": "sh", "shell": "sh", "sh": "sh", "zsh": "sh",
    "sql": "sql", "html": "html", "css": "css",
    "xml": "xml", "json": "json", "yaml": "yml", "yml": "yml",
    "r": "r", "matlab": "m", "scala": "scala",
    "dart": "dart", "lua": "lua", "perl": "pl",
    "dockerfile": "dockerfile", "makefile": "makefile",
    "toml": "toml", "ini": "ini", "conf": "conf",
    "markdown": "md", "md": "md",
}

BASE_HEADERS = {
    "User-Agent": "DeepSeek/2.1.0 Android/36",
    "Accept": "application/json",
    "Accept-Encoding": "identity",
    "Content-Type": "application/json",
    "x-client-platform": "android",
    "x-client-version": "2.1.0",
    "x-client-locale": "ar",
    "x-client-bundle-id": "com.deepseek.chat",
    "x-rangers-id": "7693812033879281421",
    "x-client-timezone-offset": "10800",
    "authorization": f"Bearer {AUTH_TOKEN}",
    "accept-charset": "UTF-8",
}

user_data = {}
USER_DATA_FILE = "user_data.json"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

def load_user_data():
    global user_data
    if os.path.exists(USER_DATA_FILE):
        try:
            with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
                user_data = json.load(f)
        except:
            user_data = {}
    else:
        user_data = {}

def save_user_data():
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(user_data, f, ensure_ascii=False, indent=2)
    except:
        pass

load_user_data()

def check_subscription(user_id):
    try:
        member = bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except:
        return False

def subscription_required(func):
    def wrapper(message):
        user_id = message.from_user.id
        if not check_subscription(user_id):
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("📢 اشترك في القناة", url=f"https://t.me/{CHANNEL_USERNAME[1:]}", style="primary"))
            markup.add(InlineKeyboardButton("✅ تم الاشتراك", callback_data="check_sub"))
            bot.reply_to(message,
                f"⚠️ عذراً، يجب عليك الاشتراك في قناتنا أولاً!\n\n"
                f"📢 {CHANNEL_USERNAME}\n"
                f"اضغط على الزر أدناه للاشتراك، ثم اضغط 'تم الاشتراك'",
                reply_markup=markup)
            return
        return func(message)
    return wrapper

def subscription_required_callback(func):
    def wrapper(call):
        user_id = call.from_user.id
        if not check_subscription(user_id):
            bot.answer_callback_query(call.id, "⚠️ يجب الاشتراك في القناة أولاً!", show_alert=True)
            return
        return func(call)
    return wrapper

def extract_code_blocks(text):
    pattern = r"```(\w*)\n?([\s\S]*?)```"
    matches = re.findall(pattern, text)
    return [(m[0].lower().strip(), m[1].strip()) for m in matches if m[1].strip()]

def get_ext(lang):
    return LANG_EXT.get(lang, "txt")

def should_send_as_file(code):
    return len(code) > CODE_FILE_THRESHOLD

def send_code_files(cid, blocks):
    for lang, code in blocks:
        if not should_send_as_file(code):
            continue
        ext = get_ext(lang)
        name = f"code.{ext}"
        caption = f"📄 `{name}`" + (f"  •  {lang.upper()}" if lang else "")
        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False, mode='w', encoding='utf-8') as f:
            f.write(code)
            tmp = f.name
        try:
            with open(tmp, 'rb') as f:
                bot.send_document(cid, f, visible_file_name=name, caption=caption)
        finally:
            os.unlink(tmp)

def strip_large_code_blocks(text):
    def replacer(m):
        lang = m.group(1).lower().strip()
        code = m.group(2).strip()
        if should_send_as_file(code):
            ext = get_ext(lang)
            return f"📎 تم إرسال الكود كملف `code.{ext}`"
        return m.group(0)
    return re.sub(r"```(\w*)\n?([\s\S]*?)```", replacer, text)

def get_pow():
    try:
        with urllib.request.urlopen(
            urllib.request.Request(POW_URL), timeout=8
        ) as r:
            return json.loads(r.read().decode()).get("x_ds_pow_response")
    except:
        return None

def create_chat_session():
    h = {**BASE_HEADERS, "host": "chat.deepseek.com", "content-length": "0"}
    try:
        req = urllib.request.Request(CREATE_SESSION_URL, data=b'', headers=h, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            return d.get("data", {}).get("biz_data", {}).get("chat_session", {}).get("id")
    except:
        return None

def list_sessions():
    h = {**BASE_HEADERS, "host": "chat.deepseek.com", "content-length": "0"}
    try:
        req = urllib.request.Request(LIST_SESSIONS_URL, data=b'', headers=h, method='POST')
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read().decode())
            return d.get("data", {}).get("biz_data", {}).get("chat_sessions", [])
    except:
        return []

def delete_session(session_id):
    h = {**BASE_HEADERS, "host": "chat.deepseek.com"}
    try:
        req = urllib.request.Request(
            DELETE_SESSION_URL,
            data=json.dumps({"chat_session_id": session_id}).encode(),
            headers=h, method='POST'
        )
        with urllib.request.urlopen(req, timeout=10):
            return True
    except:
        return False

def init_user(uid):
    if str(uid) not in user_data:
        user_data[str(uid)] = {
            "session_id": None,
            "parent_id": None,
            "chat_history": [],          # قائمة الرسائل {"role": "user"/"assistant", "content": "..."}
            "waiting": False,
            "think": False,
            "search": False,
            "total_msgs": 0,
            "total_chars": 0,
            "model_type": None,
            "temperature": 0.7,
            "max_tokens": 2048,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stream": True,
            "auto_create_session": True,
            "code_auto_send": True,
            "max_history": MAX_HISTORY,
            "response_style": "balanced"
        }
        save_user_data()
    return user_data[str(uid)]

def get_all_settings(uid):
    data = init_user(uid)
    return {
        "thinking_enabled": data.get("think", False),
        "search_enabled": data.get("search", False),
        "model_type": data.get("model_type", None),
        "temperature": data.get("temperature", 0.7),
        "max_tokens": data.get("max_tokens", 2048),
        "top_p": data.get("top_p", 0.9),
        "frequency_penalty": data.get("frequency_penalty", 0.0),
        "presence_penalty": data.get("presence_penalty", 0.0),
        "stream": data.get("stream", True),
        "auto_create_session": data.get("auto_create_session", True),
        "code_auto_send": data.get("code_auto_send", True),
        "max_history": data.get("max_history", MAX_HISTORY),
        "response_style": data.get("response_style", "balanced")
    }

def safe_edit(cid, mid, text, markup=None):
    try:
        bot.edit_message_text(text, cid, mid, reply_markup=markup,
                              disable_web_page_preview=True)
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            pass

def build_context_prompt(chat_history):
    """
    تحويل سجل المحادثة إلى نص متسلسل يُرسل كـ prompt.
    """
    if not chat_history:
        return ""
    lines = []
    for msg in chat_history:
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            lines.append(f"User: {content}")
        elif role == "assistant":
            lines.append(f"Assistant: {content}")
    return "\n".join(lines) + "\n"

def stream_with_draft(prompt, pow_response, session_id, parent_id, cid, uid):
    settings = get_all_settings(uid)
    
    payload = {
        "chat_session_id": session_id,
        "prompt": prompt,
        "ref_file_ids": [],
        "thinking_enabled": settings["thinking_enabled"],
        "search_enabled": settings["search_enabled"],
        "audio_id": None,
        "preempt": False,
        "model_type": settings["model_type"],
        "temperature": settings["temperature"],
        "max_tokens": settings["max_tokens"],
        "top_p": settings["top_p"],
        "frequency_penalty": settings["frequency_penalty"],
        "presence_penalty": settings["presence_penalty"],
        "stream": settings["stream"]
    }
    
    if parent_id:
        payload["parent_message_id"] = parent_id

    headers = {**BASE_HEADERS, "x-ds-pow-response": pow_response}
    full_text = ""
    new_parent_id = parent_id
    
    draft_id = int(time.time() * 1000) % 2147483647
    last_update = 0
    chunk_size = 0

    def send_draft(text, is_final=False):
        try:
            if is_final:
                bot.send_message(
                    cid,
                    text,
                    disable_web_page_preview=True,
                    reply_markup=chat_kb()
                )
            else:
                try:
                    bot.send_message_draft(
                        chat_id=cid,
                        draft_id=draft_id,
                        text=text + " ▌",
                        disable_web_page_preview=True
                    )
                except (AttributeError, TypeError):
                    draft_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessageDraft"
                    draft_data = json.dumps({
                        "chat_id": cid,
                        "draft_id": draft_id,
                        "text": text + " ▌",
                        "disable_web_page_preview": True
                    }).encode('utf-8')
                    req = urllib.request.Request(
                        draft_url,
                        data=draft_data,
                        headers={"Content-Type": "application/json"},
                        method='POST'
                    )
                    with urllib.request.urlopen(req, timeout=10) as response:
                        json.loads(response.read().decode())
        except Exception as e:
            pass

    try:
        req = urllib.request.Request(
            CHAT_URL,
            data=json.dumps(payload).encode(),
            headers=headers,
            method='POST'
        )
        with urllib.request.urlopen(req, timeout=90) as resp:
            buf = b""
            first_chunk = True
            last_id = parent_id
            
            while True:
                if not user_data.get(str(uid), {}).get("waiting"):
                    break
                raw = resp.read(256)
                if not raw:
                    break
                buf += raw
                while b"\n" in buf:
                    lb, buf = buf.split(b"\n", 1)
                    line = lb.decode("utf-8", errors="replace").strip()
                    if not line.startswith("data: "):
                        continue
                    ds = line[6:].strip()
                    if not ds:
                        continue
                    try:
                        evt = json.loads(ds)
                    except:
                        continue

                    if "id" in evt:
                        last_id = evt["id"]
                        new_parent_id = last_id
                    if "error" in evt:
                        send_draft("❌ خطأ: " + str(evt["error"]), True)
                        return full_text, new_parent_id

                    p = evt.get("p", "")
                    if "thinking" in p:
                        continue
                    v = evt.get("v", "")
                    if isinstance(v, str) and v:
                        if "content" in p or "text" in p or "answer" in p or p == "":
                            full_text += v
                            chunk_size += len(v)
                            
                            now = time.time()
                            if chunk_size >= 20 or now - last_update >= STREAM_INTERVAL:
                                display = full_text[-3800:] if len(full_text) > 3800 else full_text
                                
                                if first_chunk:
                                    send_draft(display)
                                    first_chunk = False
                                else:
                                    send_draft(display)
                                
                                chunk_size = 0
                                last_update = now

            if last_id != parent_id:
                new_parent_id = last_id

        if not full_text:
            bot.send_message(cid, "❌ لم يصل أي رد.", reply_markup=chat_kb())
            return "", new_parent_id

        if settings["code_auto_send"]:
            blocks = extract_code_blocks(full_text)
            has_large = any(should_send_as_file(c) for _, c in blocks)
            display_text = strip_large_code_blocks(full_text) if has_large else full_text
        else:
            display_text = full_text
            has_large = False

        send_draft(display_text, True)

        if has_large and settings["code_auto_send"]:
            send_code_files(cid, blocks)

        return full_text, new_parent_id

    except Exception as e:
        err = f"❌ خطأ: {e}"
        bot.send_message(cid, err, reply_markup=chat_kb())
        return err, parent_id

def format_relative_time(timestamp):
    """إرجاع نص زمني نسبي بالعربية مثل '7 أيام'، 'ساعة'، إلخ."""
    try:
        if not timestamp:
            return "غير معروف"
        if isinstance(timestamp, (int, float)):
            dt = datetime.fromtimestamp(timestamp)
        else:
            # محاولة تحويل النص إلى datetime
            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc).astimezone()
        diff = now - dt
        seconds = diff.total_seconds()
        if seconds < 60:
            return "الآن"
        elif seconds < 3600:
            mins = int(seconds // 60)
            return f"{mins} دقيقة" if mins == 1 else f"{mins} دقائق"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            return f"{hours} ساعة" if hours == 1 else f"{hours} ساعات"
        elif seconds < 2592000:  # 30 يوم
            days = int(seconds // 86400)
            return f"{days} يوم" if days == 1 else f"{days} أيام"
        elif seconds < 31536000:  # سنة
            months = int(seconds // 2592000)
            return f"{months} شهر" if months == 1 else f"{months} أشهر"
        else:
            years = int(seconds // 31536000)
            return f"{years} سنة" if years == 1 else f"{years} سنوات"
    except:
        return "تاريخ غير معروف"

def sessions_kb(sessions, action="select"):
    mk = InlineKeyboardMarkup(row_width=1)
    # زر إنشاء محادثة جديدة (كما في الصورة)
    mk.add(InlineKeyboardButton("➕ محادثة جديدة", callback_data="new_session", style="primary"))
    icon = "💬" if action == "select" else "🗑️"
    for s in sessions[:10]:  # نعرض آخر 10 محادثات
        sid = s.get("id", "")
        title = (s.get("title") or "بدون عنوان")[:28]
        msgs = s.get("message_count", 0)
        updated_at = s.get("updated_at")
        rel_time = format_relative_time(updated_at)
        button_text = f"{title}  •  {msgs} رسالة  •  {rel_time}"
        if action == "delete":
            button_text = f"🗑️ {button_text}"
        mk.add(InlineKeyboardButton(
            button_text,
            callback_data=f"{action}_{sid}", style="primary"))
    mk.add(InlineKeyboardButton("🔙 رجوع", callback_data="back_main"))
    return mk

def settings_kb(uid):
    settings = get_all_settings(uid)
    mk = InlineKeyboardMarkup(row_width=2)
    
    think = "✅" if settings["thinking_enabled"] else "❌"
    search = "✅" if settings["search_enabled"] else "❌"
    stream = "✅" if settings["stream"] else "❌"
    auto_create = "✅" if settings["auto_create_session"] else "❌"
    code_send = "✅" if settings["code_auto_send"] else "❌"
    
    style_text = {
        'balanced': '⚖️ متوازن',
        'concise': '📝 مختصر',
        'detailed': '📖 مفصل',
        'creative': '🎨 إبداعي'
    }.get(settings['response_style'], '⚖️ متوازن')
    
    mk.add(
        InlineKeyboardButton(f"🧠 التفكير: {think}", callback_data="toggle_think"),
        InlineKeyboardButton(f"🔍 البحث: {search}", callback_data="toggle_search"),
        InlineKeyboardButton(f"🌡️ الحرارة: {settings['temperature']}", callback_data="set_temp"),
        InlineKeyboardButton(f"📝 الرموز: {settings['max_tokens']}", callback_data="set_tokens"),
        InlineKeyboardButton(f"🎯 Top-P: {settings['top_p']}", callback_data="set_topp"),
        InlineKeyboardButton(f"📊 تكرار العقوبة: {settings['frequency_penalty']}", callback_data="set_freq"),
        InlineKeyboardButton(f"📈 وجود العقوبة: {settings['presence_penalty']}", callback_data="set_presence"),
        InlineKeyboardButton(f"🔄 التدفق: {stream}", callback_data="toggle_stream"),
        InlineKeyboardButton(f"🔄 إنشاء تلقائي: {auto_create}", callback_data="toggle_auto"),
        InlineKeyboardButton(f"📎 إرسال الكود: {code_send}", callback_data="toggle_code"),
        InlineKeyboardButton(f"📜 سجل المحادثة: {settings['max_history']}", callback_data="set_history"),
        InlineKeyboardButton(f"📝 نمط الرد: {style_text}", callback_data="toggle_style", style="primary"),
        InlineKeyboardButton("🔄 إعادة ضبط الكل", callback_data="reset_all", style="primary"),
        InlineKeyboardButton("🔙 رجوع", callback_data="back_main", style="primary"),
    )
    return mk

def chat_kb():
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(
        InlineKeyboardButton("📋 القائمة", callback_data="back_main", style="primary"),
    )
    return mk

def main_kb():
    mk = InlineKeyboardMarkup(row_width=2)
    mk.add(
        InlineKeyboardButton("📊 إحصائياتي", callback_data="stats", style="primary"),
        InlineKeyboardButton("⚙️ الإعدادات", callback_data="settings", style="primary"),
        InlineKeyboardButton("📂 المحادثات", callback_data="list_sessions", style="primary"),
        InlineKeyboardButton("➕ محادثة جديدة", callback_data="new_session", style="primary"),
        InlineKeyboardButton("❓ مساعدة", callback_data="help"),
    )
    return mk

@bot.message_handler(commands=['start'])
@subscription_required
def cmd_start(msg):
    uid = msg.from_user.id
    init_user(uid)
    bot.send_message(msg.chat.id,
        f"👋 أهلاً {msg.from_user.first_name or 'صديقي'}!\n\n"
        "أنا بوت DeepSeek 🤖\n"
        "🚀 Streaming باستخدام sendMessageDraft (الطريقة الرسمية)\n"
        "تحديث سريع • بدون حظر • تقنية جديدة من تيليجرام\n\n"
        "يتذكر البوت آخر 200 رسالة في المحادثة\n"
        "يمكنك عرض المحادثات السابقة وإنشاء جديدة وحذفها\n\n"
        "اكتب سؤالك أو اختر من القائمة:",
        reply_markup=main_kb())

@bot.message_handler(commands=['menu'])
@subscription_required
def cmd_menu(msg):
    bot.send_message(msg.chat.id, "📋 القائمة:", reply_markup=main_kb())

@bot.message_handler(commands=['new'])
@subscription_required
def cmd_new(msg):
    uid = msg.from_user.id
    data = init_user(uid)
    m = bot.send_message(msg.chat.id, "⏳ جاري الإنشاء...")
    sid = create_chat_session()
    if sid:
        data["session_id"] = sid
        data["parent_id"] = None
        data["chat_history"] = []  # مسح السجل
        save_user_data()
        safe_edit(msg.chat.id, m.message_id,
            f"✅ محادثة جديدة!\n📌 {sid[:16]}…\n\n💬 اكتب سؤالك:",
            markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("📋 القائمة", callback_data="back_main", style="primary")))
    else:
        safe_edit(msg.chat.id, m.message_id, "❌ فشل الإنشاء.")

@bot.message_handler(commands=['sessions'])
@subscription_required
def cmd_sessions(msg):
    uid = msg.from_user.id
    init_user(uid)
    ss = list_sessions()
    if not ss:
        bot.send_message(msg.chat.id, "❌ لا توجد محادثات.", reply_markup=main_kb())
        return
    bot.send_message(msg.chat.id, "📂 محادثاتك:", reply_markup=sessions_kb(ss))

@bot.message_handler(commands=['cancel'])
@subscription_required
def cmd_cancel(msg):
    uid = msg.from_user.id
    init_user(uid)
    if user_data.get(str(uid), {}).get("waiting"):
        user_data[str(uid)]["waiting"] = False
        save_user_data()
        bot.send_message(msg.chat.id, "⛔ تم الإيقاف.")
    else:
        bot.send_message(msg.chat.id, "لا يوجد شيء نشط.")

@bot.message_handler(commands=['stats'])
@subscription_required
def cmd_stats(msg):
    uid = msg.from_user.id
    init_user(uid)
    _send_stats(msg.chat.id, uid)

@bot.message_handler(commands=['settings'])
@subscription_required
def cmd_settings(msg):
    uid = msg.from_user.id
    init_user(uid)
    settings = get_all_settings(uid)
    text = "⚙️ جميع الإعدادات:\n\n"
    for key, value in settings.items():
        text += f"• {key}: {value}\n"
    bot.send_message(msg.chat.id, text, reply_markup=settings_kb(uid))

@bot.callback_query_handler(func=lambda c: True)
@subscription_required_callback
def cb(call):
    uid = call.from_user.id
    cid = call.message.chat.id
    mid = call.message.message_id
    data_cb = call.data
    data = init_user(uid)

    if data_cb == "check_sub":
        if check_subscription(uid):
            bot.answer_callback_query(call.id, "✅ تم التحقق من اشتراكك! يمكنك استخدام البوت.")
            safe_edit(cid, mid, "✅ تم التحقق من اشتراكك! يمكنك استخدام البوت.", markup=main_kb())
        else:
            bot.answer_callback_query(call.id, "❌ لا زلت غير مشترك! اشترك ثم اضغط مرة أخرى.", show_alert=True)
        return

    if data_cb == "new_session":
        bot.answer_callback_query(call.id, "⏳")
        sid = create_chat_session()
        if sid:
            data["session_id"] = sid
            data["parent_id"] = None
            data["chat_history"] = []
            save_user_data()
            safe_edit(cid, mid,
                f"✅ محادثة جديدة!\n📌 {sid[:16]}…\n\n💬 اكتب سؤالك:",
                markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("📋 القائمة", callback_data="back_main", style="primary")))
        else:
            bot.answer_callback_query(call.id, "❌ فشل الإنشاء!")

    elif data_cb == "list_sessions":
        bot.answer_callback_query(call.id, "⏳")
        ss = list_sessions()
        if not ss:
            safe_edit(cid, mid, "❌ لا توجد محادثات.",
                markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("✏️ إنشاء", callback_data="new_session", style="primary"),
                    InlineKeyboardButton("🔙 رجوع", callback_data="back_main")))
        else:
            safe_edit(cid, mid, "📂 اختر محادثة:", markup=sessions_kb(ss))

    elif data_cb.startswith("select_"):
        sid = data_cb[7:]
        data["session_id"] = sid
        data["parent_id"] = None
        data["chat_history"] = []
        save_user_data()
        bot.answer_callback_query(call.id, "✅ تم التبديل!")
        safe_edit(cid, mid, f"✅ جلسة: {sid[:16]}…\n\n💬 اكتب سؤالك:",
            markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("📋 القائمة", callback_data="back_main", style="primary")))

    elif data_cb == "delete_menu":
        bot.answer_callback_query(call.id, "⏳")
        ss = list_sessions()
        if not ss:
            safe_edit(cid, mid, "❌ لا توجد محادثات.",
                markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 رجوع", callback_data="back_main", style="primary")))
        else:
            safe_edit(cid, mid, "🗑️ اختر للحذف:", markup=sessions_kb(ss, "delete"))

    elif data_cb.startswith("delete_"):
        sid = data_cb[7:]
        mk = InlineKeyboardMarkup(row_width=2)
        mk.add(
            InlineKeyboardButton("✅ تأكيد", callback_data=f"confirm_del_{sid}", style="primary"),
            InlineKeyboardButton("❌ إلغاء", callback_data="delete_menu"))
        safe_edit(cid, mid, f"⚠️ حذف المحادثة؟\n{sid[:16]}…", markup=mk)

    elif data_cb.startswith("confirm_del_"):
        sid = data_cb[12:]
        bot.answer_callback_query(call.id, "⏳")
        if delete_session(sid):
            if data.get("session_id") == sid:
                data["session_id"] = None
                data["parent_id"] = None
                data["chat_history"] = []
                save_user_data()
            safe_edit(cid, mid, "✅ تم الحذف!",
                markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 القائمة", callback_data="back_main", style="primary")))
        else:
            safe_edit(cid, mid, "❌ فشل الحذف.",
                markup=InlineKeyboardMarkup().add(
                    InlineKeyboardButton("🔙 رجوع", callback_data="back_main")))

    elif data_cb == "stats":
        _send_stats(cid, uid, edit=(cid, mid))

    elif data_cb == "settings":
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_think":
        data["think"] = not data.get("think", False)
        save_user_data()
        st = "مفعّل" if data["think"] else "معطّل"
        bot.answer_callback_query(call.id, f"التفكير العميق: {st}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_search":
        data["search"] = not data.get("search", False)
        save_user_data()
        st = "مفعّل" if data["search"] else "معطّل"
        bot.answer_callback_query(call.id, f"البحث في الويب: {st}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_stream":
        data["stream"] = not data.get("stream", True)
        save_user_data()
        st = "مفعّل" if data["stream"] else "معطّل"
        bot.answer_callback_query(call.id, f"التدفق: {st}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_auto":
        data["auto_create_session"] = not data.get("auto_create_session", True)
        save_user_data()
        st = "مفعّل" if data["auto_create_session"] else "معطّل"
        bot.answer_callback_query(call.id, f"الإنشاء التلقائي: {st}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_code":
        data["code_auto_send"] = not data.get("code_auto_send", True)
        save_user_data()
        st = "مفعّل" if data["code_auto_send"] else "معطّل"
        bot.answer_callback_query(call.id, f"إرسال الكود: {st}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "toggle_style":
        styles = ['balanced', 'concise', 'detailed', 'creative']
        current = data.get("response_style", "balanced")
        idx = (styles.index(current) + 1) % len(styles)
        data["response_style"] = styles[idx]
        save_user_data()
        style_names = {
            'balanced': 'متوازن',
            'concise': 'مختصر',
            'detailed': 'مفصل',
            'creative': 'إبداعي'
        }
        bot.answer_callback_query(call.id, f"نمط الرد: {style_names[styles[idx]]}")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "set_temp":
        bot.answer_callback_query(call.id, "أرسل قيمة درجة الحرارة (0.1 - 2.0)", show_alert=True)
        msg = bot.send_message(cid, "🌡️ أدخل قيمة درجة الحرارة من 0.1 إلى 2.0:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "temperature", float, 0.1, 2.0)

    elif data_cb == "set_tokens":
        bot.answer_callback_query(call.id, "أرسل الحد الأقصى للرموز (1-4096)", show_alert=True)
        msg = bot.send_message(cid, "📝 أدخل الحد الأقصى للرموز من 1 إلى 4096:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "max_tokens", int, 1, 4096)

    elif data_cb == "set_topp":
        bot.answer_callback_query(call.id, "أرسل قيمة Top-P (0.1 - 1.0)", show_alert=True)
        msg = bot.send_message(cid, "🎯 أدخل قيمة Top-P من 0.1 إلى 1.0:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "top_p", float, 0.1, 1.0)

    elif data_cb == "set_freq":
        bot.answer_callback_query(call.id, "أرسل عقوبة التكرار (0.0 - 2.0)", show_alert=True)
        msg = bot.send_message(cid, "📊 أدخل عقوبة التكرار من 0.0 إلى 2.0:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "frequency_penalty", float, 0.0, 2.0)

    elif data_cb == "set_presence":
        bot.answer_callback_query(call.id, "أرسل عقوبة الوجود (0.0 - 2.0)", show_alert=True)
        msg = bot.send_message(cid, "📈 أدخل عقوبة الوجود من 0.0 إلى 2.0:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "presence_penalty", float, 0.0, 2.0)

    elif data_cb == "set_history":
        bot.answer_callback_query(call.id, "أرسل عدد الرسائل للتخزين (1-200)", show_alert=True)
        msg = bot.send_message(cid, "📜 أدخل عدد الرسائل للتخزين من 1 إلى 200:")
        bot.register_next_step_handler(msg, set_setting_value, uid, "max_history", int, 1, 200)

    elif data_cb == "reset_all":
        data.update({
            "think": False,
            "search": False,
            "model_type": None,
            "temperature": 0.7,
            "max_tokens": 2048,
            "top_p": 0.9,
            "frequency_penalty": 0.0,
            "presence_penalty": 0.0,
            "stream": True,
            "auto_create_session": True,
            "code_auto_send": True,
            "max_history": MAX_HISTORY,
            "response_style": "balanced"
        })
        save_user_data()
        bot.answer_callback_query(call.id, "✅ تم إعادة ضبط جميع الإعدادات!")
        settings = get_all_settings(uid)
        text = "⚙️ جميع الإعدادات:\n\n"
        for key, value in settings.items():
            text += f"• {key}: {value}\n"
        safe_edit(cid, mid, text, markup=settings_kb(uid))

    elif data_cb == "help":
        safe_edit(cid, mid,
            "📖 دليل الاستخدام\n\n"
            "🚀 Streaming باستخدام sendMessageDraft (الطريقة الرسمية من تيليجرام)\n"
            "• تحديث سريع • بدون حظر (Rate Limit)\n"
            "• يعمل فقط في المحادثات الخاصة (DMs)\n"
            "• يجب تفعيل 'Forum Topic Mode' للبوت عبر @BotFather\n\n"
            "الأوامر:\n"
            "/new      — محادثة جديدة\n"
            "/sessions — عرض المحادثات (مع وقت نسبي)\n"
            "/stats    — إحصائياتك\n"
            "/cancel   — إيقاف الرد الحالي\n"
            "/menu     — القائمة\n"
            "/settings — جميع الإعدادات\n\n"
            "الإعدادات المتوفرة:\n"
            "🧠 التفكير العميق — تحليل أعمق\n"
            "🔍 البحث في الويب — معلومات حديثة\n"
            "🌡️ درجة الحرارة — تحكم في الإبداع\n"
            "📝 الحد الأقصى للرموز — طول الرد\n"
            "🎯 Top-P — تنوع الردود\n"
            "🔄 التدفق — عرض تدريجي\n"
            "🔄 إنشاء تلقائي — إنشاء جلسة تلقائياً\n"
            "📎 إرسال الكود — إرسال الأكواد كملفات\n"
            "📜 سجل المحادثة — عدد الرسائل المخزنة (الحد الأقصى 200)\n"
            "📝 نمط الرد — متوازن/مختصر/مفصل/إبداعي",
            markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("🔙 رجوع", callback_data="back_main", style="primary")))

    elif data_cb == "back_main":
        safe_edit(cid, mid, "📋 القائمة:", markup=main_kb())

def set_setting_value(message, uid, key, cast_type, min_val, max_val):
    try:
        value = cast_type(message.text)
        if min_val <= value <= max_val:
            data = init_user(uid)
            data[key] = value
            save_user_data()
            bot.send_message(message.chat.id, f"✅ تم تحديث {key} إلى {value}")
            settings = get_all_settings(uid)
            text = "⚙️ جميع الإعدادات:\n\n"
            for k, v in settings.items():
                text += f"• {k}: {v}\n"
            bot.send_message(message.chat.id, text, reply_markup=settings_kb(uid))
        else:
            bot.send_message(message.chat.id, f"❌ القيمة يجب أن تكون بين {min_val} و {max_val}")
    except:
        bot.send_message(message.chat.id, "❌ قيمة غير صالحة، حاول مرة أخرى")

def _send_stats(cid, uid, edit=None):
    data = init_user(uid)
    sid = data.get("session_id")
    msgs = data.get("total_msgs", 0)
    chars = data.get("total_chars", 0)
    hist_len = len(data.get("chat_history", []))
    think = "✅" if data.get("think") else "❌"
    srch = "✅" if data.get("search") else "❌"
    sid_t = f"{sid[:20]}…" if sid else "لا توجد"
    text = (
        f"📊 إحصائياتك\n\n"
        f"💬 رسائل مُرسلة  : {msgs}\n"
        f"🔤 إجمالي الأحرف : {chars}\n"
        f"📜 الرسائل المخزنة: {hist_len}\n"
        f"🧠 التفكير العميق: {think}\n"
        f"🔍 البحث في الويب: {srch}\n"
        f"🚀 تقنية sendMessageDraft\n"
        f"📌 الجلسة النشطة : {sid_t}"
    )
    mk = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 رجوع", callback_data="back_main", style="primary"))
    if edit:
        safe_edit(edit[0], edit[1], text, markup=mk)
    else:
        bot.send_message(cid, text, reply_markup=mk)

@bot.message_handler(func=lambda m: True, content_types=['text'])
@subscription_required
def handle_message(msg):
    uid = msg.from_user.id
    cid = msg.chat.id
    data = init_user(uid)

    if data.get("waiting"):
        bot.send_message(cid, "⏳ انتظر الرد الحالي… أو /cancel")
        return

    if not data.get("session_id") and data.get("auto_create_session", True):
        m = bot.send_message(cid, "🔄 إنشاء محادثة…")
        sid = create_chat_session()
        if not sid:
            bot.edit_message_text("❌ فشل إنشاء الجلسة، أرسل /new.", cid, m.message_id)
            return
        data["session_id"] = sid
        data["parent_id"] = None
        save_user_data()
        bot.delete_message(cid, m.message_id)

    if not data.get("session_id"):
        bot.send_message(cid, "❌ لا توجد جلسة نشطة. أرسل /new لإنشاء محادثة جديدة.")
        return

    # --- إدارة سجل المحادثة ---
    max_hist = data.get("max_history", MAX_HISTORY)
    chat_history = data.get("chat_history", [])

    # إضافة رسالة المستخدم
    chat_history.append({"role": "user", "content": msg.text})

    # حذف أقدم الرسائل إذا تجاوزنا max_hist
    while len(chat_history) > max_hist:
        chat_history.pop(0)  # إزالة الأقدم

    data["chat_history"] = chat_history
    data["waiting"] = True
    data["total_msgs"] = data.get("total_msgs", 0) + 1
    data["total_chars"] = data.get("total_chars", 0) + len(msg.text)
    save_user_data()

    # بناء prompt من السجل
    context_str = build_context_prompt(chat_history)  # يتضمن كل الرسائل حتى آخر رسالة للمستخدم

    def run():
        try:
            pow_token = get_pow()
            if not pow_token:
                bot.send_message(cid, "❌ فشل POW، حاول مجدداً.", reply_markup=chat_kb())
                data["waiting"] = False
                save_user_data()
                return

            final_text, new_pid = stream_with_draft(
                context_str, pow_token,
                data["session_id"],
                data["parent_id"],
                cid, uid
            )

            # إضافة رد المساعد إلى السجل
            if final_text and not final_text.startswith("❌"):
                data["chat_history"].append({"role": "assistant", "content": final_text})
                # إعادة ضبط الحجم
                while len(data["chat_history"]) > max_hist:
                    data["chat_history"].pop(0)

            if new_pid and new_pid != data["parent_id"]:
                data["parent_id"] = new_pid

        except Exception as e:
            bot.send_message(cid, f"❌ خطأ: {e}", reply_markup=chat_kb())
        finally:
            data["waiting"] = False
            save_user_data()

    threading.Thread(target=run, daemon=True).start()

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════╗")
    print("║   🚀  DeepSeek Live Stream                  ║")
    print("║   🔥 تحديث: تذكر 200 رسالة                 ║")
    print("║   📂 عرض المحادثات بوقت نسبي               ║")
    print("╚══════════════════════════════════════════════╝")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)