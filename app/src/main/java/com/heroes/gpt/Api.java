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

    public interface Live {
        void onPartial(String header, String partial);
    }

    public static String chat(Provider p, String system, String userContent) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                return chatOnce(p, system, userContent, false, null);
            } catch (Exception e) {
                String m = String.valueOf(e.getMessage() == null ? "" : e.getMessage());
                boolean httpNoRetry = m.startsWith("HTTP 401") || m.startsWith("HTTP 403")
                        || m.startsWith("HTTP 404") || m.startsWith("HTTP 400");
                boolean retryable = !httpNoRetry;
                last = retryable && !m.startsWith("HTTP") ? new Exception(friendlyNetwork(e)) : e;
                if (!retryable || attempt == 2) break;
                long wait = retryAfterMs(m);
                try { Thread.sleep(wait); } catch (InterruptedException ie) { }
            }
        }
        throw last;
    }

    public static String chatLive(Provider p, String system, String userContent, Live live)
            throws Exception {
        if (live == null) return chat(p, system, userContent);
        Exception last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            try {
                return chatOnce(p, system, userContent, true, live);
            } catch (Exception e) {
                String m = String.valueOf(e.getMessage() == null ? "" : e.getMessage());
                boolean httpNoRetry = m.startsWith("HTTP 401") || m.startsWith("HTTP 403")
                        || m.startsWith("HTTP 404") || m.startsWith("HTTP 400");
                if (!httpNoRetry) {
                    last = m.startsWith("HTTP") ? e : new Exception(friendlyNetwork(e));
                    if (attempt == 2) break;
                    try { Thread.sleep(retryAfterMs(m)); } catch (InterruptedException ie) { }
                } else {
                    throw e;
                }
            }
        }
        last = last == null ? new Exception("فشل البث") : last;
        if (last.getMessage() != null && last.getMessage().startsWith("HTTP")) throw last;
        return chat(p, system, userContent);
    }

    private static Exception friendlyNetwork(Throwable e) {
        String m = String.valueOf(e.getMessage() == null ? e.toString() : e.getMessage());
        if (m.contains("abort") || m.contains("reset") || m.contains("ECONN")) {
            return new Exception("📶 انقطع الاتصال بالخادم أثناء التوليد — جارٍ إعادة المحاولة تلقائيًا…");
        }
        if (m.contains("timeout") || m.contains("Timeout")) {
            return new Exception("⏱ استغرق توليد الإجابة وقتًا طويلًا — جارٍ إعادة المحاولة…");
        }
        return new Exception("⚠️ ضعف شبكة مؤقت — جارٍ إعادة المحاولة…");
    }

    private static volatile long lastFreePollAt = 0L;
    private static final long FREE_GAP_MS = 46000L;

    private static void waitFreeSlot() {
        long since = System.currentTimeMillis() - lastFreePollAt;
        if (since >= 0 && since < FREE_GAP_MS) {
            try {
                Thread.sleep(FREE_GAP_MS - since);
            } catch (InterruptedException ignored) { }
        }
    }

    private static void markFreeCall() {
        lastFreePollAt = System.currentTimeMillis();
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

    private static String chatOnce(Provider p, String system, String userContent,
                                   boolean stream, Live live) throws Exception {
        String base = p.base.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        String url = base.endsWith("/chat/completions") ? base : base + "/chat/completions";
        boolean isPollinations = base.contains("pollinations.ai");
        boolean freePoll = isPollinations && (p.noKeyNeeded || p.key.trim().isEmpty());
        if (isPollinations) url += (url.contains("?") ? "&" : "?") + "referrer=heroesgpt";

        JSONObject body = new JSONObject();
        body.put("model", p.model.trim());
        if (stream) body.put("stream", true);
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
        conn.setReadTimeout(240000);
        conn.setDoOutput(true);
        conn.setRequestProperty("Content-Type", "application/json");
        conn.setRequestProperty("User-Agent", "HeroesGPT/6.0 (Android)");
        if (isPollinations) conn.setRequestProperty("Referer", "https://github.com/m777m44/HeroesGPT");
        if (!p.noKeyNeeded && p.key != null && !p.key.trim().isEmpty()) {
            conn.setRequestProperty("Authorization", "Bearer " + p.key.trim());
        }

        if (freePoll) waitFreeSlot();
        byte[] payload = body.toString().getBytes(StandardCharsets.UTF_8);
        OutputStream out = conn.getOutputStream();
        out.write(payload);
        out.close();

        if (freePoll) markFreeCall();
        int code = conn.getResponseCode();
        InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        String serverType = conn.getHeaderField("Content-Type");

        if (stream && code < 400 && serverType != null && serverType.contains("text/event-stream")) {
            String text = readStreaming(is, live);
            conn.disconnect();
            if (text.isEmpty()) throw new Exception("استجابة بث فارغة");
            return text;
        }
        String response = read(is);
        conn.disconnect();

        if (code >= 400) {
            throw new Exception(friendly(code, response));
        }

        JSONObject res = new JSONObject(response);
        JSONArray choices = res.optJSONArray("choices");
        if (choices != null && choices.length() > 0) {
            String content = extractChoiceContent(choices.getJSONObject(0));
            if (!content.isEmpty()) {
                if (live != null) live.onPartial("", content);
                return content;
            }
        }
        JSONObject err = res.optJSONObject("error");
        if (err != null) {
            throw new Exception(err.optString("message", "استجابة غير متوقعة"));
        }
        throw new Exception("استجابة غير متوقعة من الخادم: " + trim(response));
    }

    private static String extractChoiceContent(JSONObject choice) {
        JSONObject msg = choice.optJSONObject("message");
        String content = msg == null ? "" : msg.optString("content", "");
        if (content.isEmpty()) content = choice.optString("text", "");
        return content;
    }

    private static final long EMIT_GAP_MS = 110L;

    private static String readStreaming(InputStream is, Live live) throws Exception {
        byte[] buf = new byte[8192];
        StringBuilder raw = new StringBuilder();
        StringBuilder text = new StringBuilder();
        long lastEmit = 0;
        int n;
        while ((n = is.read(buf)) > 0) {
            raw.append(new String(buf, 0, n, StandardCharsets.UTF_8));
            int sep;
            while ((sep = raw.indexOf("\n")) >= 0) {
                String line = raw.substring(0, sep).trim();
                raw.delete(0, sep + 1);
                if (line.isEmpty() || !line.startsWith("data:")) continue;
                String data = line.substring(5).trim();
                if (data.equals("[DONE]")) {
                    if (live != null && text.length() > 0) {
                        live.onPartial("", text.toString());
                    }
                    is.close();
                    return text.toString();
                }
                try {
                    JSONObject o = new JSONObject(data);
                    JSONArray choices = o.optJSONArray("choices");
                    if (choices == null || choices.length() == 0) continue;
                    JSONObject c0 = choices.getJSONObject(0);
                    JSONObject delta = c0.optJSONObject("delta");
                    if (delta != null) {
                        text.append(delta.optString("content", ""));
                    } else {
                        String inline = extractChoiceContent(c0);
                        if (!inline.isEmpty()) text.append(inline);
                    }
                } catch (Exception ignored) {
                }
                long now = System.currentTimeMillis();
                if (live != null && text.length() > 0 && now - lastEmit > EMIT_GAP_MS) {
                    lastEmit = now;
                    live.onPartial("", text.toString());
                }
            }
        }
        is.close();
        return text.toString();
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
