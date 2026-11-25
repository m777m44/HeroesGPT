package com.heroes.gpt;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.util.ArrayList;
import java.util.List;

public class Elo {

    public static class Rating {
        public String heroId;
        public int score = 1200;
        public int wins;
        public int losses;
        public int ties;
    }

    private static File file(Context c) {
        File d = new File(c.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return new File(d, "arena.json");
    }

    private static List<Rating> load(Context c) {
        List<Rating> out = new ArrayList<>();
        try {
            File f = file(c);
            if (!f.exists()) return out;
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int n = in.read(buf);
            in.close();
            JSONObject o = new JSONObject(new String(buf, 0, Math.max(n, 0), "UTF-8"));
            JSONArray a = o.optJSONArray("ratings");
            if (a != null) {
                for (int i = 0; i < a.length(); i++) {
                    JSONObject ro = a.getJSONObject(i);
                    Rating r = new Rating();
                    r.heroId = ro.optString("heroId");
                    r.score = ro.optInt("score", 1200);
                    r.wins = ro.optInt("wins", 0);
                    r.losses = ro.optInt("losses", 0);
                    r.ties = ro.optInt("ties", 0);
                    if (!r.heroId.isEmpty()) out.add(r);
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    private static void save(Context c, List<Rating> rs) {
        try {
            JSONArray a = new JSONArray();
            for (Rating r : rs) {
                JSONObject ro = new JSONObject();
                ro.put("heroId", r.heroId);
                ro.put("score", r.score);
                ro.put("wins", r.wins);
                ro.put("losses", r.losses);
                ro.put("ties", r.ties);
                a.put(ro);
            }
            JSONObject o = new JSONObject();
            o.put("ratings", a);
            FileOutputStream out = new FileOutputStream(file(c));
            out.write(o.toString().getBytes("UTF-8"));
            out.close();
        } catch (Exception ignored) {
        }
    }

    private static Rating findOrCreate(Context c, List<Rating> rs, String heroId) {
        for (Rating r : rs) {
            if (r.heroId.equals(heroId)) return r;
        }
        Rating r = new Rating();
        r.heroId = heroId;
        rs.add(r);
        return r;
    }

    public static List<Rating> ratings(Context c) {
        return load(c);
    }

    public static int scoreOf(Context c, String heroId) {
        for (Rating r : load(c)) {
            if (r.heroId.equals(heroId)) return r.score;
        }
        return 1200;
    }

    public static void record(Context c, String heroA, String heroB, double sa) {
        List<Rating> rs = load(c);
        Rating ra = findOrCreate(c, rs, heroA);
        Rating rb = findOrCreate(c, rs, heroB);
        double ea = 1.0 / (1.0 + Math.pow(10, (rb.score - ra.score) / 400.0));
        double ka = ra.wins + ra.losses + ra.ties < 10 ? 48 : 24;
        double kb = rb.wins + rb.losses + rb.ties < 10 ? 48 : 24;
        ra.score = (int) Math.round(ra.score + ka * (sa - ea));
        rb.score = (int) Math.round(rb.score + kb * ((1.0 - sa) - (1.0 - ea)));
        if (sa > 0.75) {
            ra.wins++;
            rb.losses++;
        } else if (sa < 0.25) {
            rb.wins++;
            ra.losses++;
        } else {
            ra.ties++;
            rb.ties++;
        }
        save(c, rs);
    }
}
