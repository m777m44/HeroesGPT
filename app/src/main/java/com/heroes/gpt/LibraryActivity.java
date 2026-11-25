package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

public class LibraryActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_library);

        List<Object> rows = new ArrayList<>();
        for (String cat : HeroPresets.categories()) {
            rows.add(cat);
            for (HeroPresets.Preset p : HeroPresets.all()) {
                if (p.category.equals(cat)) rows.add(p);
            }
        }

        ListView lv = findViewById(R.id.library_list);
        lv.setAdapter(new BaseAdapter() {
            @Override
            public int getCount() { return rows.size(); }

            @Override
            public Object getItem(int position) { return rows.get(position); }

            @Override
            public long getItemId(int position) { return position; }

            @Override
            public int getViewTypeCount() { return 2; }

            @Override
            public int getItemViewType(int position) {
                return rows.get(position) instanceof String ? 0 : 1;
            }

            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                Object o = rows.get(position);
                if (o instanceof String) {
                    TextView tv = convertView != null && !(convertView.getTag() instanceof HeroPresets.Preset)
                            ? (TextView) convertView : newHeader();
                    tv.setText((String) o);
                    return tv;
                }
                HeroPresets.Preset p = (HeroPresets.Preset) o;
                View v = convertView != null && convertView.getTag() instanceof HeroPresets.Preset
                        ? convertView : getLayoutInflater().inflate(R.layout.item_preset, parent, false);
                TextView title = v.findViewById(R.id.preset_title);
                TextView sys = v.findViewById(R.id.preset_system);
                title.setText(p.emoji + "  " + p.name);
                sys.setText(p.system);
                v.setTag(p);
                return v;
            }

            private TextView newHeader() {
                TextView tv = new TextView(LibraryActivity.this);
                int pad = (int) (getResources().getDisplayMetrics().density * 10);
                tv.setPadding(pad, pad * 2, pad, pad / 2);
                tv.setTextColor(getColor(R.color.gold));
                tv.setTextSize(18);
                tv.setTypeface(null, android.graphics.Typeface.BOLD);
                return tv;
            }
        });
        lv.setOnItemClickListener((p, v, pos, id) -> {
            Object o = rows.get(pos);
            if (o instanceof HeroPresets.Preset) showAddDialog((HeroPresets.Preset) o);
        });
    }

    private void showAddDialog(HeroPresets.Preset p) {
        new AlertDialog.Builder(this)
                .setTitle(getString(R.string.add_preset_title, p.name))
                .setMessage(p.system)
                .setPositiveButton(R.string.add_to_team, (d, w) -> {
                    List<Hero> heroes = Stores.heroes(this);
                    heroes.add(Hero.make(p.emoji, p.name, p.system));
                    Stores.saveHeroes(this, heroes);
                    Toast.makeText(this, getString(R.string.preset_added, p.name), Toast.LENGTH_LONG).show();
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }
}
