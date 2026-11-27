package com.heroes.gpt;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.ViewGroup;
import android.webkit.ConsoleMessage;
import android.webkit.WebChromeClient;
import android.webkit.WebView;
import android.webkit.WebSettings;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;

/**
 * ▶ مشغّل السكربتات (v6.9)
 * يشغّل مخرجات فريق الأبطال بعد اكتمال برمجتها:
 *  - HTML/JS/CSS داخل WebView مع التقاط رسائل console
 *  - سكربتات Shell عبر مفسّر النظام sh مع مهلة أمان
 *  - بقية اللغات: معاينة ونسخ فقط (لا يوجد مفسّر مدمج لها)
 */
public class ScriptRunnerActivity extends Activity {

    private TextView console;
    private WebView web;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private volatile Process shellProc;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        String code = getIntent().getStringExtra("code");
        String codeFile = getIntent().getStringExtra("code_file");
        if ((code == null || code.isEmpty()) && codeFile != null) {
            try {
                byte[] b = java.nio.file.Files.readAllBytes(new File(codeFile).toPath());
                code = new String(b, StandardCharsets.UTF_8);
                new File(codeFile).delete();
            } catch (Exception ignored) { }
        }
        String title = getIntent().getStringExtra("title");
        String ext = getIntent().getStringExtra("ext");
        if (code == null) code = "";
        if (title == null || title.isEmpty()) title = "script";
        if (ext == null) ext = "";
        final String fExt = ext.toLowerCase();

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(0xFF07070B);

        TextView head = new TextView(this);
        head.setText("▶ " + title);
        head.setTextColor(0xFFFF2E4C);
        head.setTextSize(16);
        head.setPadding(40, 36, 40, 20);
        root.addView(head);

        TextView hint = new TextView(this);
        hint.setText(runnableLabel(fExt));
        hint.setTextColor(0xFF8E8BA3);
        hint.setTextSize(12);
        hint.setPadding(40, 0, 40, 16);
        root.addView(hint);

        boolean isWeb = fExt.equals("html") || fExt.equals("htm") || fExt.equals("js");
        if (isWeb) {
            web = new WebView(this);
            WebSettings st = web.getSettings();
            st.setJavaScriptEnabled(true);
            st.setAllowFileAccess(false);
            st.setAllowContentAccess(false);
            st.setDomStorageEnabled(true);
            web.setWebChromeClient(new WebChromeClient() {
                @Override
                public boolean onConsoleMessage(ConsoleMessage m) {
                    appendLine("🟣 " + m.message()
                            + (m.lineNumber() > 0 ? "  (سطر " + m.lineNumber() + ")" : ""));
                    return true;
                }
            });
            root.addView(web, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, 0, 1.0f));
        }

        TextView consoleTitle = new TextView(this);
        consoleTitle.setText("🖥 المخرجات");
        consoleTitle.setTextColor(0xFF9D4EDD);
        consoleTitle.setTextSize(13);
        consoleTitle.setPadding(40, 20, 40, 8);
        root.addView(consoleTitle);

        ScrollView sv = new ScrollView(this);
        sv.setBackgroundColor(0xFF12121C);
        console = new TextView(this);
        console.setTypeface(android.graphics.Typeface.MONOSPACE);
        console.setTextColor(0xFFEDEBF4);
        console.setTextSize(13);
        console.setPadding(28, 24, 28, 24);
        console.setTextIsSelectable(true);
        sv.addView(console);
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, isWeb ? 0.35f : 1.0f);
        int pad = (int) (12 * getResources().getDisplayMetrics().density);
        clp.setMargins(pad, 0, pad, pad);
        root.addView(sv, clp);

        setContentView(root);

        if (isWeb) {
            appendLine("▶ جارٍ التشغيل…");
            if (fExt.equals("js")) {
                String page = "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        + "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                        + "<style>body{background:#12121C;color:#EDEBF4;font-family:monospace;padding:12px;}"
                        + "</style></head><body><div id='out'></div><script>"
                        + "var __out=document.getElementById('out');"
                        + "function __w(t){var d=document.createElement('div');d.textContent=t;__out.appendChild(d);}"
                        + "(function(){var cl=console.log;console.log=function(){__w([].slice.call(arguments).join(' '));cl.apply(console,arguments);};"
                        + "console.info=console.log;console.warn=console.log;console.error=console.log;})();"
                        + "</script><script>\n" + code + "\n</script></body></html>";
                web.loadDataWithBaseURL(null, page, "text/html", "utf-8", null);
            } else {
                appendLine("▶ تم عرض الصفحة — رسائل console تظهر أسفل.");
                web.loadDataWithBaseURL(null, code, "text/html", "utf-8", null);
            }
        } else if (fExt.equals("sh") || fExt.equals("bash") || fExt.equals("shell") || fExt.equals("command")) {
            runShell(code);
        } else {
            appendLine("ℹ هذه اللغة (" + (fExt.isEmpty() ? "غير معروفة" : fExt)
                    + ") لا يوجد لها مفسّر مدمج في النظام.");
            appendLine("✅ المعاينة والنسخ متاحان — والتشغيل المباشر يعمل لسكربتات HTML / JS / Shell.");
        }
    }

    private String runnableLabel(String ext) {
        if (ext.equals("html") || ext.equals("htm")) return "🌐 صفحة ويب — تشغيل حي داخل التطبيق";
        if (ext.equals("js")) return "📜 جافاسكربت — تشغيل حي مع التقاط console";
        if (ext.equals("sh") || ext.equals("bash")) return "🐚 سكربت Shell — تشغيل عبر مفسّر النظام";
        return "📄 معاينة فقط — لا يوجد مفسّر مدمج لهذه اللغة على أندرويد";
    }

    private void runShell(final String code) {
        appendLine("▶ تشغيل السكربت عبر sh…");
        new Thread(() -> {
            try {
                File f = new File(getCacheDir(), "heroes_script.sh");
                java.io.FileOutputStream fo = new java.io.FileOutputStream(f);
                fo.write(code.getBytes(StandardCharsets.UTF_8));
                fo.close();

                ProcessBuilder pb = new ProcessBuilder("sh", f.getAbsolutePath());
                pb.redirectErrorStream(true);
                Process pr = pb.start();
                shellProc = pr;

                BufferedReader r = new BufferedReader(
                        new InputStreamReader(pr.getInputStream(), StandardCharsets.UTF_8));
                final StringBuilder sb = new StringBuilder();
                String line;
                while ((line = r.readLine()) != null) {
                    sb.append(line).append('\n');
                    if (sb.length() > 100_000) { sb.append("… (تم اقتطاع المخرجات الطويلة)"); break; }
                }
                final boolean timedOut = !pr.waitFor(15, java.util.concurrent.TimeUnit.SECONDS);
                if (timedOut) pr.destroyForcibly();
                final int codeVal = timedOut ? -1 : pr.exitValue();
                f.delete();

                ui.post(() -> {
                    if (sb.length() > 0) appendLine(sb.toString().trim());
                    appendLine(timedOut ? "⏱ أُوقِف السكربت بعد مهلة 15 ثانية (حلقة لا نهائية؟)"
                            : (codeVal == 0 ? "✅ اكتمل التنفيذ بنجاح" : "⚠ انتهى التنفيذ برمز " + codeVal));
                });
            } catch (Exception e) {
                final String msg = e.getMessage();
                ui.post(() -> appendLine("⚠ فشل التشغيل: " + msg));
            }
        }).start();
    }

    private void appendLine(final String s) {
        ui.post(() -> {
            if (console != null) console.append(s + "\n");
        });
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.loadUrl("about:blank");
            web.destroy();
            web = null;
        }
        if (shellProc != null) shellProc.destroyForcibly();
        super.onDestroy();
    }
}
