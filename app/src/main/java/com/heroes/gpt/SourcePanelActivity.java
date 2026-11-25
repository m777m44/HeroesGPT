package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public class SourcePanelActivity extends Activity {

    private List<Github.Entry> entries;
    private int openIndex = -1;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_source_panel);
        String mode = getIntent().getStringExtra("mode");
        final String title;
        if ("asset".equals(mode)) {
            entries = new java.util.ArrayList<>();
            String name = getIntent().getStringExtra("asset_path");
            title = getIntent().getStringExtra("title");
            try {
                Github.Entry e = new Github.Entry();
                e.path = name;
                e.content = SourceFiles.readAsset(this, "sources/" + name);
                entries.add(e);
            } catch (Exception ex) {
                Toast.makeText(this, R.string.no_files_found, Toast.LENGTH_LONG).show();
                finish();
                return;
            }
        } else {
            String runId = getIntent().getStringExtra("run_id");
            entries = SourceFiles.fromRun(this, runId);
            title = getString(R.string.source_panel_title);
            if (entries.isEmpty()) {
                Toast.makeText(this, R.string.no_files_found, Toast.LENGTH_LONG).show();
                finish();
                return;
            }
        }
        TextView head = findViewById(R.id.sp_header);
        head.setText(title);
        buildPanel();
    }

    private void buildPanel() {
        LinearLayout list = findViewById(R.id.sp_file_list);
        list.removeAllViews();
        TextView sub = findViewById(R.id.sp_sub);
        sub.setText(getString(R.string.source_panel_sub, entries.size()));
        for (int i = 0; i < entries.size(); i++) {
            final int idx = i;
            final Github.Entry e = entries.get(i);
            TextView row = new TextView(this);
            row.setBackgroundResource(R.drawable.bg_pill);
            String lang = detectLangFromPath(e.path);
            String icon = "📄";
            if (lang.equals(".py")) icon = "🐍";
            else if (lang.equals(".java") || lang.equals(".kt")) icon = "☕";
            else if (lang.equals(".html")) icon = "🌐";
            else if (lang.equals(".xml")) icon = "🧩";
            else if (lang.equals(".js") || lang.equals(".ts")) icon = "📜";
            String sizeKb = e.content.length() > 1800
                    ? (e.content.length() / 1024 + 1) + " KB" : "";
            row.setText(icon + "  " + e.path + (sizeKb.isEmpty() ? "" : "   ·  " + sizeKb));
            row.setTextColor(getColor(R.color.text));
            row.setTextSize(14);
            row.setPadding(dp(16), dp(13), dp(16), dp(13));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
            lp.topMargin = dp(8);
            row.setLayoutParams(lp);
            row.setOnClickListener(v -> openFullscreen(idx));
            list.addView(row);
        }
    }

    private String detectLangFromPath(String path) {
        if (path == null) return "";
        int dot = path.lastIndexOf('.');
        return dot < 0 ? "" : path.substring(dot);
    }

    private void openFullscreen(int idx) {
        openIndex = idx;
        final Github.Entry e = entries.get(idx);
        View full = findViewById(R.id.sp_fullscreen);
        View panel = findViewById(R.id.sp_panel);
        panel.setVisibility(View.GONE);
        full.setVisibility(View.VISIBLE);
        full.startAnimation(android.view.animation.AnimationUtils
                .loadAnimation(this, R.anim.slide_up));

        TextView path = findViewById(R.id.sp_full_path);
        TextView body = findViewById(R.id.sp_full_body);
        EditText name = findViewById(R.id.sp_name_input);
        path.setText(e.path);
        body.setText(e.content);
        String suggested = SourceFiles.suggestName(e.path, detectLangFromPath(e.path), e.content);
        name.setText(suggested);

        findViewById(R.id.sp_full_back).setOnClickListener(v -> closeFullscreen());
        findViewById(R.id.sp_full_copy).setOnClickListener(v -> {
            Utils.copy(this, e.content);
            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
        });
        findViewById(R.id.sp_full_download).setOnClickListener(v -> downloadWithSaf());
    }

    private void closeFullscreen() {
        findViewById(R.id.sp_fullscreen).setVisibility(View.GONE);
        findViewById(R.id.sp_panel).setVisibility(View.VISIBLE);
        openIndex = -1;
    }

    private String pendingName;

    public void saveNow(View v) {
        downloadWithSaf();
    }

    private void downloadWithSaf() {
        if (openIndex < 0) return;
        View box = getLayoutInflater().inflate(R.layout.dialog_save_name, null);
        EditText input = box.findViewById(R.id.save_name);
        TextView hint = box.findViewById(R.id.save_hint);
        EditText name = findViewById(R.id.sp_name_input);
        String current = name.getText().toString().trim();
        if (current.isEmpty()) current = SourceFiles.suggestName(
                entries.get(openIndex).path, detectLangFromPath(entries.get(openIndex).path),
                entries.get(openIndex).content);
        input.setText(current);
        String ext = detectLangFromPath(entries.get(openIndex).path);
        if (ext.isEmpty()) ext = SourceFiles.langToExt("", entries.get(openIndex).content);
        hint.setText(getString(R.string.save_ext_hint, ext));
        new AlertDialog.Builder(this)
                .setTitle(R.string.save_file_title)
                .setView(box)
                .setPositiveButton(R.string.save, (d, w) -> {
                    String typed = input.getText().toString().trim();
                    String fixed;
                    if (typed.contains(".")) {
                        String base2 = typed;
                        int dot2 = base2.lastIndexOf('.');
                        String cur = base2.substring(dot2);
                        String want = SourceFiles.langToExt(
                                detectLangFromPath(entries.get(openIndex).path),
                                entries.get(openIndex).content);
                        fixed = typed;
                        if (!cur.equals(want)) {
                            fixed = base2.substring(0, dot2) + want;
                            Toast.makeText(this, getString(R.string.save_ext_fixed, want),
                                    Toast.LENGTH_LONG).show();
                        }
                    } else {
                        String want = SourceFiles.langToExt(
                                detectLangFromPath(entries.get(openIndex).path),
                                entries.get(openIndex).content);
                        fixed = typed + want;
                    }
                    pendingName = fixed;
                    startSaf();
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private void startSaf() {
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType("text/plain");
        i.putExtra(Intent.EXTRA_TITLE, pendingName);
        try {
            startActivityForResult(i, 9001);
        } catch (Exception e) {
            Toast.makeText(this, R.string.save_failed_picker, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != 9001 || res != RESULT_OK || data == null || openIndex < 0) return;
        try {
            java.io.OutputStream os = getContentResolver().openOutputStream(data.getData());
            if (os != null) {
                os.write(entries.get(openIndex).content.getBytes(
                        java.nio.charset.StandardCharsets.UTF_8));
                os.close();
                Toast.makeText(this, R.string.saved_ok, Toast.LENGTH_LONG).show();
            }
        } catch (Exception e) {
            Toast.makeText(this, R.string.save_failed, Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public void onBackPressed() {
        if (openIndex >= 0) {
            closeFullscreen();
        } else {
            super.onBackPressed();
        }
    }

    private int dp(int v) {
        return (int) (getResources().getDisplayMetrics().density * v);
    }
}
