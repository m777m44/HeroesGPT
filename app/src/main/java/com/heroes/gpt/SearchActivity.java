package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.text.InputType;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AdapterView;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

/**
 * شاشة البحث الموحّدة — كل المحركات خلف واجهة واحدة مع محرك "الكل".
 * مؤشر التفكير 💭 يعمل أثناء البحث، وكل نتيجة لها نسخ + فتح خارجي.
 */
public class SearchActivity extends Activity {

    private String engine = "all";
    private final List<SearchEngines.Result> results = new ArrayList<>();
    private ResultsAdapter adapter;
    private ThinkingView thinking;
    private TextView statusView;
    private View runningView;
    private boolean busy = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        CrashCatcher.install(this);
        try {
            setContentView(R.layout.activity_search);
            setup();
            CrashCatcher.reportIfCrashed(this);
        } catch (Throwable t) {
            CrashCatcher.showErrorScreen(this, t);
            return;
        }
        KeyConfig.refreshFromGithubAsync(this);
    }

    private void setup() {
        thinking = findViewById(R.id.search_thinking);
        statusView = findViewById(R.id.search_status);
        runningView = findViewById(R.id.search_running);

        adapter = new ResultsAdapter();
        ListView lv = findViewById(R.id.search_results);
        lv.setAdapter(adapter);
        lv.setOnItemClickListener((parent, view, position, id) -> {
            if (position < 0 || position >= results.size()) return;
            showResultDialog(results.get(position));
        });

        findViewById(R.id.search_go).setOnClickListener(v -> go());
        EditText input = findViewById(R.id.search_input);
        input.setOnEditorActionListener((tv, actionId, event) -> {
            go();
            return true;
        });

        buildChips();
        refreshStatus();
    }

    private void buildChips() {
        LinearLayout chips = findViewById(R.id.search_engine_chips);
        chips.removeAllViews();
        for (String[] e : SearchEngines.ENGINES) {
            final String id = e[0];
            TextView chip = new TextView(this);
            chip.setText(e[1]);
            chip.setTextSize(12);
            int pad = (int) (getResources().getDisplayMetrics().density * 10);
            chip.setPadding(pad, pad / 2, pad, pad / 2);
            chip.setBackgroundResource("all".equals(id)
                    ? R.drawable.bg_pill_on : R.drawable.bg_pill);
            chip.setTextColor(getColor("all".equals(id) ? R.color.accent : R.color.text));
            chip.setOnClickListener(v -> {
                if (busy) return;
                engine = id;
                buildChips();
                refreshStatus();
            });
            chips.addView(chip);
            LinearLayout.LayoutParams lp = (LinearLayout.LayoutParams) chip.getLayoutParams();
            lp.setMargins(0, 0, (int) (getResources().getDisplayMetrics().density * 8), 0);
            chip.setLayoutParams(lp);
        }
    }

    private void refreshStatus() {
        StringBuilder sb = new StringBuilder("🔗 المتصل: ");
        List<KeyConfig.Status> st = KeyConfig.statuses(this);
        int connected = 0;
        for (KeyConfig.Status s : st) {
            if (s.id.equals("gh_token")) continue;
            if (s.connected) connected++;
        }
        sb.append(connected).append("/").append(st.size() - 1).append(" مفتاح");
        if (!SearchEngines.isReady(this, engine)) {
            sb.append("  ⚠️ مفتاح ").append(SearchEngines.labelOf(engine)).append(" غير متصل — أضفه في keys.json");
        }
        statusView.setText(sb.toString());
    }

    private void go() {
        if (busy) return;
        EditText input = findViewById(R.id.search_input);
        String q = input.getText().toString().trim();
        if (q.isEmpty()) return;
        if (!SearchEngines.isReady(this, engine)) {
            Toast.makeText(this, getString(R.string.search_key_missing, SearchEngines.labelOf(engine)),
                    Toast.LENGTH_LONG).show();
            return;
        }
        busy = true;
        results.clear();
        adapter.notifyDataSetChanged();
        thinking.setGlyph("💭");
        thinking.start();
        runningView.setVisibility(View.VISIBLE);
        refreshStatus();
        final String query = q;
        final String eng = engine;
        new Thread(() -> {
            List<SearchEngines.Result> out = null;
            String err = null;
            try {
                out = SearchEngines.search(this, eng, query);
            } catch (Exception e) {
                err = e.getMessage() == null ? "خطأ غير معروف" : e.getMessage();
            }
            final List<SearchEngines.Result> got = out;
            final String e0 = err;
            runOnUiThread(() -> {
                busy = false;
                thinking.stop();
                runningView.setVisibility(View.GONE);
                if (got != null && !got.isEmpty()) {
                    results.addAll(got);
                    refreshStatus();
                } else if (got != null) {
                    Toast.makeText(this, R.string.search_no_results, Toast.LENGTH_SHORT).show();
                } else {
                    Toast.makeText(this, getString(R.string.search_failed, e0), Toast.LENGTH_LONG).show();
                }
                adapter.notifyDataSetChanged();
            });
        }).start();
    }

    private void showResultDialog(SearchEngines.Result r) {
        new AlertDialog.Builder(this)
                .setTitle(r.title)
                .setMessage((r.snippet == null || r.snippet.isEmpty() ? "" : r.snippet + "\n\n")
                        + (r.engine == null ? "" : "—" + r.engine + "\n") + r.url)
                .setPositiveButton(R.string.search_open, (d, w) -> {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(r.url)));
                    } catch (Exception e) {
                        Toast.makeText(this, R.string.search_no_browser, Toast.LENGTH_SHORT).show();
                    }
                })
                .setNeutralButton(R.string.search_copy, (d, w) -> {
                    Utils.copy(this, r.title + "\n" + r.url + "\n" + (r.snippet == null ? "" : r.snippet));
                    Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton(R.string.close, null)
                .show();
    }

    private class ResultsAdapter extends BaseAdapter {
        @Override
        public int getCount() { return results.size(); }

        @Override
        public Object getItem(int position) { return results.get(position); }

        @Override
        public long getItemId(int position) { return position; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            SearchEngines.Result r = results.get(position);
            View row = convertView != null ? convertView
                    : getLayoutInflater().inflate(R.layout.item_search_result, parent, false);
            ((TextView) row.findViewById(R.id.sr_title)).setText(r.title);
            ((TextView) row.findViewById(R.id.sr_snippet)).setText(
                    r.snippet == null || r.snippet.isEmpty() ? "—" :
                            (r.snippet.length() > 220 ? r.snippet.substring(0, 220) + "…" : r.snippet));
            ((TextView) row.findViewById(R.id.sr_url)).setText(
                    (r.engine == null ? "" : r.engine + " • ") + r.url);
            row.findViewById(R.id.sr_copy).setOnClickListener(v -> {
                Utils.copy(SearchActivity.this, r.title + "\n" + r.url + "\n" + (r.snippet == null ? "" : r.snippet));
                Toast.makeText(SearchActivity.this, R.string.copied, Toast.LENGTH_SHORT).show();
            });
            row.findViewById(R.id.sr_open).setOnClickListener(v -> showResultDialog(r));
            return row;
        }
    }
}
