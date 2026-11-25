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
import android.widget.ImageButton;
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
    private Button tabMission;
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
    private ImageButton battleGo;
    private Button newBattleBtn;
    private boolean battleBusy;
    private String lastQuestion = "";

    private Hero chatHero;
    private final List<String[]> chatConvo = new ArrayList<>();
    private TextView chatOut;
    private TextView chatTitle;
    private boolean chatBusy;

    private ListView ranksList;
    private EditText missionInput;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        CrashCatcher.install(this);
        super.onCreate(savedInstanceState);
        try {
            setContentView(R.layout.activity_arena_home);
            setupAll(savedInstanceState);
            CrashCatcher.reportIfCrashed(this);
        } catch (Throwable t) {
            CrashCatcher.showErrorScreen(this, t);
        }
    }

    private void setupAll(Bundle savedInstanceState) {
        setContentView(R.layout.activity_arena_home);

        flipper = findViewById(R.id.flipper);
        tabMission = findViewById(R.id.tab_mission);
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
        missionInput = findViewById(R.id.mission_input);

        tabMission.setOnClickListener(v -> switchTab(0));
        tabBattle.setOnClickListener(v -> switchTab(1));
        tabChat.setOnClickListener(v -> switchTab(2));
        tabRanks.setOnClickListener(v -> switchTab(3));
        findViewById(R.id.mission_launch).setOnClickListener(v -> onLaunchMission());
        findViewById(R.id.mission_status).setOnClickListener(v -> openLatestMission());
        findViewById(R.id.m_tpl_biz).setOnClickListener(v -> setMissionText(R.string.tpl_biz_full));
        findViewById(R.id.m_tpl_learn).setOnClickListener(v -> setMissionText(R.string.tpl_learn_full));
        findViewById(R.id.m_tpl_app).setOnClickListener(v -> setMissionText(R.string.tpl_app_full));
        findViewById(R.id.m_tpl_content).setOnClickListener(v -> setMissionText(R.string.tpl_content_full));

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
        findViewById(R.id.direct_save).setOnClickListener(v -> saveDirectChat());

        findViewById(R.id.vote_judge).setOnClickListener(v -> runJudge());
        findViewById(R.id.battle_share).setOnClickListener(v -> shareBattle());
        nameA.setOnClickListener(v -> pickBattleHero(true));
        nameB.setOnClickListener(v -> pickBattleHero(false));

        Stores.ensureFreeRotationBackup(this);
        switchTab(0);
        startNewBattle();
        checkUpdateSilently();
        if (!Stores.setting(this, "pin").isEmpty()) {
            startActivity(new Intent(this, LockActivity.class));
        }
    }

    private void switchTab(int i) {
        flipper.setDisplayedChild(i);
        tabMission.setBackgroundResource(i == 0 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        tabBattle.setBackgroundResource(i == 1 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        tabChat.setBackgroundResource(i == 2 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        tabRanks.setBackgroundResource(i == 3 ? R.drawable.bg_tab_selected : R.drawable.bg_chip);
        if (i == 3) refreshRanks();
        if (i == 0) refreshMission();
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshMission();
    }

    private void onLaunchMission() {
        String goal = missionInput.getText().toString().trim();
        if (goal.isEmpty()) {
            Toast.makeText(this, R.string.enter_goal, Toast.LENGTH_LONG).show();
            return;
        }
        Stores.Run run = Stores.newRun(this, goal, Stores.heroes(this));
        Stats.inc(this, Stats.RUNS);
        missionInput.setText("");
        Intent i = new Intent(this, RunActivity.class);
        i.putExtra("run_id", run.id);
        i.putExtra("autostart", true);
        startActivity(i);
    }

    private void openLatestMission() {
        List<Stores.Run> runs = Stores.runs(this);
        if (runs.isEmpty()) return;
        Intent i = new Intent(this, RunActivity.class);
        i.putExtra("run_id", runs.get(0).id);
        startActivity(i);
    }

    private void setMissionText(int res) {
        missionInput.setText(getString(res));
        missionInput.setSelection(missionInput.getText().length());
    }

    private void refreshMission() {
        TextView team = findViewById(R.id.mission_team_show);
        if (team != null) {
            StringBuilder sb = new StringBuilder();
            int n = 0;
            for (Hero h : Stores.heroes(this)) {
                if (!h.enabled) continue;
                sb.append(h.emoji).append(" ").append(h.name);
                n++;
                if (n < 12) sb.append("   ·   ");
            }
            team.setText(n == 0 ? getString(R.string.arena_home_need_two) : sb.toString().trim());
        }
        TextView st = findViewById(R.id.mission_status);
        if (st == null) return;
        List<Stores.Run> runs = Stores.runs(this);
        if (runs.isEmpty()) {
            st.setText(R.string.mission_status_none);
        } else {
            Stores.Run r = runs.get(0);
            String hero = r.stage < r.heroes.size()
                    ? r.heroes.get(Math.min(r.stage, r.heroes.size() - 1)).name
                    : "تم التسليم ✓";
            st.setText(getString(R.string.latest_run, r.goal, r.stage, r.heroes.size(), hero));
        }
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
        lastQuestion = text;
        Stats.inc(this, Stats.BATTLES);
        outA.setText(R.string.thinking);
        outB.setText(R.string.thinking);
        final java.util.concurrent.CountDownLatch latch = new java.util.concurrent.CountDownLatch(2);
        final List<Provider> usable = usableProviders();
        final int size = usable.size();
        final int ia = size == 0 ? 0 : rnd.nextInt(size);
        final int ib = size == 0 ? 0 : (ia + 1 + (size > 1 ? rnd.nextInt(size - 1) : 0)) % size;
        final List<Provider> orderA = orderedFrom(usable, ia);
        final List<Provider> orderB = orderedFrom(usable, ib);
        new Thread(() -> {
            try {
                String res = chatFirstOk(orderA, heroA.system, text);
                convoA.add(new String[]{"assistant", res});
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
                String res = chatFirstOk(orderB, heroB.system, text);
                convoB.add(new String[]{"assistant", res});
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
        Stats.inc(this, Stats.VOTES);
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
        Stats.inc(this, Stats.MESSAGES);
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


    private List<Provider> orderedFrom(List<Provider> usable, int start) {
        List<Provider> out = new ArrayList<>();
        for (int k = 0; k < usable.size(); k++) out.add(usable.get((start + k) % usable.size()));
        return out;
    }

    private String chatFirstOk(List<Provider> order, String system, String text) throws Exception {
        Exception last = null;
        for (Provider p : order) {
            try {
                return Api.chat(p, system, text);
            } catch (Exception e) {
                last = e;
            }
        }
        throw last != null ? last : new IllegalStateException("no provider");
    }

    private void pickBattleHero(final boolean slotA) {
        List<Hero> heroes = Stores.heroes(this);
        List<Hero> enabled = new ArrayList<>();
        for (Hero h : heroes) if (h.enabled) enabled.add(h);
        if (enabled.isEmpty()) return;
        List<String> names = new ArrayList<>();
        for (Hero h : enabled) names.add(h.emoji + " " + h.name);
        new AlertDialog.Builder(this)
                .setTitle(slotA ? R.string.pick_hero_a : R.string.pick_hero_b)
                .setItems(names.toArray(new String[0]), (d, w) -> {
                    Hero picked = enabled.get(w);
                    if (!slotA && heroA != null && picked.id.equals(heroA.id)) {
                        Toast.makeText(this, R.string.arena_home_need_two, Toast.LENGTH_SHORT).show();
                        return;
                    }
                    if (slotA) {
                        heroA = picked;
                        convoA.clear();
                        outA.setText(R.string.empty_chat);
                    } else {
                        heroB = picked;
                        convoB.clear();
                        outB.setText(R.string.empty_chat);
                    }
                })
                .show();
    }

    private void runJudge() {
        if (heroA == null || heroB == null || battleBusy) return;
        final String ansA = lastAssistant(convoA);
        final String ansB = lastAssistant(convoB);
        if (ansA.isEmpty() || ansB.isEmpty()) return;
        Toast.makeText(this, R.string.judge_thinking, Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                List<Provider> usable = usableProviders();
                if (usable.isEmpty()) throw new IllegalStateException("no providers");
                Provider p = usable.get(rnd.nextInt(usable.size()));
                String prompt = getString(R.string.judge_prompt, lastQuestion, clip(ansA, 3000), clip(ansB, 3000));
                String res = Api.chat(p, "You are a fair precise arena judge. Reply with one word only: A, B, or TIE.", prompt).trim();
                final double sa;
                if (res.startsWith("A")) sa = 1.0;
                else if (res.startsWith("B")) sa = 0.0;
                else if (res.toUpperCase().contains("TIE")) sa = 0.5;
                else throw new IllegalStateException("unclear");
                ui.post(() -> vote(sa));
            } catch (Exception e) {
                ui.post(() -> Toast.makeText(this, R.string.judge_failed, Toast.LENGTH_LONG).show());
            }
        }).start();
    }

    private String lastAssistant(List<String[]> convo) {
        for (int i = convo.size() - 1; i >= 0; i--) {
            if (convo.get(i)[0].equals("assistant")) return convo.get(i)[1];
        }
        return "";
    }

    private String clip(String s, int max) {
        return s.length() > max ? s.substring(0, max) + "…" : s;
    }

    private void shareBattle() {
        if (lastQuestion.isEmpty()) return;
        StringBuilder sb = new StringBuilder();
        sb.append("\u2694\ufe0f \u0645\u0639\u0631\u0643\u0629 HeroesGPT\n\n");
        sb.append("\ud83e\uddfa \u0627\u0644\u0633\u0624\u0627\u0644:\n").append(lastQuestion).append("\n\n");
        sb.append("\u2014 A: ").append(safeNameA()).append(" \u2014\n").append(render(convoA, safeNameA()));
        sb.append("\n\u2014 B: ").append(safeNameB()).append(" \u2014\n").append(render(convoB, safeNameB()));
        Utils.shareText(this, "HeroesGPT", sb.toString());
    }

    private void saveDirectChat() {
        if (chatConvo.isEmpty()) return;
        String title = chatHero == null ? "\u062f\u0631\u062f\u0634\u0629" : chatHero.emoji + " " + chatHero.name;
        StringBuilder sb = new StringBuilder();
        for (String[] m : chatConvo) {
            sb.append(m[0].equals("user") ? "\ud83e\uddf1 \u0623\u0646\u062a: " : "\u26a1 " + title + ": ").append(m[1]).append("\n\n");
        }
        Stores.saveChat(this, title, sb.toString());
        Stats.inc(this, Stats.SAVED_CHATS);
        Toast.makeText(this, R.string.saved, Toast.LENGTH_SHORT).show();
    }

    private void checkUpdateSilently() {
        new Thread(() -> {
            try {
                Updater.Info info = Updater.check();
                if (info.versionCode > Updater.currentVersionCode(ArenaHomeActivity.this)) {
                    ui.post(() -> {
                        Button b = findViewById(R.id.header_update);
                        b.setText(R.string.update_available_badge);
                        b.setTextColor(getColor(R.color.danger));
                        showBanner(info);
                    });
                }
            } catch (Exception ignored) {
            }
        }).start();
    }

    private void showBanner(Updater.Info info) {
        View banner = findViewById(R.id.update_banner);
        if (banner == null || banner.getVisibility() == View.VISIBLE) return;
        TextView msg = findViewById(R.id.banner_msg);
        if (msg != null && info != null) {
            String notes = info.notes == null ? "" : info.notes;
            int cut = notes.indexOf(46);
            String line = notes.isEmpty() ? "" 
                    : notes.substring(0, cut > 0 && cut < 90 ? cut : Math.min(notes.length(), 90));
            msg.setText(getString(R.string.banner_update_msg, info.versionName));
            TextView notesView = findViewById(R.id.banner_notes);
            if (notesView != null) notesView.setText(line);
        }
        banner.setVisibility(View.VISIBLE);
        banner.startAnimation(android.view.animation.AnimationUtils.loadAnimation(this, R.anim.slide_up));
        findViewById(R.id.banner_update).setOnClickListener(v ->
                startActivity(new Intent(this, UpdateActivity.class)));
        findViewById(R.id.banner_close).setOnClickListener(v -> banner.setVisibility(View.GONE));
    }
}
