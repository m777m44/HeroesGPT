package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.ListView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ChatsActivity extends Activity {

    private List<Stores.SavedChat> chats;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_chats);
        refresh();
    }

    private void refresh() {
        chats = Stores.chats(this);
        ListView lv = findViewById(R.id.chats_list);
        TextView empty = findViewById(R.id.chats_empty);
        if (chats.isEmpty()) {
            empty.setVisibility(View.VISIBLE);
            lv.setVisibility(View.GONE);
            return;
        }
        empty.setVisibility(View.GONE);
        lv.setVisibility(View.VISIBLE);
        lv.setAdapter(new BaseAdapter() {
            @Override
            public int getCount() { return chats.size(); }

            @Override
            public Object getItem(int position) { return chats.get(position); }

            @Override
            public long getItemId(int position) { return position; }

            @Override
            public View getView(int position, View convertView, ViewGroup parent) {
                View v = convertView != null ? convertView
                        : getLayoutInflater().inflate(R.layout.item_saved_chat, parent, false);
                Stores.SavedChat sc = chats.get(position);
                ((TextView) v.findViewById(R.id.chat_saved_title)).setText(sc.title);
                ((TextView) v.findViewById(R.id.chat_saved_preview)).setText(sc.preview);
                return v;
            }
        });
        lv.setOnItemClickListener((p, v, pos, id) -> showChat(chats.get(pos)));
    }

    private void showChat(Stores.SavedChat sc) {
        new AlertDialog.Builder(this)
                .setTitle(sc.title)
                .setMessage(sc.text)
                .setPositiveButton(R.string.share, (d, w) ->
                        Utils.shareText(this, sc.title, sc.text))
                .setNeutralButton(R.string.copy, (d, w) -> {
                    Utils.copy(this, sc.text);
                    Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show();
                })
                .setNegativeButton(R.string.delete, (d, w) -> {
                    Stores.deleteChat(this, sc.id);
                    Toast.makeText(this, R.string.deleted, Toast.LENGTH_SHORT).show();
                    refresh();
                })
                .show();
    }
}
