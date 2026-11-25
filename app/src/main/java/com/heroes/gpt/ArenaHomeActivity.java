package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;
import android.widget.ViewFlipper;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;

public class ArenaHomeActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Random rnd = new Random();

    private ViewFlipper flipper;
    private Button tabBattle;
    private Button tabChat;
    private Button tabRanks;

    private Hero heroA;
    private Hero heroB;
    private final List<String[]> convoA = new ArrayList<>();
    private final List<String[]> convoB = new ArrayList<>();
    private TextView outA;
    private TextView outB;
    private TextView nameA;
    private TextView nameB;
    private LinearLayout voteBar;
    private Button battleGo;
    private Button newBattleBtn;
    private boolean battleBusy;

    private Hero chatHero;
    private final List<String[]> chatConvo = new ArrayList<>();
    private TextView chatOut;
    private TextView chatTitle;
    private boolean chatBusy;

    private ListView ranksList;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_arena_home);

        flipper = findViewById(R.id.flipper);
        tabBattle = findViewById(R.id.tab_battle);
        tabChat = findViewById(R.id.tab_chat);
        tabRanks = findViewById(R.id.tab_ranks);
        outA = findViewById(R.id.battle_out_a);
        outB = findViewById(R.id.battle_out_b);
        nameA = findViewById(R.id.battle_name_a);
        nameB = findViewById(R.id.battle_name_b);
        voteBar = findViewById(R.id.vote_bar);
        battleGo = findViewById(R.id.battle_go);
        newBattleBtn = findViewById(R.id.new_battle_btn);

        chatOut = findViewById(R.id.direct_out);
        chatTitle = findViewById(R.id.direct_title);
        ranksList = findViewById(R.id.ranks_list);

        tabBattle.setOnClickListener(v -> switchTab(0));
        tabChat.setOnClickListener(v -> switchTab(1));
        tabRanks.setOnClickListener(v -> switchTab(2));

        findViewById(R.id.header_team).setOnClickListener(v ->
                startActivity(new Intent(this, CockpitActivity.class)));
        findViewById(R.id.header_update).setOnClickListener(v ->
                startActivity(new Intent(this, UpdateActivity.class)));

        battleGo.setOnClickListener(v -> sendBattlePrompt());
        newBattleBtn.setOnClickListener(v -> startNewBattle());
        findViewById(R.id.vote_a).setOnClickListener(v -> vote(1.0));
        findViewById(R.id.vote_tie).setOnClickListener(v -> vote(0.5));
        findViewById(R.id.vote_b).setOnClickListener(v -> vote(0.0));
        findViewById(R.id.vote_bad).setOnClickListener(v -> vote(0.25));

        findViewById(R.id.direct_send).setOnClickListener(v -> sendDirect());
        findViewById(R.id.direct_pick).setOnClickListener(v -> pickChatHero(Stores.heroes(this)));

        switchTab(0);
        startNewBattle();
    }

    private void switchTab(int i) {
        flipper.setDisplayedChild(i);
        tabBattle.setBackgroundResource(i == 0 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        tabChat.setBackgroundResource(i == 1 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        tabRanks.setBackgroundResource(i == 2 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        if (i == 2) refreshRanks();
    }

    private void startNewBattle() {
        List<Hero> heroes = Stores.heroes(this);
        List<Hero> enabled = new ArrayList<>();
        for (Hero h : heroes) if (h.enabled) enabled.add(h);
        if (enabled.size() < 2) {
            Toast.makeText(this, R.string.arena_home_need_two, Toast.LENGTH_LONG).show();
            return;
        }
        int i = rnd.nextInt(enabled.size());
        int j = rnd.nextInt(enabled.size() - 1);
        if (j >= i) j++;
        heroA = enabled.get(i);
        heroB = enabled.get(j);
        convoA.clear();
        convoB.clear();
        nameA.setText(R.string.model_a);
        nameB.setText(R.string.model_b);
        outA.setText(R.string.empty_chat);
        outB.setText(R.string.empty_chat);
        voteBar.setVisibility(View.GONE);
        newBattleBtn.setVisibility(View.GONE);
        battleGo.setVisibility(View.VISIBLE);
    }

    private String render(List<String[]> convo, String heroName) {
        StringBuilder sb = new StringBuilder();
        for (String[] m : convo) {
            sb.append(m[0].equals("user") ? "🫵 أنت: " : "⚡ " + heroName + ": ").append(m[1]).append("\n\n");
        }
        return sb.toString();
    }

    private void sendBattlePrompt() {
        if (battleBusy) return;
        String text = ((EditText) findViewById(R.id.battle_input)).getText().toString().trim();
        if (text.isEmpty()) {
            Toast.makeText(this, R.string.enter_goal, Toast.LENGTH_LONG).show();
            return;
        }
        battleBusy = true;
        outA.setText(R.string.thinking);
        outB.setText(R.string.thinking);
        final java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(2);
        final List<Provider> usable = usableProviders();
        final Provider pa = usable.isEmpty() ? null : usable.get(rnd.nextInt(usable.size()));
        final Provider pb = usable.isEmpty() ? null : usable.get(rnd.nextInt(usable.size()));
        new Thread(() -> {
            try {
                if (pa != null) {
                    String res = Api.chat(pa, heroA.system, text);
                    convoA.add(new String[]{"assistant", res});
                }
            } catch (Exception e) {
                convoA.add(new String[]{"assistant", "⚠️ " + safeErr(e)});
            }
            ui.post(() -> {
                outA.setText(render(convoA, safeNameA()));
                latch.countDown();
            });
        }).start();
        new Thread(() -> {
            try {
                if (pb != null) {
                    String res = Api.chat(pb, heroB.system, text);
                    convoB.add(new String[]{"assistant", res});
                }
            } catch (Exception e) {
                convoB.add(new String[]{"assistant", "⚠️ " + safeErr(e)});
            }
            ui.post(() -> {
                outB.setText(render(convoB, safeNameB()));
                latch.countDown();
            });
        }).start();
        new Thread(() -> {
            try {
                latch.await();
            } catch (InterruptedException ignored) {
            }
            ui.post(() -> {
                battleBusy = false;
                outA.setText(render(convoA, safeNameA()));
                outB.setText(render(convoB, safeNameB()));
                voteBar.setVisibility(View.VISIBLE);
            });
        }).start();
    }

    private String safeNameA() { return heroA == null ? "A" : heroA.name; }
    private String safeNameB() { return heroB == null ? "B" : heroB.name; }
    private String safeErr(Exception e) { return e.getMessage() == null ? "خطأ" : e.getMessage(); }

    private List<Provider> usableProviders() {
        List<Provider> out = new ArrayList<>();
        for (Provider p : Stores.providers(this)) {
            if (p.enabled && !p.base.trim().isEmpty() && (p.noKeyNeeded || !p.key.trim().isEmpty())) out.add(p);
        }
        return out;
    }

    private void vote(double sa) {
        if (heroA == null || heroB == null) return;
        Elo.record(this, heroA.id, heroB.id, sa);
        nameA.setText(heroA.emoji + " " + heroA.name);
        nameB.setText(heroB.emoji + " " + heroB.name);
        voteBar.setVisibility(View.GONE);
        newBattleBtn.setVisibility(View.VISIBLE);
        Toast.makeText(this, R.string.vote_saved, Toast.LENGTH_SHORT).show();
        refreshRanks();
    }

    private void pickChatHero(List<Hero> heroes) {
        List<String> names = new ArrayList<>();
        for (Hero h : heroes) names.add(h.emoji + " " + h.name);
        new AlertDialog.Builder(this)
                .setTitle(R.string.chat_pick_hero)
                .setItems(names.toArray(new String[0]), (d, w) -> {
                    chatHero = heroes.get(w);
                    chatConvo.clear();
                    chatConvo.add(new String[]{"assistant", "أنا " + chatHero.emoji + " " + chatHero.name + ". تفضل، أنا مستعد."});
                    chatTitle.setText(chatHero.emoji + " " + chatHero.name);
                    chatOut.setText(render(chatConvo, chatHero.name));
                })
                .show();
    }

    private void sendDirect() {
        if (chatBusy) return;
        if (chatHero == null) {
            pickChatHero(Stores.heroes(this));
            return;
        }
        String text = ((EditText) findViewById(R.id.direct_input)).getText().toString().trim();
        if (text.isEmpty()) return;
        ((EditText) findViewById(R.id.direct_input)).setText("");
        chatConvo.add(new String[]{"user", text});
        chatOut.setText(render(chatConvo, chatHero.name));
        chatBusy = true;
        new Thread(() -> {
            try {
                Provider p = Orchestrator.pickProvider(this, chatHero, 0);
                String res = Api.chat(p, chatHero.system, buildDirectContext());
                chatConvo.add(new String[]{"assistant", res});
            } catch (Exception e) {
                chatConvo.add(new String[]{"assistant", "⚠️ " + safeErr(e)});
            }
            chatBusy = false;
            ui.post(() -> chatOut.setText(render(chatConvo, chatHero.name)));
        }).start();
    }

    private String buildDirectContext() {
        StringBuilder sb = new StringBuilder();
        for (String[] m : chatConvo) {
            sb.append(m[0].equals("user") ? "المستخدم: " : "أنت: ").append(m[1]).append("\n\n");
        }
        sb.append("ردّ على آخر رسالة للمستخدم ردًّا مباشرًا أوضح وأدق.");
        return sb.toString();
    }

    private void refreshRanks() {
        List<Elo.Rating> ratings = Elo.ratings(this);
        List<Hero> heroes = Stores.heroes(this);
        List<Object[]> rows = new ArrayList<>();
        for (Hero h : heroes) {
            int score = Elo.scoreOf(this, h.id);
            int w = 0, l = 0, t = 0;
            for (Elo.Rating r : ratings) {
                if (r.heroId.equals(h.id)) { w = r.wins; l = r.losses; t = r.ties; break; }
            }
            rows.add(new Object[]{h, score, w, l, t});
        }
        Collections.sort(rows, (x, y) -> Integer.compare((Integer) y[1], (Integer) x[1]));
        List<Object[]> sorted = rows;
        ranksList.setAdapter(new BaseAdapter() {
            @Override
            public int getCount() { return sorted.size(); }

            @Override
            public Object getItem(int position) { return sorted.get(position); }

            @Override
            public long getItemId(int position) { return position; }

            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                View v = convertView != null ? convertView
                        : getLayoutInflater().inflate(R.layout.item_rank, parent, false);
                Object[] row = sorted.get(position);
                Hero h = (Hero) row[0];
                String[] medals = {"🥇", "🥈", "🥉"};
                ((TextView) v.findViewById(R.id.rank_pos)).setText(position < 3 ? medals[position] : (position + 1) + ".");
                ((TextView) v.findViewById(R.id.rank_hero)).setText(h.emoji + " " + h.name);
                ((TextView) v.findViewById(R.id.rank_score)).setText(String.valueOf(row[1]));
                ((TextView) v.findViewById(R.id.rank_record)).setText(wlt(row));
                return v;
            }

            private String wlt(Object[] row) {
                return "فوز " + row[2] + " · تعادل " + row[4] + " · خسارة " + row[3];
            }
        });
    }

}
