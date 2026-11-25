package com.heroes.gpt;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;

import java.util.List;

public class ProvidersActivity extends Activity {

    private List<Provider> providers;
    private ProviderAdapter adapter;

    private static final String[] PRESET_NAMES = {
            "Pollinations — مجاني بلا مفتاح",
            "GLM-4.5-Flash — مجاني (z.ai)",
            "Gemini — مجاني (Google AI Studio)",
            "OpenRouter — نماذج :free",
            "DeepSeek",
            "مخصص"
    };
    private static final String[] PRESET_BASES = {
            "https://text.pollinations.ai/openai",
            "https://api.z.ai/api/paas/v4",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://openrouter.ai/api/v1",
            "https://api.deepseek.com",
            ""
    };
    private static final String[] PRESET_MODELS = {
            "openai",
            "glm-4.5-flash",
            "gemini-2.5-flash",
            "deepseek/deepseek-chat-v3-0324:free",
            "deepseek-chat",
            ""
    };
    private static final boolean[] PRESET_NOKEY = {true, false, false, false, false, false};

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_providers);
        providers = Stores.providers(this);
        adapter = new ProviderAdapter();
        ((ListView) findViewById(R.id.provider_list)).setAdapter(adapter);
    }

    public void onAddProvider(View v) {
        new AlertDialog.Builder(this)
                .setTitle(R.string.choose_preset)
                .setItems(PRESET_NAMES, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        Provider p = Provider.make(PRESET_NAMES[w], PRESET_BASES[w],
                                PRESET_MODELS[w], "", PRESET_NOKEY[w]);
                        providers.add(p);
                        Stores.saveProviders(ProvidersActivity.this, providers);
                        adapter.notifyDataSetChanged();
                        editProvider(p);
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private void editProvider(final Provider p) {
        View dialogView = LayoutInflater.from(this).inflate(R.layout.dialog_edit_provider, null);
        final EditText name = dialogView.findViewById(R.id.edit_pname);
        final EditText base = dialogView.findViewById(R.id.edit_base);
        final EditText model = dialogView.findViewById(R.id.edit_model);
        final EditText key = dialogView.findViewById(R.id.edit_key);
        name.setText(p.name);
        base.setText(p.base);
        model.setText(p.model);
        key.setText(p.key);
        new AlertDialog.Builder(this)
                .setTitle(R.string.edit_provider)
                .setView(dialogView)
                .setPositiveButton(R.string.save, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        p.name = name.getText().toString().trim().isEmpty()
                                ? p.name : name.getText().toString().trim();
                        p.base = base.getText().toString().trim();
                        p.model = model.getText().toString().trim();
                        p.key = key.getText().toString().trim();
                        Stores.saveProviders(ProvidersActivity.this, providers);
                        adapter.notifyDataSetChanged();
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private class ProviderAdapter extends BaseAdapter {

        @Override
        public int getCount() {
            return providers.size();
        }

        @Override
        public Object getItem(int position) {
            return providers.get(position);
        }

        @Override
        public long getItemId(int position) {
            return position;
        }

        @Override
        public View getView(final int position, View convertView, ViewGroup parent) {
            View row = convertView;
            if (row == null) {
                row = LayoutInflater.from(ProvidersActivity.this)
                        .inflate(R.layout.item_provider, parent, false);
            }
            final Provider p = providers.get(position);
            TextView name = row.findViewById(R.id.provider_name);
            TextView status = row.findViewById(R.id.provider_status);

            name.setText(p.name);
            boolean ready = p.noKeyNeeded || !p.key.trim().isEmpty();
            status.setText(ready ? R.string.ready : R.string.needs_key);
            status.setTextColor(getColor(ready ? R.color.ok : R.color.text_dim));

            row.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    editProvider(p);
                }
            });
            row.setOnLongClickListener(new View.OnLongClickListener() {
                @Override
                public boolean onLongClick(View v) {
                    new AlertDialog.Builder(ProvidersActivity.this)
                            .setTitle(p.name)
                            .setItems(new CharSequence[]{getString(R.string.delete)},
                                    new DialogInterface.OnClickListener() {
                                        @Override
                                        public void onClick(DialogInterface d, int w) {
                                            providers.remove(position);
                                            Stores.saveProviders(ProvidersActivity.this, providers);
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
