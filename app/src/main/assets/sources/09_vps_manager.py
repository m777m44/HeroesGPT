

import json
import sys
import time
import uuid
import argparse
import requests

BASE = "https://android.chat.openai.com"
UA = "ChatGPT/1.2026.293 (Android 10; unknown; build 2629319)"
FREE_MODELS = ["auto", "gpt-5-6", "gpt-5-6-mini", "gpt-6", "gpt-6-mini"]

G = "\033[92m"; C = "\033[96m"; Y = "\033[93m"; R = "\033[91m"; D = "\033[90m"; B = "\033[1m"; X = "\033[0m"


class CGPT:
    def __init__(self, token=None, device_id=None, account_id=None, proxy=None):
        self.token = token
        self.device_id = device_id or str(uuid.uuid4())
        self.account_id = account_id or "default"
        self.session_id = str(uuid.uuid4())
        self.conversation_id = None
        self.parent_id = None
        self.s = requests.Session()
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}

    def _headers(self, target_path, stream=False):
        h = {
            "user-agent": UA,
            "oai-package-name": "com.openai.chatgpt",
            "x-openai-target-path": target_path,
            "oai-client-type": "android",
            "oai-device-id": self.device_id,
            "x-device-tier": "flagship",
            "chatgpt-account-id": self.account_id,
            "chatgpt-residency-region": "no_constraint",
            "accept-language": "ar-SA,ar;q=0.9",
            "accept": "text/event-stream,application/json" if stream else "application/json",
            "content-type": "application/json",
            "oai-client-session": json.dumps({
                "client_session_id": str(uuid.uuid4()),
                "client_session_start": int(time.time() * 1000),
            }),
        }
        if self.token:
            h["authorization"] = f"Bearer {self.token}"
        return h

    def _api(self, path, body=None, method=None):
        prefix = "/backend-anon" if not self.token else "/backend-api"
        url = BASE + prefix + path
        hdrs = self._headers(prefix + path)
        if method == "GET" or body is None:
            return self.s.get(url, headers=hdrs, timeout=30)
        return self.s.post(url, headers=hdrs, json=body, timeout=60)

    def prepare(self):
        body = {
            "conversation_id": self.conversation_id,
            "action": "next",
            "parent_message_id": self.parent_id,
            "messages": [],
            "model": "auto",
            "supported_encodings": ["v1"],
            "supports_buffering": True,
            "timezone": "Asia/Baghdad",
        }
        body = {k: v for k, v in body.items() if v is not None}
        try:
            r = self._api("/f/conversation/prepare", body)
            if r.status_code == 200:
                return r.json().get("conduit_token")
        except Exception:
            pass
        return None

    def _msg(self, text):
        return {
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"parts": [text], "content_type": "text"},
            "status": "finished_successfully",
            "recipient": "all",
            "metadata": {
                "model_slug": "auto", "default_model_slug": "auto",
                "is_visually_hidden_from_conversation": False,
                "exclude_after_next_user_message": False,
                "content_references": [], "search_result_groups": [],
                "search_queries": [], "submission_mode": "manual_send",
                "image_results": [], "real_time_audio_has_video": False,
                "system_hints": [], "dictation": False,
                "voice_mode_message": False, "trigger_async_ux": False,
                "writing_blocks": {},
            },
        }

    def new_chat(self):
        self.conversation_id = None
        self.parent_id = None
        self.session_id = str(uuid.uuid4())

    def chat(self, text, model="auto", on_delta=None, retries=2):
        last_err = None
        for attempt in range(retries + 1):
            res = self._chat_once(text, model, on_delta)
            if res["ok"] and res["text"]:
                return res
            last_err = res
            if res.get("status") in (401, 403):
                break
            time.sleep(1.5)
        return last_err or {"ok": False, "status": 0, "body": "خطأ غير معروف"}

    def _chat_once(self, text, model, on_delta):
        conduit = self.prepare()
        body = {
            "action": "next",
            "messages": [self._msg(text)],
            "model": model,
            "supported_encodings": ["v1"],
            "supports_buffering": True,
            "timezone": "Asia/Baghdad",
        }
        if self.conversation_id:
            body["conversation_id"] = self.conversation_id
        if self.parent_id:
            body["parent_message_id"] = self.parent_id

        prefix = "/backend-anon" if not self.token else "/backend-api"
        hdrs = self._headers(prefix + "/f/conversation", stream=True)
        hdrs["oai-session-id"] = self.session_id
        hdrs["x-oai-convo-session-id"] = self.session_id
        hdrs["x-oai-turn-trace-id"] = str(uuid.uuid4())
        hdrs["x-openai-web-sse-compression"] = "gzip"
        hdrs["cache-control"] = "no-cache"
        hdrs["x-oai-library-attachments-format"] = "unified-v1"
        if conduit:
            hdrs["x-conduit-token"] = conduit

        try:
            r = self.s.post(BASE + prefix + "/f/conversation", headers=hdrs,
                            json=body, timeout=180, stream=True)
        except Exception as e:
            return {"ok": False, "status": 0, "body": str(e)[:200]}
        if r.status_code != 200:
            return {"ok": False, "status": r.status_code, "body": r.text[:300]}

        full = ""
        result = {"ok": True, "text": "", "conversation_id": None, "message_id": None}

        def handle_ops(ops):
            nonlocal full
            for op in ops:
                if not isinstance(op, dict):
                    continue
                p, v, o = op.get("p", ""), op.get("v"), op.get("o")
                if o == "append" and "/parts/" in p and isinstance(v, str):
                    full += v
                    if on_delta:
                        on_delta(v)
                elif o in ("set", "replace") and "/parts/" in p and isinstance(v, str):
                    full = v

        def handle_msg(msg):
            nonlocal full
            if not isinstance(msg, dict):
                return
            if (msg.get("author") or {}).get("role") == "assistant":
                if msg.get("id"):
                    result["message_id"] = msg["id"]
                parts = (msg.get("content") or {}).get("parts") or []
                joined = "".join(x for x in parts if isinstance(x, str))
                if joined and len(joined) >= len(full):
                    full = joined

        try:
            for raw in r.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                data = raw[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except Exception:
                    continue
                if isinstance(ev, str):
                    continue
                if isinstance(ev, list):
                    handle_ops(ev)
                    continue
                if not isinstance(ev, dict):
                    continue
                if ev.get("conversation_id"):
                    result["conversation_id"] = ev["conversation_id"]
                    self.conversation_id = ev["conversation_id"]
                v = ev.get("v")
                if isinstance(v, list):
                    handle_ops(v)
                elif isinstance(v, dict) and "message" in v:
                    handle_msg(v["message"])
                elif isinstance(v, str) and ev.get("o") in ("append", "set", "replace"):
                    handle_ops([ev])
                if isinstance(ev.get("message"), dict):
                    handle_msg(ev["message"])
        except Exception as e:
            if not full:
                return {"ok": False, "status": 0, "body": str(e)[:200]}

        if result["message_id"]:
            self.parent_id = result["message_id"]
        result["text"] = full
        return result

    def models(self):
        try:
            r = self._api("/models?iim=false", method="GET")
            if r.status_code == 200:
                return [m.get("slug") for m in r.json().get("models", [])]
        except Exception:
            pass
        return []


def banner(model):
    print(f"""{C}{B}
 ╔══════════════════════════════════════════════╗
 ║        ChatGPT Free — بدون حساب 🚀            ║
 ║   النموذج: {model:<10}  |  الذاكرة: مفعّلة      ║
 ║        Developer: @Q_B_h                     ║
 ╚══════════════════════════════════════════════╝{X}
{D}الأوامر:  نموذج <اسم> لتبديل النموذج  |  جديد = محادثة جديدة  |  خروج{X}
{D}النماذج: {' | '.join(FREE_MODELS)}{X}
{D}حقوق المطور: @Q_B_h — All rights reserved{X}
""")


def run_cli(token=None, proxy=None, start_model="auto"):
    c = CGPT(token=token, proxy=proxy)
    model = start_model
    banner(model)
    while True:
        try:
            q = input(f"{G}{B}ضع سؤالك:{X} ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{C}إلى اللقاء 👋{X}")
            break
        if not q:
            continue
        low = q.lower()
        if low in ("خروج", "exit", "quit"):
            print(f"{C}إلى اللقاء 👋{X}")
            break
        if low in ("جديد", "new"):
            c.new_chat()
            print(f"{Y}✦ محادثة جديدة — الذاكرة صُفّرت{X}")
            continue
        if low.startswith("نموذج ") or low.startswith("model "):
            name = q.split(None, 1)[1].strip()
            if name in FREE_MODELS:
                model = name
                print(f"{Y}✦ النموذج الآن: {model}{X}")
            else:
                print(f"{R}نموذج غير معروف. المتاح: {' | '.join(FREE_MODELS)}{X}")
            continue
        if low in ("نماذج", "models"):
            print(f"{Y}النماذج المجانية: {' | '.join(FREE_MODELS)}{X}")
            continue

        print(f"{C}{B}GPT:{X} ", end="", flush=True)
        res = c.chat(q, model=model, on_delta=lambda d: print(d, end="", flush=True))
        if res["ok"] and res["text"]:
            if not res.get("_streamed"):
                pass
            print()
        else:
            print(f"{R}[تعثر الطلب — status={res.get('status')}] {res.get('body', '')[:150]}{X}")
            print(f"{D}جرّب مرة أخرى أو اكتب: جديد{X}")


def main():
    ap = argparse.ArgumentParser(
        description="ChatGPT Free — محادثة بدون حساب | Developer: @Q_B_h"
    )
    ap.add_argument("message", nargs="?", help="سؤال واحد سريع (بدونها = محادثة تفاعلية)")
    ap.add_argument("--token", help="توكن حساب (اختياري — بدونه مجاني)")
    ap.add_argument("--model", default="auto", choices=FREE_MODELS)
    ap.add_argument("--proxy")
    args = ap.parse_args()

    if args.message:
        c = CGPT(token=args.token, proxy=args.proxy)
        res = c.chat(args.message, model=args.model,
                     on_delta=lambda d: print(d, end="", flush=True))
        print()
        if not (res["ok"] and res["text"]):
            print(f"[!] status={res.get('status')} {res.get('body', '')[:200]}")
            sys.exit(1)
    else:
        run_cli(token=args.token, proxy=args.proxy, start_model=args.model)


if __name__ == "__main__":
    main()