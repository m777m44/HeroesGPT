import requests
import uuid
import json
import os
import warnings

warnings.filterwarnings('ignore')
requests.packages.urllib3.disable_warnings()

MODEL = "gpt-5.6"

GRAY = "\033[90m"
RESET = "\033[0m"
ITALIC_WHITE = "\033[3;37m"
SEPARATOR = GRAY + "─" * 60 + RESET

class ConversationData:
    def __init__(self, conv_id):
        self.conv_id = conv_id
        self.conversation_id = None
        self.parent_message_id = None
        self.headers = {}

user_conversations = {}
user_current_conv = {}

HEADERS = {
    'User-Agent': "ChatGPT/1.2027.000 (Android 15; RMX3834; build 2700000)",
    'Accept': "application/json",
    'Accept-Encoding': "gzip",
    'Content-Type': "application/json",
    'oai-package-name': "com.Modderme",
    'oai-client-type': "android",
    'oai-device-id': "84329164059103383964",
    'accept-language': "en-US,en;q=0.9,ar-EG;q=0.8,ar;q=0.7",
    'x-device-tier': "lower_mid",
    'chatgpt-account-id': "84329164059103383964",
    'chatgpt-residency-region': "no_constraint",
    'Cookie': "__cflb=04dTod5Jcx9DYJeMeKbyj32ve2B3i9pLVRxJxEAaKD; _cfuvid=PXu6q36jhfgxnsdFkDmqwLzCfHOSgG588liApL0856A-1777834828.2542033-1.0.1.1-JFC10kaoqt9_IXzxrixI6zZuAm.TzRPF14QfJiD43MQ; oai-ll=; oai-sc=0gAAAAABp959mEmk6Qr5JsnqYMpWx1-15EJhCVV2EV6SQpet7Z7SjNuAT0x2cVScJu_g_TE9_NXidYfi68DtZfl4ImOQIRkr8PF-R-v9PUl7IPGtYiF1rwqdVm0NjapKV1lROdrmNGkiuNgcVMGYXMrP45hfmmQKiCQ5MBQLjfI7XI2tKSLvHT3WkjFEnmDZIRtVz85lyV9pxK181GJRARSxM53m06IfD3jEDjVbSR5QDQbL6Nxl4l7c; __cf_bm=y_lpbPz3viZYHSAd8nCLtIlm2JBCYWvEwOz8xvvwFow-1777835878.3854406-1.0.1.1-Muu0UxZKqufJhSVDELNGz2fO12Xcqc.oJ3hINoXkGIc2tGinJqVnmBTM7EAKDRfqdl1WdKtZ06fuCJ3y5DddxeMPVlBNX_r7daQReYa59qkFBwXOF3p4W3lwU.tdPN9A"
}

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_banner():
    print("""
                           @k_p_x1
    """)
    print(SEPARATOR)

def get_conduit_token():
    url = "https://android.chat.openai.com/backend-api/f/conversation/prepare"
    payload = {
        "action": "next",
        "messages": [],
        "model": "auto",
        "history_and_training_disabled": False,
        "fork_from_shared_post": False,
        "enable_message_followups": False,
        "force_use_sse": False,
        "force_use_search": None,
        "force_paragen": False,
        "supports_buffering": False,
        "timezone": "Africa/Cairo",
        "timezone_offset_min": -180,
        "system_hints": [],
        "is_onboarding_conversation": False
    }
    try:
        r = requests.post(url, json=payload, headers=HEADERS, timeout=30, verify=False)
        if r.status_code == 200:
            return r.json().get("conduit_token")
    except:
        pass
    return None

def create_conversation(user_id):
    token = get_conduit_token()
    if not token:
        return None
    conv_headers = HEADERS.copy()
    conv_headers['Conduit-Token'] = token
    conv_headers['x-oai-convo-session-id'] = str(uuid.uuid4())
    conv_headers['x-oai-turn-trace-id'] = str(uuid.uuid4())
    conv_headers['x-openai-target-path'] = "/backend-api/f/conversation"
    conv_id = str(uuid.uuid4())[:8]
    conv = ConversationData(conv_id)
    conv.headers = conv_headers
    if user_id not in user_conversations:
        user_conversations[user_id] = {}
    user_conversations[user_id][conv_id] = conv
    user_current_conv[user_id] = conv_id
    return conv_id

def send_message(user_id, text):
    conv_id = user_current_conv.get(user_id)
    if not conv_id or user_id not in user_conversations:
        conv_id = create_conversation(user_id)
        if not conv_id:
            return "آسف، ما قدرنا نفتح محادثة"
    conv = user_conversations[user_id][conv_id]
    msg_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    
    payload = {
        "action": "next",
        "messages": [{
            "id": msg_id,
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [text]},
            "status": "finished_successfully"
        }],
        "model": MODEL,
        "parent_message_id": conv.parent_message_id if conv.parent_message_id else parent_id,
        "stream": True,
        "timezone": "Africa/Cairo",
        "timezone_offset_min": -180,
        "system_hints": [""]
    }
    if conv.conversation_id:
        payload["conversation_id"] = conv.conversation_id
    try:
        print(SEPARATOR)
        print(f"{ITALIC_WHITE}{RESET}", end="", flush=True)
        r = requests.post(
            'https://android.chat.openai.com/backend-api/f/conversation',
            headers=conv.headers,
            json=payload,
            stream=True,
            timeout=120,
            verify=False
        )
        if r.status_code != 200:
            print(f"\nخطأ: {r.status_code}")
            print(SEPARATOR)
            return "آسف، السيرفر ما رد"
        full = ""
        first = True
        for line in r.iter_lines():
            if not line:
                continue
            try:
                data = line.decode('utf-8')
                if data.startswith('data: '):
                    data = data[6:]
                    if data == '[DONE]':
                        break
                    j = json.loads(data)
                    if 'conversation_id' in j:
                        conv.conversation_id = j['conversation_id']
                    if 'message' in j and j['message']:
                        if 'parent_id' in j['message']:
                            conv.parent_message_id = j['message']['parent_id']
                        if 'content' in j['message']:
                            c = j['message']['content']
                            if 'parts' in c and c['parts']:
                                part = c['parts'][0]
                                if part and part != full:
                                    if first:
                                        print(f"{ITALIC_WHITE}{part}{RESET}", end="", flush=True)
                                        first = False
                                    else:
                                        new = part[len(full):]
                                        if new:
                                            print(f"{ITALIC_WHITE}{new}{RESET}", end="", flush=True)
                                    full = part
            except:
                continue
        print()
        print(SEPARATOR)
        return full if full else "ما في جواب"
    except Exception as e:
        print(f"\nصار خطأ: {str(e)}")
        print(SEPARATOR)
        return "خطأ غير متوقع"

def main():
    user_id = 1
    clear_screen()
    print_banner()
    
    while True:
        try:
            inp = input(f"\nأنت: {RESET}").strip()
            if not inp:
                continue
            send_message(user_id, inp)
        except KeyboardInterrupt:
            print("\n\nمع السلامة!")
            break
        except Exception as e:
            print(f"خطأ: {e}")
            print(SEPARATOR)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nتم الإيقاف")