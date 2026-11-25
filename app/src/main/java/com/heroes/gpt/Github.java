package com.heroes.gpt;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;

public class Github {

    public static final String API = "https://api.github.com";
    public static final String CONFIG_URL = "https://github.com/settings/tokens";

    public static class Repo {
        public String fullName;
        public String description;
        public boolean isPrivate;
        public long stars;
    }

    public static class GFile {
        public String name;
        public String path;
        public String type;
        public long size;
    }

    public static class Entry {
        public String path;
        public String content;
    }

    public static String validateToken(String token) throws Exception {
        JSONObject u = new JSONObject(get("/user", token, 200));
        return u.optString("login", "");
    }

    public static List<Repo> myRepos(String token) throws Exception {
        List<Repo> out = new ArrayList<>();
        JSONArray a = new JSONArray(get("/user/repos?sort=updated&per_page=50", token, 200));
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.getJSONObject(i);
            Repo r = new Repo();
            r.fullName = o.optString("full_name", "");
            r.description = o.optString("description", "");
            r.isPrivate = o.optBoolean("private", false);
            r.stars = o.optLong("stargazers_count", 0);
            if (!r.fullName.isEmpty()) out.add(r);
        }
        return out;
    }

    public static String createRepo(String token, String name, String desc, boolean priv) throws Exception {
        JSONObject body = new JSONObject();
        body.put("name", name);
        body.put("description", desc == null ? "" : desc);
        body.put("private", priv);
        body.put("auto_init", true);
        JSONObject o = new JSONObject(send("POST", "/user/repos", token, body.toString(), 201));
        return o.optString("full_name", "");
    }

    public static List<GFile> listPath(String token, String repo, String path) throws Exception {
        List<GFile> out = new ArrayList<>();
        String p = path == null || path.isEmpty() ? "" : "/" + encode(path);
        JSONArray a;
        try {
            a = new JSONArray(get("/repos/" + repo + "/contents" + p, token, 200));
        } catch (Exception e) {
            if (String.valueOf(e.getMessage()).startsWith("HTTP 404")) return out;
            throw e;
        }
        for (int i = 0; i < a.length(); i++) {
            JSONObject o = a.getJSONObject(i);
            GFile f = new GFile();
            f.name = o.optString("name", "");
            f.path = o.optString("path", "");
            f.type = o.optString("type", "blob");
            f.size = o.optLong("size", 0);
            out.add(f);
        }
        return out;
    }

    public static String fileContent(String token, String repo, String path) throws Exception {
        JSONObject o = new JSONObject(get("/repos/" + repo + "/contents/" + encode(path), token, 200));
        String b64 = o.optString("content", "");
        if (b64.isEmpty()) return "";
        return new String(Base64.getMimeDecoder().decode(b64), StandardCharsets.UTF_8);
    }

    private static String existingSha(String token, String repo, String path, String branch) {
        try {
            String q = "/repos/" + repo + "/contents/" + encode(path)
                    + (branch == null || branch.isEmpty() ? "" : "?ref=" + branch);
            return new JSONObject(get(q, token, 200)).optString("sha", "");
        } catch (Exception e) {
            return "";
        }
    }

    public static void putFile(String token, String repo, String path, String content,
                               String message, String branch) throws Exception {
        JSONObject body = new JSONObject();
        body.put("message", message == null || message.isEmpty()
                ? "HeroesGPT: " + path : message);
        body.put("content", Base64.getEncoder()
                .encodeToString(content.getBytes(StandardCharsets.UTF_8)));
        if (branch != null && !branch.isEmpty()) body.put("branch", branch);
        String sha = existingSha(token, repo, path, branch);
        if (!sha.isEmpty()) body.put("sha", sha);
        send("PUT", "/repos/" + repo + "/contents/" + encode(path), token, body.toString(), 0);
    }

    public static void uploadAll(String token, String repo, List<Entry> files,
                                 String prefix, String branch, StringBuilder log) {
        for (Entry e : files) {
            try {
                putFile(token, repo, prefix + "/" + e.path, e.content,
                        "HeroesGPT: add " + prefix + "/" + e.path, branch);
                log.append("\u2713 ").append(e.path).append("\n");
            } catch (Exception ex) {
                log.append("\u2717 ").append(e.path).append(" \u2014 ").append(shortErr(ex)).append("\n");
            }
        }
    }

    public static void dispatchBuild(String token, String repo, String workflow, String ref)
            throws Exception {
        JSONObject body = new JSONObject();
        body.put("ref", ref == null || ref.isEmpty() ? "main" : ref);
        send("POST", "/repos/" + repo + "/actions/workflows/" + workflow + "/dispatches",
                token, body.toString(), 204);
    }

    public static void openIssues(String token, String repo, String title, String bodyText)
            throws Exception {
        JSONObject b = new JSONObject();
        b.put("title", title);
        b.put("body", bodyText);
        send("POST", "/repos/" + repo + "/issues", token, b.toString(), 201);
    }

    private static String encode(String path) {
        return path.replace(" ", "%20");
    }

    private static String shortErr(Exception e) {
        String m = e.getMessage() == null ? "خطأ" : e.getMessage();
        return m.length() > 120 ? m.substring(0, 120) : m;
    }

    private static void req(String token, HttpURLConnection c) {
        c.setRequestProperty("Authorization", "Bearer " + token);
        c.setRequestProperty("Accept", "application/vnd.github+json");
        c.setRequestProperty("User-Agent", "HeroesGPT/6.0 (Android)");
    }

    private static String get(String path, String token, int expected) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(API + path).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        req(token, c);
        int code = c.getResponseCode();
        String body = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
        c.disconnect();
        if (expected != 0 && code != expected) throw new Exception(friendly(code, body));
        return body;
    }

    private static String send(String method, String path, String token, String body,
                               int expected) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(API + path).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(60000);
        c.setDoOutput(true);
        req(token, c);
        byte[] payload = body.getBytes(StandardCharsets.UTF_8);
        OutputStream out = c.getOutputStream();
        out.write(payload);
        out.close();
        int code = c.getResponseCode();
        String res = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
        c.disconnect();
        if (expected != 0 && code != expected) throw new Exception(friendly(code, res));
        return res == null || res.isEmpty() ? "{}" : res;
    }

    private static String friendly(int code, String body) {
        if (code == 401) return "🔑 المفتاح الشخصي غير صالح أو منتهي — أنشئ توكنين جديدًا من Settings → Developer settings → Personal access tokens";
        if (code == 403) return "🚫 صلاحية غير كافية — استخدم توكنين يشمل صلاحية repo كاملة";
        if (code == 404) return "🔍 غير موجود — تحقق من اسم المستودع أو المسار (HTTP 404)";
        if (code == 422) return "⚠️ الطلب مرفوض — غالبًا الاسم مستخدم مسبقًا أو الملف الفارغ (HTTP 422)";
        String t = body == null ? "" : body;
        return "HTTP " + code + (t.isEmpty() ? "" : " — " + t.substring(0, Math.min(t.length(), 200)));
    }

    private static String readStream(java.io.InputStream is) throws Exception {
        if (is == null) return "";
        byte[] buf = new byte[8192];
        StringBuilder sb = new StringBuilder();
        int n;
        while ((n = is.read(buf)) > 0) sb.append(new String(buf, 0, n, StandardCharsets.UTF_8));
        is.close();
        return sb.toString();
    }
}
