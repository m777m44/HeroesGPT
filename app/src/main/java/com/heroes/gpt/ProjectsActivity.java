package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.content.Intent;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.TextView;

import java.util.List;

public class ProjectsActivity extends Activity {

    private List<Stores.Run> runs;
    private RunAdapter adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_projects);
        runs = Stores.runs(this);
        adapter = new RunAdapter();
        ((ListView) findViewById(R.id.projects_list)).setAdapter(adapter);
    }

    private class RunAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return runs.size();
        }

        @Override
        public Object getItem(int position) {
            return runs.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(final int position, View convertView, ViewGroup parent) {
            View row = convertView;
            if (row == null) {
                row = LayoutInflater.from(ProjectsActivity.this)
                        .inflate(R.layout.item_project, parent, false);
            }
            Stores.Run r = runs.get(position);
            TextView goal = row.findViewById(R.id.project_goal);
            TextView meta = row.findViewById(R.id.project_meta);

            goal.setText(r.goal.length() > 80 ? r.goal.substring(0, 80) + "…" : r.goal);
            boolean complete = r.stage >= r.heroes.size();
            meta.setText(complete
                    ? getString(R.string.project_done, r.heroes.size())
                    : getString(R.string.project_progress, r.stage, r.heroes.size()));
            meta.setTextColor(getColor(complete ? R.color.ok : R.color.accent));

            row.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Intent i = new Intent(ProjectsActivity.this, RunActivity.class);
                    i.putExtra("run_id", runs.get(position).id);
                    startActivity(i);
                }
            });
            row.setOnLongClickListener(new View.OnLongClickListener() {
                @Override
                public boolean onLongClick(View v) {
                    new AlertDialog.Builder(ProjectsActivity.this)
                            .setTitle(R.string.delete_title)
                            .setPositiveButton(R.string.delete, new DialogInterface.OnClickListener() {
                                @Override
                                public void onClick(DialogInterface d, int w) {
                                    Stores.deleteRun(ProjectsActivity.this, runs.get(position).id);
                                    runs.remove(position);
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
