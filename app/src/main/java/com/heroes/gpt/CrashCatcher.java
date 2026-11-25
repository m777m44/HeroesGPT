package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;

public class CrashCatcher {

    private static File file(Activity a) {
        File d = new File(a.getFilesDir(), "data");
        if (!d.exists()) d.mkdirs();
        return new File(d, "crash.txt");
    }

    public static void install(final Activity a) {
        final Thread.UncaughtExceptionHandler prev = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((t, e) -> {
            append(a, "---- Crash ----\n" + stackOf(e) + "\n");
            if (prev != null) prev.uncaughtException(t, e);
        });
    }

    public static void append(Activity a, String text) {
        try {
            FileOutputStream out = new FileOutputStream(file(a), true);
            out.write(text.getBytes(StandardCharsets.UTF_8));
            out.close();
        } catch (Exception ignored) {
        }
    }

    public static void reportIfCrashed(final Activity a) {
        try {
            File f = file(a);
            if (!f.exists()) return;
            FileInputStream in = new FileInputStream(f);
            byte[] buf = new byte[(int) Math.min(f.length(), 12000)];
            int n = in.read(buf);
            in.close();
            f.delete();
            if (n <= 0) return;
            final String trace = new String(buf, 0, n, StandardCharsets.UTF_8).trim();
            if (trace.isEmpty()) return;

            TextView tv = new TextView(a);
            int pad = (int) (a.getResources().getDisplayMetrics().density * 16);
            tv.setPadding(pad, pad, pad, pad);
            tv.setTextSize(12);
            tv.setTextColor(a.getColor(R.color.text));
            tv.setText(trace.length() > 3500 ? trace.substring(trace.length() - 3500) : trace);
            ScrollView sv = new ScrollView(a);
            sv.addView(tv);

            new AlertDialog.Builder(a)
                    .setTitle(R.string.crash_title)
                    .setMessage(R.string.crash_msg)
                    .setView(sv)
                    .setPositiveButton(R.string.share, (d, w) ->
                            Utils.shareText(a, "HeroesGPT - crash report", trace))
                    .setNegativeButton(android.R.string.ok, null)
                    .show();
        } catch (Exception ignored) {
        }
    }

    public static void showErrorScreen(final Activity a, Throwable t) {
        append(a, "---- Startup error ----\n" + stackOf(t) + "\n");
        try {
            LinearLayout root = new LinearLayout(a);
            root.setOrientation(LinearLayout.VERTICAL);
            int pad = (int) (a.getResources().getDisplayMetrics().density * 24);
            root.setPadding(pad, pad * 2, pad, pad);

            TextView title = new TextView(a);
            title.setText(R.string.error_screen);
            title.setTextSize(20);
            title.setTypeface(null, android.graphics.Typeface.BOLD);
            title.setTextColor(a.getColor(R.color.danger));
            title.setGravity(android.view.Gravity.CENTER);
            root.addView(title);

            TextView msg = new TextView(a);
            msg.setText(t.getClass().getSimpleName() + ": " + t.getMessage() + "\n\n"
                    + a.getString(R.string.crash_msg));
            msg.setTextSize(14);
            msg.setTextColor(a.getColor(R.color.text));
            msg.setPadding(0, pad, 0, pad);
            root.addView(msg);

            Button share = new Button(a);
            share.setText(R.string.share);
            share.setOnClickListener(v ->
                    Utils.shareText(a, "HeroesGPT - startup error", stackOf(t)));
            root.addView(share);

            Button retry = new Button(a);
            retry.setText(R.string.retry);
            retry.setOnClickListener(v -> a.recreate());
            root.addView(retry);

            a.setContentView(root);
        } catch (Exception ignored) {
        }
    }

    private static String stackOf(Throwable t) {
        StringWriter sw = new StringWriter();
        t.printStackTrace(new PrintWriter(sw));
        return sw.toString();
    }
}
