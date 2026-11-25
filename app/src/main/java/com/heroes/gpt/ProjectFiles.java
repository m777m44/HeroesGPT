package com.heroes.gpt;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class ProjectFiles {

    public static List<Github.Entry> extract(Stores.Run run) {
        List<Github.Entry> out = new ArrayList<>();
        Pattern fence = Pattern.compile("```([A-Za-z0-9_+\\-.\\s]*)\\s*(?:【?([^\\n`【】]+)】?)?\\n([\\s\\S]*?)```");
        for (int i = 0; i < run.results.size(); i++) {
            Stores.Run.Result res = run.results.get(i);
            if (res.status != Orchestrator.STATUS_DONE || res.output == null) continue;
            if (i >= run.heroes.size()) continue;
            String agent = run.heroes.get(i).name;
            Matcher m = fence.matcher(res.output);
            int k = 1;
            while (m.find()) {
                String lang = m.group(1) == null ? "" : m.group(1).trim();
                String name = m.group(2);
                String path = guessPath(name, lang, agent, k++);
                String code = m.group(3);
                out.add(entry(out, new Github.Entry(), path, code));
            }
        }
        return out;
    }

    private static Github.Entry entry(List<Github.Entry> existing, Github.Entry e,
                                      String path, String code) {
        String p = path;
        int n = 2;
        while (true) {
            boolean dup = false;
            for (Github.Entry prev : existing) if (prev.path.equals(p)) { dup = true; break; }
            if (!dup) break;
            int dot = p.lastIndexOf('.');
            p = dot > 0 ? p.substring(0, dot) + "_" + n + p.substring(dot) : p + "_" + n;
            n++;
        }
        e.path = p;
        e.content = code == null ? "" : code;
        return e;
    }

    private static String guessPath(String name, String lang, String agent, int k) {
        String base = "";
        if (name != null && !name.trim().isEmpty()) {
            base = sanitize(name.trim());
        } else if (lang.contains("json")) {
            base = "data_" + k + ".json";
        } else if (lang.contains("py")) {
            base = "script_" + k + ".py";
        } else if (lang.contains("js")) {
            base = "main_" + k + ".js";
        } else if (lang.contains("xml")) {
            base = "layout_" + k + ".xml";
        } else if (lang.contains("java") || lang.contains("kotlin")) {
            base = "Code" + k + (lang.contains("kotlin") ? ".kt" : ".java");
        } else if (lang.contains("html")) {
            base = "index_" + k + ".html";
        } else if (lang.contains("css")) {
            base = "styles_" + k + ".css";
        } else {
            base = "note_" + k + ".md";
        }
        String dir = sanitize(agent);
        return dir + "/" + base;
    }

    private static String sanitize(String s) {
        String r = s.replaceAll("[^A-Za-z0-9\\u0621-\\u064A_\\- ]", "").trim();
        if (r.isEmpty()) r = "file";
        if (r.contains(" ")) r = r.replaceAll("\\s+", "_");
        return r;
    }
}
