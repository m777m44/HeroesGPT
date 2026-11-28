package com.heroes.gpt;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * واجهة موحدة لكل محركات البحث — SearchEngine.search(query): Result
 * المدعومة: Brave، Serper، Tavily، Google CSE، Bing، DuckDuckGo، SearXNG، Exa، Perplexity.
 * المفاتيح تُقرأ من KeyConfig (keys.json / الإعدادات المحلية) — لا مفاتيح في الشيفرة.
 */
public class SearchEngines {

    public static class Result {
        public String title = "";
        public String url = "";
        public String snippet = "";
        public String engine = "";
    }

    /** كتالوج المحركات: {id, label, keyId (فارغ = يعمل بلا مفتاح)} */
    public static final String[][] ENGINES = {
            {"all", "الكل", ""},
            {"duckduckgo", "DuckDuckGo", ""},
            {"searxng", "SearXNG", "searxng_url"},
            {"brave", "Brave", "brave"},
            {"serper", "Serper", "serper"},
            {"tavily", "Tavily", "tavily"},
            {"google_cse", "Google CSE", "google_cse_key"},
            {"bing", "Bing", "bing"},
            {"exa", "Exa", "exa"},
            {"perplexity", "Perplexity", "perplexity"},
    };

    public static String labelOf(String id) {
        for (String[] e : ENGINES) if (e[0].equals(id)) return e[1];
        return id;
    }

    public static String keyIdOf(String id) {
        for (String[] e : ENGINES) if (e[0].equals(id)) return e[2];
        return "";
    }

    public static boolean needsKey(String id) {
        return !keyIdOf(id).isEmpty();
    }

    public static boolean isReady(Context c, String id) {
        if (!needsKey(id)) return true;
        return KeyConfig.connected(c, keyIdOf(id));
    }

    /** البحث الموحد — يدعم "all" لدمج نتائج كل المحركات المتصلة. */
    public static List<Result> search(Context c, String engineId, String query) throws Exception {
        if ("all".equals(engineId)) return searchAll(c, query);
        return searchOne(c, engineId, query);
    }

    private static List<Result> searchAll(Context c, String query) {
        List<Result> out = new ArrayList<>();
        StringBuilder errs = new StringBuilder();
        for (String[] e : ENGINES) {
            String id = e[0];
            if ("all".equals(id)) continue;
            if (!isReady(c, id)) continue;
            try {
                List<Result> rs = searchOne(c, id, query);
                if (rs != null) {
                    for (Result r : rs) {
                        if (out.size() >= 30) break;
                        r.engine = labelOf(id);
                        out.add(r);
                    }
                }
            } catch (Exception ex) {
                errs.append(labelOf(id)).append(": ")
                        .append(ex.getMessage() == null ? "خطأ" : ex.getMessage()).append(" • ");
            }
        }
        if (out.isEmpty() && errs.length() > 0) {
            Result r = new Result();
            r.title = "⚠️ لم ينجح أي محرك بحث";
            r.snippet = errs.toString().replaceAll(" • $", "");
            out.add(r);
        }
        return out;
    }

    private static List<Result> searchOne(Context c, String engineId, String query) throws Exception {
        switch (engineId) {
            case "duckduckgo": return ddg(query);
            case "searxng": return searxng(c, query);
            case "brave": return brave(c, query);
            case "serper": return serper(c, query);
            case "tavily": return tavily(c, query);
            case "google_cse": return googleCse(c, query);
            case "bing": return bing(c, query);
            case "exa": return exa(c, query);
            case "perplexity": return perplexity(c, query);
            default: throw new Exception("محرك غير معروف: " + engineId);
        }
    }

    // ===== DuckDuckGo (بلا مفتاح — Instant Answer API) =====
    private static List<Result> ddg(String query) throws Exception {
        String url = "https://api.duckduckgo.com/?q="
                + URLEncoder.encode(query, "UTF-8") + "&format=json&no_html=1&skip_disambig=1";
        JSONObject o = new JSONObject(httpGet(url, null));
        List<Result> out = new ArrayList<>();
        String at = o.optString("AbstractText", "").trim();
        if (!at.isEmpty()) {
            Result r = new Result();
            r.title = o.optString("Heading", query);
            r.url = o.optString("AbstractURL", "https://duckduckgo.com/?q=" + URLEncoder.encode(query, "UTF-8"));
            r.snippet = at;
            r.engine = "DuckDuckGo";
            out.add(r);
        }
        collectTopics(o.optJSONArray("RelatedTopics"), out, query);
        if (out.isEmpty()) {
            Result r = new Result();
            r.title = "لا نتائج مباشرة";
            r.url = "https://duckduckgo.com/?q=" + URLEncoder.encode(query, "UTF-8");
            r.snippet = "DuckDuckGo Instant Answer لم يجد نتيجة مباشرة — افتح الرابط للبحث الكامل على الويب.";
            r.engine = "DuckDuckGo";
            out.add(r);
        }
        return out;
    }

    private static void collectTopics(JSONArray arr, List<Result> out, String query) {
        if (arr == null) return;
        for (int i = 0; i < arr.length() && out.size() < 12; i++) {
            try {
                JSONObject t = arr.getJSONObject(i);
                if (t.has("Topics")) {
                    collectTopics(t.getJSONArray("Topics"), out, query);
                    continue;
                }
                String text = t.optString("Text", "").trim();
                String url = t.optString("FirstURL", "").trim();
                if (text.isEmpty() || url.isEmpty()) continue;
                Result r = new Result();
                r.title = text.contains(" - ") ? text.substring(0, text.indexOf(" - ")) : ("نتيجة " + (i + 1));
                if (r.title.length() > 70) r.title = r.title.substring(0, 70) + "…";
                r.url = url;
                r.snippet = text;
                r.engine = "DuckDuckGo";
                out.add(r);
            } catch (Exception ignored) { }
        }
    }

    // ===== SearXNG (بلا مفتاح — مثيل عام أو خاص) =====
    private static List<Result> searxng(Context c, String query) throws Exception {
        String base = KeyConfig.key(c, "searxng_url");
        if (base.isEmpty()) base = "https://searx.be";
        base = base.endsWith("/") ? base.substring(0, base.length() - 1) : base;
        String url = base + "/search?q=" + URLEncoder.encode(query, "UTF-8") + "&format=json";
        JSONObject o = new JSONObject(httpGet(url, null));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONArray("results");
        if (rs != null) {
            for (int i = 0; i < rs.length() && out.size() < 15; i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("url", "");
                r.snippet = r0.optString("content", "");
                r.engine = "SearXNG";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Brave Search =====
    private static List<Result> brave(Context c, String query) throws Exception {
        String key = require(c, "brave", "Brave");
        String url = "https://api.search.brave.com/res/v1/web/search?q="
                + URLEncoder.encode(query, "UTF-8") + "&count=10";
        String[][] headers = {{"X-Subscription-Token", key}, {"Accept", "application/json"}};
        JSONObject o = new JSONObject(httpGet(url, headers));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONObject("web") == null ? null : o.getJSONObject("web").optJSONArray("results");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("url", "");
                r.snippet = r0.optString("description", "");
                r.engine = "Brave";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Serper.dev =====
    private static List<Result> serper(Context c, String query) throws Exception {
        String key = require(c, "serper", "Serper");
        JSONObject body = new JSONObject().put("q", query).put("num", 10);
        String[][] headers = {{"X-API-KEY", key}};
        JSONObject o = new JSONObject(httpJson("https://google.serper.dev/v1/search", "POST", body, headers));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONArray("organic");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("link", "");
                r.snippet = r0.optString("snippet", "");
                r.engine = "Serper";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Tavily =====
    private static List<Result> tavily(Context c, String query) throws Exception {
        String key = require(c, "tavily", "Tavily");
        JSONObject body = new JSONObject().put("api_key", key).put("query", query)
                .put("max_results", 10).put("search_depth", "basic");
        JSONObject o = new JSONObject(httpJson("https://api.tavily.com/search", "POST", body, null));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONArray("results");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("url", "");
                r.snippet = r0.optString("content", "");
                r.engine = "Tavily";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Google Programmable Search (CSE) =====
    private static List<Result> googleCse(Context c, String query) throws Exception {
        String key = require(c, "google_cse_key", "Google CSE");
        String cx = require(c, "google_cse_cx", "Google CSE");
        String url = "https://www.googleapis.com/customsearch/v1?key=" + URLEncoder.encode(key, "UTF-8")
                + "&cx=" + URLEncoder.encode(cx, "UTF-8")
                + "&q=" + URLEncoder.encode(query, "UTF-8") + "&num=10";
        JSONObject o = new JSONObject(httpGet(url, null));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONArray("items");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("link", "");
                r.snippet = r0.optString("snippet", "");
                r.engine = "Google CSE";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Bing Web Search =====
    private static List<Result> bing(Context c, String query) throws Exception {
        String key = require(c, "bing", "Bing");
        String url = "https://api.bing.microsoft.com/v7.0/search?q="
                + URLEncoder.encode(query, "UTF-8") + "&count=10";
        String[][] headers = {{"Ocp-Apim-Subscription-Key", key}};
        JSONObject o = new JSONObject(httpGet(url, headers));
        List<Result> out = new ArrayList<>();
        JSONObject wp = o.optJSONObject("webPages");
        JSONArray rs = wp == null ? null : wp.optJSONArray("value");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("name", "نتيجة " + (i + 1));
                r.url = r0.optString("url", "");
                r.snippet = r0.optString("snippet", "");
                r.engine = "Bing";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Exa.ai =====
    private static List<Result> exa(Context c, String query) throws Exception {
        String key = require(c, "exa", "Exa");
        JSONObject body = new JSONObject().put("query", query).put("numResults", 10)
                .put("contents", new JSONObject().put("text", true).put("text", new JSONObject().put("maxCharacters", 300)));
        String[][] headers = {{"x-api-key", key}};
        JSONObject o = new JSONObject(httpJson("https://api.exa.ai/search", "POST", body, headers));
        List<Result> out = new ArrayList<>();
        JSONArray rs = o.optJSONArray("results");
        if (rs != null) {
            for (int i = 0; i < rs.length(); i++) {
                JSONObject r0 = rs.getJSONObject(i);
                Result r = new Result();
                r.title = r0.optString("title", "نتيجة " + (i + 1));
                r.url = r0.optString("url", "");
                String txt = r0.optString("text", r0.optString("snippet", ""));
                r.snippet = txt.length() > 300 ? txt.substring(0, 300) + "…" : txt;
                r.engine = "Exa";
                if (!r.url.isEmpty()) out.add(r);
            }
        }
        return out;
    }

    // ===== Perplexity (بحث + إجابة) =====
    private static List<Result> perplexity(Context c, String query) throws Exception {
        String key = require(c, "perplexity", "Perplexity");
        JSONObject msg = new JSONObject().put("role", "user")
                .put("content", "ابحث عن: " + query + " — أجب مختصرًا مع المصادر.");
        JSONObject body = new JSONObject().put("model", "sonar")
                .put("messages", new JSONArray().put(msg));
        String[][] headers = {{"Authorization", "Bearer " + key}};
        JSONObject o = new JSONObject(httpJson("https://api.perplexity.ai/chat/completions", "POST", body, headers));
        List<Result> out = new ArrayList<>();
        String answer = o.optJSONArray("choices") != null
                ? o.getJSONArray("choices").getJSONObject(0).optJSONObject("message").optString("content", "")
                : "";
        if (!answer.isEmpty()) {
            Result r = new Result();
            r.title = "💬 إجابة Perplexity: " + (query.length() > 50 ? query.substring(0, 50) + "…" : query);
            r.url = "https://www.perplexity.ai/search?q=" + URLEncoder.encode(query, "UTF-8");
            r.snippet = answer;
            r.engine = "Perplexity";
            out.add(r);
        }
        return out;
    }

    private static String require(Context c, String keyId, String label) throws Exception {
        String k = KeyConfig.key(c, keyId);
        if (k.isEmpty()) throw new Exception("مفتاح " + label + " غير متصل — أضفه في keys.json أو شاشة المفاتيح");
        return k;
    }

    // ===== HTTP helpers =====
    private static String httpGet(String url, String[][] headers) throws Exception {
        return httpRaw(url, "GET", null, headers);
    }

    private static String httpJson(String url, String method, JSONObject body, String[][] headers) throws Exception {
        return httpRaw(url, method, body == null ? null : body.toString(), headers);
    }

    private static String httpRaw(String urlStr, String method, String body, String[][] headers) throws Exception {
        HttpURLConnection con = (HttpURLConnection) new URL(urlStr).openConnection();
        con.setConnectTimeout(15000);
        con.setReadTimeout(20000);
        con.setRequestMethod(method);
        con.setRequestProperty("User-Agent", "HeroesGPT/8.0");
        con.setRequestProperty("Accept", "application/json");
        if (headers != null) for (String[] h : headers) con.setRequestProperty(h[0], h[1]);
        if (body != null) {
            con.setDoOutput(true);
            con.setRequestProperty("Content-Type", "application/json");
            OutputStream os = con.getOutputStream();
            os.write(body.getBytes(StandardCharsets.UTF_8));
            os.close();
        }
        int code = con.getResponseCode();
        InputStream in = code >= 400 ? con.getErrorStream() : con.getInputStream();
        ByteArrayOutputStream bo = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        if (in != null) while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
        if (in != null) in.close();
        String resp = new String(bo.toByteArray(), StandardCharsets.UTF_8);
        if (code >= 400) {
            String shortMsg = resp.length() > 180 ? resp.substring(0, 180) + "…" : resp;
            throw new Exception("HTTP " + code + (shortMsg.isEmpty() ? "" : " — " + shortMsg));
        }
        return resp;
    }
}
