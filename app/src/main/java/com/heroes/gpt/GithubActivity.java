package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.View;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.util.List;

public class GithubActivity extends Activity {

    private LinearLayout loginPanel;
    private LinearLayout accountPanel;
    private TextView whoami;
    private TextView repoShow;
    private EditText tokenInput;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_github);
        loginPanel = findViewById(R.id.gh_login_panel);
        accountPanel = findViewById(R.id.gh_account_panel);
        whoami = findViewById(R.id.gh_whoami);
        repoShow = findViewById(R.id.gh_repo_show);
        tokenInput = findViewById(R.id.gh_token_input);

        findViewById(R.id.gh_login_btn).setOnClickListener(v -> login());
        findViewById(R.id.gh_open_config).setOnClickListener(v ->
                Utils.openUrl(this, Github.CONFIG_URL));
        findViewById(R.id.gh_logout_btn).setOnClickListener(v -> {
            Stores.setSetting(this, "gh_token", "");
            Stores.setSetting(this, "gh_login", "");
            Stores.setSetting(this, "gh_repo", "");
            refresh();
            Toast.makeText(this, R.string.gh_logged_out, Toast.LENGTH_SHORT).show();
        });
        findViewById(R.id.gh_pick_repo).setOnClickListener(v -> pickRepo());
        findViewById(R.id.gh_new_repo).setOnClickListener(v -> newRepo());
        findViewById(R.id.gh_browse).setOnClickListener(v -> browse());
        findViewById(R.id.gh_push_last).setOnClickListener(v -> pushLastRun());
        findViewById(R.id.gh_build).setOnClickListener(v -> buildApk());
        findViewById(R.id.gh_open_web).setOnClickListener(v -> openRepo());
        refresh();
    }

    private void refresh() {
        String token = Stores.setting(this, "gh_token");
        String login = Stores.setting(this, "gh_login");
        String repo = Stores.setting(this, "gh_repo");
        loginPanel.setVisibility(token.isEmpty() ? View.VISIBLE : View.GONE);
        accountPanel.setVisibility(token.isEmpty() ? View.GONE : View.VISIBLE);
        whoami.setText(login.isEmpty() ? "..." : getString(R.string.gh_welcome, login));
        repoShow.setText(repo.isEmpty() ? getString(R.string.gh_no_repo)
                : getString(R.string.gh_linked_repo, repo));
    }

    private interface Busy {
        void run(AlertDialog dlg);
    }

    private void busy(int msgRes, Busy body) {
        View box = getLayoutInflater().inflate(R.layout.dialog_wait, null);
        ((TextView) box.findViewById(R.id.wait_msg)).setText(msgRes);
        AlertDialog dlg = new AlertDialog.Builder(this)
                .setView(box)
                .setCancelable(true)
                .show();
        new Thread(() -> body.run(dlg)).start();
    }

    private void login() {
        final String token = tokenInput.getText().toString().trim();
        if (token.isEmpty()) {
            Toast.makeText(this, R.string.gh_need_token, Toast.LENGTH_SHORT).show();
            return;
        }
        busy(R.string.gh_checking, (dlg) -> {
            Exception[] err = {null};
            final String[] login = {""};
            try {
                login[0] = Github.validateToken(token);
                Stores.setSetting(this, "gh_token", token);
                Stores.setSetting(this, "gh_login", login[0]);
            } catch (Exception e) {
                err[0] = e;
            }
            final Exception e0 = err[0];
            dlg.dismiss();
            runOnUiThread(() -> {
                if (e0 != null) {
                    new AlertDialog.Builder(this)
                            .setTitle(R.string.gh_login_failed)
                            .setMessage(e0.getMessage() == null ? "خطأ" : e0.getMessage())
                            .setPositiveButton(R.string.close, null)
                            .show();
                } else {
                    tokenInput.setText("");
                    refresh();
                    Toast.makeText(this, getString(R.string.gh_welcome, login[0]),
                            Toast.LENGTH_LONG).show();
                }
            });
        });
    }

    private void pickRepo() {
        final String token = Stores.setting(this, "gh_token");
        if (token.isEmpty()) return;
        busy(R.string.gh_loading_repos, (dlg) -> {
            Exception[] err = {null};
            final List<Github.Repo>[] found = new List[1];
            try { found[0] = Github.myRepos(token); }
            catch (Exception e) { err[0] = e; }
            final Exception e0 = err[0];
            dlg.dismiss();
            runOnUiThread(() -> {
                if (e0 != null) {
                    ghError(e0);
                    return;
                }
                List<Github.Repo> repos = found[0];
                if (repos == null || repos.isEmpty()) {
                    Toast.makeText(this, R.string.gh_no_repos, Toast.LENGTH_LONG).show();
                    return;
                }
                String[] names = new String[repos.size()];
                for (int i = 0; i < repos.size(); i++) {
                    Github.Repo r = repos.get(i);
                    names[i] = (r.isPrivate ? "\ud83d\udd12 " : "\ud83d\udce6 ") + r.fullName;
                }
                new AlertDialog.Builder(this)
                        .setTitle(R.string.gh_pick_repo)
                        .setItems(names, (d, w) -> {
                            Stores.setSetting(this, "gh_repo", repos.get(w).fullName);
                            refresh();
                        })
                        .setNegativeButton(R.string.close, null)
                        .show();
            });
        });
    }

    private void newRepo() {
        final String token = Stores.setting(this, "gh_token");
        if (token.isEmpty()) return;
        View box = getLayoutInflater().inflate(R.layout.dialog_new_repo, null);
        EditText name = box.findViewById(R.id.nr_name);
        EditText desc = box.findViewById(R.id.nr_desc);
        android.widget.CheckBox priv = box.findViewById(R.id.nr_private);
        new AlertDialog.Builder(this)
                .setTitle(R.string.gh_new_repo)
                .setView(box)
                .setPositiveButton(R.string.create, (d, w) -> {
                    String n = name.getText().toString().trim();
                    if (n.isEmpty()) return;
                    busy(R.string.gh_creating, (dlg) -> {
                        Exception[] err = {null};
                        final String[] full = {""};
                        try {
                            full[0] = Github.createRepo(token, n,
                                    desc.getText().toString().trim(), priv.isChecked());
                        } catch (Exception e) { err[0] = e; }
                        final Exception e0 = err[0];
                        dlg.dismiss();
                        runOnUiThread(() -> {
                            if (e0 != null) {
                                ghError(e0);
                                return;
                            }
                            Stores.setSetting(this, "gh_repo", full[0]);
                            refresh();
                            Toast.makeText(this, getString(R.string.gh_created, full[0]),
                                    Toast.LENGTH_LONG).show();
                        });
                    });
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private void browse() {
        final String token = Stores.setting(this, "gh_token");
        final String repo = Stores.setting(this, "gh_repo");
        if (repo.isEmpty()) {
            Toast.makeText(this, R.string.gh_pick_repo_first, Toast.LENGTH_SHORT).show();
            return;
        }
        openDir(token, repo, "");
    }

    private void openDir(final String token, final String repo, final String dir) {
        busy(R.string.gh_loading_files, (dlg) -> {
            Exception[] err = {null};
            final List<Github.GFile>[] found = new List[1];
            try { found[0] = Github.listPath(token, repo, dir); }
            catch (Exception e) { err[0] = e; }
            final Exception e0 = err[0];
            dlg.dismiss();
            runOnUiThread(() -> {
                if (e0 != null) {
                    ghError(e0);
                    return;
                }
                List<Github.GFile> files = found[0];
                if (files == null || files.isEmpty()) {
                    Toast.makeText(this, R.string.gh_empty_repo, Toast.LENGTH_SHORT).show();
                    return;
                }
                String[] names = new String[files.size()];
                for (int i = 0; i < files.size(); i++) {
                    Github.GFile f = files.get(i);
                    names[i] = (f.type.equals("dir") ? "\ud83d\udcc1 " : "\ud83d\udcc4 ") + f.name;
                }
                new AlertDialog.Builder(this)
                        .setTitle(dir.isEmpty() ? repo : dir)
                        .setItems(names, (d, w) -> {
                            Github.GFile f = files.get(w);
                            if (f.type.equals("dir")) openDir(token, repo, f.path);
                            else viewRemoteFile(token, repo, f.path);
                        })
                        .setNegativeButton(R.string.close, null)
                        .show();
            });
        });
    }

    private void viewRemoteFile(final String token, final String repo, final String path) {
        busy(R.string.gh_loading_file, (dlg) -> {
            Exception[] err = {null};
            final String[] content = {""};
            try { content[0] = Github.fileContent(token, repo, path); }
            catch (Exception e) { err[0] = e; }
            final Exception e0 = err[0];
            dlg.dismiss();
            runOnUiThread(() -> {
                if (e0 != null) {
                    ghError(e0);
                    return;
                }
                View box = getLayoutInflater().inflate(R.layout.dialog_file_view, null);
                ((TextView) box.findViewById(R.id.file_path)).setText(path);
                ((TextView) box.findViewById(R.id.file_body)).setText(content[0]);
                new AlertDialog.Builder(this)
                        .setView(box)
                        .setPositiveButton(R.string.copy, (d, w) -> {
                            Utils.copy(this, content[0]);
                            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
                        })
                        .setNegativeButton(R.string.close, null)
                        .show();
            });
        });
    }

    private void pushLastRun() {
        final String token = Stores.setting(this, "gh_token");
        final String repo = Stores.setting(this, "gh_repo");
        if (repo.isEmpty()) {
            Toast.makeText(this, R.string.gh_pick_repo_first, Toast.LENGTH_LONG).show();
            return;
        }
        List<Stores.Run> runs = Stores.runs(this);
        if (runs.isEmpty()) {
            Toast.makeText(this, R.string.no_runs_yet, Toast.LENGTH_SHORT).show();
            return;
        }
        pushRun(token, repo, runs.get(0));
    }

    private void pushRun(final String token, final String repo, final Stores.Run run) {
        busy(R.string.pushing, (dlg) -> {
            StringBuilder log = new StringBuilder();
            List<Github.Entry> files = ProjectFiles.extract(run);
            if (files.isEmpty()) {
                Github.Entry e = new Github.Entry();
                e.path = "REPORT_" + run.id + ".md";
                StringBuilder sb = new StringBuilder("🎯 ").append(run.goal).append("\n\n");
                for (int i = 0; i < run.heroes.size(); i++) {
                    sb.append(run.heroes.get(i).emoji).append(" ")
                      .append(run.heroes.get(i).name).append(":\n")
                      .append(run.results.get(i).output).append("\n\n");
                }
                e.content = sb.toString();
                files.add(e);
            }
            Github.uploadAll(token, repo, files, "HeroesGPT/" + run.id, null, log);
            dlg.dismiss();
            runOnUiThread(() -> new AlertDialog.Builder(this)
                    .setTitle(R.string.push_done_title)
                    .setMessage(log.toString().trim())
                    .setPositiveButton(R.string.open_repo, (d2, w2) ->
                            Utils.openUrl(this, "https://github.com/" + repo))
                    .setNegativeButton(R.string.close, null)
                    .show());
        });
    }

    private void buildApk() {
        final String token = Stores.setting(this, "gh_token");
        final String repo = Stores.setting(this, "gh_repo");
        if (repo.isEmpty()) {
            Toast.makeText(this, R.string.gh_pick_repo_first, Toast.LENGTH_LONG).show();
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle(R.string.gh_build_title)
                .setMessage(getString(R.string.gh_build_msg, repo))
                .setPositiveButton(R.string.build, (d, w) -> {
                    new Thread(() -> {
                        try {
                            Github.dispatchBuild(token, repo, "apk-build.yml", "main");
                        } catch (Exception ignored) { }
                    }).start();
                    Toast.makeText(this, R.string.gh_build_started, Toast.LENGTH_LONG).show();
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private void openRepo() {
        String repo = Stores.setting(this, "gh_repo");
        if (repo.isEmpty()) {
            Toast.makeText(this, R.string.gh_pick_repo_first, Toast.LENGTH_SHORT).show();
            return;
        }
        Utils.openUrl(this, "https://github.com/" + repo);
    }

    private void ghError(Exception e) {
        new AlertDialog.Builder(this)
                .setTitle(R.string.gh_error_title)
                .setMessage(e.getMessage() == null ? "خطأ" : e.getMessage())
                .setPositiveButton(R.string.close, null)
                .show();
    }
}
