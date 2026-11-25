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
import android.widget.Toast;

import java.util.List;

public class ProvidersActivity extends Activity {

    private List<Provider> providers;
    private ProviderAdapter adapter;

    private static final String[] PRESET_NAMES = {
            "Pollinations — مجاني بلا مفتاح",
            "Groq — مجاني فائق السرعة",
            "Cerebras — مجاني (1M يوميًا)",
            "Hugging Face — مجاني",
            "Mistral — مجاني (La Plateforme)",
            "Cohere — تجربة مجانية",
            "Gemini — Google AI Studio",
            "OpenRouter — نماذج :free",
            "BazaarLink — 130 نموذجًا",
            "Together AI — 5$ رصيد مجاني",
            "Fireworks AI — رصيد مجاني",
            "DeepInfra — رصيد مجاني",
            "NVIDIA NIM — تجربة مجانية",
            "SambaNova — مجاني",
            "DeepSeek",
            "مخصص"
    };
    private static final String[] PRESET_BASES = {
            "https://text.pollinations.ai/openai",
            "https://api.groq.com/openai/v1",
            "https://api.cerebras.ai/v1",
            "https://router.huggingface.co/v1",
            "https://api.mistral.ai/v1",
            "https://api.cohere.ai/compatibility/v1",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://openrouter.ai/api/v1",
            "https://api.bazaarlink.ai/v1",
            "https://api.together.xyz/v1",
            "https://api.fireworks.ai/inference/v1",
            "https://api.deepinfra.com/v1/openai",
            "https://integrate.api.nvidia.com/v1",
            "https://api.sambanova.ai/v1",
            "https://api.deepseek.com",
            ""
    };
    private static final String[] PRESET_MODELS = {
            "openai",
            "llama-3.3-70b-versatile",
            "llama-3.3-70b",
            "meta-llama/Llama-3.3-70B-Instruct",
            "mistral-small-latest",
            "command-r7b-12-2024",
            "gemini-3.8-flash",
            "google/gemma-4-31b-it:free",
            "glm-4.7-flash",
            "meta-llama/Llama-3.3-70B-Instruct-Turbo",
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "meta-llama/Llama-3.3-70B-Instruct",
            "meta/llama-3.3-70b-instruct",
            "Meta-Llama-3.3-70B-Instruct",
            "deepseek-chat",
            ""
    };
    private static final boolean[] PRESET_NOKEY = {true,false,false,false,false,false,false,false,false,false,false,false,false,false,false,false};

    private static final String[] PRESET_KEYURLS = {
            "https://enter.pollinations.ai/?ref=classic",
            "https://console.groq.com/keys",
            "https://cloud.cerebras.ai",
            "https://huggingface.co/settings/tokens",
            "https://console.mistral.ai/api-keys",
            "https://dashboard.cohere.com/api-keys",
            "https://aistudio.google.com/api-keys",
            "https://openrouter.ai/settings/keys",
            "https://bazaarlink.ai/keys",
            "https://api.together.ai/settings/api-keys",
            "https://fireworks.ai/account/api-keys",
            "https://deepinfra.com/dash/keys",
            "https://build.nvidia.com",
            "https://cloud.sambanova.ai/apis",
            "https://platform.deepseek.com/api_keys",
            ""
    };

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_providers);
        providers = Stores.providers(this);
        adapter = new ProviderAdapter();
        ((ListView) findViewById(R.id.provider_list)).setAdapter(adapter);
    }

    public void onQuickImport(View v) {
        View box = LayoutInflater.from(this).inflate(R.layout.dialog_quick_keys, null);
        final EditText input = box.findViewById(R.id.qk_input);
        new AlertDialog.Builder(this)
                .setTitle(R.string.qk_title)
                .setMessage(R.string.qk_msg)
                .setView(box)
                .setPositiveButton(R.string.qk_apply, (d, w) -> {
                    String text = input.getText().toString();
                    int n = applyKeys(text);
                    if (n == 0) {
                        Toast.makeText(this, R.string.qk_none, Toast.LENGTH_LONG).show();
                    } else {
                        Stores.saveProviders(this, providers);
                        adapter.notifyDataSetChanged();
                        Toast.makeText(this, getString(R.string.qk_done, n),
                                Toast.LENGTH_LONG).show();
                    }
                })
                .setNegativeButton(R.string.cancel, null)
                .show();
    }

    private String findProviderBase(String part) {
        for (Provider p : providers) {
            if (p.base != null && p.base.contains(part)) return p.id;
        }
        return null;
    }

    private int applyKeys(String text) {
        int count = 0;
        java.util.regex.Matcher m = java.util.regex.Pattern
                .compile("[A-Za-z0-9_\\.\\-]{20,}").matcher(text);
        while (m.find()) {
            String t = m.group().trim();
            String target = null;
            if (t.startsWith("sk-or-v1")) target = findProviderBase("openrouter.ai");
            else if (t.startsWith("sk-bl")) target = findProviderBase("bazaarlink.ai");
            else if (t.startsWith("sk_") || t.startsWith("sk-")) target = findProviderBase("pollinations.ai");
            else if (t.startsWith("AQ.")) target = findProviderBase("generativelanguage");
            else if (t.startsWith("AIzaSy")) target = findProviderBase("generativelanguage");
            else if (t.startsWith("gsk_")) target = findProviderBase("groq.com");
            else if (t.startsWith("hf_")) target = findProviderBase("huggingface");
            else continue;
            if (target == null) continue;
            for (Provider p : providers) {
                if (p.id.equals(target)) {
                    p.key = t;
                    p.enabled = true;
                    count++;
                    break;
                }
            }
        }
        return count;
    }

    public void onAddProvider(View v) {
        new AlertDialog.Builder(this)
                .setTitle(R.string.choose_preset)
                .setItems(PRESET_NAMES, new DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(DialogInterface d, int w) {
                        Provider p = Provider.make(PRESET_NAMES[w], PRESET_BASES[w],
                                PRESET_MODELS[w], "", PRESET_NOKEY[w], PRESET_KEYURLS[w]);
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
        dialogView.findViewById(R.id.paste_key_btn).setOnClickListener(v -> {
            String clip = Utils.paste(this);
            if (clip.isEmpty()) {
                Toast.makeText(this, R.string.clipboard_empty, Toast.LENGTH_SHORT).show();
            } else {
                key.setText(clip.trim());
                key.setSelection(clip.trim().length());
                Toast.makeText(this, R.string.key_pasted, Toast.LENGTH_SHORT).show();
            }
        });
        View keyBtn = dialogView.findViewById(R.id.get_key_btn);
        keyBtn.setVisibility(p.keyUrl == null || p.keyUrl.isEmpty() ? View.GONE : View.VISIBLE);
        keyBtn.setOnClickListener(v -> Utils.openUrl(this, p.keyUrl));
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
            View copyBtn = row.findViewById(R.id.provider_copy);
            View keyBtn = row.findViewById(R.id.provider_key);

            name.setText(p.name);
            boolean ready = p.noKeyNeeded || !p.key.trim().isEmpty();
            status.setText(ready ? R.string.ready : R.string.needs_key);
            status.setTextColor(getColor(ready ? R.color.ok : R.color.text_dim));

            copyBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Utils.copy(ProvidersActivity.this,
                            p.name + "\n" + p.base + "\n" + p.model + "\n" + p.key);
                    Toast.makeText(ProvidersActivity.this, R.string.copied, Toast.LENGTH_SHORT).show();
                }
            });
            keyBtn.setVisibility(p.keyUrl == null || p.keyUrl.isEmpty() ? View.GONE : View.VISIBLE);
            keyBtn.setOnClickListener(new View.OnClickListener() {
                @Override
                public void onClick(View v) {
                    Utils.openUrl(ProvidersActivity.this, p.keyUrl);
                }
            });

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
                            .setItems(new CharSequence[]{getString(R.string.delete),
                                            getString(R.string.copy_key), getString(R.string.get_free_key)},
                                    new DialogInterface.OnClickListener() {
                                        @Override
                                        public void onClick(DialogInterface d, int w) {
                                            if (w == 0) {
                                                providers.remove(position);
                                                Stores.saveProviders(ProvidersActivity.this, providers);
                                                adapter.notifyDataSetChanged();
                                            } else if (w == 1) {
                                                Utils.copy(ProvidersActivity.this, p.key);
                                                Toast.makeText(ProvidersActivity.this,
                                                        p.key.isEmpty() ? R.string.key_empty : R.string.key_copied,
                                                        Toast.LENGTH_SHORT).show();
                                            } else {
                                                Utils.openUrl(ProvidersActivity.this, p.keyUrl);
                                            }
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
