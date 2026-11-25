import requests
import json
import time
import sys

KEY = "AIzaSy…REDACTED…"
URL = "https://ai-multi-search-backend-321697147922.europe-west6.run.app/ask"

HEADERS = {
    'User-Agent': "Dalvik/2.1.0 (Linux; U; Android 16; 2311DRK48G Build/BP2A.250605.031.A3)",
    'Connection': "Keep-Alive",
    'Accept-Encoding': "gzip",
    'Content-Type': "application/json",
    'X-Android-Package': "com.lmtechstudio.aimultisearch",
    'X-Android-Cert': "5D08264B44E0E53FBCCC70B4F016474CC6C5AB5C",
    'Accept-Language': "ar-EG, en-US",
    'X-Client-Version': "Android/Fallback/X23001000/FirebaseCore-Android",
    'X-Firebase-GMPID': "1:321697147922:android:26e6fb8e30dcc23dfffccb",
    'X-Firebase-Client': "H4sIAAAAAAAA_6tWykhNLCpJSk0sKVayio7VUSpLLSrOzM9TslIyUqoFAFyivEQfAAAA"
}

token = None
token_expiry = 0

def get_token():
    global token, token_expiry
    if token and time.time() < token_expiry - 60:
        return token
    
    r = requests.post(
        "https://www.googleapis.com/identitytoolkit/v3/relyingparty/signupNewUser",
        params={'key': KEY},
        data=json.dumps({"clientType": "CLIENT_TYPE_ANDROID"}),
        headers=HEADERS
    )
    data = r.json()
    token = "Bearer " + data["idToken"]
    token_expiry = time.time() + int(data["expiresIn"])
    
    return token

SEARCH_CFG = {
    'claude': {"app_version": "1.2.8", "search_id": "825a35c5-aac2-49d7-8317-5b7a68ae6cae"},
}

def make_prompt(q, claude=False):
    base = (
        "You MUST answer in the EXACT same language as the user question.\n"
        "Do NOT change language.\nDo NOT mix languages.\nDo NOT translate unless explicitly asked.\n\n"
        "Formatting rules:\n- No tables.\n- No markdown tables.\n- No ASCII tables.\n"
        "- Do NOT use pipe characters: |\n- Use clean bullet points or short paragraphs.\n\n"
        f"User question:\n{q}"
    )
    return base

def stream_response_simple(provider, question):
    current_token = get_token()
    cfg = SEARCH_CFG[provider]
    av = cfg["app_version"]
    
    payload = {
        "provider": provider,
        "prompt": make_prompt(question, provider == "claude"),
        "plan": "ULTRA",
        "app_version": av
    }
    
    headers = {
        'User-Agent': "okhttp/4.12.0",
        'Accept-Encoding': "gzip",
        'authorization': current_token,
        'x-plan': "ULTRA",
        'x-app-version': av,
        'x-search-id': cfg["search_id"],
        'x-search-expected': "2",
        'content-type': "application/json; charset=utf-8"
    }
    
    try:
        r = requests.post(URL, data=json.dumps(payload), headers=headers, stream=True, timeout=60)
        
        if r.status_code != 200:
            print(f"خطأ: {r.status_code}")
            return
        
        print(f"\n[{provider.upper()}] ", end="", flush=True)
        
        full_response = ""
        for line in r.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode('utf-8'))
                    if data.get("ok"):
                        answer = data.get("answer", "")
                        if answer:
                            for char in answer:
                                print(char, end="", flush=True)
                                time.sleep(0.01)
                            full_response = answer
                    elif "claude" in data:
                        chunk = data["claude"]
                        print(chunk, end="", flush=True)
                        full_response += chunk
                except json.JSONDecodeError:
                    print(line.decode('utf-8'), end="", flush=True)
        
        print("\n")
        return full_response
        
    except requests.exceptions.Timeout:
        print("خطأ: انتهت المهلة")
    except Exception as e:
        print(f"خطأ: {e}")

while True:
    question = input("انت >> ")
      
    print()
    stream_response_simple('claude', question)