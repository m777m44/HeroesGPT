package com.heroes.gpt;

import android.content.Context;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;

public class Stats {

    public static final String RUNS = "runs";
    public static final String MESSAGES = "messages";
    public static final String BATTLES = "battles";
    public static final String VOTES = "votes";
    public static final String SAVED_CHATS = "saved_chats";

    private static File file(Context c) {
        File d = new File(c.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return new File(d, "stats.json");
    }

    private static JSONObject load(Context c) {
        try {
            File f = file(c);
            if (!f.exists()) return new JSONObject();
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) f.length()];
            int n = in.read(buf);
            in.close();
            return new JSONObject(new String(buf, 0, Math.max(n, 0), "UTF-8"));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    public static int get(Context c, String key) {
        return load(c).optInt(key, 0);
    }

    public static void inc(Context c, String key) {
        try {
            JSONObject o = load(c);
            o.put(key, o.optInt(key, 0) + 1);
            FileOutputStream out = new FileOutputStream(file(c));
            out.write(o.toString().getBytes("UTF-8"));
            out.close();
        } catch (Exception ignored) {
        }
    }
}
