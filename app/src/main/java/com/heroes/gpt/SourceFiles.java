package com.heroes.gpt;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public class SourceFiles {

    public static final String EXT_PY = "py";

    public static String langToExt(String lang, String code) {
        String l = lang == null ? "" : lang.trim().toLowerCase();
        if (l.isEmpty()) l = guessFromCode(code);
        Map<String, String> m = new HashMap<>();
        m.put("python", ".py"); m.put("py", ".py"); m.put("python3", ".py");
        m.put("javascript", ".js"); m.put("js", ".js"); m.put("node", ".js");
        m.put("typescript", ".ts"); m.put("ts", ".ts");
        m.put("java", ".java");
        m.put("kotlin", ".kt"); m.put("kt", ".kt");
        m.put("xml", ".xml"); m.put("html", ".html"); m.put("css", ".css");
        m.put("json", ".json"); m.put("yaml", ".yaml"); m.put("yml", ".yml");
        m.put("bash", ".sh"); m.put("shell", ".sh"); m.put("sh", ".sh");
        m.put("c", ".c"); m.put("cpp", ".cpp"); m.put("c++", ".cpp");
        m.put("cs", ".cs"); m.put("csharp", ".cs");
        m.put("go", ".go"); m.put("rust", ".rs"); m.put("rs", ".rs");
        m.put("sql", ".sql"); m.put("php", ".php"); m.put("ruby", ".rb");
        m.put("swift", ".swift"); m.put("dart", ".dart");
        m.put("markdown", ".md"); m.put("md", ".md");
        m.put("text", ".txt"); m.put("txt", ".txt");
        m.put("gradle", ".gradle"); m.put("properties", ".properties");
        String ext = m.get(l);
        return ext == null ? ".txt" : ext;
    }

    private static String guessFromCode(String code) {
        String s = code == null ? "" : code;
        String head = s.length() > 600 ? s.substring(0, 600) : s;
        if (head.startsWith("<?xml")) return "xml";
        if (head.contains("<html") || head.contains("<!DOCTYPE html")) return "html";
        if (head.contains("import telebot") || head.contains("import requests")
                || head.startsWith("import ") || head.startsWith("from ")
                || head.contains("def ") || head.contains("print(")) return "python";
        if (head.contains("public static void main") || head.contains("package ")) return "java";
        if (head.contains("{") && head.contains("\":")) return "json";
        if (head.contains("@Composable") || head.contains("fun main")) return "kotlin";
        if (head.contains("_sdk") && head.contains("cloud.google")) return "python";
        return "";
    }

    public static String suggestName(String title, String lang, String code) {
        String base = "code";
        if (title != null && !title.trim().isEmpty()) {
            String t = title.trim().replace(' ', '_');
            int slash = t.lastIndexOf('/');
            if (slash >= 0) t = t.substring(slash + 1);
            base = t.replaceAll("[^A-Za-z0-9_\\-\\.\\u0621-\\u064A]", "");
            if (base.isEmpty()) base = "code";
        }
        int dot = base.lastIndexOf('.');
        String noExt = dot > 0 ? base.substring(0, dot) : base;
        String cur = dot > 0 ? base.substring(dot) : "";
        String want = langToExt(lang, code);
        boolean hasRealExt = cur.matches("\\.[A-Za-z0-9]{1,8}");
        return noExt + (hasRealExt ? cur : want);
    }

    public static List<Github.Entry> fromRun(Context c, String runId) {
        Stores.Run run = Stores.loadRun(c, runId);
        return run == null ? new ArrayList<>() : ProjectFiles.extract(run);
    }

    public static List<Object[]> bundledSources(Context c) {
        List<Object[]> out = new ArrayList<>();
        try {
            String raw = readAsset(c, "sources/index.json");
            JSONObject o = new JSONObject(raw);
            org.json.JSONArray items = o.optJSONArray("items");
            if (items != null) {
                for (int i = 0; i < items.length(); i++) {
                    JSONObject it = items.getJSONObject(i);
                    out.add(new Object[]{it.optString("file", ""),
                            it.optString("title", it.optString("file", "")),
                            it.optLong("size", 0)});
                }
            }
        } catch (Exception ignored) { }
        return out;
    }

    public static String readAsset(Context c, String path) throws Exception {
        InputStream in = c.getAssets().open(path);
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        in.close();
        return new String(bos.toByteArray(), java.nio.charset.StandardCharsets.UTF_8);
    }
}
