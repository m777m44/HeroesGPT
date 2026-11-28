package com.heroes.gpt;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * الواجهة الموحدة — HEROESGPT ⚡
 * واجهة واحدة بأسلوب Claude Code: دردشة + برمجة + بناء تطبيقات + فريق الأبطال،
 * وكل الأدوات (الفريق، المفاتيح، GitHub، المكتبة، التحديث) في شريط واحد أعلى الشاشة.
 */
public class ConsoleActivity extends Activity {

    private static final String MODE_CHAT = "chat";
    private static final String MODE_CODE = "code";
    private static final String MODE_APPS = "apps";
    private static final String MODE_TEAM = "team";

    private static final int CTX_STEP_BUDGET = 3500;
    private static final int CTX_TOTAL_BUDGET = 14000;
    private static final int LIVE_TAIL = 2500;

    private final List<String[]> messages = new ArrayList<>(); // {role: user|ai, text}
    private final Handler ui = new Handler(Looper.getMainLooper());
    private ConsoleAdapter adapter;
    private Hero agent;          // شخصية HEROESGPT الافتراضية
    private String mode = MODE_CHAT;
    private boolean busy = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        CrashCatcher.install(this);
        try {
            setContentView(R.layout.activity_console);
            setup();
            CrashCatcher.reportIfCrashed(this);
        } catch (Throwable t) {
            CrashCatcher.showErrorScreen(this, t);
            return;
        }
        KeyVault.autoRestoreIfEmpty(this);
    }

    private void setup() {
        agent = Hero.make("⚡", "HEROESGPT", "");
        agent.providerId = "auto";
        agent.id = "heroesgpt";

        adapter = new ConsoleAdapter();
        ListView lv = findViewById(R.id.con_list);
        lv.setAdapter(adapter);

        TextView t = findViewById(R.id.con_title);
        t.setShadowLayer(22, 0, 0, 0x99E6284C);

        messages.add(new String[]{"ai", getString(R.string.console_welcome)});
        adapter.notifyDataSetChanged();

        // شريط الأدوات الموحد — بدون زر السورسات
        findViewById(R.id.con_team).setOnClickListener(v ->
                startActivity(new Intent(this, ArenaHomeActivity.class)));
        findViewById(R.id.con_keys).setOnClickListener(v ->
                startActivity(new Intent(this, ProvidersActivity.class)));
        findViewById(R.id.con_github).setOnClickListener(v ->
                startActivity(new Intent(this, GithubActivity.class)));
        findViewById(R.id.con_library).setOnClickListener(v ->
                startActivity(new Intent(this, RepoLibraryActivity.class)));
        findViewById(R.id.con_update).setOnClickListener(v ->
                startActivity(new Intent(this, UpdateActivity.class)));

        findViewById(R.id.con_mode_chat).setOnClickListener(v -> setMode(MODE_CHAT));
        findViewById(R.id.con_mode_code).setOnClickListener(v -> setMode(MODE_CODE));
        findViewById(R.id.con_mode_apps).setOnClickListener(v -> setMode(MODE_APPS));
        findViewById(R.id.con_mode_team).setOnClickListener(v -> setMode(MODE_TEAM));
        setModeUi();

        findViewById(R.id.con_send).setOnClickListener(v -> onSend());
    }

    private void setMode(String m) {
        if (busy) {
            Toast.makeText(this, R.string.console_busy, Toast.LENGTH_SHORT).show();
            return;
        }
        mode = m;
        setModeUi();
    }

    private void setModeUi() {
        int on = R.drawable.bg_pill_on;
        int off = R.drawable.bg_pill;
        ((TextView) findViewById(R.id.con_mode_chat)).setBackgroundResource(mode.equals(MODE_CHAT) ? on : off);
        ((TextView) findViewById(R.id.con_mode_code)).setBackgroundResource(mode.equals(MODE_CODE) ? on : off);
        ((TextView) findViewById(R.id.con_mode_apps)).setBackgroundResource(mode.equals(MODE_APPS) ? on : off);
        ((TextView) findViewById(R.id.con_mode_team)).setBackgroundResource(mode.equals(MODE_TEAM) ? on : off);
    }

    private String systemFor(String m) {
        StringBuilder sb = new StringBuilder();
        sb.append("أنت HEROESGPT ⚡ — وكيل ذكاء اصطناعي متطور يعمل داخل تطبيق HeroesGPT. ")
          .append("تردد بلغة المستخدم نفسها (العربية غالبًا)، بإجابات دقيقة ومنظمة واحترافية بدون حشو. ")
          .append("عند كتابة كود، ضعه داخل كتل ``` بشكل صحيح مع تحديد اللغة.");
        if (MODE_CODE.equals(m)) {
            sb.append("\n\nدورك الحالي: مهندس برمجيات خبير. اكتب كودًا كاملًا نظيفًا حديثًا جاهزًا للتشغيل، ")
              .append("مع شرح موجز للبنية والقرارات المهمة، وحلّ الأخطاء بدقة.");
        } else if (MODE_APPS.equals(m)) {
            sb.append("\n\nدورك الحالي: باني تطبيقات محترف. حوّل فكرة المستخدم إلى تطبيق كامل: ")
              .append("خطة موجزة، هيكل الملفات، ثم كل الملفات كاملة داخل كتل كود مع تحديد مسار كل ملف، ")
              .append("وتعليمات تشغيل واضحة في النهاية.");
        } else {
            sb.append("\n\nدورك الحالي: مساعد ذكي شامل — دردشة، معرفة، تحليل، كتابة، وأفكار إبداعية.");
        }
        sb.append(styleFor(Orchestrator.currentMode(this)));
        return sb.toString();
    }

    private static String styleFor(String m) {
        if (Orchestrator.MODE_FAST.equals(m)) {
            return "\n\n⚡ أسلوب الرد: سريع ومباشر ودقيق، بدون شروحات طويلة.";
        }
        if (Orchestrator.MODE_DEEP.equals(m)) {
            return "\n\n🧠 أسلوب الرد: تفكير عميق — حلّل بهدوء، خطط خطواتك، أنجز بأعلى جودة، راجع نفسك، ثم أخرج النتيجة النهائية فقط.";
        }
        return "\n\n⚖️ أسلوب الرد: متوازن — فكرة قصيرة قبل الإجابة ثم إنجاز بإيجاز محترف.";
    }

    private void onSend() {
        if (busy) {
            Toast.makeText(this, R.string.console_busy, Toast.LENGTH_SHORT).show();
            return;
        }
        EditText input = findViewById(R.id.con_input);
        String text = input.getText().toString().trim();
        if (text.isEmpty()) return;
        input.setText("");

        messages.add(new String[]{"user", text});
        adapter.notifyDataSetChanged();

        if (MODE_TEAM.equals(mode)) runTeam(text);
        else runDirect(text);
    }

    // ===== وضع الدردشة/البرمجة/التطبيقات — HEROESGPT مباشرة مع تدوير المزوّدين =====
    private void runDirect(String text) {
        busy = true;
        final int ph = addAi("⚡ HEROESGPT • 🧠 يفكّر…");
        new Thread(() -> {
            String sys = systemFor(mode);
            String ctx = buildChatContext(text);
            String lastErr = null;
            String out = null;
            for (int attempt = 0; attempt < 3 && out == null; attempt++) {
                Provider p = Orchestrator.pickProvider(this, agent, attempt);
                try {
                    out = Api.chatLive(p, sys, ctx, (header, partial) -> {
                        String tail = partial == null ? "" : partial;
                        if (tail.length() > LIVE_TAIL) tail = "…\n" + tail.substring(tail.length() - LIVE_TAIL);
                        String shown = tail.isEmpty()
                                ? "⚡ HEROESGPT • 🧠 يفكّر…"
                                : "⚡ HEROESGPT • ⏳ يكتب الآن…\n\n" + tail;
                        updateAi(ph, shown);
                    });
                } catch (Exception e) {
                    lastErr = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                    try { Thread.sleep(1200L * (attempt + 1)); } catch (InterruptedException ie) { }
                }
            }
            if (out != null) updateAi(ph, out);
            else updateAi(ph, "⚠️ " + getString(R.string.chat_error, String.valueOf(lastErr)));
            busy = false;
            ui.post(() -> adapter.notifyDataSetChanged());
        }).start();
    }

    private String buildChatContext(String latest) {
        StringBuilder sb = new StringBuilder("المحادثة حتى الآن:\n\n");
        for (String[] m : messages) {
            if (m[0].equals("ai") && m[1].startsWith("⚡ HEROESGPT • ")) continue; // بث غير مكتمل
            sb.append(m[0].equals("user") ? "المستخدم: " : "HEROESGPT: ")
              .append(m[1].length() > 2000 ? m[1].substring(0, 2000) + "…" : m[1])
              .append("\n\n");
            if (sb.length() > 12000) break;
        }
        sb.append("المستخدم: ").append(latest)
          .append("\n\nردّ على آخر رسالة للمستخدم ردًّا مباشرًا كـ HEROESGPT.");
        return sb.toString();
    }

    // ===== وضع فريق الأبطال — كل الأبطال يعملون داخل المحادثة =====
    private void runTeam(String goal) {
        busy = true;
        final List<Hero> heroes = Stores.heroes(this);
        if (heroes.isEmpty()) {
            messages.add(new String[]{"ai", "⚠️ لا يوجد أبطال — افتح ⚔️ الفريق وأنشئ فريقك"});
            adapter.notifyDataSetChanged();
            busy = false;
            return;
        }
        new Thread(() -> {
            StringBuilder ctx = new StringBuilder("فكرة المستخدم:\n").append(goal).append("\n\n");
            final String modeStyle = styleFor(Orchestrator.currentMode(this));
            boolean anyDone = false;
            for (int i = 0; i < heroes.size(); i++) {
                Hero h = heroes.get(i);
                if (!h.enabled) continue;
                final int ph = addAi(h.emoji + " " + h.name + " • 🧠 يفكّر…");
                StringBuilder prompt = new StringBuilder();
                prompt.append("فكرة المستخدم:\n").append(goal).append("\n\n");
                if (ctx.length() < CTX_TOTAL_BUDGET) {
                    prompt.append("عمل من سبقوك في الفريق:\n").append(ctx);
                } else {
                    prompt.append("[سياق مختصر لتسريع الفريق]\n");
                }
                prompt.append("\nأنت الآن ").append(h.name).append(" في فريق الأبطال. أنجز دورك المحدد في تعليماتك ")
                      .append("على أعلى مستوى من الجودة والاحترافية، وبنفس لغة فكرة المستخدم.")
                      .append(modeStyle);

                String out = null;
                String lastErr = null;
                for (int a = 0; a < 3 && out == null; a++) {
                    Provider p = Orchestrator.pickProvider(this, h, i + a);
                    try {
                        out = Api.chatLive(p, h.system, prompt.toString(), (header, partial) -> {
                            String tail = partial == null ? "" : partial;
                            if (tail.length() > LIVE_TAIL) tail = "…\n" + tail.substring(tail.length() - LIVE_TAIL);
                            updateAi(ph, h.emoji + " " + h.name + " • ⚡ يعمل الآن\n\n" + tail);
                        });
                    } catch (Exception e) {
                        lastErr = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                        try { Thread.sleep(1200L * (a + 1)); } catch (InterruptedException ie) { }
                    }
                }
                if (out != null) {
                    anyDone = true;
                    updateAi(ph, out);
                    if (ctx.length() < CTX_TOTAL_BUDGET) {
                        String trimmed = out.length() > CTX_STEP_BUDGET ? out.substring(0, CTX_STEP_BUDGET) + "…\n[اقتُطع جزء لطول النص]" : out;
                        ctx.append("--- عمل ").append(h.name).append(" ---\n").append(trimmed).append("\n\n");
                    }
                } else {
                    updateAi(ph, h.emoji + " " + h.name + " • ⚠ توقّف مؤقتًا: " + lastErr);
                }
            }
            final boolean done = anyDone;
            ui.post(() -> {
                if (done) messages.add(new String[]{"ai", "✅ الفريق أنهى المهمة. اكتب فكرة جديدة أو حوّل الوضع إلى 💬 دردشة للمتابعة."});
                adapter.notifyDataSetChanged();
            });
            busy = false;
        }).start();
    }

    private int addAi(String text) {
        messages.add(new String[]{"ai", text});
        ui.post(() -> adapter.notifyDataSetChanged());
        return messages.size() - 1;
    }

    private void updateAi(int idx, String text) {
        if (idx >= 0 && idx < messages.size()) {
            messages.get(idx)[1] = text;
            ui.post(() -> adapter.notifyDataSetChanged());
        }
    }

    private class ConsoleAdapter extends BaseAdapter {
        @Override
        public int getCount() { return messages.size(); }

        @Override
        public Object getItem(int position) { return messages.get(position); }

        @Override
        public long getItemId(int position) { return position; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            String[] m = messages.get(position);
            boolean user = m[0].equals("user");
            TextView tv = convertView instanceof TextView
                    ? (TextView) convertView : new TextView(ConsoleActivity.this);
            int pad = (int) (getResources().getDisplayMetrics().density * 12);
            tv.setPadding(pad, pad, pad, pad);
            tv.setTextSize(14);
            tv.setTextColor(getColor(user ? R.color.text : R.color.gold));
            tv.setBackgroundResource(user ? R.drawable.bg_card : R.drawable.bg_chip);
            tv.setTextIsSelectable(true);
            tv.setText(user ? "🫵 أنت:\n" + m[1] : m[1]);
            return tv;
        }
    }
}
