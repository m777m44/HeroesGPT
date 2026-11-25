package com.heroes.gpt;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.widget.EditText;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public class CockpitActivity extends Activity {

    private List<Stores.Run> runs;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_cockpit);
        Stores.heroes(this);
        Stores.providers(this);
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshRuns();
    }

    private void refreshRuns() {
       runs = Stores.runs(this);
        TextView status = findViewById(R.id.runs_status);
        if (runs.isEmpty()) {
            status.setText(getString(R.string.majestic_welcome));
        } else {
            Stores.Run latest = runs.get(0);
            String hero = latest.stage < latest.heroes.size()
                    ? latest.heroes.get(Math.min(latest.stage, latest.heroes.size() - 1)).name
                    : "تم التسليم ✓";
            status.setText(getString(R.string.latest_run, latest.goal, latest.stage, latest.heroes.size(), hero));
        }
    }

    public void onLaunch(View v) {
        EditText input = findViewById(R.id.goal);
        String goal = input.getText().toString().trim();
        if (goal.isEmpty()) {
            Toast.makeText(this, R.string.enter_goal, Toast.LENGTH_LONG).show();
            return;
        }
        Stores.Run run = Stores.newRun(this, goal, Stores.heroes(this));
        input.setText("");
        Intent i = new Intent(this, RunActivity.class);
        i.putExtra("run_id", run.id);
        i.putExtra("autostart", true);
        startActivity(i);
    }

    public void onLatestRun(View v) {
        if (runs == null || runs.isEmpty()) return;
        Stores.Run run = runs.get(0);
        if (run.stage < run.heroes.size()) {
            Intent i = new Intent(this, RunActivity.class);
            i.putExtra("run_id", run.id);
            i.putExtra("autostart", true);
            startActivity(i);
        } else {
            viewRun(run);
        }
    }

    private void viewRun(Stores.Run run) {
        Intent i = new Intent(this, RunActivity.class);
        i.putExtra("run_id", run.id);
        startActivity(i);
    }

    public void onProjects(View v) {
        startActivity(new Intent(this, ProjectsActivity.class));
    }

    public void onTeam(View v) {
        startActivity(new Intent(this, TeamActivity.class));
    }

    public void onProviders(View v) {
        startActivity(new Intent(this, ProvidersActivity.class));
    }
}
