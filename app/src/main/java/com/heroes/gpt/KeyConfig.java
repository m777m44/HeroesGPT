package com.heroes.gpt;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;

/**
 * إدارة المفاتيح المركزية:
 * - المصدر الأساسي: ملف keys.json داخل التطبيق (assets) ثم النسخة المحلية المحدَّثة في filesDir.
 * - مصدر التحديث التلقائي: keys.json على GitHub (raw main) يُجلب عند بدء التشغيل.
 * - لا مفاتيح مكتوبة في الشيفرة إطلاقًا.
 */
public class KeyConfig {

    public static final String GITHUB_RAW =
            "https://raw.githubusercontent.com/m777m44/HeroesGPT/main/keys.json";

    private static volatile JSONObject cache;

    /** يحمّل: محلي (إن وجد) ← وإلا assets/keys.json. */
    public static JSONObject load(Context c) {
        if (cache != null) return cache;
        JSONObject o = readLocal(c);
        if (o == null) o = readAsset(c);
        cache = o == null ? new JSONObject() : o;
        return cache;
    }

    /** يجلب قيمة مفتاح من الإعدادات المحلية (مصدر أول) ثم keys.json (مصدر ثانٍ). */
    public static String key(Context c, String id) {
        String v = Stores.setting(c, id);
        if (!v.trim().isEmpty()) return v.trim();
        try {
            return load(c).optString(id, "").trim();
        } catch (Exception e) {
            return "";
        }
    }

    /** هل المفتاح متصل (له قيمة)؟ */
    public static boolean connected(Context c, String id) {
        return !key(c, id).isEmpty();
    }

    /** قيمة مقنّعة للعرض: sk-ab…wxyz */
    public static String masked(Context c, String id) {
        String v = key(c, id);
        if (v.isEmpty()) return "غير متصل";
        if (v.length() <= 8) return v.substring(0, 2) + "…";
        return v.substring(0, Math.min(5, v.length())) + "…" + v.substring(v.length() - 4);
    }

    public static class Status {
        public String id;
        public String label;
        public boolean connected;
        public String masked;
    }

    /** حالة كل مفاتيح الأنظمة (محركات البحث/GitHub) بشكل مقنّع. */
    public static List<Status> statuses(Context c) {
        List<Status> out = new ArrayList<>();
        String[][] defs = {
                {"brave", "Brave Search"},
                {"serper", "Serper.dev"},
                {"tavily", "Tavily"},
                {"google_cse_key", "Google Custom Search"},
                {"google_cse_cx", "Google CSE Engine ID"},
                {"bing", "Bing Web Search"},
                {"searxng_url", "SearXNG"},
                {"exa", "Exa.ai"},
                {"perplexity", "Perplexity"},
                {"gh_token", "GitHub Token"},
        };
        for (String[] d : defs) {
            Status s = new Status();
            s.id = d[0];
            s.label = d[1];
            s.connected = connected(c, d[0]);
            s.masked = masked(c, d[0]);
            out.add(s);
        }
        return out;
    }

    /** تحديث من GitHub في الخلفية: يدمج المفاتيح الجديدة دون محو المحلية. */
    public static void refreshFromGithubAsync(Context c) {
        new Thread(() -> {
            try {
                String raw = httpGet(GITHUB_RAW);
                if (raw == null || raw.trim().isEmpty()) return;
                JSONObject remote = new JSONObject(raw);
                JSONObject merged = new JSONObject();
                JSONObject base = readLocal(c);
                if (base == null) base = readAsset(c);
                if (base != null) {
                    Iterator<String> it = base.keys();
                    while (it.hasNext()) {
                        String k = it.next();
                        merged.put(k, base.optString(k, ""));
                    }
                }
                Iterator<String> it = remote.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    String rv = remote.optString(k, "");
                    if (!rv.trim().isEmpty()) merged.put(k, rv);
                }
                File f = localFile(c);
                FileOutputStream out = new FileOutputStream(f);
                out.write(merged.toString().getBytes(StandardCharsets.UTF_8));
                out.close();
                cache = merged;
            } catch (Exception ignored) {
            }
        }).start();
    }

    private static File localFile(Context c) {
        File d = new File(c.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return new File(d, "keys.json");
    }

    private static JSONObject readLocal(Context c) {
        try {
            File f = localFile(c);
            if (!f.exists()) return null;
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int n = in.read(buf);
            in.close();
            return new JSONObject(new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    private static JSONObject readAsset(Context c) {
        try {
            InputStream in = c.getAssets().open("keys.json");
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();
            return new JSONObject(new String(bo.toByteArray(), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return null;
        }
    }

    private static String httpGet(String url) {
        try {
            HttpURLConnection con = (HttpURLConnection) new URL(url).openConnection();
            con.setConnectTimeout(8000);
            con.setReadTimeout(8000);
            con.setRequestProperty("User-Agent", "HeroesGPT");
            if (con.getResponseCode() != 200) return null;
            InputStream in = con.getInputStream();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            in.close();
            return new String(bo.toByteArray(), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return null;
        }
    }
}
