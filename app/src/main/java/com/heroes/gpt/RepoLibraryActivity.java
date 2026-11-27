package com.heroes.gpt;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class RepoLibraryActivity extends Activity {

    private JSONArray projects;
    private int projectIdx = -1;
    private final List<String> dirStack = new ArrayList<>();
    private final List<Object[]> rows = new ArrayList<>();

    private TextView sub;
    private BaseAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_repo_library);
        sub = findViewById(R.id.repo_sub);
        projects = SourceFiles.repoProjects(this);
        if (projects.length() == 0) {
            Toast.makeText(this, R.string.no_files_found, Toast.LENGTH_SHORT).show();
            finish();
            return;
        }
        adapter = new BaseAdapter() {
            @Override
            public int getCount() { return rows.size(); }
            @Override
            public Object getItem(int position) { return rows.get(position); }
            @Override
            public long getItemId(int position) { return position; }
            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                    View v = convertView != null ? convertView
                            : getLayoutInflater().inflate(R.layout.item_source, parent, false);
                    Object[] row = rows.get(position);
                    TextView t = v.findViewById(R.id.src_title);
                    TextView d = v.findViewById(R.id.src_desc);
                    t.setText((String) row[0]);
                    d.setText((String) row[1]);
                    return v;
            }
        };
        ListView lv = findViewById(R.id.repo_list);
        lv.setAdapter(adapter);
        lv.setOnItemClickListener((p, v, pos, id) -> openRow(pos));
        showRoot();
    }

    private void showRoot() {
        projectIdx = -1;
        dirStack.clear();
        rows.clear();
        int total = 0;
        long bytes = 0;
        for (int i = 0; i < projects.length(); i++) {
            JSONObject p = projects.optJSONObject(i);
            if (p == null) continue;
            total += p.optInt("count", 0);
            bytes += p.optLong("bytes", 0);
            String src = p.optString("source", "");
            rows.add(new Object[]{"📦  " + p.optString("name", "?"),
                    src.isEmpty() ? (p.optInt("count", 0) + " ملفًا  ·  " + human(p.optLong("bytes", 0)))
                                  : (src + "  ·  " + p.optInt("count", 0) + " ملفًا  ·  " + human(p.optLong("bytes", 0))),
                    T_PROJ + String.valueOf(i)});
        }
        sub.setText(total + " ملفًا · " + human(bytes) + " · " + projects.length() + " " + getString(R.string.repo_projects_count));
        adapter.notifyDataSetChanged();
    }

    private void showLevel() {
        rows.clear();
        JSONObject p = projects.optJSONObject(projectIdx);
        if (p == null) { showRoot(); return; }
        String projectName = p.optString("name", "");
        String dir = dirStack.isEmpty() ? "" : dirStack.get(dirStack.size() - 1);
        Map<String, Long> dirs = new LinkedHashMap<>();
        List<Object[]> files = new ArrayList<>();
        JSONArray arr = p.optJSONArray("files");
        String prefix = projectName + "/" + (dir.isEmpty() ? "" : dir + "/");
        int count = 0;
        for (int i = 0; arr != null && i < arr.length(); i++) {
            JSONObject f = arr.optJSONObject(i);
            if (f == null) continue;
            String path = f.optString("path", "");
            if (!path.startsWith(prefix)) continue;
            String rel = path.substring(prefix.length());
            int slash = rel.indexOf('/');
            if (slash >= 0) {
                String d = rel.substring(0, slash);
                Long old = dirs.get(d);
                dirs.put(d, (old == null ? 0 : old) + f.optLong("size", 0));
            } else {
                count++;
                files.add(new Object[]{iconFor(rel) + "  " + rel,
                        human(f.optLong("size", 0)), rel});
            }
        }
        for (Map.Entry<String, Long> e : dirs.entrySet()) {
            rows.add(new Object[]{"📁  " + e.getKey() + "/",
                    human(e.getValue()), T_DIR + e.getKey()});
        }
        for (Object[] f : files) {
            rows.add(new Object[]{f[0], f[1], T_FILE + (String) f[2]});
        }
        String where = dir.isEmpty() ? projectName : dir.substring(dir.lastIndexOf('/') + 1);
        sub.setText(projectName + " › " + where + "  ·  " + count + " ملفًا مباشرًا");
        adapter.notifyDataSetChanged();
    }

    private static final int T_DIR = 1;
    private static final int T_FILE = 2;
    private static final int T_PROJ = 3;

    private void openRow(int pos) {
        if (pos < 0 || pos >= rows.size()) return;
        Object[] row = rows.get(pos);
        if (row == null || row.length < 3 || row[2] == null) {
            // صف غير معروف: افتح المشروع المقابل إن كنا في الجذر
            if (projectIdx < 0 && pos < projects.length()) { projectIdx = pos; dirStack.clear(); showLevel(); }
            return;
        }
        String tag = (String) row[2];
        if (tag.startsWith(String.valueOf(T_PROJ))) {
            try {
                int idx = Integer.parseInt(tag.substring(1));
                if (idx >= 0 && idx < projects.length()) {
                    projectIdx = idx;
                    dirStack.clear();
                    showLevel();
                }
            } catch (NumberFormatException ignored) { }
        } else if (tag.startsWith(String.valueOf(T_FILE))) {
            String rel = tag.substring(1);
            JSONObject p = projects.optJSONObject(projectIdx);
            if (p == null) return;
            Intent i = new Intent(this, SourcePanelActivity.class);
            i.putExtra("mode", "repoasset");
            i.putExtra("asset_path", SourceFiles.repoAssetPath(p.optString("name", ""), rel));
            i.putExtra("title", rel);
            startActivity(i);
        } else {
            String rel = tag.substring(1);
            dirStack.add(dirStack.isEmpty() ? rel
                    : dirStack.get(dirStack.size() - 1) + "/" + rel);
            showLevel();
        }
    }

    @Override
    public void onBackPressed() {
        if (projectIdx >= 0) {
            if (!dirStack.isEmpty()) {
                dirStack.remove(dirStack.size() - 1);
                showLevel();
                return;
            }
            showRoot();
            return;
        }
        super.onBackPressed();
    }

    private String iconFor(String path) {
        String ext = "";
        int dot = path.lastIndexOf('.');
        if (dot >= 0) ext = path.substring(dot);
        switch (ext) {
            case ".py": return "🐍";
            case ".java": return "☕";
            case ".kt": return "🅺";
            case ".ts": case ".tsx": case ".js": case ".jsx": return "📜";
            case ".xml": return "🧩";
            case ".html": case ".mdx": return "🌐";
            case ".css": return "🎨";
            case ".json": return "🔧";
            case ".md": return "📖";
            case ".yml": case ".yaml": return "⚙️";
            case ".sh": return "🐚";
            case ".txt": return "📄";
            default: return "📄";
        }
    }

    private String human(long b) {
        if (b < 1800) return b + " B";
        if (b < 1024 * 1024) return (b / 1024 + 1) + " KB";
        return String.format(java.util.Locale.US, "%.1f MB", b / 1024.0 / 1024.0);
    }
}
