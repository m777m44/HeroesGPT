package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;
import java.util.concurrent.atomic.AtomicBoolean;

public class RunActivity extends Activity implements Orchestrator.Callback {

    private Stores.Run run;
    private StepAdapter adapter;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private TextView headline;
    private final Handler tick = new Handler(Looper.getMainLooper());
    private long liveStartAt;
    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (!running.get()) return;
            long s = (System.currentTimeMillis() - liveStartAt) / 1000L;
            TextView t = findViewById(R.id.live_timer);
            if (t != null) t.setText(s + "s");
            tick.postDelayed(this, 1000L);
        }
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_run);
        headline = findViewById(R.id.headline);
        String id = getIntent().getStringExtra("run_id");
        run = id == null ? null : Stores.loadRun(this, id);
        if (run == null) {
            finish();
            return;
        }
        headline.setText(run.goal);
        adapter = new StepAdapter();
        ((ListView) findViewById(R.id.steps)).setAdapter(adapter);

        boolean autostart = getIntent().getBooleanExtra("autostart", false);
        if (autostart && run.stage < run.heroes.size()) {
            launch();
        }
        updateButtons();
        refreshCompletion();
    }

    private void refreshCompletion() {
        View card = findViewById(R.id.complete_card);
        int done = 0, failed = 0, active = 0;
        for (Hero h : run.heroes) if (h.enabled) active++;
        for (Stores.Run.Result r : run.results) {
            if (r.status == Orchestrator.STATUS_DONE) done++;
            else if (r.status == Orchestrator.STATUS_FAILED) failed++;
        }
        boolean all = active > 0 && done == active;
        card.setVisibility(all ? View.VISIBLE : View.GONE);
        if (all) {
            TextView st = findViewById(R.id.complete_stats);
            st.setText(getString(R.string.complete_stats, run.goal, active, done, failed));
        }
    }

    private void launch() {
        if (!running.compareAndSet(false, true)) return;
        updateButtons();
        tick.postDelayed(ticker, 1000L);
        Orchestrator.runRemaining(this, run, this);
    }

    public void onResumeRun(View v) {
        launch();
    }

    private void updateButtons() {
        TextView btn = findViewById(R.id.resume_btn);
        ProgressBar bar = findViewById(R.id.progress);
        boolean inProgress = running.get();
        btn.setVisibility(inProgress ? View.GONE
                : (run.stage < run.heroes.size() ? View.VISIBLE : View.GONE));
        bar.setVisibility(inProgress ? View.VISIBLE : View.GONE);
        int done = 0;
        for (Stores.Run.Result r : run.results) {
            if (r.status == Orchestrator.STATUS_DONE) done++;
        }
        TextView counter = findViewById(R.id.counter);
        counter.setText(getString(R.string.progress_counter, done, run.heroes.size()));
    }

    @Override
    public void onStepChanged(final int index) {
        runOnUiThread(() -> {
            adapter.notifyDataSetChanged();
            updateButtons();
            refreshCompletion();
        });
    }

    @Override
    public void onLive(final int index, final String header, final String partial) {
        runOnUiThread(() -> {
            if (!running.get()) return;
            View card = findViewById(R.id.live_card);
            card.setVisibility(View.VISIBLE);
            TextView hero = findViewById(R.id.live_hero);
            TextView text = findViewById(R.id.live_text);
            TextView dot = findViewById(R.id.live_dot);
            hero.setText(header);
            if (partial == null || partial.isEmpty()) {
                text.setText(R.string.thinking);
                dot.setText("🧠");
            } else {
                String shown = partial.length() > 1400
                        ? partial.substring(partial.length() - 1400) : partial;
                text.setText(shown);
                dot.setText("⚡");
            }
        });
    }

    @Override
    public void onFinished(final boolean allDone) {
        runOnUiThread(() -> {
            running.set(false);
            findViewById(R.id.live_card).setVisibility(View.GONE);
            tick.removeCallbacks(ticker);
            adapter.notifyDataSetChanged();
            updateButtons();
            refreshCompletion();
            Toast.makeText(this, allDone ? R.string.mission_complete : R.string.mission_paused,
                    Toast.LENGTH_LONG).show();
        });
    }

    private class StepAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return run.heroes.size();
        }

        @Override
        public Object getItem(int position) {
            return run.heroes.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(final int position, View convertView, ViewGroup parent) {
            View row = convertView;
            if (row == null) {
                row = LayoutInflater.from(RunActivity.this)
                        .inflate(R.layout.item_step, parent, false);
            }
            Hero hero = run.heroes.get(position);
            Stores.Run.Result res = run.results.get(position);

            TextView icon = row.findViewById(R.id.status_icon);
            TextView name = row.findViewById(R.id.hero_name);
            TextView body = row.findViewById(R.id.step_output);
            TextView copy = row.findViewById(R.id.step_copy);

            name.setText(hero.emoji + "  " + hero.name);
            body.setVisibility(View.GONE);
            copy.setVisibility(View.GONE);

            if (!hero.enabled) {
                icon.setText("⏸");
                name.setTextColor(getColor(R.color.text_dim));
            } else {
                switch (res.status) {
                    case Orchestrator.STATUS_DONE:
                        icon.setText("✓");
                        name.setTextColor(getColor(R.color.ok));
                        body.setText(res.output);
                        body.setVisibility(View.VISIBLE);
                        copy.setVisibility(View.VISIBLE);
                        copy.setOnClickListener(v -> {
                            Utils.copy(RunActivity.this, res.output);
                            Toast.makeText(RunActivity.this, R.string.copied, Toast.LENGTH_SHORT).show();
                        });
                        body.setOnClickListener(new View.OnClickListener() {
                            boolean expanded = false;

                            @Override
                            public void onClick(View v) {
                                expanded = !expanded;
                                body.setMaxLines(expanded ? Integer.MAX_VALUE : 4);
                            }
                        });
                        break;
                    case Orchestrator.STATUS_RUNNING:
                        icon.setText("⚡");
                        name.setTextColor(getColor(R.color.accent));
                        name.startAnimation(android.view.animation.AnimationUtils
                                .loadAnimation(RunActivity.this, R.anim.blink));
                        break;
                    case Orchestrator.STATUS_FAILED:
                        icon.setText("✗");
                        name.setTextColor(getColor(R.color.danger));
                        body.setText("⚠ " + res.error);
                        body.setVisibility(View.VISIBLE);
                        break;
                    default:
                        icon.setText("○");
                        name.setTextColor(getColor(R.color.text));
                        break;
                }
            }
            body.setMaxLines(4);
            return row;
        }
    }

    private String reportText() {
        StringBuilder sb = new StringBuilder();
        sb.append("🚀 تقرير مهمة من HeroesGPT\n\n");
        sb.append("🎯 الهدف: ").append(run.goal).append("\n");
        for (int i = 0; i < run.heroes.size(); i++) {
            Hero h = run.heroes.get(i);
            Stores.Run.Result res = run.results.get(i);
            sb.append("\n").append(h.emoji).append(" ").append(h.name).append(":\n");
            if (res.status == Orchestrator.STATUS_DONE) sb.append(res.output);
            else if (res.status == Orchestrator.STATUS_FAILED) sb.append("⚠️ فشل — ").append(res.error);
            else sb.append("⏳ لم يُنجز بعد");
            sb.append("\n\n");
        }
        return sb.toString();
    }

    public void onShareReport(View v) {
        Utils.shareText(this, "HeroesGPT", reportText());
    }

    public void onCopyReport(View v) {
        Utils.copy(this, reportText());
        Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
    }

    public void onShowFiles(View v) {
        List<Github.Entry> files = ProjectFiles.extract(run);
        if (files.isEmpty()) {
            Toast.makeText(this, R.string.no_files_found, Toast.LENGTH_LONG).show();
            return;
        }
        String[] names = new String[files.size()];
        for (int i = 0; i < files.size(); i++) names[i] = files.get(i).path;
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.project_files_title, files.size()))
                .setItems(names, (d, w) -> showFile(files.get(w)))
                .setNegativeButton(R.string.close, null)
                .show();
    }

    private void showFile(final Github.Entry f) {
        View box = getLayoutInflater().inflate(R.layout.dialog_file_view, null);
        TextView path = box.findViewById(R.id.file_path);
        TextView body = box.findViewById(R.id.file_body);
        path.setText(f.path);
        body.setText(f.content);
        new AlertDialog.Builder(this)
                .setView(box)
                .setPositiveButton(R.string.copy, (d, w) -> {
                    Utils.copy(this, f.content);
                    Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton(R.string.close, null)
                .show();
    }

    public void onPushGithub(View v) {
        String token = Stores.setting(this, "gh_token");
        String chosen = Stores.setting(this, "gh_repo");
        if (token.isEmpty()) {
            startActivity(new Intent(this, GithubActivity.class));
            Toast.makeText(this, R.string.connect_github_first, Toast.LENGTH_LONG).show();
            return;
        }
        if (chosen.isEmpty()) {
            startActivity(new Intent(this, GithubActivity.class));
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.push_confirm_title)
                .setMessage(getString(R.string.push_confirm_msg, chosen))
                .setPositiveButton(R.string.push_now, (d, w) -> pushToGithub(token, chosen))
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private void pushToGithub(final String token, final String repo) {
        View progress = getLayoutInflater().inflate(R.layout.dialog_wait, null);
        TextView msg = progress.findViewById(R.id.wait_msg);
        msg.setText(R.string.pushing);
        final AlertDialog dlg = new AlertDialog.Builder(this)
                .setView(progress)
                .setCancelable(false)
                .show();
        new Thread(() -> {
            List<Github.Entry> files = ProjectFiles.extract(run);
            StringBuilder log = new StringBuilder();
            if (files.isEmpty()) {
                Github.Entry e = new Github.Entry();
                e.path = "REPORT_" + run.id + ".md";
                e.content = reportText();
                files.add(e);
            }
            try {
                Github.uploadAll(token, repo, files, "HeroesGPT/" + run.id, null, log);
            } catch (Exception e) {
                log.append("⚠ ").append(e.getMessage() == null ? "خطأ" : e.getMessage());
            }
            final String result = log.length() == 0
                    ? "لا توجد ملفات" : log.toString().trim();
            runOnUiThread(() -> {
                dlg.dismiss();
                new AlertDialog.Builder(this)
                        .setTitle(R.string.push_done_title)
                        .setMessage(result)
                        .setPositiveButton(R.string.open_repo, (d2, w2) ->
                                Utils.openUrl(this, "https://github.com/" + repo))
                        .setNegativeButton(R.string.close, null)
                        .show();
            });
        }).start();
    }
}
