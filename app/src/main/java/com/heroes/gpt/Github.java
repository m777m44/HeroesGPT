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
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;

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

    public static class CommitResult {
        public int uploaded;
        public int failed;
        public final StringBuilder log = new StringBuilder();
        public String branch = "main";
    }

    public static String validateToken(String token) throws Exception {
        JSONObject u = get("/user", token, 200);
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
        JSONObject o = get("/repos/" + repo + "/contents/" + encode(path), token, 200);
        String b64 = o.optString("content", "");
        if (b64.isEmpty()) return "";
        return new String(Base64.getMimeDecoder().decode(b64), StandardCharsets.UTF_8);
    }

    public static String defaultBranch(String token, String repo) {
        try {
            JSONObject o = get("/repos/" + repo, token, 200);
            String b = o.optString("default_branch", "main");
            return b == null || b.isEmpty() ? "main" : b;
        } catch (Exception e) {
            return "main";
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
        send("PUT", "/repos/" + repo + "/contents/" + encode(path), token, body.toString(), 0);
    }

    private static boolean softHttp(String msg) {
        return msg.contains("HTTP 500") || msg.contains("HTTP 502") || msg.contains("HTTP 503")
                || msg.contains("HTTP 504") || msg.contains("HTTP 409")
                || !msg.startsWith("HTTP ");
    }

    private static String createBlob(String token, String repo, String content) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 4; attempt++) {
            try {
                JSONObject body = new JSONObject();
                body.put("content", content);
                body.put("encoding", "utf-8");
                JSONObject o = new JSONObject(sendNoretry("POST", "/repos/" + repo + "/git/blobs",
                        token, body.toString()));
                return o.optString("sha", "");
            } catch (HttpException e) {
                last = e;
                if (e.code == 401 || e.code == 403 || e.code == 404
                        || e.code == 413) throw e;
                if (attempt == 3) break;
                try { Thread.sleep(600L * (attempt + 1)); } catch (InterruptedException ie) { }
            } catch (Exception e) {
                last = e;
                if (attempt == 3) break;
                try { Thread.sleep(600L * (attempt + 1)); } catch (InterruptedException ie) { }
            }
        }
        throw last == null ? new Exception("blob failed") : last;
    }

    private static String[] getRef(String token, String repo, String branch) throws Exception {
        HttpEntity ref = getRaw("/repos/" + repo + "/git/ref/heads/" + branch, token);
        Handle409:
        if (ref.code >= 400) {
            boolean emptyRepo = ref.code == 409 || ref.code == 404;
            HandleEmpty: {
                if (!emptyRepo) throw new HttpException(ref.code, friendly(ref.code, ref.body));
                break HandleEmpty;
            }
            break Handle409;
        }
        String commitSha = new JSONObject(ref.body).getJSONObject("object").optString("sha", "");
        HttpEntity commit = getRaw("/repos/" + repo + "/git/commits/" + commitSha, token);
        return new String[]{commitSha,
                commit.code < 400 ? new JSONObject(commit.body).optString("tree", "") : ""};
    }

    public static CommitResult commitAll(String token, String repo, List<Entry> files,
                                         String prefix, String message, String branchHint)
            throws Exception {
        if (files == null || files.isEmpty()) throw new Exception("لا توجد ملفات للرفع");
        CommitResult out = new CommitResult();
        out.branch = branchHint == null || branchHint.isEmpty()
                ? defaultBranch(token, repo) : branchHint;

        Map<String, String> contents = new HashMap<>();
        List<String> order = new ArrayList<>();
        for (Entry e : files) {
            String path = (prefix == null || prefix.isEmpty() ? "" : prefix + "/") + e.path;
            if (!contents.containsKey(path)) order.add(path);
            contents.put(path, e.content);
        }

        final int total = order.size();
        final AtomicInteger blobDone = new AtomicInteger();
        final Map<String, String> shas = new HashMap<>();
        final Map<String, Exception> blobFail = new HashMap<>();
        ExecutorService pool = Executors.newFixedThreadPool(Math.min(4, total));
        try {
            List<Future<?>> futures = new ArrayList<>();
            for (final String path : order) {
                futures.add(pool.submit(() -> {
                    try {
                        shas.put(path, createBlob(token, repo, contents.get(path)));
                        blobDone.incrementAndGet();
                    } catch (Exception ex) {
                        blobFail.put(path, ex);
                    }
                }));
            }
            for (Future<?> f : futures) f.get();
        } finally {
            pool.shutdown();
        }

        for (String path : order) {
            Exception ex = blobFail.get(path);
            if (ex != null) {
                out.failed++;
                out.log.append("✗ ").append(path).append(" — ").append(shortErr(ex)).append('\n');
            }
        }
        if (shas.isEmpty()) {
            throw blobFail.isEmpty() ? new Exception("فشل رفع المحتويات") : blobFail.values().iterator().next();
        }

        String commitMsg = message == null || message.isEmpty()
                ? "HeroesGPT: upload " + shas.size() + " files"
                : message;

        for (int attempt = 0; attempt < 4; attempt++) {
            String baseSha;
            String baseTree;
            try {
                String[] ref = getRef(token, repo, out.branch);
                baseSha = ref[0];
                baseTree = ref[1];
            } catch (HttpException refEx) {
                if (attempt < 3 && (refEx.code == 409 || refEx.code == 404)) {
                    String initPath = (prefix == null || prefix.isEmpty()
                            ? "HeroesGPT-README" : prefix) + "/README.md";
                    putFile(token, repo, initPath, "# HeroesGPT\n", "HeroesGPT: init", out.branch);
                    continue;
                }
                throw refEx;
            } catch (Exception refEx) {
                throw refEx;
            }

            JSONArray treeArr = new JSONArray();
            for (String path : shas.keySet()) {
                JSONObject t = new JSONObject();
                t.put("path", path);
                t.put("mode", "100644");
                t.put("type", "blob");
                t.put("sha", shas.get(path));
                treeArr.put(t);
            }
            try {
                JSONObject treeBody = new JSONObject();
                if (!baseTree.isEmpty()) treeBody.put("base_tree", baseTree);
                treeBody.put("tree", treeArr);
                HttpEntity treeRes = postJson(token, repo, "/git/trees", treeBody);
                String treeSha = new JSONObject(treeRes.body).optString("sha", "");

                JSONObject cBody = new JSONObject();
                cBody.put("message", commitMsg);
                cBody.put("tree", treeSha);
                JSONArray parents = new JSONArray();
                parents.put(baseSha);
                cBody.put("parents", parents);
                HttpEntity cRes = postJson(token, repo, "/git/commits", cBody);
                String newSha = new JSONObject(cRes.body).optString("sha", "");

                JSONObject rBody = new JSONObject();
                rBody.put("sha", newSha);
                rBody.put("force", attempt >= 2);
                HttpEntity refRes = patchJson(token, repo,
                        "/git/refs/heads/" + out.branch, rBody);
                if (refRes.code < 300) {
                    out.uploaded = shas.size();
                    out.log.insert(0, "✓ رُفِع " + shas.size() + " ملفًا في تحديث واحد إلى فرع "
                            + out.branch + "\n");
                    return out;
                }
                String m = String.valueOf(refRes.body);
                if (m.contains("not a fast forward") || m.contains("fast-forward")) {
                    if (attempt == 3) {
                        throw new Exception("المستودع يتغيّر أثناء الرفع — حاول مجددًا");
                    }
                    continue;
                }
                throw new HttpException(refRes.code, friendly(refRes.code, refRes.body));
            } catch (HttpException e) {
                throw e;
            }
        }
        throw new Exception("تعذر إتمام الرفع — المستودع مشغول، حاول مجددًا");
    }

    public static class HttpException extends Exception {
        public final int code;
        public HttpException(int code, String msg) {
            super(msg);
            this.code = code;
        }
    }

    public static class HttpEntity {
        public int code;
        public String body = "";
    }

    private static HttpEntity getRaw(String path, String token) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(API + path).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(30000);
        req(token, c);
        int code = c.getResponseCode();
        String body = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
        c.disconnect();
        HttpEntity e = new HttpEntity();
        e.code = code;
        e.body = body;
        return e;
    }

    private static JSONObject get(String path, String token, int expected) throws Exception {
        HttpEntity e = getRaw(path, token);
        if (expected != 0 && e.code != expected && e.code < 400) {
            throw new Exception("HTTP " + e.code);
        }
        if (e.code >= 400) throw new HttpException(e.code, friendly(e.code, e.body));
        return e.body.isEmpty() ? new JSONObject() : new JSONObject(e.body);
    }

    private static String sendNoretry(String method, String path, String token, String body)
            throws Exception {
        HttpEntity e = httpEntity(method, path, token, body.toString());
        if (e.code >= 400) throw new HttpException(e.code, friendly(e.code, e.body));
        return e.body == null || e.body.isEmpty() ? "{}" : e.body;
    }

    private static HttpEntity postJson(String token, String repo, String sub, JSONObject body)
            throws Exception {
        HttpEntity e = httpEntity("POST", "/repos/" + repo + sub, token, body.toString());
        if (e.code >= 400) throw new HttpException(e.code, friendly(e.code, e.body));
        return e;
    }

    private static HttpEntity patchJson(String token, String repo, String sub, JSONObject body)
            throws Exception {
        return httpEntity("PATCH", "/repos/" + repo + sub, token, body.toString());
    }

    private static HttpEntity httpEntity(String method, String path, String token, String body)
            throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(API + path).openConnection();
        c.setRequestMethod(method);
        c.setConnectTimeout(15000);
        c.setReadTimeout(120000);
        c.setDoOutput(true);
        req(token, c);
        OutputStream out = c.getOutputStream();
        out.write(body.getBytes(StandardCharsets.UTF_8));
        out.close();
        int code = c.getResponseCode();
        String res = readStream(code >= 400 ? c.getErrorStream() : c.getInputStream());
        c.disconnect();
        HttpEntity e = new HttpEntity();
        e.code = code;
        e.body = res == null ? "" : res;
        return e;
    }

    private static String send(String method, String path, String token, String body,
                               int expected) throws Exception {
        Exception last = null;
        for (int attempt = 0; attempt < 3; attempt++) {
            HttpEntity e = httpEntity(method, path, token, body);
            if (e.code < 400) return e.body == null || e.body.isEmpty() ? "{}" : e.body;
            Exception ex = new HttpException(e.code, friendly(e.code, e.body));
            if (e.code == 401 || e.code == 403 || e.code == 404 || e.code == 422) throw ex;
            if (e.code >= 500 || e.code == 409) {
                last = ex;
                try { Thread.sleep(800L * (attempt + 1)); } catch (InterruptedException ie) { }
                continue;
            }
            throw ex;
        }
        throw last == null ? new Exception("request failed") : last;
    }

    public static void openIssues(String token, String repo, String title, String bodyText)
            throws Exception {
        JSONObject b = new JSONObject();
        b.put("title", title);
        b.put("body", bodyText);
        send("POST", "/repos/" + repo + "/issues", token, b.toString(), 201);
    }

    public static void dispatchBuild(String token, String repo, String workflow, String ref)
            throws Exception {
        JSONObject b = new JSONObject();
        b.put("ref", ref);
        send("POST", "/repos/" + repo + "/actions/workflows/" + workflow + "/dispatches",
                token, b.toString(), 204);
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
        c.setRequestProperty("User-Agent", "HeroesGPT/6.2 (Android)");
    }

    private static String friendly(int code, String body) {
        String t = body == null ? "" : body;
        if (code == 401) return "🔑 المفتاح الشخصي غير صالح أو منتهي — أنشئ توكنين جديدًا من Settings → Developer settings → Personal access tokens";
        if (code == 403) return "🚫 صلاحية غير كافية — استخدم توكنين يشمل صلاحية repo كاملة";
        if (code == 404) return "🔍 غير موجود — تحقق من اسم المستودع أو المسار (HTTP 404)";
        if (code == 409) return "⏳ المستودع يتغيّر حاليًا على GitHub — أعد المحاولة بعد لحظات";
        if (code == 413) return "📦 ملف أكبر من حد GitHub المسموح (100 ميجابايت)";
        if (code == 422 && t.contains("fast")) {
            return "🔄 تعارض تحديث الفرع (fast-forward) — سيُعاد المحاولة تلقائيًا";
        }
        if (code == 422) return "⚠️ الطلب مرفوض — غالبًا الاسم مستخدم مسبقًا أو الملف الفارغ (HTTP 422)";
        if (code >= 500) return "🛠 خوادم GitHub مشغولة مؤقتًا (" + code + ") — سيُعاد المحاولة تلقائيًا";
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
