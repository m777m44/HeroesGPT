package com.heroes.gpt;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.List;

public class ArenaActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());
    private List<Provider> usable = new ArrayList<>();
    private Spinner left;
    private Spinner right;
    private Button goBtn;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_arena);
        left = findViewById(R.id.arena_left);
        right = findViewById(R.id.arena_right);
        goBtn = findViewById(R.id.arena_go);
        TextView la = findViewById(R.id.arena_left_out);
        TextView ra = findViewById(R.id.arena_right_out);

        for (Provider p : Stores.providers(this)) {
            if (p.enabled && !p.base.trim().isEmpty() && (p.noKeyNeeded || !p.key.trim().isEmpty())) {
                usable.add(p);
            }
        }
        if (usable.size() < 2) {
            Toast.makeText(this, R.string.arena_need_two, Toast.LENGTH_LONG).show();
            goBtn.setEnabled(false);
        }
        List<String> names = new ArrayList<>();
        for (Provider p : usable) names.add(p.name);
        ArrayAdapter<String> ad = new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, names);
        left.setAdapter(ad);
        right.setAdapter(usable.size() > 1 ? new ArrayAdapter<>(this, android.R.layout.simple_spinner_dropdown_item, names.subList(1, names.size())) : ad);
        right.setSelection(usable.size() > 1 ? 0 : 0);

        goBtn.setOnClickListener(v -> {
            String prompt = ((EditText) findViewById(R.id.arena_prompt)).getText().toString().trim();
            if (prompt.isEmpty()) {
                Toast.makeText(this, R.string.enter_goal, Toast.LENGTH_LONG).show();
                return;
            }
            int ia = Math.min(left.getSelectedItemPosition(), usable.size() - 1);
            int ibRaw = right.getSelectedItemPosition();
            int ib = usable.size() > 1 ? Math.min(ibRaw + 1, usable.size() - 1) : Math.min(ia + 1, usable.size() - 1);
            if (ib == ia && usable.size() > 1) ib = (ia + 1) % usable.size();
            final Provider pa = usable.get(Math.max(ia, 0));
            final Provider pb = usable.get(Math.max(ib, 0));
            goBtn.setEnabled(false);
            la.setText(R.string.arena_running);
            ra.setText(R.string.arena_running);
            new Thread(() -> {
                runOne(pa, prompt, la);
                runOne(pb, prompt, ra);
                ui.post(() -> goBtn.setEnabled(true));
            }).start();
        });
    }

    private void runOne(Provider p, String prompt, TextView out) {
        try {
            String res = Api.chat(p, "أنت أخصائيُ المقارنة: أجب بأفضل جودة وإيجاز، وبنفس لغة سؤال المستخدم.", prompt);
            ui.post(() -> out.setText(res));
        } catch (Exception e) {
            String msg = e.getMessage() == null ? "خطأ" : e.getMessage();
            ui.post(() -> out.setText(getString(R.string.arena_failed, msg)));
        }
    }
}
