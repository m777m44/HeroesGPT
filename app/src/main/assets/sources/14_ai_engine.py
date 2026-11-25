import requests
import json
import time
import os
import uuid
import hashlib
import telebot
from telebot import types
from io import BytesIO

BOT_TOKEN = "توكن بوتك"
bot = telebot.TeleBot(BOT_TOKEN)

MODELS = {
    "WAN 2.6": "3-36", "WAN 2.2": "3-10", "Veo 3.1": "3-11", "Sora 2 Pro": "3-18",
    "Sora 2": "3-13", "WAN 2.5": "3-15", "Grok": "3-19", "Kling O1": "3-35",
    "Kling 2.6": "3-33", "Kling 2.5": "3-1", "Seedance 1.5 Pro": "3-38",
    "Seedance 1.0": "3-21", "Pixverse V5": "3-27", "Pika 2.2": "3-26",
    "Runway Gen-4 Turbo": "3-25", "Luma Ray 2": "3-4", "Hailuo 2.3": "3-17", "Hailuo 02": "3-3"
}

user_data = {}

class PixWithAI:
    def __init__(self):
        self.base_url = "https://api.pixwith.ai/api"
        self.session_token = hashlib.md5(f"{uuid.uuid4()}{int(time.time()*1000)}".encode()).hexdigest() + "0"
        self.headers = {
            'authority': 'api.pixwith.ai', 'accept': '*/*', 'origin': 'https://pixwith.ai',
            'referer': 'https://pixwith.ai/', 'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
            'x-session-token': self.session_token
        }

    def _opts(self, url):
        try:
            requests.options(url, headers={'origin': 'https://pixwith.ai', 'referer': 'https://pixwith.ai/'}, timeout=10)
        except:
            pass

    def get_upload_url(self, filename):
        self._opts(f"{self.base_url}/chats/pre_url")
        h = self.headers.copy()
        h['content-type'] = 'application/json'
        try:
            r = requests.post(f"{self.base_url}/chats/pre_url", headers=h,
                            json={"image_name": filename, "content_type": "image/jpeg"}, timeout=15)
            if 'x-session-token' in r.headers:
                self.session_token = r.headers['x-session-token']
                self.headers['x-session-token'] = self.session_token
            return r.json()
        except:
            return {}

    def upload_image(self, data, image_data, filename):
        try:
            s3 = data.get("data", {}).get("url", data) if "data" in data else data
            url, fields = s3.get("url"), s3.get("fields", {})
            if not url or not fields:
                return None
            self._opts(url)
            files = [(k, (None, str(v))) for k, v in fields.items()]
            files.append(('file', (filename, image_data, 'image/jpeg')))
            r = requests.post(url, files=files, headers={'origin': 'https://pixwith.ai'}, timeout=60)
            return fields.get("key") if r.status_code in [200, 204] else None
        except:
            return None

    def create_video(self, image_key, prompt="", model_id="3-38"):
        self._opts(f"{self.base_url}/items/create")
        h = self.headers.copy()
        h['content-type'] = 'application/json'
        try:
            r = requests.post(f"{self.base_url}/items/create", headers=h, json={
                "images": {"image1": image_key}, "prompt": prompt,
                "options": {"prompt_optimization": True, "num_outputs": 1, "aspect_ratio": "16:9",
                           "resolution": "480p", "duration": 4, "sound": True}, "model_id": model_id
            }, timeout=15)
            if 'x-session-token' in r.headers:
                self.session_token = r.headers['x-session-token']
                self.headers['x-session-token'] = self.session_token
            return r.json()
        except:
            return {}

    def get_history(self):
        h = self.headers.copy()
        h['content-type'] = 'application/json'
        try:
            r = requests.post(f"{self.base_url}/items/history", headers=h,
                            json={"tool_type": "3", "tag": "", "page": 0, "page_size": 12}, timeout=15)
            if 'x-session-token' in r.headers:
                self.session_token = r.headers['x-session-token']
                self.headers['x-session-token'] = self.session_token
            return r.json()
        except:
            return {}


@bot.message_handler(commands=['start'])
def start_command(message):
    user_id = message.from_user.id
    user_data[user_id] = {'api': PixWithAI(), 'model_id': '3-38', 'model_name': 'Seedance 1.5 Pro'}
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📤 رفع صورة", callback_data="upload_image"))
    markup.add(types.InlineKeyboardButton("🎬 اختيار النموذج", callback_data="choose_model"))
    markup.add(types.InlineKeyboardButton("ℹ️ معلومات", callback_data="info"))
    bot.send_message(message.chat.id, f"مرحباً بك في بوت PixWithAI 🎥\n\nالنموذج الحالي: {user_data[user_id]['model_name']}\n\nاستخدم الأزرار أدناه للبدء:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "upload_image")
def upload_image_callback(call):
    user_id = call.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {'api': PixWithAI(), 'model_id': '3-38', 'model_name': 'Seedance 1.5 Pro'}
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"النموذج المختار: {user_data[user_id]['model_name']}\n\nالآن أرسل الصورة التي تريد تحويلها إلى فيديو:")
    bot.register_next_step_handler(msg, process_image)


@bot.callback_query_handler(func=lambda call: call.data == "choose_model")
def choose_model_callback(call):
    user_id = call.from_user.id
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for model_name, model_id in MODELS.items():
        current = "✅ " if user_data.get(user_id, {}).get('model_id') == model_id else ""
        buttons.append(types.InlineKeyboardButton(f"{current}{model_name}", callback_data=f"model_{model_id}_{model_name}"))
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i + 1])
        else:
            markup.add(buttons[i])
    bot.answer_callback_query(call.id)
    bot.edit_message_text("اختر النموذج المطلوب:", call.message.chat.id, call.message.message_id, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "info")
def info_callback(call):
    user_id = call.from_user.id
    current_model = user_data.get(user_id, {}).get('model_name', 'Seedance 1.5 Pro')
    bot.answer_callback_query(call.id)
    bot.edit_message_text(f"📊 معلومات البوت:\n\n🎬 النموذج الحالي: {current_model}\n📝 عدد النماذج المتاحة: {len(MODELS)}\n\nكيفية الاستخدام:\n1️⃣ اختر النموذج المطلوب\n2️⃣ ارفع الصورة\n3️⃣ أدخل النص التوضيحي (Prompt)\n4️⃣ انتظر معالجة الفيديو\n\nتم التطوير بواسطة: @LL_php", call.message.chat.id, call.message.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("model_"))
def model_callback(call):
    user_id = call.from_user.id
    parts = call.data.split("_", 2)
    model_id = parts[1]
    model_name = parts[2]
    if user_id not in user_data:
        user_data[user_id] = {'api': PixWithAI()}
    user_data[user_id]['model_id'] = model_id
    user_data[user_id]['model_name'] = model_name
    bot.answer_callback_query(call.id, f"تم اختيار: {model_name}")
    bot.edit_message_text(f"✅ تم اختيار النموذج: {model_name}\nID: {model_id}\n\nالآن يمكنك رفع صورة لإنشاء الفيديو.", call.message.chat.id, call.message.message_id)


@bot.message_handler(content_types=['photo'])
def process_image(message):
    user_id = message.from_user.id
    if user_id not in user_data:
        user_data[user_id] = {'api': PixWithAI(), 'model_id': '3-38', 'model_name': 'Seedance 1.5 Pro'}
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        user_data[user_id]['image_data'] = downloaded_file
        user_data[user_id]['filename'] = f"temp_{user_id}.jpg"
        bot.send_message(message.chat.id, "تم استلام الصورة ✅\n\nالآن أرسل النص التوضيحي (Prompt) للفيديو:\n(أو أرسل '-' إذا لم ترغب بإضافة نص)")
        bot.register_next_step_handler(message, process_prompt)
    except:
        pass


def process_prompt(message):
    user_id = message.from_user.id
    if user_id not in user_data or 'image_data' not in user_data[user_id]:
        return
    prompt = message.text if message.text != '-' else ""
    api = user_data[user_id]['api']
    image_data = user_data[user_id]['image_data']
    filename = user_data[user_id]['filename']
    model_id = user_data[user_id]['model_id']
    model_name = user_data[user_id]['model_name']
    processing_msg = bot.send_message(message.chat.id, f"🔄 جاري المعالجة...\n\nالنموذج: {model_name}\nالنص: {prompt if prompt else 'بدون نص'}")
    try:
        upload_res = api.get_upload_url(filename)
        if not upload_res.get("code") in [0, 1]:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            return
        bot.edit_message_text(f"📤 جاري رفع الصورة...\n\nالنموذج: {model_name}", message.chat.id, processing_msg.message_id)
        image_key = api.upload_image(upload_res, image_data, filename)
        if not image_key:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            return
        bot.edit_message_text(f"🎬 جاري إنشاء الفيديو...\n\nالنموذج: {model_name}", message.chat.id, processing_msg.message_id)
        video_res = api.create_video(image_key, prompt, model_id)
        if not video_res.get("code") in [0, 1]:
            bot.delete_message(message.chat.id, processing_msg.message_id)
            return
        for i in range(30):
            bot.edit_message_text(f"⏳ جاري المعالجة... ({i+1}/30)\n\nالنموذج: {model_name}\nالرجاء الانتظار...", message.chat.id, processing_msg.message_id)
            time.sleep(10)
            history = api.get_history()
            items = history.get("data", {}).get("items", [])
            if items:
                latest = items[0]
                if latest.get("status") == 2:
                    for result in latest.get('result_urls', []):
                        if not result.get('is_input', True):
                            video_url = result.get('hd')
                            bot.edit_message_text(f"📥 جاري تحميل الفيديو...\n\nالنموذج: {model_name}", message.chat.id, processing_msg.message_id)
                            video_response = requests.get(video_url, timeout=120)
                            if video_response.status_code == 200:
                                bot.delete_message(message.chat.id, processing_msg.message_id)
                                video_file = BytesIO(video_response.content)
                                video_file.name = 'video.mp4'
                                bot.send_video(message.chat.id, video_file, caption=f"✅ تم إنشاء الفيديو بنجاح\n\nالنموذج: {model_name}\n{f'النص: {prompt}' if prompt else ''}", supports_streaming=True)
                                del user_data[user_id]['image_data']
                                return
                            else:
                                bot.delete_message(message.chat.id, processing_msg.message_id)
                                return
                elif latest.get("status") == 3:
                    bot.delete_message(message.chat.id, processing_msg.message_id)
                    return
        bot.edit_message_text("انتهت مهلة الانتظار الرجاء المحاولة مرة أخرى", message.chat.id, processing_msg.message_id)
    except:
        try:
            bot.delete_message(message.chat.id, processing_msg.message_id)
        except:
            pass
    finally:
        if user_id in user_data and 'image_data' in user_data[user_id]:
            del user_data[user_id]['image_data']


if __name__ == "__main__":
    print("√")
    bot.infinity_polling()