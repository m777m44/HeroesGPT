package com.heroes.gpt;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public class Hero {
    public String id;
    public String emoji;
    public String name;
    public String system;
    public boolean enabled = true;
    public String providerId = "auto";
    public int order;

    public JSONObject toJson() throws Exception {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("emoji", emoji);
        o.put("name", name);
        o.put("system", system);
        o.put("enabled", enabled);
        o.put("providerId", providerId);
        o.put("order", order);
        return o;
    }

    public static Hero fromJson(JSONObject o) {
        Hero h = new Hero();
        h.id = o.optString("id");
        h.emoji = o.optString("emoji", "⚡");
        h.name = o.optString("name", "بطل");
        h.system = o.optString("system", "");
        h.enabled = o.optBoolean("enabled", true);
        h.providerId = o.optString("providerId", "auto");
        h.order = o.optInt("order", 0);
        return h;
    }

    public static Hero make(String emoji, String name, String system) {
        Hero h = new Hero();
        h.id = "h" + System.nanoTime();
        h.emoji = emoji;
        h.name = name;
        h.system = system;
        return h;
    }

    public static List<Hero> defaults() {
        List<Hero> list = new ArrayList<>();
        list.add(Hero.make("🪄", "مهندس البرومبت",
                "أنت مهندس برومبت خبير في فريق الأبطال. مهمتك تحويل فكرة المستخدم البسيطة إلى موجّه (prompt) احترافي كامل: الدور المطلوب، السياق، المخرجات المحددة، القيود، ومعايير الجودة. اكتب الموجه النهائي فقط بشكل منظم وبالعربية، ثم مترجمًا إلى صيغة جاهزة للتنفيذ."));
        list.add(Hero.make("🧭", "المحلل",
                "أنت محلل خبير في فريق الأبطال. تدرس الهدف والموجّه الذي أنجزه من سبقوك، وتحلل المتطلبات والجمهور والبدائل والمخاطر والفرص. أنتج تحليلًا واضحًا من نقاط قصيرة، وتنتهي بأهم 3 توصيات."));
        list.add(Hero.make("🗺️", "المخطط",
                "أنت مخطط تنفيذي خبير. تحوّل التحليل إلى خطة عمل مرقمة خطوة بخطوة، مع توزيع الوقت التقديري والناتج المتوقع من كل خطوة. خطتك يجب أن تكون قابلة للتنفيذ مباشرة."));
        list.add(Hero.make("✍️", "الكاتب",
                "أنت كاتب محترف متعدد الأساليب. تأخذ الخطة وتنتج المحتوى النهائي بجودة عالية وبدون حشو: نصوص جاهزة للنشر بأسلوب مؤثر ومناسب لجمهور المشروع."));
        list.add(Hero.make("🏗️", "الباني",
                "أنت مهندس برمجيات أول (Senior) في الفريق. تأخذ الخطة وتبني المنتج الفعلي: كود كامل قابل للتشغيل أو المخرجات التقنية المطلوبة، مع شرح موجز للبنية. اكتب كودًا نظيفًا حديثًا ومباشرًا."));
        list.add(Hero.make("🎨", "المصمم",
                "أنت مدير تصميم. تراجع مخرجات الباني من ناحية الهوية البصرية وتجربة المستخدم والإحساس المهيب، وتعطي توجيهات تصميم محددة قابلة للتطبيق (ألوان، مسافات، حركة، نبرة النصوص)."));
        list.add(Hero.make("🧪", "المجرّب",
                "أنت مهندس اختبار. تفحص مخرجات الفريق وتبني قائمة اختبارات تكتشف الأخطاء والثغرات، وتكتب النتائج المتوقعة. اذكر أي خطأ حقيقي وجدته بوضوح مع موقعه."));
        list.add(Hero.make("🔧", "المصلّح",
                "أنت مهندس إصلاح. تأخذ الأخطاء التي وجدها المجرّب في السجل وتنتج الإصلاح الدقيق لكل خطأ: ما تم تغييره ولماذا، مع النسخة المعدلة النهائية."));
        list.add(Hero.make("🔍", "المدقّق",
                "أنت مدقّق جودة صارم. تدقق كل جزء من مخرجات الفريق: الدقة، الاتساق، الاكتمال، والجودة. أعطِ كل عنصر تقييمًا من 10 مع مبرر موجز، ولا تمرر أي ضعف دون ملاحظة."));
        list.add(Hero.make("💡", "المستشار التنفيذي",
                "أنت المستشار التنفيذي للفريق، ودورك الأخير قبل التسليم. تلخص أعمال الفريق كلها في تقرير تسليم نهائي أنيق: ما تم إنجازه، القرارات المهمة، توصيات التطوير القادمة، والمخاطر المتبقية."));
        return list;
    }

    public static JSONArray toJsonArray(List<Hero> heroes) throws Exception {
        JSONArray a = new JSONArray();
        for (Hero h : heroes) a.put(h.toJson());
        return a;
    }

    public static List<Hero> fromJsonArray(JSONArray a) {
        List<Hero> out = new ArrayList<>();
        for (int i = 0; i < a.length(); i++) out.add(Hero.fromJson(a.optJSONObject(i)));
        return out;
    }
}
