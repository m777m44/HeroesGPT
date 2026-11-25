package com.heroes.gpt;

import android.content.Context;
import android.content.Intent;
import android.net.Uri;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class Updater {

    public static final String MANIFEST_URL =
            "https://raw.githubusercontent.com/m777m44/HeroesGPT/main/latest.json";
    public static final String APK_URL =
            "https://github.com/m777m44/HeroesGPT/releases/latest/download/HeroesGPT.apk";
    public static final String APK_NAME = "HeroesGPT.apk";

    public static class Info {
        public int versionCode;
        public String versionName = "";
        public String notes = "";
    }

    public interface Progress {
        void onProgress(int percent);
    }

    public static Info check() throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL(MANIFEST_URL).openConnection();
        c.setConnectTimeout(15000);
        c.setReadTimeout(15000);
        InputStream is = c.getResponseCode() >= 400 ? c.getErrorStream() : c.getInputStream();
        String body = read(is);
        c.disconnect();
        if (body.isEmpty()) throw new Exception("Empty update manifest");
        JSONObject o = new JSONObject(body);
        Info i = new Info();
        i.versionCode = o.optInt("versionCode", 0);
        i.versionName = o.optString("versionName", "");
        i.notes = o.optString("notes", "");
        return i;
    }

    public static int currentVersionCode(Context ctx) {
        try {
            return ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).versionCode;
        } catch (Exception e) {
            return 0;
        }
    }

    public static String currentVersionName(Context ctx) {
        try {
            return ctx.getPackageManager().getPackageInfo(ctx.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }

    public static File apkFile(Context ctx) {
        File dir = new File(ctx.getFilesDir(), "update");
        if (!dir.exists()) dir.mkdirs();
        return new File(dir, APK_NAME);
    }

    public static File download(Context ctx, Progress cb) throws Exception {
        File out = apkFile(ctx);
        HttpURLConnection c = (HttpURLConnection) new URL(APK_URL).openConnection();
        c.setConnectTimeout(20000);
        c.setReadTimeout(60000);
        c.setInstanceFollowRedirects(true);
        int code = c.getResponseCode();
        if (code >= 400) {
            c.disconnect();
            throw new Exception("HTTP " + code);
        }
        InputStream is = c.getInputStream();
        long total = c.getContentLengthLong();
        if (total <= 0) total = c.getContentLength();
        FileOutputStream os = new FileOutputStream(out);
        byte[] buf = new byte[8192];
        long done = 0;
        int last = -1;
        int n;
        while ((n = is.read(buf)) > 0) {
            os.write(buf, 0, n);
            done += n;
            if (total > 0 && cb != null) {
                int pct = (int) (done * 100 / total);
                if (pct != last) {
                    last = pct;
                    final int p = pct;
                    cb.onProgress(p);
                }
            }
        }
        os.close();
        is.close();
        c.disconnect();
        return out;
    }

    public static void install(Context ctx) {
        File apk = apkFile(ctx);
        if (!apk.exists()) return;
        Uri uri = Uri.parse("content://com.heroes.gpt.apk/" + APK_NAME);
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(uri, "application/vnd.android.package-archive");
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        ctx.startActivity(i);
    }

    private static String read(InputStream is) throws Exception {
        if (is == null) return "";
        byte[] buf = new byte[8192];
        StringBuilder sb = new StringBuilder();
        int n;
        while ((n = is.read(buf)) > 0) {
            sb.append(new String(buf, 0, n, "UTF-8"));
        }
        is.close();
        return sb.toString();
    }
}
