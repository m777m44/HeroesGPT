package com.heroes.gpt;

import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.widget.EditText;
import android.widget.Toast;

public class LockActivity extends Activity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_lock);
    }

    public void onUnlock(View v) {
        String pin = Stores.setting(this, "pin");
        EditText input = findViewById(R.id.lock_pin);
        String attempt = input.getText().toString().trim();
        if (attempt.equals(pin)) {
            finish();
        } else {
            Toast.makeText(this, R.string.lock_wrong, Toast.LENGTH_LONG).show();
            input.setText("");
        }
    }

    @Override
    public void onBackPressed() {
        moveTaskToBack(true);
    }
}
