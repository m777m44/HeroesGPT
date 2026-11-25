package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.widget.Button;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;

public class UpdateActivity extends Activity {

    private final Handler ui = new Handler(Looper.getMainLooper());
    private TextView status;
    private ProgressBar bar;
    private Button installBtn;
    private Button checkBtn;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_update);
        status = findViewById(R.id.update_status);
        bar = findViewById(R.id.update_bar);
        installBtn = findViewById(R.id.install_btn);
        checkBtn = findViewById(R.id.check_btn);
        checkBtn.setOnClickListener(v -> check());
        installBtn.setOnClickListener(v -> download());
        status.setText(getString(R.string.current_version_fmt, Updater.currentVersionName(this)));
        check();
    }

    private void check() {
        status.setText(R.string.checking_update);
        installBtn.setVisibility(View.GONE);
        new Thread(() -> {
            try {
                Updater.Info info = Updater.check();
                int cur = Updater.currentVersionCode(this);
                ui.post(() -> {
                    if (info.versionCode > cur) {
                        status.setText(getString(R.string.update_available, info.versionName, info.notes));
                        installBtn.setVisibility(View.VISIBLE);
                    } else {
                        status.setText(R.string.up_to_date);
                        installBtn.setVisibility(View.GONE);
                    }
                });
            } catch (Exception e) {
                String msg = e.getMessage() == null ? "?" : e.getMessage();
                ui.post(() -> status.setText(getString(R.string.update_check_failed, msg)));
            }
        }).start();
    }

    private void download() {
        checkBtn.setEnabled(false);
        installBtn.setEnabled(false);
        bar.setProgress(0);
        bar.setVisibility(View.VISIBLE);
        status.setText(R.string.downloading);
        new Thread(() -> {
            try {
                Updater.download(this, pct -> ui.post(() -> {
                    bar.setProgress(pct);
                    status.setText(getString(R.string.download_progress, pct));
                }));
                ui.post(() -> {
                    bar.setProgress(100);
                    status.setText(R.string.download_done);
                    showInstallDialog();
                });
            } catch (Exception e) {
                String msg = e.getMessage() == null ? "?" : e.getMessage();
                ui.post(() -> {
                    status.setText(getString(R.string.download_failed, msg));
                    checkBtn.setEnabled(true);
                    installBtn.setEnabled(true);
                    Toast.makeText(this, R.string.update_check_failed_short, Toast.LENGTH_LONG).show();
                });
            }
        }).start();
    }

    private void showInstallDialog() {
        new AlertDialog.Builder(this)
                .setTitle(R.string.update_ready_title)
                .setMessage(R.string.update_ready_msg)
                .setPositiveButton(R.string.install, (d, w) -> {
                    try {
                        Updater.install(this);
                    } catch (Exception e) {
                        Toast.makeText(this, R.string.install_failed, Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton(R.string.cancel, (d, w) -> {
                    checkBtn.setEnabled(true);
                    installBtn.setEnabled(true);
                })
                .show();
    }
}
