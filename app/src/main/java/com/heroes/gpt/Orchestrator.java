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

    public interface Callback {
        void onStepChanged(int index);

        void onFinished(boolean allDone);
    }

    public static String contextUpTo(Stores.Run run, int index) {
        StringBuilder sb = new StringBuilder();
        sb.append("المهمة الأصلية:\n").append(run.goal).append("\n\n");
        int budget = 6000;
        for (int i = 0; i < index && i < run.heroes.size(); i++) {
            Stores.Run.Result res = run.results.get(i);
            if (res.status != Orchestrator.STATUS_DONE || res.output.isEmpty()) continue;
            String out = res.output;
            if (out.length() > budget) out = out.substring(0, budget) + "…\n[اقتُطع جزء لطول النص]";
            sb.append("--- عمل ").append(run.heroes.get(i).name).append(" ---\n")
              .append(out).append("\n\n");
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
                ui.post(() -> cb.onStepChanged(idx));

                Provider p = pickProvider(c, hero, i);
                String prompt = "فكرة المستخدم:\n" + run.goal
                        + "\n\nما أنجزه من سبقوك في الفريق:\n" + contextUpTo(run, i)
                        + "\n\nأنت الآن ".concat(hero.name).concat(" في فريق الأبطال. أنجز دورك المحدد في تعليماتك على أعلى مستوى من الجودة والمهنية، وبنفس لغة فكرة المستخدم.");
                try {
                    String out = Api.chat(p, hero.system, prompt);
                    res.output = out;
                    res.status = STATUS_DONE;
                } catch (Exception e) {
                    res.status = STATUS_FAILED;
                    res.error = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
                }
                run.stage = i + 1;
                Stores.saveRun(c, run);
                final Provider used = p;
                ui.post(() -> {
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
}
