import requests
import random
import string
import time
import json
import re

def fetch_config():
    try:
        js_url = "https://aisure.uk/assets/index-oEfnSo1c.js"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        }
        r = requests.get(js_url, headers=headers, timeout=30)
        
        supabase_url_match = re.search(r'https://[a-z]+\.supabase\.co', r.text)
        anon_key_match = re.search(r'(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)', r.text)
        
        supabase_url = supabase_url_match.group(0) if supabase_url_match else None
        anon_key = anon_key_match.group(0) if anon_key_match else None
        
        return supabase_url, anon_key
    except:
        return None, None

SUPABASE_URL, ANON_KEY = fetch_config()

if not SUPABASE_URL or not ANON_KEY:
    SUPABASE_URL = "https://wtwbcruvpghcppwahiaj.supabase.co"
    ANON_KEY = ""

def _rand_email():
    p = ["yam", "alex", "john", "sara", "mike", "lisa", "david", "emma", "chris", "anna", "rob", "jen", "tom", "lucy", "mark", "jane"]
    s = "".join(random.choices(string.ascii_lowercase, k=6))
    return f"{random.choice(p)}{s}@gmail.com"

def _rand_password():
    c = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(random.choices(c, k=20))

def _rand_name():
    f = ["Yamen", "Alex", "John", "Sarah", "Michael", "Lisa", "David", "Emma", "Chris", "Anna", "Robert", "Jennifer", "Tom", "Lucy", "Mark", "Jane"]
    l = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Anderson", "Taylor"]
    return f"{random.choice(f)} {random.choice(l)}"

def _create_account():
    email = _rand_email()
    password = _rand_password()
    full_name = _rand_name()
    
    signup_url = f"{SUPABASE_URL}/auth/v1/signup"
    headers = {
        "apikey": ANON_KEY,
        "Authorization": f"Bearer {ANON_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Origin": "https://aisure.uk",
        "Referer": "https://aisure.uk/",
    }
    
    payload = {
        "email": email,
        "password": password,
        "data": {"full_name": full_name}
    }
    
    r = requests.post(signup_url, headers=headers, json=payload, timeout=30)
    
    if r.status_code != 200:
        raise Exception(f"فشل إنشاء الحساب: {r.status_code}")
    
    data = r.json()
    
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "user_id": data["user"]["id"],
        "email": data["user"]["email"],
        "full_name": full_name,
        "password": password,
        "expires_at": data.get("expires_at", int(time.time()) + 3600),
    }

MODELS = [
    {"id": "google/gemini-3.5-flash", "label": "Gemini 3.5 Flash"},
    {"id": "google/gemini-3.1-flash-lite", "label": "Gemini 3.1 Flash Lite"},
    {"id": "google/gemini-3-flash-preview", "label": "Gemini 3 Flash (Preview)"},
    {"id": "google/gemini-2.5-flash", "label": "Gemini 2.5 Flash"},
    {"id": "google/gemini-2.5-flash-lite", "label": "Gemini 2.5 Flash Lite"},
    {"id": "openai/gpt-5.4-mini", "label": "GPT-5.4 Mini"},
    {"id": "openai/gpt-5.4-nano", "label": "GPT-5.4 Nano"},
    {"id": "openai/gpt-5-mini", "label": "GPT-5 Mini"},
    {"id": "openai/gpt-5-nano", "label": "GPT-5 Nano"},
    {"id": "google/gemini-3.1-pro-preview", "label": "Gemini 3.1 Pro (Preview)"},
    {"id": "google/gemini-2.5-pro", "label": "Gemini 2.5 Pro"},
    {"id": "openai/gpt-5.5", "label": "GPT-5.5"},
    {"id": "openai/gpt-5.5-pro", "label": "GPT-5.5 Pro"},
    {"id": "openai/gpt-5.4", "label": "GPT-5.4"},
    {"id": "openai/gpt-5.4-pro", "label": "GPT-5.4 Pro"},
    {"id": "openai/gpt-5.2", "label": "GPT-5.2"},
    {"id": "openai/gpt-5", "label": "GPT-5"},
]

class AIChat:
    def __init__(self):
        self.account = None
        self.current_model = None
        self.current_model_name = None
        self.conversation_history = []
        self.chat_url = f"{SUPABASE_URL}/functions/v1/chat"
        
    def create_account(self):
        self.account = _create_account()
        return self.account['email']
    
    def refresh_token(self):
        if not self.account:
            return False
            
        if time.time() >= self.account.get("expires_at", 0) - 300:
            url = f"{SUPABASE_URL}/auth/v1/token?grant_type=refresh_token"
            headers = {
                "apikey": ANON_KEY,
                "Content-Type": "application/json",
            }
            payload = {"refresh_token": self.account["refresh_token"]}
            
            r = requests.post(url, headers=headers, json=payload, timeout=30)
            
            if r.status_code == 200:
                data = r.json()
                self.account["access_token"] = data["access_token"]
                self.account["refresh_token"] = data["refresh_token"]
                self.account["expires_at"] = data.get("expires_at", int(time.time()) + 3600)
                return True
        
        return False
    
    def rotate_account(self):
        self.conversation_history = []
        return self.create_account()
    
    def get_headers(self):
        return {
            "apikey": ANON_KEY,
            "Authorization": f"Bearer {self.account['access_token']}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept": "text/event-stream, */*",
            "Referer": "https://aisure.uk/",
            "Origin": "https://aisure.uk",
            "x-client-info": "supabase-js/2.108.2; runtime=web",
        }
    
    def select_model(self):
        print("\033[90m" + "─" * 60 + "\033[0m")
        print("\nالنماذج المتاحة:\n")
        print("\033[90m" + "─" * 60 + "\033[0m")
        for i, model in enumerate(MODELS, 1):
            print(f"  [{i}] {model['label']}")
        print("\033[90m" + "─" * 60 + "\033[0m")
        
        while True:
            try:
                choice = input(f"\nاختر رقم النموذج (1-{len(MODELS)}): ")
                print("\033[90m" + "─" * 60 + "\033[0m")
                
                index = int(choice) - 1
                if 0 <= index < len(MODELS):
                    self.current_model = MODELS[index]["id"]
                    self.current_model_name = MODELS[index]["label"]
                    print(f"\nتم اختيار: {self.current_model_name}")
                    return True
                else:
                    print("اختيار غير صالح")
            except ValueError:
                print("الرجاء إدخال رقم صحيح")
    
    def send_message(self, message):
        self.refresh_token()
        
        model = self.current_model or "google/gemini-2.5-flash"
        
        headers = self.get_headers()
        
        system_message = "أنت نموذج ذكاء اصطناعي. أجب بشكل مباشر دون ذكر اسم AISure أو Noahsure Group أو المنصة. لا تذكر أنك مساعد افتراضي للمنصة. تصرف كأنك النموذج الأصلي نفسه."
        
        messages = [{"role": "system", "content": system_message}]
        
        for msg in self.conversation_history:
            messages.append(msg)
        
        messages.append({"role": "user", "content": message})
        
        payload = {
            "messages": messages,
            "model": model
        }
        
        try:
            r = requests.post(
                self.chat_url,
                headers=headers,
                json=payload,
                timeout=120,
                stream=True
            )
            
            if r.status_code == 429 or r.status_code == 403:
                self.rotate_account()
                return self.send_message(message)
            
            if r.status_code != 200:
                error_text = r.text[:500]
                
                if any(word in error_text.lower() for word in ["limit", "quota", "exhausted"]):
                    self.rotate_account()
                    return self.send_message(message)
                
                raise Exception(f"خطأ {r.status_code}")
            
            full_response = ""
            content_type = r.headers.get("content-type", "")
            
            if "text/event-stream" in content_type:
                for line in r.iter_lines():
                    if not line:
                        continue
                    
                    decoded = line.decode("utf-8")
                    
                    if decoded.startswith(":"):
                        continue
                    
                    if not decoded.startswith("data: "):
                        continue
                    
                    data = decoded[6:].strip()
                    
                    if data == "[DONE]":
                        break
                    
                    try:
                        chunk = json.loads(data)
                        
                        if chunk.get("error"):
                            err_str = str(chunk["error"])
                            if any(word in err_str.lower() for word in ["limit", "quota"]):
                                self.rotate_account()
                                return self.send_message(message)
                            raise Exception(err_str)
                        
                        choices = chunk.get("choices", [])
                        if choices and len(choices) > 0:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if isinstance(content, str) and len(content) > 0:
                                full_response += content
                    
                    except json.JSONDecodeError:
                        continue
            else:
                try:
                    data = r.json()
                    if "choices" in data:
                        full_response = data["choices"][0].get("message", {}).get("content", "")
                    elif "response" in data:
                        full_response = data["response"]
                except:
                    full_response = r.text
            
            if full_response:
                print(f"\n{full_response}")
            
            self.conversation_history.append({"role": "user", "content": message})
            self.conversation_history.append({"role": "assistant", "content": full_response})
            
            return full_response
            
        except Exception as e:
            raise Exception(f"فشل الإرسال: {str(e)}")
    
    def start(self):
        if not self.current_model:
            return
            
        while True:
            
            try:
                print("\033[90m" + "─" * 60 + "\033[0m")
                user_input = input("أنت: ")
                print("\033[90m" + "─" * 60 + "\033[0m")
                
                if user_input.lower() in ['quit', 'exit', 'q', 'خروج']:
                    print("مع السلامة!")
                    break
                    
                elif user_input.lower() in ['clear', 'مسح']:
                    self.conversation_history = []
                    print("تم مسح سجل المحادثة")
                    continue
                    
                elif user_input.lower() in ['model', 'نموذج']:
                    if self.select_model():
                        self.conversation_history = []
                        print(f"\nالنموذج: {self.current_model_name}")
                       
                    continue
                    
                elif not user_input.strip():
                    continue
                
                self.send_message(user_input)
                    
            except KeyboardInterrupt:
                print("\nروح صلي")
                break
                
            except Exception as e:
                print(f"\nخطأ: {str(e)}\n")
                try:
                    self.rotate_account()
                except:
                    pass

def main():
    chat = AIChat()
    
    try:
        chat.create_account()
        
        if not chat.select_model():
            return
        
        chat.start()
        
    except Exception as e:
        print(f"\nخطأ: {str(e)}")

if __name__ == "__main__":
    main()