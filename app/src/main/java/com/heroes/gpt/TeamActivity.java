package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;

import java.util.List;

public class TeamActivity extends Activity {

    private List<Hero> heroes;
    private HeroAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_team);
        heroes = Stores.heroes(this);
        adapter = new HeroAdapter();
        ((ListView) findViewById(R.id.team_list)).setAdapter(adapter);
    }

    public void onAddHero(View v) {
        editHero(null, true);
    }

    private void editHero(final Hero hero, final boolean isNew) {
        View dialogView = LayoutInflater.from(this).inflate(R.layout.dialog_edit_hero, null);
        final EditText emoji = dialogView.findViewById(R.id.edit_emoji);
        final EditText name = dialogView.findViewById(R.id.edit_name);
        final EditText system = dialogView.findViewById(R.id.edit_system);
        if (hero != null) {
            emoji.setText(hero.emoji);
            name.setText(hero.name);
            system.setText(hero.system);
        }
        new AlertDialog.Builder(this)
                .setTitle(isNew ? R.string.add_hero : R.string.edit_hero)
                .setView(dialogView)
                .setPositiveButton(R.string.save, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        String n = name.getText().toString().trim();
                        if (n.isEmpty()) return;
                        if (isNew) {
                            Hero h = Hero.make(
                                    emoji.getText().toString().trim().isEmpty()
                                            ? "⚡" : emoji.getText().toString().trim(),
                                    n, system.getText().toString().trim());
                            h.order = heroes.size();
                            heroes.add(h);
                        } else {
                            hero.emoji = emoji.getText().toString().trim().isEmpty()
                                    ? "⚡" : emoji.getText().toString().trim();
                            hero.name = n;
                            hero.system = system.getText().toString().trim();
                        }
                        Stores.saveHeroes(TeamActivity.this, heroes);
                        adapter.notifyDataSetChanged();
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private class HeroAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return heroes.size();
        }

        @Override
        public Object getItem(int position) {
            return heroes.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(final int position, View convertView, ViewGroup parent) {
            View row = convertView;
            if (row == null) {
                row = LayoutInflater.from(TeamActivity.this)
                        .inflate(R.layout.item_hero, parent, false);
            }
            final Hero h = heroes.get(position);
            TextView icon = row.findViewById(R.id.hero_icon);
            TextView name = row.findViewById(R.id.hero_title);
            TextView toggle = row.findViewById(R.id.hero_toggle);

            icon.setText(h.emoji);
            name.setText(h.name);
            name.setTextColor(getColor(h.enabled ? R.color.text : R.color.text_dim));
            toggle.setText(h.enabled ? R.string.active : R.string.paused);
            toggle.setTextColor(getColor(h.enabled ? R.color.ok : R.color.text_dim));

            toggle.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    h.enabled = !h.enabled;
                    Stores.saveHeroes(TeamActivity.this, heroes);
                    adapter.notifyDataSetChanged();
                }
            });

            row.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    editHero(h, false);
                }
            });

            row.setOnLongClickListener(new View.OnLongClickListener() {
                @Override
                public boolean onLongClick(View v) {
                    new AlertDialog.Builder(TeamActivity.this)
                            .setTitle(h.name)
                            .setItems(new CharSequence[]{
                                            getString(R.string.delete),
                                            getString(R.string.move_up)},
                                    new DialogInterface.OnClickListener() {
                                        @Override
                                        public void onClick(DialogInterface d, int w) {
                                            if (w == 0) {
                                                heroes.remove(position);
                                            } else if (position > 0) {
                                                heroes.add(position - 1, heroes.remove(position));
                                            }
                                            Stores.saveHeroes(TeamActivity.this, heroes);
                                            adapter.notifyDataSetChanged();
                                        }
                                    })
                            .setNegativeButton(R.string.cancel, null)
                            .show();
                    return true;
                }
            });
            return row;
        }
    }
}
