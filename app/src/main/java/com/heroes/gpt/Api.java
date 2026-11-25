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
        String base = p.base.trim();
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        String url = base.endsWith("/chat/completions") ? base : base + "/chat/completions";

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
            throw new Exception("HTTP " + code + " — " + trim(response));
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
