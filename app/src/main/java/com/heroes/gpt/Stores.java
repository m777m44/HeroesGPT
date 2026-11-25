package com.heroes.gpt;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

public class Stores {

    public static class Run {
        public String id;
        public String goal;
        public long createdAt;
        public int stage;
        public List<Hero> heroes = new ArrayList<>();
        public List<Result> results = new ArrayList<>();

        public static class Result {
            public String heroId;
            public int status;
            public String output = "";
            public String error = "";
        }
    }

    private static File baseDir(Context c) {
        File d = new File(c.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    private static File file(Context c, String name) {
        return new File(baseDir(c), name + ".json");
    }

    private static String read(File f) throws Exception {
        if (!f.exists()) return "";
        InputStream in = new FileInputStream(f);
        byte[] buf = new byte[(int) f.length()];
        int n = in.read(buf);
        in.close();
        return new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8);
    }

    private static void write(File f, String s) throws Exception {
        FileOutputStream out = new FileOutputStream(f);
        out.write(s.getBytes(StandardCharsets.UTF_8));
        out.close();
    }

    private static final String HEROES = "heroes";
    private static final String PROVIDERS = "providers";

    public static List<Hero> heroes(Context c) {
        try {
            String s = read(file(c, HEROES));
            if (!s.isEmpty()) return Hero.fromJsonArray(new JSONArray(s));
        } catch (Exception ignored) {
        }
        List<Hero> d = Hero.defaults();
        saveHeroes(c, d);
        return d;
    }

    public static void saveHeroes(Context c, List<Hero> heroes) {
        try {
            write(file(c, HEROES), Hero.toJsonArray(heroes).toString());
        } catch (Exception ignored) {
        }
    }

    public static List<Provider> providers(Context c) {
        try {
            String s = read(file(c, PROVIDERS));
            if (!s.isEmpty()) {
                List<Provider> out = new ArrayList<>();
                JSONArray a = new JSONArray(s);
                for (int i = 0; i < a.length(); i++) out.add(Provider.fromJson(a.getJSONObject(i)));
                return out;
            }
        } catch (Exception ignored) {
        }
        List<Provider> d = new ArrayList<>();
        d.add(Provider.freeDefault());
        d.add(Provider.make("GLM-4.5-Flash — مجاني (z.ai)", "https://api.z.ai/api/paas/v4", "glm-4.5-flash", "", false));
        d.add(Provider.make("Gemini — مجاني (Google AI Studio)", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-2.5-flash", "", false));
        d.add(Provider.make("OpenRouter — نماذج :free", "https://openrouter.ai/api/v1", "deepseek/deepseek-chat-v3-0324:free", "", false));
        d.add(Provider.make("DeepSeek", "https://api.deepseek.com", "deepseek-chat", "", false));
        saveProviders(c, d);
        return d;
    }

    public static void ensureRecommendedFreeProviders(Context c) {
        try {
            ensureFreeRotationBackup(c);
            List<Provider> ps = providers(c);
            boolean changed = false;
            for (Provider p : ps) {
                String b = p.base == null ? "" : p.base;
                if (p.keyUrl == null) p.keyUrl = "";
                String u = p.keyUrl;
                if (u.isEmpty() && b.contains("pollinations.ai")) { p.keyUrl = "https://enter.pollinations.ai/?ref=classic"; changed = true; }
                else if (u.isEmpty() && b.contains("generativelanguage.googleapis.com")) { p.keyUrl = "https://aistudio.google.com/api-keys"; changed = true; }
                else if (u.isEmpty() && b.contains("openrouter.ai")) { p.keyUrl = "https://openrouter.ai/settings/keys"; changed = true; }
                else if (u.isEmpty() && b.contains("api.deepseek.com")) { p.keyUrl = "https://platform.deepseek.com/api_keys"; changed = true; }
                if (b.contains("openrouter.ai") && p.model.contains("deepseek-chat-v3-0324:free")) { p.model = "google/gemma-4-31b-it:free"; changed = true; }
                if (b.contains("generativelanguage.googleapis.com") && p.model.contains("gemini-2.5-flash")) { p.model = "gemini-3.8-flash"; changed = true; }
            }
            if (!hasBase(ps, "api.bazaarlink.ai")) {
                ps.add(Provider.make("BazaarLink — 130 نموذجًا", "https://api.bazaarlink.ai/v1",
                        "glm-4.7-flash", "", false, "https://bazaarlink.ai/keys"));
                changed = true;
            }
            if (!hasBase(ps, "api.groq.com")) {
                ps.add(Provider.make("Groq — مجاني فائق السرعة", "https://api.groq.com/openai/v1",
                        "llama-3.3-70b-versatile", "", false, "https://console.groq.com/keys"));
                ps.add(Provider.make("Cerebras — مجاني (1M يوميًا)", "https://api.cerebras.ai/v1",
                        "llama-3.3-70b", "", false, "https://cloud.cerebras.ai"));
                ps.add(Provider.make("Hugging Face — مجاني", "https://router.huggingface.co/v1",
                        "meta-llama/Llama-3.3-70B-Instruct", "", false, "https://huggingface.co/settings/tokens"));
                ps.add(Provider.make("Mistral — مجاني (La Plateforme)", "https://api.mistral.ai/v1",
                        "mistral-small-latest", "", false, "https://console.mistral.ai/api-keys"));
                ps.add(Provider.make("Cohere — تجربة مجانية", "https://api.cohere.ai/compatibility/v1",
                        "command-r7b-12-2024", "", false, "https://dashboard.cohere.com/api-keys"));
                ps.add(Provider.make("Together AI — 5$ رصيد مجاني", "https://api.together.xyz/v1",
                        "meta-llama/Llama-3.3-70B-Instruct-Turbo", "", false, "https://api.together.ai/settings/api-keys"));
                ps.add(Provider.make("Fireworks AI — رصيد مجاني", "https://api.fireworks.ai/inference/v1",
                        "accounts/fireworks/models/llama-v3p3-70b-instruct", "", false, "https://fireworks.ai/account/api-keys"));
                ps.add(Provider.make("DeepInfra — رصيد مجاني", "https://api.deepinfra.com/v1/openai",
                        "meta-llama/Llama-3.3-70B-Instruct", "", false, "https://deepinfra.com/dash/keys"));
                ps.add(Provider.make("NVIDIA NIM — تجربة مجانية", "https://integrate.api.nvidia.com/v1",
                        "meta/llama-3.3-70b-instruct", "", false, "https://build.nvidia.com"));
                ps.add(Provider.make("SambaNova — مجاني", "https://api.sambanova.ai/v1",
                        "Meta-Llama-3.3-70B-Instruct", "", false, "https://cloud.sambanova.ai/apis"));
                changed = true;
            }
            if (changed) saveProviders(c, ps);
        } catch (Exception ignored) { }
    }

    private static boolean hasBase(List<Provider> ps, String basePart) {
        for (Provider p : ps) if (p.base != null && p.base.contains(basePart)) return true;
        return false;
    }

    public static void ensureFreeRotationBackup(Context c) {
        try {
            List<Provider> ps = providers(c);
            int usable = 0;
            for (Provider p : ps) {
                if (p.enabled && !p.base.trim().isEmpty()
                        && (p.noKeyNeeded || !p.key.trim().isEmpty())) usable++;
            }
            if (usable >= 2) return;
            for (Provider p : ps) {
                if (p.base.contains("openai-fast") && p.noKeyNeeded) return;
            }
            ps.add(Provider.make("Pollinations Turbo — مجاني بلا مفتاح",
                    "https://text.pollinations.ai/openai", "openai-fast", "", true));
            saveProviders(c, ps);
        } catch (Exception ignored) { }
    }

    public static void saveProviders(Context c, List<Provider> providers) {
        try {
            JSONArray a = new JSONArray();
            for (Provider p : providers) a.put(p.toJson());
            write(file(c, PROVIDERS), a.toString());
        } catch (Exception ignored) {
        }
    }

    private static File runsDir(Context c) {
        File d = new File(baseDir(c), "runs");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    public static Run newRun(Context c, String goal, List<Hero> team) {
        Run r = new Run();
        r.id = String.valueOf(System.currentTimeMillis());
        r.goal = goal;
        r.createdAt = System.currentTimeMillis();
        for (Hero h : team) {
            r.heroes.add(h);
            Run.Result res = new Run.Result();
            res.heroId = h.id;
            r.results.add(res);
        }
        saveRun(c, r);
        return r;
    }

    public static Run loadRun(Context c, String id) {
        try {
            String s = read(new File(runsDir(c), id + ".json"));
            if (s.isEmpty()) return null;
            JSONObject o = new JSONObject(s);
            Run r = new Run();
            r.id = o.getString("id");
            r.goal = o.optString("goal", "");
            r.createdAt = o.optLong("createdAt", 0);
            r.stage = o.optInt("stage", 0);
            r.heroes = Hero.fromJsonArray(o.optJSONArray("heroes"));
            JSONArray rs = o.optJSONArray("results");
            if (rs != null) {
                for (int i = 0; i < rs.length(); i++) {
                    JSONObject ro = rs.getJSONObject(i);
                    Run.Result res = new Run.Result();
                    res.heroId = ro.optString("heroId");
                    res.status = ro.optInt("status", 0);
                    res.output = ro.optString("output");
                    res.error = ro.optString("error");
                    r.results.add(res);
                }
            }
            return r;
        } catch (Exception e) {
            return null;
        }
    }

    public static void saveRun(Context c, Run r) {
        try {
            JSONObject o = new JSONObject();
            o.put("id", r.id);
            o.put("goal", r.goal);
            o.put("createdAt", r.createdAt);
            o.put("stage", r.stage);
            JSONArray hs = new JSONArray();
            for (Hero h : r.heroes) hs.put(h.toJson());
            o.put("heroes", hs);
            JSONArray rs = new JSONArray();
            for (Run.Result res : r.results) {
                JSONObject ro = new JSONObject();
                ro.put("heroId", res.heroId);
                ro.put("status", res.status);
                ro.put("output", res.output);
                ro.put("error", res.error);
                rs.put(ro);
            }
            o.put("results", rs);
            write(new File(runsDir(c), r.id + ".json"), o.toString());
        } catch (Exception ignored) {
        }
    }

    public static List<Run> runs(Context c) {
        List<Run> out = new ArrayList<>();
        File[] files = runsDir(c).listFiles();
        if (files != null) {
            for (File f : files) {
                Run r = loadRun(c, f.getName().replace(".json", ""));
                if (r != null) out.add(r);
            }
        }
        java.util.Collections.sort(out, (a, b) -> Long.compare(b.createdAt, a.createdAt));
        return out;
    }

    public static void deleteRun(Context c, String id) {
        new File(runsDir(c), id + ".json").delete();
    }

    public static class SavedChat {
        public String id;
        public String title;
        public String text;
        public long createdAt;
        public String preview = "";
    }

    private static File settingsFile(Context c) {
        File d = new File(c.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return new File(d, "settings.json");
    }

    public static String setting(Context c, String key) {
        try {
            File f = settingsFile(c);
            if (!f.exists()) return "";
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int n = in.read(buf);
            in.close();
            return new JSONObject(new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8)).optString(key, "");
        } catch (Exception e) {
            return "";
        }
    }

    public static void setSetting(Context c, String key, String value) {
        try {
            File f = settingsFile(c);
            JSONObject o = new JSONObject();
            if (f.exists()) {
                FileInputStream in = new FileInputStream(f);
                byte[] buf = new byte[(int) f.length()];
                int n = in.read(buf);
                in.close();
                o = new JSONObject(new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8));
            }
            o.put(key, value);
            FileOutputStream out = new FileOutputStream(f);
            out.write(o.toString().getBytes(StandardCharsets.UTF_8));
            out.close();
        } catch (Exception ignored) {
        }
    }

    private static File chatsDir(Context c) {
        File d = new File(baseDir(c), "chats");
        if (!d.exists()) d.mkdirs();
        return d;
    }

    public static void saveChat(Context c, String title, String text) {
        try {
            File f = new File(chatsDir(c), System.currentTimeMillis() + ".json");
            JSONObject o = new JSONObject();
            o.put("id", f.getName().replace(".json", ""));
            o.put("title", title);
            o.put("text", text);
            o.put("createdAt", System.currentTimeMillis());
            FileOutputStream out = new FileOutputStream(f);
            out.write(o.toString().getBytes(StandardCharsets.UTF_8));
            out.close();
        } catch (Exception ignored) {
        }
    }

    public static List<SavedChat> chats(Context c) {
        List<SavedChat> out = new ArrayList<>();
        File[] files = chatsDir(c).listFiles();
        if (files != null) {
            for (File f : files) {
                try {
                    FileInputStream in = new FileInputStream(f);
                    byte[] buf = new byte[(int) f.length()];
                    int n = in.read(buf);
                    in.close();
                    JSONObject o = new JSONObject(new String(buf, 0, Math.max(n, 0), StandardCharsets.UTF_8));
                    SavedChat sc = new SavedChat();
                    sc.id = o.optString("id", f.getName().replace(".json", ""));
                    sc.title = o.optString("title", "");
                    sc.text = o.optString("text", "");
                    sc.createdAt = o.optLong("createdAt", 0);
                    if (sc.text.length() > 140) sc.preview = sc.text.substring(0, 140) + "…";
                    else sc.preview = sc.text;
                    out.add(sc);
                } catch (Exception ignored) {
                }
            }
        }
        java.util.Collections.sort(out, (a, b) -> Long.compare(b.createdAt, a.createdAt));
        return out;
    }

    public static void deleteChat(Context c, String id) {
        new File(chatsDir(c), id + ".json").delete();
    }
}
