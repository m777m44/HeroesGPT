package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

public class ChatActivity extends Activity {

    private final List<String[]> messages = new ArrayList<>();
    private final Handler ui = new Handler(Looper.getMainLooper());
    private Hero hero;
    private ChatAdapter adapter;
    private TextView heroTitle;
    private boolean busy = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chat);
        adapter = new ChatAdapter();

        List<Hero> heroes = Stores.heroes(this);
        String heroId = getIntent().getStringExtra("hero_id");
        if (heroes.isEmpty()) {
            Toast.makeText(this, R.string.chat_need_hero, Toast.LENGTH_LONG).show();
            finish();
            return;
        }
        hero = null;
        if (heroId != null) {
            for (Hero h : heroes) if (h.id.equals(heroId)) hero = h;
        } else {
            pickHero(heroes);
        }

        ListView lv = findViewById(R.id.chat_list);
        lv.setAdapter(adapter);
        lv.setTranscriptMode(ListView.TRANSCRIPT_MODE_ALWAYS_SCROLL);
        lv.setStackFromBottom(true);
        heroTitle = findViewById(R.id.chat_hero);
        findViewById(R.id.chat_send).setOnClickListener(v -> {
            if (busy) return;
            if (hero == null) { pickHero(Stores.heroes(this)); return; }
            EditText input = findViewById(R.id.chat_input);
            String text = input.getText().toString().trim();
            if (text.isEmpty()) return;
            input.setText("");
            messages.add(new String[]{"user", text});
            adapter.notifyDataSetChanged();
            send();
        });
    }

    private void pickHero(List<Hero> heroes) {
        List<String> names = new ArrayList<>();
        for (Hero h : heroes) names.add(h.emoji + " " + h.name);
        new AlertDialog.Builder(this)
                .setTitle(R.string.chat_pick_hero)
                .setItems(names.toArray(new String[0]), (d, w) -> {
                    hero = heroes.get(w);
                    messages.clear();
                    messages.add(new String[]{"assistant", "أنا " + hero.emoji + " " + hero.name + ". تفضل، أنا مستعد."});
                    heroTitle.setText(hero.emoji + " " + hero.name);
                    adapter.notifyDataSetChanged();
                })
                .setOnCancelListener(d -> finish())
                .show();
    }

    private void send() {
        busy = true;
        final int step = (int) (System.currentTimeMillis() / 1000);
        new Thread(() -> {
            try {
                Provider p = Orchestrator.pickProvider(this, hero, step);
                String res = Api.chat(p, hero.system, buildContext());
                messages.add(new String[]{"assistant", res});
            } catch (Exception e) {
                String msg = e.getMessage() == null ? "خطأ" : e.getMessage();
                messages.add(new String[]{"assistant", "⚠️ " + getString(R.string.chat_error, msg)});
            } finally {
                busy = false;
                ui.post(() -> adapter.notifyDataSetChanged());
            }
        }).start();
    }

    private String buildContext() {
        StringBuilder sb = new StringBuilder();
        for (String[] m : messages) {
            sb.append(m[0].equals("user") ? "المستخدم: " : "أنت: ").append(m[1]).append("\n\n");
        }
        sb.append("ردّ على آخر رسالة للمستخدم ردًّا مباشرًا أوضح وأدق.");
        return sb.toString();
    }

    private class ChatAdapter extends BaseAdapter {
        @Override
        public int getCount() { return messages.size(); }

        @Override
        public Object getItem(int position) { return messages.get(position); }

        @Override
        public long getItemId(int position) { return position; }

        @Override
        public View getView(int position, View convertView, ViewGroup parent) {
            String[] m = messages.get(position);
            boolean user = m[0].equals("user");
            TextView tv = convertView instanceof TextView
                    ? (TextView) convertView : new TextView(ChatActivity.this);
            int pad = (int) (getResources().getDisplayMetrics().density * 12);
            tv.setPadding(pad, pad, pad, pad);
            tv.setTextSize(14);
            tv.setTextColor(getColor(user ? R.color.text : R.color.gold));
            tv.setBackgroundResource(user ? R.drawable.bg_card : R.drawable.bg_chip);
            tv.setText((user ? "🫵 أنت: " : "⚡ " + (hero == null ? "البطل" : hero.name) + ": ") + m[1]);
            return tv;
        }
    }
}
