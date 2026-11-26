package com.heroes.gpt;

import org.json.JSONObject;

public class Provider {
    public String id;
    public String name;
    public String base;
    public String model;
    public String key;
    public boolean enabled = true;
    public boolean noKeyNeeded = false;
    public String keyUrl = "";
    public String kind = "openai";

    public JSONObject toJson() throws Exception {
        JSONObject o = new JSONObject();
        o.put("id", id);
        o.put("name", name);
        o.put("base", base);
        o.put("model", model);
        o.put("key", key);
        o.put("enabled", enabled);
        o.put("noKeyNeeded", noKeyNeeded);
        o.put("keyUrl", keyUrl == null ? "" : keyUrl);
        o.put("kind", kind == null || kind.isEmpty() ? "openai" : kind);
        return o;
    }

    public static Provider fromJson(JSONObject o) {
        Provider p = new Provider();
        p.id = o.optString("id");
        p.name = o.optString("name", "مزوّد");
        p.base = o.optString("base", "");
        p.model = o.optString("model", "");
        p.key = o.optString("key", "");
        p.enabled = o.optBoolean("enabled", true);
        p.noKeyNeeded = o.optBoolean("noKeyNeeded", false);
        p.keyUrl = o.optString("keyUrl", "");
        p.kind = o.optString("kind", "openai");
        if (p.kind.isEmpty()) p.kind = "openai";
        return p;
    }

    public static Provider make(String name, String base, String model, String key, boolean noKeyNeeded) {
        return make(name, base, model, key, noKeyNeeded, "");
    }

    public static Provider makeSimple(String name, String base) {
        Provider p = make(name, base, "", "", true);
        p.kind = "simple";
        return p;
    }

    public static Provider make(String name, String base, String model, String key,
                                boolean noKeyNeeded, String keyUrl) {
        Provider p = new Provider();
        p.id = "p" + System.nanoTime();
        p.name = name;
        p.base = base;
        p.model = model;
        p.key = key;
        p.noKeyNeeded = noKeyNeeded;
        p.keyUrl = keyUrl == null ? "" : keyUrl;
        return p;
    }

    public static Provider freeDefault() {
        return Provider.make("Pollinations — مجاني بلا مفتاح",
                "https://text.pollinations.ai/openai",
                "openai",
                "",
                true);
    }
}
