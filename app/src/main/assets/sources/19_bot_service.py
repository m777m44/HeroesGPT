import requests
import json
import time
import re
import random
import telebot
from typing import Optional, Dict, List
from dataclasses import dataclass
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

bot = telebot.TeleBot('توكنك_قلبي')
BASE_URL_TEMP_MAIL = "https://tempmailc.com/api/v1"

COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Origin': 'https://tempmailc.com',
    'Referer': 'https://tempmailc.com/',
    'Content-Type': 'application/json'
}

@dataclass
class AccountInfo:
    email: str = ""
    token: str = ""
    user_id: str = ""
    display_name: str = ""
    credits: int = 0
    balance: int = 0
    daily_remaining: int = 0
    daily_limit: int = 0
    session_file: str = ""

class TempMailCClient:
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(COMMON_HEADERS)
        self.email = None
    
    def create_mailbox(self, domain: Optional[str] = None, max_retries: int = 5) -> Dict:
        url = f"{BASE_URL_TEMP_MAIL}/new"
        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.get(url)
                if resp.status_code == 429:
                    wait = 5 * attempt + random.uniform(1, 3)
                    time.sleep(wait)
                    continue
                if resp.status_code not in (200, 201):
                    raise Exception(f"HTTP {resp.status_code}")
                
                data = resp.json()

                if isinstance(data, dict):
                    self.email = data.get('email') or data.get('mail') or data.get('address')
                elif isinstance(data, str):
                    self.email = data
                else:
                    self.email = resp.text.strip()
                
                if not self.email:
                    raise Exception("لم يتم استلام البريد من الخدمة")
                
                return {"email": self.email}
                
            except Exception as e:
                if attempt < max_retries:
                    wait = 5 * attempt + random.uniform(1, 3)
                    time.sleep(wait)
                else:
                    raise Exception(f"فشل إنشاء البريد بعد {max_retries} محاولات: {e}")
        raise Exception("فشل إنشاء البريد")
    
    def get_messages(self) -> List[Dict]:
        if not self.email:
            raise Exception("لا يوجد بريد صالح")
        url = f"{BASE_URL_TEMP_MAIL}/inbox"
        params = {"email": self.email}
        try:
            resp = self.session.get(url, params=params)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            data = resp.json()
            if isinstance(data, list):
                return data
            elif isinstance(data, dict) and 'messages' in data:
                return data['messages']
            elif isinstance(data, dict) and 'inbox' in data:
                return data['inbox']
            else:
                return []
        except Exception as e:
            raise Exception(f"فشل جلب الرسائل: {e}")
    
    def get_message_body(self, message_id: str) -> Dict:
        if not self.email:
            raise Exception("لا يوجد بريد صالح")
        url = f"{BASE_URL_TEMP_MAIL}/message"
        params = {"email": self.email, "msg_id": message_id}
        try:
            resp = self.session.get(url, params=params)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            return resp.json()
        except Exception as e:
            raise Exception(f"فشل جلب محتوى الرسالة: {e}")
    
    def wait_for_code(self, max_attempts: int = 30, delay: int = 3, verbose: bool = True) -> Optional[str]:
        processed_ids = set()
        for attempt in range(max_attempts):
            time.sleep(delay)
            try:
                messages = self.get_messages()
                if not messages:
                    continue
                for msg in messages:
                    msg_id = msg.get('id') or msg.get('msg_id') or msg.get('_id')
                    if not msg_id or msg_id in processed_ids:
                        continue
                    processed_ids.add(msg_id)
                    try:
                        full_msg = self.get_message_body(msg_id)
                        subject = full_msg.get('subject', '')
                        body = full_msg.get('body', '')
                        text = full_msg.get('text', '')
                        html = full_msg.get('html', '')
                        from_email = full_msg.get('from', '')
                        combined = f"{subject} {body} {text} {html} {from_email}"
                        code = self._extract_code(combined)
                        if code:
                            return code
                    except Exception as e:
                        continue
            except Exception as e:
                continue
        return None
    
    @staticmethod
    def _extract_code(text: str) -> Optional[str]:
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = re.sub(r'\s+', ' ', clean).strip()
        patterns = [
            r'\b(\d{6})\b',
            r'رمز[:\s]*(\d{6})',
            r'code[:\s]*(\d{6})',
            r'verification[:\s]*(\d{6})',
            r'كود[:\s]*(\d{6})',
            r'is your.*?(\d{6})',
            r'(\d{6})[^.]*$',
            r'otp[:\s]*(\d{6})'
        ]
        for pat in patterns:
            match = re.search(pat, clean, re.IGNORECASE)
            if match:
                return match.group(1)
        return None

class PicAIClient:
    BASE_URL = "https://picai.com/api"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "PicAIPythonClient/1.0"
        })
        self.user_data = None

    def _request(self, method: str, endpoint: str, data: Optional[Dict] = None,
                 params: Optional[Dict] = None, timeout: int = 30) -> Dict:
        url = f"{self.BASE_URL}/{endpoint.lstrip('/')}"
        try:
            resp = self.session.request(
                method=method,
                url=url,
                json=data if data else None,
                params=params,
                timeout=timeout,
            )
            try:
                result = resp.json()
            except json.JSONDecodeError:
                result = {"text": resp.text} if resp.text else {}
            if resp.status_code >= 400:
                error_msg = result.get("error") or result.get("detail") or f"HTTP {resp.status_code}"
                raise Exception(f"Request failed: {error_msg}")
            return result
        except requests.exceptions.Timeout:
            raise Exception("Request timed out")
        except requests.exceptions.ConnectionError:
            raise Exception("Connection error")

    def _get(self, endpoint: str, params: Optional[Dict] = None, timeout: int = 30) -> Dict:
        return self._request("GET", endpoint, params=params, timeout=timeout)

    def _post(self, endpoint: str, data: Optional[Dict] = None, timeout: int = 30) -> Dict:
        return self._request("POST", endpoint, data=data, timeout=timeout)

    def _delete(self, endpoint: str, timeout: int = 30) -> Dict:
        return self._request("DELETE", endpoint, timeout=timeout)

    def get_me(self) -> Dict:
        result = self._get("me")
        self.user_data = result
        return result

    def is_authenticated(self) -> bool:
        try:
            me = self.get_me()
            return bool(me.get("user"))
        except Exception:
            return False

    def request_email_code(self, email: str) -> None:
        self._post("auth/email/request", data={"email": email})

    def verify_email_code(self, email: str, code: str) -> Dict:
        result = self._post("auth/email/verify", data={"email": email, "code": code})
        self.user_data = result
        return result

    def logout(self) -> None:
        self._post("logout")
        self.session.cookies.clear()
        self.user_data = None

    def get_models(self) -> List[Dict]:
        result = self._get("models")
        if isinstance(result, list):
            return result
        return result.get("models", [])

    def get_templates(self) -> List[Dict]:
        result = self._get("templates")
        if isinstance(result, list):
            return result
        return result.get("templates", [])

    def get_tools(self) -> List[Dict]:
        result = self._get("tools")
        if isinstance(result, list):
            return result
        return result.get("tools", [])

    def get_gallery(self, page: int = 1, limit: int = 20) -> List[Dict]:
        params = {"page": page, "limit": limit}
        result = self._get("gallery", params=params)
        if isinstance(result, list):
            return result
        return result.get("items", [])

    def get_stats(self) -> Dict:
        return self._get("stats")

    def get_payment_packs(self) -> Dict:
        return self._get("payments/packs")

    def update_profile(self, display_name: str) -> Dict:
        return self._post("me/profile", data={"displayName": display_name})

    def update_email(self, email: str) -> Dict:
        return self._post("me/email", data={"email": email})

    def get_payments(self) -> List[Dict]:
        result = self._get("me/payments")
        return result.get("payments", [])

    def get_library(self, before: Optional[str] = None, limit: int = 20,
                    tool: Optional[str] = None, from_ms: Optional[int] = None,
                    to_ms: Optional[int] = None) -> Dict:
        params = {"limit": limit}
        if before:
            params["before"] = before
        if tool:
            params["tool"] = tool
        if from_ms is not None:
            params["from"] = str(from_ms)
        if to_ms is not None:
            params["to"] = str(to_ms)
        return self._get("library", params=params)

    def delete_library_item(self, item_id: str) -> None:
        self._delete(f"library/{item_id}")

    def clear_library(self) -> None:
        self._delete("library")

    def import_library_items(self, items: List[Dict]) -> List[Dict]:
        result = self._post("library/import", data={"items": items})
        return result.get("items", [])

    def fal_run(self, model_id: str, input_data: Dict, library_meta: Optional[Dict] = None,
                template_id: Optional[str] = None, on_progress=None, on_job_id=None) -> Dict:
        payload = {
            "modelId": model_id,
            "input": input_data,
        }
        if library_meta:
            payload["libraryMeta"] = library_meta
        if template_id:
            payload["templateId"] = template_id
        response = self._post("fal/run", data=payload, timeout=60)
        job_id = response.get("jobId")
        if not job_id:
            raise Exception("No jobId returned from /fal/run")
        if on_job_id:
            on_job_id(job_id, response.get("tool"))
        return self._poll_job(job_id, on_progress=on_progress)

    def _poll_job(self, job_id: str, on_progress=None, timeout: int = 600) -> Dict:
        start_time = time.time()
        while time.time() - start_time < timeout:
            status_data = self._get(f"fal/jobs/{job_id}")
            status = status_data.get("status")
            if status == "pending":
                if on_progress:
                    on_progress("Queued…")
            elif status == "running":
                if on_progress:
                    on_progress("جاري توليد...")
            elif status == "succeeded":
                outputs = status_data.get("outputs", [])
                library = status_data.get("library", [])
                credits = status_data.get("credits", {})
                return {
                    "images": [item for item in outputs if item.get("kind") == "image"],
                    "videos": [item for item in outputs if item.get("kind") == "video"],
                    "library": library,
                    "credits": credits,
                }
            elif status == "failed":
                error_msg = status_data.get("error") or status_data.get("errorCode") or "Job failed"
                raise Exception(f"Generation failed: {error_msg}")
            else:
                pass
            time.sleep(2)
        raise Exception("Polling timeout")

    def get_active_jobs(self) -> List[Dict]:
        result = self._get("fal/jobs/active")
        return result.get("jobs", [])

    def upload_image(self, data_url: str) -> str:
        result = self._post("fal/upload", data={"dataUrl": data_url})
        return result.get("url")

    def vote_gallery(self, item_id: str, value: int) -> Dict:
        return self._post(f"gallery/{item_id}/vote", data={"value": value})

    def unvote_gallery(self, item_id: str) -> Dict:
        return self._delete(f"gallery/{item_id}/vote")

    def get_share_url(self, item_id: str) -> Optional[str]:
        result = self._get(f"share-url/{item_id}")
        return result.get("url")

    def auto_register(self, domain: Optional[str] = None, verbose: bool = True) -> AccountInfo:
        temp_client = TempMailCClient()
        mailbox_data = temp_client.create_mailbox(domain)
        email = temp_client.email
        self.request_email_code(email)
        code = temp_client.wait_for_code(verbose=verbose)
        if not code:
            raise Exception("فشل استقبال رمز التحقق")
        result = self.verify_email_code(email, code)
        user_data = result.get("user", {})
        account = AccountInfo(
            email=email,
            token=result.get("token", ""),
            user_id=user_data.get("id", ""),
            display_name=user_data.get("displayName", ""),
            credits=user_data.get("credits", 0),
            balance=user_data.get("balance", 0),
            daily_remaining=user_data.get("dailyRemaining", 0),
            daily_limit=user_data.get("dailyLimit", 0),
            session_file=""
        )
        return account

    def generate_image(self, model_id: str, prompt: str) -> Dict:
        result = self.fal_run(
            model_id=model_id,
            input_data={"prompt": prompt, "num_inference_steps": 20},
            library_meta={"prompt": prompt}
        )
        return result

user_sessions = {}

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    
    if chat_id not in user_sessions:
        user_sessions[chat_id] = {"state": "waiting_for_model"}
    
    if user_sessions[chat_id].get("state") == "waiting_for_model":
        show_model_selection(chat_id)
    elif user_sessions[chat_id].get("state") == "waiting_for_prompt":
        prompt = message.text.strip()
        if prompt:
            user_sessions[chat_id]["prompt"] = prompt
            user_sessions[chat_id]["state"] = "generating"
            generate_and_send_image(chat_id)
        else:
            bot.reply_to(message, "الرجاء إدخال وصف الصورة.")

def show_model_selection(chat_id):
    markup = InlineKeyboardMarkup(row_width=2)
    models = [
        ("GPT Image 2", "gpt-image-2"),
        ("Nano Banana", "nano-banana"),
        ("FLUX Pro", "flux-pro"),
        ("Ideogram v2", "ideogram-v2"),
        ("Seedream V4", "seedream-v4"),
        ("FLUX.1", "flux-schnell"),
        ("Recraft v3", "recraft-v3")
    ]
    for name, model_id in models:
        markup.add(InlineKeyboardButton(name, callback_data=f"model_{model_id}"))
    
    bot.send_message(chat_id, "اختر النموذج:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
def handle_model_selection(call):
    chat_id = call.message.chat.id
    model_id = call.data.replace("model_", "")
    
    user_sessions[chat_id]["model_id"] = model_id
    user_sessions[chat_id]["state"] = "waiting_for_prompt"
    
    bot.edit_message_text(
        chat_id=chat_id,
        message_id=call.message.message_id,
        text=f"تم اختيار النموذج. أرسل وصف الصورة:"
    )
    
    bot.answer_callback_query(call.id)

def generate_and_send_image(chat_id):
    try:
        client = PicAIClient()
        
        bot.send_message(chat_id, "جاري توليد الصورة...")
        
        account = client.auto_register(verbose=False)
        
        model_id = user_sessions[chat_id]["model_id"]
        prompt = user_sessions[chat_id]["prompt"]
        
        result = client.generate_image(model_id, prompt)
        
        images = result.get("images", [])
        if images:
            for img in images:
                image_url = img.get('url')
                if image_url:
                    bot.send_photo(chat_id, image_url, caption=f" تم التوليد صورة حبي")
        else:
            bot.send_message(chat_id, "❌ لم يتم العثور على صور في النتيجة.")
        
        try:
            client.logout()
        except:
            pass
        
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ: {str(e)}")
    finally:
        user_sessions[chat_id]["state"] = "waiting_for_model"
        show_model_selection(chat_id)

if __name__ == "__main__":
    bot.polling(none_stop=True)