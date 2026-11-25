import requests
import json
# شرح ai مني
# ========== الإعدادات ==========
PROXY_API = "http://178.238.226.8:8080/proxy"   # API البروكسي الخاص بنا
TARGET_URL = "https://caller-uegx.vercel.app/api/v1/search"  # الرابط الأصلي
# =============================

phone = input("📱 أدخل رقم الهاتف: ")

payload = {
    "phone": phone,
}

headers = {
    'User-Agent': "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Mobile Safari/537.36",
 #   'Accept-Encoding': "gzip, deflate, br, zstd",
    'Content-Type': "application/json",
    'sec-ch-ua-platform': "\"Android\"",
    'sec-ch-ua': "\"Google Chrome\";v=\"149\", \"Chromium\";v=\"149\", \"Not)A;Brand\";v=\"24\"",
    'sec-ch-ua-mobile': "?1",
    'origin': "https://caller-uegx.vercel.app",
    'sec-fetch-site': "same-origin",
    'sec-fetch-mode': "cors",
    'sec-fetch-dest': "empty",
    'referer': "https://caller-uegx.vercel.app/",
    'accept-language': "ar-IQ,ar;q=0.9,en-US;q=0.8,en;q=0.7",
    'priority': "u=1, i",
}

try:
    # إرسال طلب POST إلى API البروكسي مع تمرير الرابط الأصلي في ?url=
    response = requests.post(
        PROXY_API,
        params={"url": TARGET_URL},   # الرابط المستهدف
        data=json.dumps(payload),     # الجسم (JSON)
        headers=headers,              # الترويسات (ستنتقل إلى الموقع الأصلي)
        timeout=20
    )

    # التحقق من تجاوز الحد (429)
    if response.status_code == 429:
        print("❌ تم تجاوز الحد المسموح (50 طلب/5 دقائق).")
        print("   راسل الأدمن للاشتراك: https://t.me/Q_B_H")
        exit(1)

    # التحقق من أخطاء HTTP أخرى
    response.raise_for_status()

    # عرض الرد القادم من الخدمة
    data = response.json()
    print("\n✅ تم جلب البيانات عبر البروكسي:")
    print(json.dumps(data, indent=2, ensure_ascii=False))

except requests.exceptions.HTTPError as e:
    print(f"❌ خطأ في استجابة الموقع: {e}")
except requests.exceptions.RequestException as e:
    print(f"❌ فشل الاتصال: {e}")
except ValueError:
    print("❌ الرد ليس بصيغة JSON.")