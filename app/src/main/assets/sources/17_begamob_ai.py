import base64
import hashlib
import hmac
import json
import os
import random
import string
import sys
import time
import uuid

import requests

G = "\033[92m"; R = "\033[91m"; Y = "\033[93m"; C = "\033[96m"; W = "\033[97m"; D = "\033[90m"; M = "\033[95m"; X = "\033[0m"

print(f"""{M}
   ██████╗ ███████╗ ██████╗  █████╗ ███╗   ███╗ ██████╗ ██████╗
   ██╔══██╗██╔════╝██╔════╝ ██╔══██╗████╗ ████║██╔═══██╗██╔══██╗
   ██████╔╝█████╗  ██║  ███╗███████║██╔████╔██║██║   ██║██████╔╝
   ██╔══██╗██╔══╝  ██║   ██║██╔══██║██║╚██╔╝██║██║   ██║██╔══██╗
   ██████╔╝███████╗╚██████╔╝██║  ██║██║ ╚═╝ ██║╚██████╔╝██████╔╝
   ╚═════╝ ╚══════╝ ╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚═════╝
{W}        BEGAMOB — Free AI Proxy Tool | 42 Model
{Y}                  الحقوق: @Q_b_h
{D}      chatapi.begamob.com • JWT يُصاغ محلياً • بلا حدود{X}
""")

SEC = "stteam-ikameglobal-chatapiopenai"
URL = "https://chatapi.begamob.com/api/v2/chatCustom"

MDLS = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4", "gpt-3.5-turbo", "o1", "o1-mini",
        "o3-mini", "o3", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano", "gpt-5", "chatgpt-4o-latest",
        "claude-3.5-sonnet", "claude-3.7-sonnet", "claude-sonnet-4", "claude-3.5-haiku",
        "claude-3-opus", "claude-opus-4", "claude-3-haiku",
        "gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro", "gemini-1.5-pro",
        "gemini-1.5-flash", "gemini-2.0-flash-lite", "gemini-pro",
        "deepseek-v3", "deepseek-r1", "deepseek-chat",
        "qwen-max", "qwen-plus", "qwen2.5-72b",
        "llama-3.3-70b", "llama-3.1-405b",
        "mistral-large", "mixtral-8x7b",
        "grok-3", "grok-2",
        "command-r-plus", "yi-large"]

print(f"  {C}── النماذج المتاحة ──{X}")
for i in range(0, len(MDLS), 3):
    row = ""
    for j in range(3):
        if i + j < len(MDLS):
            row += f"{W}{i+j+1:>2}{D}.{G}{MDLS[i+j]:<20}{X}"
    print("   " + row)
print(f"   {W} 0.{Y}اسم مخصص{X}")

pm = input(f"\n  {Y}البروكسي: 1) بدون  2) رابط سكني  3) ملف [1]: {W}").strip() or "1"
plink = ""
pool = []
if pm == "2":
    plink = input(f"  {Y}رابط البروكسي: {W}").strip()
    if plink and "://" not in plink:
        plink = "http://" + plink
elif pm == "3":
    pf = input(f"  {Y}مسار الملف: {W}").strip()
    if os.path.exists(pf):
        pool = [l.strip() for l in open(pf, encoding="utf-8") if l.strip()]
        print(f"  {G}[+] {len(pool)} بروكسي{X}")
    else:
        print(f"  {R}[-] الملف غير موجود — مباشر{X}")
        pm = "1"

mi = input(f"\n  {Y}اختر النموذج [22=gemini-2.0-flash]: {W}").strip() or "22"
if mi == "0":
    mdl = input(f"  {Y}اكتب اسم النموذج: {W}").strip() or "gemini-2.0-flash"
elif mi.isdigit() and 1 <= int(mi) <= len(MDLS):
    mdl = MDLS[int(mi) - 1]
else:
    mdl = "gemini-2.0-flash"

tp = input(f"  {Y}النوع: 1) سؤال وجواب  2) محادثة بذاكرة [1]: {W}").strip() or "1"
sys_p = input(f"  {Y}كليشة الأدمن system (فارغ = بدون): {W}").strip()
mtk = input(f"  {Y}أقصى توكن [16000، السقف 16384]: {W}").strip()
mtk = int(mtk) if mtk.isdigit() else 16000
if mtk > 16384:
    mtk = 16384
ofn = input(f"  {Y}ملف الحفظ [begamob_chat.txt]: {W}").strip() or "begamob_chat.txt"

print(f"\n  {D}── النموذج: {mdl} | النوع: {'محادثة' if tp == '2' else 'سؤال وجواب'} | توكن: {mtk} | الحفظ: {ofn} ──{X}")
if sys_p:
    print(f"  {M}⚙ كليشة الأدمن مفعلة: {sys_p[:60]}{X}")
print(f"  {D}اكتب 0 للخروج{X}\n")

hist = []
qn = 0
t0 = time.time()

while True:
    try:
        q = input(f"  {C}✦ سؤالك: {W}").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if q == "0":
        break
    if not q:
        continue
    qn += 1

    now = int(time.time())
    h64 = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    p64 = base64.urlsafe_b64encode(json.dumps({"iat": now * 1000 + 328, "exp": now + 900,
        "bundleId": "com.chatbot.ai.aichat.openaibot.chat", "os": "Android",
        "versionApp": "35.0.2"}, separators=(",", ":")).encode()).rstrip(b"=").decode()
    s64 = base64.urlsafe_b64encode(hmac.new(SEC.encode(), f"{h64}.{p64}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    tok = f"{h64}.{p64}.{s64}"
    uh = f"bundleId:com.chatbot.ai.aichat.openaibot.chat/versionApp:35.0.2/OS:Android/osVersion:29/userId:{uuid.uuid4().hex}/deviceId:{uuid.uuid4().hex.upper()}"
    hdr = {"authorization": f"Bearer {tok}", "user-header": uh,
           "content-type": "application/json; charset=UTF-8", "user-agent": "okhttp/4.12.0"}

    px = None
    if pm == "2" and plink:
        pu = plink
        if "unlimited.ipsms.com" in pu:
            sc, rest = pu.split("://", 1)
            cr, ho = rest.split("@", 1)
            us, pw2 = cr.split(":", 1)
            bs = us.split("-zone-")[0].split("-session-")[0].split("-country-")[0]
            sid = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
            pu = f"{sc}://{bs}-zone-custom-session-{sid}:{pw2}@{ho}"
        px = {"http": pu, "https": pu}
    elif pm == "3" and pool:
        pu = random.choice(pool)
        if "://" not in pu:
            pu = "http://" + pu
        px = {"http": pu, "https": pu}

    msgs = []
    if sys_p:
        msgs.append({"content": [{"text": sys_p, "type": "text"}], "role": "system"})
    if tp == "2":
        msgs += hist
    msgs.append({"content": [{"text": q, "type": "text"}], "role": "user"})

    ans = None
    cur = mtk
    for att in range(3):
        try:
            r = requests.post(URL, headers=hdr, json={"max_tokens": cur, "messages": msgs, "model": mdl},
                              timeout=180, proxies=px)
            j = r.json()
            ch = j.get("choices")
            if ch:
                ans = ch[0]["message"]["content"]
                break
            code = str(j.get("error", {}).get("code", r.status_code))
            if code.startswith("4") and cur > 8000:
                cur = 8000
                continue
            print(f"  {R}❌ خطأ {code}: {str(j)[:100]}{X}")
            break
        except Exception as e:
            print(f"  {R}❌ محاولة {att + 1}: {str(e)[:70]}{X}")
            time.sleep(3)

    if ans:
        print(f"\n  {G}⬢ {mdl}:{W}\n")
        for ln in ans.split("\n"):
            print(f"  {ln}")
        print()
        with open(ofn, "a", encoding="utf-8") as f:
            f.write(f"{'─' * 50}\nالنموذج: {mdl} | السؤال #{qn}\n{'─' * 50}\nس: {q}\n\nج: {ans}\n\n")
        if tp == "2":
            hist.append({"content": [{"text": q, "type": "text"}], "role": "user"})
            hist.append({"content": [{"text": ans, "type": "text"}], "role": "assistant"})
        print(f"  {D}[{len(ans)} حرف | محفوظ في {ofn}]{X}\n")

el = time.time() - t0
print(f"\n{C}{'═' * 46}")
print(f"  {G}✅ أسئلة مُجابة : {qn}")
print(f"  {W}⏱ المدة        : {el / 60:.1f} دقيقة")
print(f"  {Y}💾 المحادثة      : {ofn}")
print(f"{C}{'═' * 46}{X}\n")
