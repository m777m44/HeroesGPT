import requests
import telebot
from telebot import types

BOT_TOKEN = "توكن_بوتك"
API_URL = "https://mukhtasarquran.alwaysdata.net/api.php"

bot = telebot.TeleBot(BOT_TOKEN)
user_sessions = {}


@bot.message_handler(commands=['start'])
def send_welcome(message):
    user_sessions.pop(message.chat.id, None)
    welcome_text = (
        "✨ **مرحباً بك في بوت إنشاء الصور بالذكاء الاصطناعي!**\n\n"
        "أرسل لي الوصف."
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")


@bot.message_handler(func=lambda message: True)
def handle_prompt(message):
    chat_id = message.chat.id
    user_sessions[chat_id] = {'prompt': message.text}
    markup = types.InlineKeyboardMarkup(row_width=3)
    btn1 = types.InlineKeyboardButton("1:1", callback_data="ratio_1:1")
    btn2 = types.InlineKeyboardButton("16:9", callback_data="ratio_16:9")
    btn3 = types.InlineKeyboardButton("9:16", callback_data="ratio_9:16")
    btn4 = types.InlineKeyboardButton("4:3", callback_data="ratio_4:3")
    btn5 = types.InlineKeyboardButton("3:4", callback_data="ratio_3:4")

    markup.add(btn1, btn2, btn3)
    markup.add(btn4, btn5)

    bot.send_message(
        chat_id,
        "📐 **اختر مقاس الصورة المطلوب:**",
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("ratio_"))
def handle_ratio(call):
    chat_id = call.message.chat.id
    if chat_id not in user_sessions:
        bot.answer_callback_query(call.id, "حدث خطأ، يرجى إرسال الوصف من جديد.")
        return

    ratio = call.data.split("_")[1]
    user_sessions[chat_id]['ratio'] = ratio
    markup = types.InlineKeyboardMarkup(row_width=4)
    btns = [types.InlineKeyboardButton(str(i), callback_data=f"count_{i}") for i in range(1, 5)]
    markup.add(*btns)

    bot.edit_message_text(
        "🖼️ **اختر عدد الصور المراد إنشاؤها (الحد الأقصى 4):**",
        chat_id=chat_id,
        message_id=call.message.message_id,
        reply_markup=markup,
        parse_mode="Markdown"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("count_"))
def handle_count(call):
    chat_id = call.message.chat.id
    if chat_id not in user_sessions:
        bot.answer_callback_query(call.id, "حدث خطأ، يرجى إرسال الوصف من جديد.")
        return

    count = int(call.data.split("_")[1])
    session_data = user_sessions[chat_id]
    prompt = session_data['prompt']
    ratio = session_data['ratio']
    bot.edit_message_text(
        "⏳ **جاري إنشاء الصور، يرجى الانتظار...**",
        chat_id=chat_id,
        message_id=call.message.message_id,
        parse_mode="Markdown"
    )
    try:
        payload = {
            "prompt": prompt,
            "ratio": ratio,
            "count": count
        }
        response = requests.post(API_URL, data=payload, timeout=90)
        
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("status") is True and "data" in res_json:
                image_urls = list(res_json["data"].values())
                bot.delete_message(chat_id, call.message.message_id)
                if len(image_urls) == 1:
                    bot.send_photo(chat_id, image_urls[0], caption=f"✨ **الطلب:** {prompt}")
                else:
                    media_group = [types.InputMediaPhoto(url) for url in image_urls]
                    bot.send_media_group(chat_id, media_group)
            else:
                bot.edit_message_text(
                    "❌ فشل في إنشاء الصور. حاول مرة أخرى لاحقاً.",
                    chat_id=chat_id,
                    message_id=call.message.message_id
                )
        else:
            bot.edit_message_text(
                f"❌ حدث خطأ في السيرفر (كود: {response.status_code}).",
                chat_id=chat_id,
                message_id=call.message.message_id
            )

    except Exception as e:
        bot.edit_message_text(
            "❌ حدث خطأ أثناء الاتصال بالخدمة.",
            chat_id=chat_id,
            message_id=call.message.message_id
        )
    user_sessions.pop(chat_id, None)


if __name__ == "__main__":
    print("روح شوف يعمل...")
    bot.infinity_polling(skip_pending=True)
