package com.heroes.gpt;

import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import java.util.ArrayList;
import java.util.List;

public class Orchestrator {

    public static final int STATUS_PENDING = 0;
    public static final int STATUS_RUNNING = 1;
    public static final int STATUS_DONE = 2;
    public static final int STATUS_FAILED = 3;
    public static final int STATUS_SKIPPED = 4;

    public static final String MODE_FAST = "fast";
    public static final String MODE_BALANCED = "balanced";
    public static final String MODE_DEEP = "deep";

    public interface Callback {
        void onStepChanged(int index);

        void onFinished(boolean allDone);

        default void onLive(int index, String header, String partial) { }
    }

    public static String currentMode(Context c) {
        String m = Stores.setting(c, "mode");
        return m.isEmpty() ? MODE_BALANCED : m;
    }

    public static void setMode(Context c, String mode) {
        Stores.setSetting(c, "mode", mode);
    }

    private static String styleFor(String mode) {
        if (MODE_FAST.equals(mode)) {
            return "\n\n⚡ نمط التنفيذ: سريع — أجب مباشرةً بأقصى سرعة وبدقة، دون شروح طويلة.";
        }
        if (MODE_DEEP.equals(mode)) {
            return "\n\n🧠 نمط التنفيذ: تفكير عميق — (1) حلّل المهمة والسياق بهدوء، (2) خطّط خطواتك بإيجاز، "
                    + "(3) أنجز العمل كاملًا بأعلى جودة، (4) راجع مخرجاتك ذاتيًا وصحّح أي ضعف، "
                    + "(5) أخرِج النتيجة النهائية فقط بصيغة منظمة وواضحة.";
        }
        return "\n\n⚖️ نمط التنفيذ: متوازن — فكّر فكرًا قصيرًا قبل الإجابة، ثم أنجز دورك بدقة وإيجاز محترف.";
    }

    public static String contextUpTo(Stores.Run run, int index) {
        StringBuilder sb = new StringBuilder();
        sb.append("المهمة الأصلية:\n").append(run.goal).append("\n\n");
        int budget = 3500;
        for (int i = 0; i < index && i < run.heroes.size(); i++) {
            Stores.Run.Result res = run.results.get(i);
            if (res.status != Orchestrator.STATUS_DONE || res.output.isEmpty()) continue;
            String out = res.output;
            if (out.length() > budget) out = out.substring(0, budget) + "…\n[اقتُطع جزء لطول النص]";
            if (sb.length() > 14000) {
                sb.append("[سياق مختصر لتسريع الفريق]\n\n");
            } else {
                sb.append("--- عمل ").append(run.heroes.get(i).name).append(" ---\n")
                  .append(out).append("\n\n");
            }
        }
        return sb.toString();
    }

    public static Provider pickProvider(Context c, Hero hero, int stepIndex) {
        List<Provider> providers = Stores.providers(c);
        List<Provider> usable = new ArrayList<>();
        for (Provider p : providers) {
            if (p.enabled && !p.base.trim().isEmpty() && (p.noKeyNeeded || !p.key.trim().isEmpty())) {
                usable.add(p);
            }
        }
        if (!"auto".equals(hero.providerId)) {
            for (Provider p : providers) {
                if (p.id.equals(hero.providerId)) return p;
            }
        }
        if (usable.isEmpty()) {
            Provider fallback = Provider.freeDefault();
            fallback.id = "fallback";
            return fallback;
        }
        return usable.get(stepIndex % usable.size());
    }

    public static void runRemaining(final Context c, final Stores.Run run, final Callback cb) {
        final Handler ui = new Handler(Looper.getMainLooper());
        final String mode = currentMode(c);
        new Thread(() -> {
            for (int i = run.stage; i < run.heroes.size(); i++) {
                final Hero hero = run.heroes.get(i);
                final int idx = i;
                if (!hero.enabled) {
                    run.results.get(i).status = STATUS_SKIPPED;
                    run.stage = i + 1;
                    Stores.saveRun(c, run);
                    ui.post(() -> cb.onStepChanged(idx));
                    continue;
                }
                final Stores.Run.Result res = run.results.get(i);
                res.status = STATUS_RUNNING;
                res.error = "";
                ui.post(() -> {
                    cb.onStepChanged(idx);
                    cb.onLive(idx, hero.emoji + " " + hero.name + " • 🧠 يفكّر ويخطّط…", "");
                });

                String lastErr = null;
                for (int attempt = 0; attempt < 3; attempt++) {
                    Provider p = pickProvider(c, hero, i + attempt);
                    String prompt = buildPrompt(run, hero, i, mode);
                    try {
                        String out = Api.chatLive(p, hero.system, prompt, (header, partial) ->
                                ui.post(() -> cb.onLive(idx,
                                        hero.emoji + " " + hero.name + " • ⚡ يعمل الآن", partial)));
                        res.output = out;
                        res.status = STATUS_DONE;
                        lastErr = null;
                        break;
                    } catch (Exception e) {
                        lastErr = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                        try {
                            Thread.sleep(1500L * (attempt + 1));
                        } catch (InterruptedException ie) { }
                    }
                }
                if (lastErr != null) {
                    res.status = STATUS_FAILED;
                    res.error = lastErr;
                }
                run.stage = i + 1;
                Stores.saveRun(c, run);
                ui.post(() -> {
                    cb.onLive(idx,
                            res.status == STATUS_DONE
                                    ? hero.emoji + " " + hero.name + " • ✓ أتمّ دوره"
                                    : hero.emoji + " " + hero.name + " • ⚠ توقف مؤقتًا",
                            res.status == STATUS_DONE ? res.output : res.error);
                    cb.onStepChanged(idx);
                    if (res.status == STATUS_DONE && idx == run.heroes.size() - 1) {
                        cb.onFinished(true);
                    }
                });
            }
            final boolean all = run.stage >= run.heroes.size();
            ui.post(() -> cb.onFinished(all));
        }).start();
    }

    private static String buildPrompt(Stores.Run run, Hero hero, int index, String mode) {
        return "فكرة المستخدم:\n" + run.goal
                + "\n\nما أنجزه من سبقوك في الفريق:\n" + contextUpTo(run, index)
                + "\n\nأنت الآن " + hero.name + " في فريق الأبطال. أنجز دورك المحدد في تعليماتك "
                + "على أعلى مستوى من الجودة والاحترافية، وبنفس لغة فكرة المستخدم."
                + styleFor(mode);
    }
}
