package com.heroes.gpt;

import android.app.Activity;
import android.os.Bundle;
import android.widget.TextView;

public class StatsActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_stats);
        TextView body = findViewById(R.id.stats_body);
        String s = "👥 " + getString(R.string.stat_heroes) + ": " + Stores.heroes(this).size()
                + "\n🚀 " + getString(R.string.stat_runs) + ": " + Stats.get(this, Stats.RUNS)
                + "\n⚔️ " + getString(R.string.stat_battles) + ": " + Stats.get(this, Stats.BATTLES)
                + "\n🗳️ " + getString(R.string.stat_votes) + ": " + Stats.get(this, Stats.VOTES)
                + "\n💬 " + getString(R.string.stat_messages) + ": " + Stats.get(this, Stats.MESSAGES)
                + "\n💾 " + getString(R.string.stat_saved_chats) + ": " + Stats.get(this, Stats.SAVED_CHATS);
        body.setText(s);
    }
}
