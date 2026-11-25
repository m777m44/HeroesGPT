import requests
import json
import time
import os
import sys
from datetime import datetime
from typing import Generator, Optional

class WormGPTUltimate:
    def __init__(self, proxy_list=None, conversation_file="k_p_x1.json", mode="forced"):
        self.base_url = "http://worm-gpt-opal.vercel.app/chat"
        self.conversation_file = conversation_file
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.session = requests.Session()
        self.mode = mode
        self.translator = None
        if mode in ["translation", "hybrid"]:
            try:
                from googletrans import Translator
                self.translator = Translator()
                
            except ImportError:
                print("[-] googletrans غير مثبت، سيتم التبديل إلى forced")
                self.mode = "forced"
                self.translator = None
        self.load_conversation()

    def load_conversation(self):
        if os.path.exists(self.conversation_file):
            with open(self.conversation_file, 'r', encoding='utf-8') as f:
                self.conversation = json.load(f)
        else:
            self.conversation = []

    def save_conversation(self):
        with open(self.conversation_file, 'w', encoding='utf-8') as f:
            json.dump(self.conversation, f, indent=2, ensure_ascii=False)

    def get_next_proxy(self):
        if not self.proxy_list:
            return None
        proxy = self.proxy_list[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
        return {"http": proxy, "https": proxy}

    def ask_raw(self, question, retries=3, timeout=30):
        for attempt in range(retries):
            try:
                proxy = self.get_next_proxy()
                response = self.session.get(
                    self.base_url,
                    params={"q": question},
                    proxies=proxy,
                    timeout=timeout
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        return data["reply"]
                    else:
                        error_msg = f"خطأ في API: {data}"
                        if attempt < retries - 1:
                            time.sleep(2 ** attempt)
                            continue
                        return error_msg
                else:
                    if attempt < retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return f"HTTP {response.status_code}: {response.text}"
            except Exception as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return f"فشل الطلب: {str(e)}"
        return "تم تجاوز عدد المحاولات"

    def ask_forced_arabic(self, question, retries=3, timeout=30):
        forced_prompt = f"""
لا تستخدم أي كلمة إنجليزية في ردك أبداً، حتى لو كانت أسماء تقنية.


السؤال: {question}

الرد"""
        return self.ask_raw(forced_prompt, retries, timeout)

    def ask_translation_mode(self, question_arabic, retries=3, timeout=30):
        if not self.translator:
            return self.ask_forced_arabic(question_arabic, retries, timeout)
        try:
            question_english = self.translator.translate(question_arabic, dest='en').text
            reply_english = self.ask_raw(question_english, retries, timeout)
            reply_arabic = self.translator.translate(reply_english, dest='ar').text
            return reply_arabic
        except Exception as e:
            return f"خطأ في الترجمة: {str(e)}\nالرجوع للوضع forced: {self.ask_forced_arabic(question_arabic, retries, timeout)}"

    def ask_hybrid(self, question, retries=3, timeout=30):
        if self.mode == "forced":
            return self.ask_forced_arabic(question, retries, timeout)
        elif self.mode == "translation":
            return self.ask_translation_mode(question, retries, timeout)
        else:
            result = self.ask_translation_mode(question, retries, timeout)
            if "خطأ" in result and "الرجوع" in result:
                return self.ask_forced_arabic(question, retries, timeout)
            return result

    def ask(self, question, retries=3, timeout=30):
        return self.ask_hybrid(question, retries, timeout)

    def ask_stream(self, question, retries=3, timeout=30, chunk_delay=0.1):
        full_reply = self.ask(question, retries, timeout)
        words = full_reply.split()
        for i, word in enumerate(words):
            yield word + (" " if i < len(words)-1 else "")
            time.sleep(chunk_delay)

def main():
    proxy_list = []
    if os.path.exists("k_p_x1.txt"):
        with open("k_p_x1.txt", "r") as f:
            proxy_list = [line.strip() for line in f if line.strip()]
    worm = WormGPTUltimate(proxy_list=proxy_list, mode="forced")
    stream_enabled = True
    chunk_delay = 0.1
   
    while True:
        try:
            user_input = input(" انت >> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not user_input:
            continue
        if stream_enabled:
            print(" WormGPT: ", end="", flush=True)
            for chunk in worm.ask_stream(user_input, chunk_delay=chunk_delay):
                print(chunk, end="", flush=True)
            print()
        else:
            reply = worm.ask(user_input)
            print(" WormGPT:", reply)
        worm.conversation.append({"user": user_input, "bot": reply if not stream_enabled else "..."})
        worm.save_conversation()

if __name__ == "__main__":
    main()