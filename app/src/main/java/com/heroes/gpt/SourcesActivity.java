package com.heroes.gpt;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public class SourcesActivity extends Activity {

    private List<Object[]> items;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_sources);
        items = SourceFiles.bundledSources(this);
        if (items.isEmpty()) {
            Toast.makeText(this, R.string.no_files_found, Toast.LENGTH_SHORT).show();
        }
        ListView lv = findViewById(R.id.sources_list);
        lv.setAdapter(new BaseAdapter() {
            @Override
            public int getCount() { return items.size(); }
            @Override
            public Object getItem(int position) { return items.get(position); }
            @Override
            public long getItemId(int position) { return position; }
            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                View v = convertView != null ? convertView
                        : getLayoutInflater().inflate(R.layout.item_source, parent, false);
                Object[] row = items.get(position);
                String file = (String) row[0];
                String title = (String) row[1];
                long bytes = row[2] == null ? 0 : (long) row[2];
                String icon = "\ud83d\udc0d";
                if (file.endsWith(".py")) icon = "\ud83d\udc0d";
                int dot = title.indexOf("—");
                TextView t = v.findViewById(R.id.src_title);
                TextView d = v.findViewById(R.id.src_desc);
                t.setText(icon + " " + title);
                String kb = bytes > 1800 ? (bytes / 1024 + 1) + " KB" : "";
                d.setText(file + (kb.isEmpty() ? "" : "  ·  " + kb));
                return v;
            }
        });
        lv.setOnItemClickListener((p, v, pos, id) -> {
            Object[] row = items.get(pos);
            Intent i = new Intent(this, SourcePanelActivity.class);
            i.putExtra("mode", "asset");
            i.putExtra("asset_path", (String) row[0]);
            i.putExtra("title", (String) row[1]);
            startActivity(i);
        });
    }
}
