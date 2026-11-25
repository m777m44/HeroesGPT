import telebot, requests, base64, random, string, json
from telebot import types

TOKEN = 'توكنك'
bot = telebot.TeleBot(TOKEN)

users_data = {}

def rsa_enc(m, n, e):
    ps = []
    while len(ps) < (128 - len(m) - 3):
        r = random.randint(1, 255)
        ps.append(r)
    eb = b'\x00\x02' + bytes(ps) + b'\x00' + m.encode()
    p = int.from_bytes(eb, 'big')
    c = pow(p, e, n)
    return base64.b64encode(c.to_bytes(128, 'big')).decode()

def gen_id():
    r = lambda n: ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))
    return f"{r(14)}-{r(15)}-3f700d7e-921600-{r(15)}"

def clean_txt(t):
    t = t.replace("-=- --", " ").replace("-=-n-", "\n").replace("-=-", "")
    lines = t.split('\n')
    cleaned = []
    for l in lines:
        l = l.strip()
        if l.startswith("- "): l = l[2:]
        elif l.startswith("-"): l = l[1:]
        cleaned.append(l)
    return "\n".join(cleaned).strip()

def get_ai_response(msgs):
    n = 136236490358183259653189950748359669580190635598405237306311768987156534532312435393317272373703463400839797405683556405633769494895560212863113877037049039352461932992309204029954183762382698647733158589129700438379720646895034736836216527276967880354063143356560735956241651941835057143194078092683552570413
    e = 65537
    vt = rsa_enc(gen_id(), n, e)
    url = 'https://api.chattide.ai/aigc/chat/v2/professional/stream'
    h = {
        'lang': 'ar', 'vtoken': vt, 'source': 'web',
        'content-type': 'application/json',
        'accept': 'text/event-stream,application/json',
        'referer': 'https://www.chattide.ai/',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64 ) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    p = {
        'spaceHandle': True, 'roleId': 0,
        'messages': msgs,
        'conversationId': None, 'model': 'gpt-5.6-luna'
    }
    try:
        r = requests.post(url, headers=h, json=p, stream=True, timeout=60)
        res = ""
        for line in r.iter_lines():
            if line:
                d = line.decode()
                if d.startswith("data:"):
                    txt = d[5:].strip()
                    if txt == "--@DONE@--": break
                    if txt: res += txt
        return clean_txt(res)
    except:
        return "Connection Error."

def format_code(text):
    if "```" in text: return text
    lines = text.split('\n')
    new_text, in_code = "", False
    for line in lines:
        is_code = any(line.strip().startswith(x) for x in ['import ', 'from ', 'def ', 'class ', 'if ', 'for ', 'while ', 'print(', 'var ', 'const ', 'let ', 'function ']) or (';' in line and '=' in line)
        if is_code and not in_code:
            new_text += "```python\n" + line + "\n"; in_code = True
        elif not is_code and in_code:
            new_text += "```\n" + line + "\n"; in_code = False
        else:
            new_text += line + "\n"
    if in_code: new_text += "```"
    return new_text

@bot.message_handler(commands=['start'])
def start(m):
    uid = m.chat.id
    users_data[uid] = {'history': [], 'memory': True}
    markup = types.InlineKeyboardMarkup()
    b1 = types.InlineKeyboardButton("⚙️ Settings", callback_data="settings", style="danger")
    b2 = types.InlineKeyboardButton("🔄 New Chat", callback_data="new_chat", style="primary")
    markup.row(b1, b2)
    bot.send_message(uid, "Hello I am chat gpt Ask me and I will answer", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: True)
def callback(c):
    uid = c.message.chat.id
    if uid not in users_data: users_data[uid] = {'history': [], 'memory': True}
    bot.answer_callback_query(c.id)
    if c.data == "new_chat":
        users_data[uid]['history'] = []
        bot.send_message(uid, "Memory cleared. New chat started.")
    elif c.data == "settings":
        markup = types.InlineKeyboardMarkup()
        status = "Enabled ✅" if users_data[uid]['memory'] else "Disabled ❌"
        btn = types.InlineKeyboardButton(f"Memory: {status}", callback_data="toggle_mem", style="primary")
        markup.add(btn)
        bot.edit_message_text("Bot Settings:", uid, c.message.message_id, reply_markup=markup)
    elif c.data == "toggle_mem":
        users_data[uid]['memory'] = not users_data[uid]['memory']
        callback(c)

@bot.message_handler(func=lambda m: True)
def handle_msg(m):
    uid = m.chat.id
    if uid not in users_data: users_data[uid] = {'history': [], 'memory': True}
    bot.send_chat_action(uid, 'typing')
    q = m.text
    msgs = users_data[uid]['history'] + [{"role": "user", "content": [{"type": "text", "text": q}]}] if users_data[uid]['memory'] else [{"role": "user", "content": [{"type": "text", "text": q}]}]
    ans = get_ai_response(msgs)
    bot.reply_to(m, format_code(ans), parse_mode='Markdown')
    if users_data[uid]['memory']:
        users_data[uid]['history'].append({"role": "user", "content": [{"type": "text", "text": q}]})
        users_data[uid]['history'].append({"role": "assistant", "content": [{"type": "text", "text": ans}]})
        if len(users_data[uid]['history']) > 100: users_data[uid]['history'] = users_data[uid]['history'][-100:]

bot.polling(none_stop=True)