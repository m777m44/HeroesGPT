package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
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
 * "هيروس الكل" — الواجهة الموحدة v8.0
 * زر واحد لكل شيء: دردشة + برمجة + بناء تطبيقات + فريق الأبطال (يعمل داخليًا وخفيةً).
 * شريط الأدوات: هيروس الكل (رئيسي) • المفاتيح • GitHub • بحث • إعدادات • التحديث.
 * مؤشر التفكير 💭 يعمل أثناء كل عملية توليد، مع إيقاف وإعادة توليد ونسخ.
 */
public class ConsoleActivity extends Activity {

    private static final int CTX_STEP_BUDGET = 3500;
    private static final int CTX_TOTAL_BUDGET = 14000;
    private static final int LIVE_TAIL = 2500;

    private final List<String[]> messages = new ArrayList<>(); // {role: user|ai, text}
    private final Handler ui = new Handler(Looper.getMainLooper());
    private ConsoleAdapter adapter;
    private Hero agent;
    private boolean busy = false;
    private String lastUserText = null;
    private boolean lastWasTeam = false;

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
        KeyConfig.refreshFromGithubAsync(this);
    }

    private void setup() {
        agent = Hero.make("⚡", "HEROESGPT", "");
        agent.providerId = "auto";
        agent.id = "heroesgpt";

        adapter = new ConsoleAdapter();
        ListView lv = findViewById(R.id.con_list);
        lv.setAdapter(adapter);
        lv.setOnItemLongClickListener((parent, view, position, id) -> {
            if (position >= 0 && position < messages.size()) {
                showMessageActions(position);
                return true;
            }
            return false;
        });

        TextView t = findViewById(R.id.con_title);
        t.setShadowLayer(22, 0, 0, 0x99D77757);

        messages.add(new String[]{"ai", getString(R.string.console_welcome)});
        adapter.notifyDataSetChanged();

        // شريط الأدوات الموحد — هيروس الكل رئيسي، لا مكتبة ولا فريق ولا أوضاع
        findViewById(R.id.con_heroes).setOnClickListener(v ->
                Toast.makeText(this, R.string.heroes_active, Toast.LENGTH_SHORT).show());
        findViewById(R.id.con_keys).setOnClickListener(v ->
                startActivity(new Intent(this, ProvidersActivity.class)));
        findViewById(R.id.con_github).setOnClickListener(v ->
                startActivity(new Intent(this, GithubActivity.class)));
        findViewById(R.id.con_search).setOnClickListener(v ->
                startActivity(new Intent(this, SearchActivity.class)));
        findViewById(R.id.con_settings).setOnClickListener(v -> showSettings());
        findViewById(R.id.con_update).setOnClickListener(v ->
                startActivity(new Intent(this, UpdateActivity.class)));

        findViewById(R.id.con_send).setOnClickListener(v -> onSend());
        findViewById(R.id.con_stop).setOnClickListener(v -> onStopClicked());
    }

    // ===== الإعدادات: وضع التفكير + حفظ الجلسة + مسح المحادثة =====
    private void showSettings() {
        String[] items = {
                getString(R.string.mode_fast),
                getString(R.string.mode_balanced),
                getString(R.string.mode_deep),
                getString(R.string.con_save_session),
                getString(R.string.con_clear)
        };
        new AlertDialog.Builder(this)
                .setTitle(R.string.settings_title)
                .setItems(items, (d, w) -> {
                    if (w <= 2) {
                        String mode = w == 0 ? Orchestrator.MODE_FAST
                                : w == 1 ? Orchestrator.MODE_BALANCED : Orchestrator.MODE_DEEP;
                        Orchestrator.setMode(this, mode);
                        Toast.makeText(this, getString(R.string.settings_mode_set, items[w]),
                                Toast.LENGTH_SHORT).show();
                    } else if (w == 3) {
                        saveSession();
                    } else {
                        clearChat();
                    }
                })
                .setNegativeButton(R.string.close, null)
                .show();
    }

    private void saveSession() {
        StringBuilder sb = new StringBuilder();
        for (String[] m : messages) {
            sb.append(m[0].equals("user") ? "🧑 أنت:\n" : "⚡ HEROESGPT:\n")
              .append(m[1]).append("\n\n");
        }
        Stores.saveChat(this, "جلسة " + new java.text.SimpleDateFormat("MM-dd HH:mm",
                java.util.Locale.US).format(new java.util.Date()), sb.toString());
        Toast.makeText(this, R.string.saved_ok, Toast.LENGTH_SHORT).show();
    }

    private void clearChat() {
        if (busy) {
            Toast.makeText(this, R.string.console_busy, Toast.LENGTH_SHORT).show();
            return;
        }
        messages.clear();
        messages.add(new String[]{"ai", getString(R.string.console_welcome)});
        lastUserText = null;
        lastWasTeam = false;
        adapter.notifyDataSetChanged();
    }

    // ===== إرسال — زر واحد "هيروس الكل" يقرر داخليًا: دردشة مباشرة أم عمل فريق داخلي =====
    private void onSend() {
        if (busy) {
            Toast.makeText(this, R.string.console_busy, Toast.LENGTH_SHORT).show();
            return;
        }
        EditText input = findViewById(R.id.con_input);
        String text = input.getText().toString().trim();
        if (text.isEmpty()) return;
        input.setText("");

        lastUserText = text;
        messages.add(new String[]{"user", text});
        adapter.notifyDataSetChanged();

        if (looksLikeTask(text)) {
            lastWasTeam = true;
            runInternalTeam(text);
        } else {
            lastWasTeam = false;
            runDirect(text);
        }
    }

    /** كشف المهام البرمجية/البناء — عندئذٍ يعمل فريق الأبطال داخليًا وخفيةً. */
    private static boolean looksLikeTask(String text) {
        String t = text.toLowerCase();
        String[] keys = {"ابني", "ابنِ", "أنشئ", "انشئ", "اصنع", "صمم", "برمج", "اكتب تطبيق",
                "اكتب سكربت", "أنشئ تطبيق", "انشئ تطبيق", "build", "create", "develop",
                "make an app", "write an app", "write a script", "تطبيق ", "موقع ", "سكربت"};
        for (String k : keys) if (t.contains(k)) return true;
        return false;
    }

    private void setBusy(boolean b) {
        busy = b;
        findViewById(R.id.con_stop).setVisibility(b ? View.VISIBLE : View.GONE);
        Button send = findViewById(R.id.con_send);
        send.setEnabled(!b);
        send.setAlpha(b ? 0.5f : 1f);
    }

    private void onStopClicked() {
        Api.CANCEL.set(true);
        Toast.makeText(this, R.string.con_stopping, Toast.LENGTH_SHORT).show();
    }

    private void showMessageActions(int position) {
        final String[] m = messages.get(position);
        boolean isAi = m[0].equals("ai");
        List<String> opts = new ArrayList<>();
        opts.add(getString(R.string.search_copy));
        boolean canRegen = isAi && !busy && lastUserText != null
                && position == messages.size() - 1;
        if (canRegen) opts.add(getString(R.string.con_regen));
        new AlertDialog.Builder(this)
                .setTitle(isAi ? "⚡ HEROESGPT" : "🧑 رسالتك")
                .setItems(opts.toArray(new String[0]), (d, w) -> {
                    if (opts.get(w).equals(getString(R.string.con_regen))) {
                        regenerate();
                    } else {
                        Utils.copy(this, m[1]);
                        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
                    }
                })
                .setNegativeButton(R.string.close, null)
                .show();
    }

    private void regenerate() {
        if (busy || lastUserText == null) return;
        // أزل آخر رسالة ذكاء اصطناعي ثم أعد العمل
        if (!messages.isEmpty() && messages.get(messages.size() - 1)[0].equals("ai")) {
            messages.remove(messages.size() - 1);
            adapter.notifyDataSetChanged();
        }
        if (lastWasTeam) runInternalTeam(lastUserText);
        else runDirect(lastUserText);
    }

    private void beginThinking() {
        Api.CANCEL.set(false);
        setBusy(true);
        ThinkingView th = findViewById(R.id.con_thinking);
        th.setGlyph("🤔");
        th.start();
    }

    private void endThinking() {
        ThinkingView th = findViewById(R.id.con_thinking);
        th.stop();
        setBusy(false);
    }

    private static boolean isStopped(Exception e) {
        return String.valueOf(e.getMessage()).contains("GENERATION_STOPPED");
    }

    // ===== دردشة/برمجة مباشرة — HEROESGPT مع تدوير المزوّدين وبث حي =====
    private void runDirect(String text) {
        beginThinking();
        final int ph = addAi("⚡ HEROESGPT • 🤔 يفكّر…");
        new Thread(() -> {
            String sys = systemFor();
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
                                ? "⚡ HEROESGPT • 🤔 يفكّر…"
                                : "⚡ HEROESGPT • ⏳ يكتب الآن…\n\n" + tail;
                        updateAi(ph, shown);
                    });
                } catch (Exception e) {
                    if (isStopped(e)) break;
                    lastErr = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                    try { Thread.sleep(1200L * (attempt + 1)); } catch (InterruptedException ie) { }
                }
            }
            if (Api.CANCEL.get() && out == null) {
                updateAi(ph, getString(R.string.con_stopped));
            } else if (out != null) {
                updateAi(ph, out);
            } else {
                updateAi(ph, "⚠️ " + getString(R.string.chat_error, String.valueOf(lastErr)));
            }
            ui.post(() -> { endThinking(); adapter.notifyDataSetChanged(); });
        }).start();
    }

    private String systemFor() {
        StringBuilder sb = new StringBuilder();
        sb.append("أنت HEROESGPT ⚡ — وكيل ذكاء اصطناعي متطور يعمل داخل تطبيق HeroesGPT في وضع \"هيروس الكل\": ")
          .append("واجهة واحدة تجمع الدردشة والبرمجة وبناء التطبيقات. ")
          .append("تردد بلغة المستخدم نفسها (العربية غالبًا)، بإجابات دقيقة ومنظمة واحترافية بدون حشو. ")
          .append("عند كتابة كود، ضعه داخل كتل ``` بشكل صحيح مع تحديد اللغة.")
          .append(" إذا كان الطلب برمجيًا فاكتب كودًا كاملًا جاهزًا للتشغيل؛ وإذا كان طلب بناء تطبيق فقدم خطة وملفات كاملة مع تعليمات التشغيل.");
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

    // ===== الفريق الداخلي (خفي) — مخطط ← باني ← مراجع، يُستخدم للمهام البرمجية =====
    private void runInternalTeam(String goal) {
        beginThinking();
        final int ph = addAi("🤔 HEROESGPT • الفريق الداخلي يعمل…");
        new Thread(() -> {
            final List<Hero> heroes = Stores.heroes(this);
            Hero planner = heroes.size() > 0 ? heroes.get(0) : Hero.make("🧠", "المخطط", "");
            Hero builder = heroes.size() > 1 ? heroes.get(1) : Hero.make("🛠", "الباني", "");
            Hero reviewer = heroes.size() > 2 ? heroes.get(heroes.size() - 1) : Hero.make("🎓", "المراجع", "");
            final String modeStyle = styleFor(Orchestrator.currentMode(this));

            StringBuilder ctx = new StringBuilder("مهمة المستخدم:\n").append(goal).append("\n\n");
            String plan = null, build = null, review = null;

            plan = stepAgent(ph, planner, "🧠 المخطط", "خطط المهمة بدقة: المتطلبات، البنية، الملفات، خطوات التنفيذ. كن مختصرًا ومحترفًا.",
                    goal, ctx, modeStyle, "المخطط");
            if (plan != null && ctx.length() < CTX_TOTAL_BUDGET) {
                ctx.append("--- الخطة ---\n").append(trim(plan)).append("\n\n");
            }
            if (Api.CANCEL.get()) { finishTeam(ph, null, plan, null); return; }

            build = stepAgent(ph, builder, "🛠 الباني", "نفّذ الخطة: اكتب كل الملفات/الكود كاملًا جاهزًا للتشغيل داخل كتل ``` مع تحديد مسار كل ملف.",
                    goal, ctx, modeStyle, "الباني");
            if (build != null && ctx.length() < CTX_TOTAL_BUDGET) {
                ctx.append("--- التنفيذ ---\n").append(trim(build)).append("\n\n");
            }
            if (Api.CANCEL.get()) { finishTeam(ph, null, plan, build); return; }

            review = stepAgent(ph, reviewer, "🎓 المراجع", "راجع التنفيذ: أخطاء، تحسينات، ملاحظات نهائية قصيرة. إن كان سليمًا قل ذلك.",
                    goal, ctx, modeStyle, "المراجع");

            finishTeam(ph, review, plan, build);
        }).start();
    }

    private String stepAgent(int ph, Hero h, String fallbackName, String rolePrompt,
                             String goal, StringBuilder ctx, String modeStyle, String stageLabel) {
        ui.post(() -> updateAi(ph, "🤔 HEROESGPT • الفريق الداخلي: " + stageLabel + " يعمل…"));
        StringBuilder prompt = new StringBuilder();
        prompt.append("مهمة المستخدم:\n").append(goal).append("\n\n");
        if (ctx.length() < CTX_TOTAL_BUDGET) {
            prompt.append("سياق العمل:\n").append(ctx).append("\n");
        }
        prompt.append("\nدورك: ").append(rolePrompt)
              .append("\nأنت الآن ").append(h.name).append(" في فريق HEROESGPT الداخلي. أنجز دورك بأعلى جودة وبنفس لغة المستخدم.")
              .append(modeStyle);

        String out = null;
        String lastErr = null;
        for (int a = 0; a < 3 && out == null; a++) {
            Provider p = Orchestrator.pickProvider(this, h, a);
            try {
                out = Api.chatLive(p, h.system, prompt.toString(), null);
            } catch (Exception e) {
                if (isStopped(e)) break;
                lastErr = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                try { Thread.sleep(1200L * (a + 1)); } catch (InterruptedException ie) { }
            }
        }
        if (out == null && !Api.CANCEL.get()) {
            final String e0 = lastErr;
            ui.post(() -> updateAi(ph, "⚠️ " + getString(R.string.chat_error, String.valueOf(e0))));
        }
        return out;
    }

    private void finishTeam(int ph, String review, String plan, String build) {
        StringBuilder finalOut = new StringBuilder();
        if (Api.CANCEL.get()) {
            finalOut.append(getString(R.string.con_stopped));
            if (build != null) finalOut.append("\n\n--- ما أُنجز قبل الإيقاف ---\n").append(build);
        } else if (build != null) {
            if (plan != null && plan.length() <= 1200) {
                finalOut.append("📋 الخطة:\n").append(plan).append("\n\n");
            }
            finalOut.append(build);
            if (review != null && review.length() <= 800) {
                finalOut.append("\n\n🎓 مراجعة نهائية:\n").append(review);
            }
            finalOut.append("\n\n⚙️ ").append(getString(R.string.con_team_note));
        } else {
            finalOut.append("⚠️ ").append(getString(R.string.chat_error, "تعذّر إنجاز المهمة — حاول مجددًا"));
        }
        final String out = finalOut.toString();
        ui.post(() -> {
            updateAi(ph, out);
            endThinking();
            adapter.notifyDataSetChanged();
        });
    }

    private static String trim(String s) {
        return s.length() > CTX_STEP_BUDGET ? s.substring(0, CTX_STEP_BUDGET) + "…\n[اقتُطع جزء لطول النص]" : s;
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
            tv.setTextColor(getColor(user ? R.color.text : R.color.accent));
            tv.setBackgroundResource(user ? R.drawable.bg_card : R.drawable.bg_chip);
            tv.setTextIsSelectable(true);
            tv.setText(user ? "🧑 أنت:\n" + m[1] : m[1]);
            return tv;
        }
    }
}
