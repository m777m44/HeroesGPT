package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
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
        Stats.inc(this, Stats.RUNS);
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

    public void onLibrary(View v) {
        startActivity(new Intent(this, LibraryActivity.class));
    }

    public void onArena(View v) {
        startActivity(new Intent(this, ArenaActivity.class));
    }

    public void onChat(View v) {
        startActivity(new Intent(this, ChatActivity.class));
    }

    public void onUpdate(View v) {
        startActivity(new Intent(this, UpdateActivity.class));
    }

    private void setTemplate(int res) {
        EditText input = findViewById(R.id.goal);
        input.setText(getString(res));
        input.setSelection(input.getText().length());
    }

    public void onTemplateBiz(View v) { setTemplate(R.string.tpl_biz_full); }

    public void onTemplateLearn(View v) { setTemplate(R.string.tpl_learn_full); }

    public void onTemplateApp(View v) { setTemplate(R.string.tpl_app_full); }

    public void onTemplateContent(View v) { setTemplate(R.string.tpl_content_full); }

    public void onStats(View v) {
        startActivity(new Intent(this, StatsActivity.class));
    }

    public void onChats(View v) {
        startActivity(new Intent(this, ChatsActivity.class));
    }

    public void onLock(View v) {
        final EditText input = new EditText(this);
        input.setInputType(android.text.InputType.TYPE_CLASS_NUMBER | android.text.InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        input.setHint(R.string.lock_hint);
        new AlertDialog.Builder(this)
                .setTitle(R.string.pin_manage)
                .setMessage(R.string.pin_manage_msg)
                .setView(input)
                .setPositiveButton(android.R.string.ok, (d, w) -> {
                    String val = input.getText().toString().trim();
                    Stores.setSetting(this, "pin", val);
                    Toast.makeText(this, val.isEmpty() ? R.string.pin_removed : R.string.pin_set_ok,
                            Toast.LENGTH_LONG).show();
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    public void onBackup(View v) {
        try {
            org.json.JSONObject o = new org.json.JSONObject();
            o.put("app", "HeroesGPT");
            o.put("version", 1);
            org.json.JSONArray hs = new org.json.JSONArray();
            for (Hero h : Stores.heroes(this)) hs.put(h.toJson());
            o.put("heroes", hs);
            org.json.JSONArray ps = new org.json.JSONArray();
            for (Provider p : Stores.providers(this)) ps.put(p.toJson());
            o.put("providers", ps);
            Utils.shareText(this, "HeroesGPT backup", o.toString());
            Toast.makeText(this, R.string.backup_done, Toast.LENGTH_LONG).show();
        } catch (Exception e) {
            Toast.makeText(this, R.string.restore_bad, Toast.LENGTH_LONG).show();
        }
    }

    public void onRestore(View v) {
        final EditText input = new EditText(this);
        input.setHint(R.string.restore_hint);
        new AlertDialog.Builder(this)
                .setTitle(R.string.restore)
                .setMessage(R.string.restore_hint)
                .setView(input)
                .setPositiveButton(R.string.restore, (d, w) -> {
                    try {
                        org.json.JSONObject o = new org.json.JSONObject(input.getText().toString().trim());
                        boolean restored = false;
                        org.json.JSONArray hs = o.optJSONArray("heroes");
                        if (hs != null && hs.length() > 0) {
                            Stores.saveHeroes(this, Hero.fromJsonArray(hs));
                            restored = true;
                        }
                        org.json.JSONArray ps = o.optJSONArray("providers");
                        if (ps != null && ps.length() > 0) {
                            java.util.List<Provider> providers = new java.util.ArrayList<>();
                            for (int i = 0; i < ps.length(); i++) providers.add(Provider.fromJson(ps.getJSONObject(i)));
                            Stores.saveProviders(this, providers);
                            restored = true;
                        }
                        Toast.makeText(this, restored ? R.string.restore_ok : R.string.restore_bad,
                                Toast.LENGTH_LONG).show();
                    } catch (Exception e) {
                        Toast.makeText(this, R.string.restore_bad, Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }
}
