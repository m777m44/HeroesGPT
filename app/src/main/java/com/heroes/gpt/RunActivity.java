package com.heroes.gpt;

import android.app.Activity;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

import java.util.concurrent.atomic.AtomicBoolean;

public class RunActivity extends Activity implements Orchestrator.Callback {

    private Stores.Run run;
    private StepAdapter adapter;
    private final AtomicBoolean running = new AtomicBoolean(false);
    private TextView headline;

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
    }

    private void launch() {
        if (!running.compareAndSet(false, true)) return;
        updateButtons();
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
        });
    }

    @Override
    public void onFinished(final boolean allDone) {
        runOnUiThread(() -> {
            running.set(false);
            adapter.notifyDataSetChanged();
            updateButtons();
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

            name.setText(hero.emoji + "  " + hero.name);
            body.setVisibility(View.GONE);

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
}
