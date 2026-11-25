package com.heroes.gpt;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.List;

public class Api {

    public static String chat(Provider p, String system, String userContent) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                return chatOnce(p, system, userContent);
            } catch (Exception e) {
                String m = String.valueOf(e.getMessage());
                boolean retryable = m.contains("HTTP 429") || m.contains("HTTP 402")
                        || m.contains("HTTP 500") || m.contains("HTTP 502")
                        || m.contains("HTTP 503") || m.contains("HTTP 504");
                last = e;
                if (!retryable || attempt == 2) break;
                long wait = retryAfterMs(m);
                try { Thread.sleep(wait); } catch (InterruptedException ie) { }
            }
        }
        throw last;
    }

    private static long retryAfterMs(String msg) {
        try {
            int i = msg.indexOf("Retry after ");
            if (i >= 0) {
                int j = i + "Retry after ".length();
                StringBuilder n = new StringBuilder();
                while (j < msg.length() && Character.isDigit(msg.charAt(j))) { n.append(msg.charAt(j)); j++; }
                int sec = Integer.parseInt(n.toString());
                return Math.min(sec + 1, 50) * 1000L;
            }
        } catch (Exception ignored) { }
        return 3000L;
    }

    private static String chatOnce(Provider p, String system, String userContent) throws Exception {
        String base = p.base.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        String url = base.endsWith("/chat/completions") ? base : base + "/chat/completions";
        boolean isPollinations = base.contains("pollinations.ai");
        if (isPollinations) url += (url.contains("?") ? "&" : "?") + "referrer=heroesgpt";

        JSONObject body = new JSONObject();
        body.put("model", p.model.trim());
        JSONArray msgs = new JSONArray();
        if (system != null && !system.trim().isEmpty()) {
            JSONObject s = new JSONObject();
            s.put("role", "system");
            s.put("content", system.trim());
            msgs.put(s);
        }
        JSONObject u = new JSONObject();
        u.put("role", "user");
        u.put("content", userContent);
        msgs.put(u);
        body.put("messages", msgs);

        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        conn.setRequestMethod("POST");
        conn.setConnectTimeout(30000);
        conn.setReadTimeout(180000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("User-Agent", "HeroesGPT/5.1 (Android)");
        if (isPollinations) conn.setRequestProperty("Referer", "https://github.com/m777m44/HeroesGPT");
        if (!p.noKeyNeeded && p.key != null && !p.key.trim().isEmpty()) {
            conn.setRequestProperty("Authorization", "Bearer " + p.key.trim());
        }

        byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
        OutputStream out = conn.getOutputStream();
        out.write(payload);
        out.close();

        int code = conn.getResponseCode();
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        String response = read(is);
        conn.disconnect();

        if (code >= 400) {
            throw new Exception(friendly(code, response));
        }

        JSONObject res = new JSONObject(response);
        JSONArray choices = res.optJSONArray("choices");
        if (choices != null && choices.length() > 0) {
            JSONObject msg = choices.getJSONObject(0).optJSONObject("message");
            String content = msg == null ? "" : msg.optString("content", "");
            if (!content.isEmpty()) return content;
        }
        JSONObject err = res.optJSONObject("error");
        if (err != null) {
            throw new Exception(err.optString("message", "استجابة غير متوقعة"));
        }
        throw new Exception("استجابة غير متوقعة من الخادم: " + trim(response));
    }

    private static String friendly(int code, String body) {
        String b = body == null ? "" : body;
        String lc = b.toLowerCase();
        if (lc.contains("free_limit") || lc.contains("rate") || code == 429 || code == 402) {
            String w = extract(b, "Retry after ", "s");
            return "⏳ الحد المجاني للخدمة: انتظر " + (w.isEmpty() ? "ربع دقيقة" : w + " ثانية")
                    + " وحاول مجددًا. لحد أعلى مجانًا: احصل على مفتاح من enter.pollinations.ai وضعه في قسم المصادر.";
        }
        if (code == 401 || code == 403) {
            return "🔑 هذا المصدر يحتاج مفتاح API — افتح قسم «المصادر» وأضف مفتاحك. مفتاح Pollinations مجاني من enter.pollinations.ai";
        }
        if (code == 404) return "🔍 المسار أو النموذج غير موجود في هذا المصدر — تحقق من اسم النموذج في قسم «المصادر».";
        if (code >= 500) return "🛠 خادم المصدر مشغول مؤقتًا (" + code + ") — سيحاول التطبيق التبديل إلى مصدر آخر تلقائيًا.";
        return "HTTP " + code + " — " + trim(b);
    }

    private static String extract(String s, String start, String end) {
        try {
            int i = s.indexOf(start);
            if (i < 0) return "";
            int j = i + start.length();
            StringBuilder n = new StringBuilder();
            while (j < s.length() && Character.isDigit(s.charAt(j))) { n.append(s.charAt(j)); j++; }
            return n.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private static String trim(String s) {
        if (s == null) return "لا توجد تفاصيل";
        s = s.trim();
        return s.length() > 300 ? s.substring(0, 300) + "…" : s;
    }

    private static String read(InputStream is) throws Exception {
        if (is == null) return "";
        byte[] buf = new byte[8192];
        StringBuilder sb = new StringBuilder();
        int n;
        while ((n = is.read(buf)) > 0) {
            sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
        }
        is.close();
        return sb.toString();
    }
}
