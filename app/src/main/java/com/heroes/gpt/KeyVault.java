package com.heroes.gpt;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.List;

import javax.crypto.Cipher;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.PBEKeySpec;
import javax.crypto.spec.SecretKeySpec;

/**
 * الخزنة المشفرة — KeyVault (v6.6)
 * تشفير مفاتيح المزودين بمعيار AES-256-GCM (سري + نزاهة مضادة للعبث)
 * مع اشتقاق مفتاح PBKDF2-HmacSHA256، ورفعها/استعادتها من المستودع بنقرة واحدة.
 * الملف في المستودع مشفّر بالكامل — لا يظهر فيه أي مفتاح بصيغته الأصلية.
 */
public final class KeyVault {

    // سر التشفير مدمج داخل التطبيق (مقسّم لتعذّر السحب السطحي)
    private static final String S1 = "81ac6a740cf5c88f7abebf75c2d37e28";
    private static final String S2 = "d7e8a99b002b709e4bac778313238b25";
    private static final char[] SECRET = (S1 + S2).toCharArray();

    private static final int ITERS = 120000;
    private static final int GCM_TAG_BITS = 128;
    public static final String VAULT_PATH = "keys/heroes-vault.json";
    public static final String DEFAULT_REPO = "m777m44/HeroesGPT";

    private KeyVault() { }

    // ---------- primitives ----------

    private static SecretKeySpec deriveKey(byte[] salt) throws Exception {
        PBEKeySpec spec = new PBEKeySpec(SECRET, salt, ITERS, 256);
        byte[] km = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256")
                .generateSecret(spec).getEncoded();
        spec.clearPassword();
        return new SecretKeySpec(km, "AES");
    }

    private static String b64(byte[] b) {
        return android.util.Base64.encodeToString(b, android.util.Base64.NO_WRAP);
    }

    private static byte[] unb64(String s) {
        return android.util.Base64.decode(s, android.util.Base64.NO_WRAP);
    }

    private static String sha256hex(byte[] b) {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(b);
            StringBuilder sb = new StringBuilder();
            for (byte x : d) sb.append(String.format("%02x", x));
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    // ---------- encrypt / decrypt ----------

    /** يشفر قائمة المزودين ويعيد نص JSON للخزنة (آمن للنشر في مستودع عام). */
    public static String encrypt(List<Provider> ps) throws Exception {
        JSONArray arr = new JSONArray();
        for (Provider p : ps) {
            if (p == null || p.key == null || p.key.trim().isEmpty()) continue;
            JSONObject po = new JSONObject();
            po.put("name", p.name == null ? "" : p.name);
            po.put("base", p.base == null ? "" : p.base);
            po.put("model", p.model == null ? "" : p.model);
            po.put("key", p.key);
            po.put("kind", p.kind == null ? "openai" : p.kind);
            po.put("keyUrl", p.keyUrl == null ? "" : p.keyUrl);
            arr.put(po);
        }
        if (arr.length() == 0) throw new Exception("لا توجد مفاتيح لحفظها في الخزنة — أضف مفاتيحك أولًا");

        JSONObject payload = new JSONObject();
        payload.put("app", "HeroesGPT");
        payload.put("providers", arr);
        byte[] plain = payload.toString().getBytes(StandardCharsets.UTF_8);

        SecureRandom rnd = new SecureRandom();
        byte[] salt = new byte[16];
        byte[] iv = new byte[12];
        rnd.nextBytes(salt);
        rnd.nextBytes(iv);

        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.ENCRYPT_MODE, deriveKey(salt), new GCMParameterSpec(GCM_TAG_BITS, iv));
        byte[] ct = c.doFinal(plain);

        JSONObject vault = new JSONObject();
        vault.put("app", "HeroesGPT");
        vault.put("v", 2);
        vault.put("alg", "AES-256-GCM");
        vault.put("kdf", "PBKDF2-HmacSHA256");
        vault.put("iters", ITERS);
        vault.put("salt", b64(salt));
        vault.put("iv", b64(iv));
        vault.put("ct", b64(ct));
        vault.put("fp", sha256hex(ct).substring(0, 12));
        vault.put("createdAt", System.currentTimeMillis());
        return vault.toString(2);
    }

    /** يفك التشفير ويتحقق من النزاهة (أي عبث = فشل) ويعيد قائمة المزودين. */
    public static List<Provider> decrypt(String vaultJson) throws Exception {
        JSONObject vault = new JSONObject(vaultJson);
        if (!"HeroesGPT".equals(vault.optString("app")))
            throw new Exception("الملف ليس خزنة HeroesGPT");
        byte[] salt = unb64(vault.getString("salt"));
        byte[] iv = unb64(vault.getString("iv"));
        byte[] ct = unb64(vault.getString("ct"));
        Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE, deriveKey(salt), new GCMParameterSpec(GCM_TAG_BITS, iv));
        byte[] plain;
        try {
            plain = c.doFinal(ct);
        } catch (Exception e) {
            throw new Exception("فشل فك التشفير — الخزنة تالفة أو غير مكتملة");
        }
        JSONObject payload = new JSONObject(new String(plain, StandardCharsets.UTF_8));
        JSONArray arr = payload.optJSONArray("providers");
        List<Provider> out = new ArrayList<>();
        if (arr != null) {
            for (int i = 0; i < arr.length(); i++) {
                JSONObject po = arr.optJSONObject(i);
                if (po == null) continue;
                Provider p = new Provider();
                p.id = "p" + System.nanoTime() + "_" + i;
                p.name = po.optString("name", "مزوّد");
                p.base = po.optString("base", "");
                p.model = po.optString("model", "");
                p.key = po.optString("key", "");
                p.kind = po.optString("kind", "openai");
                p.keyUrl = po.optString("keyUrl", "");
                p.enabled = true;
                p.noKeyNeeded = false;
                if (!p.base.isEmpty() && !p.key.isEmpty()) out.add(p);
            }
        }
        if (out.isEmpty()) throw new Exception("الخزنة لا تحتوي مفاتيح صالحة");
        return out;
    }

    /** بصمة الخزنة الحالية (للتحقق السريع) أو "" إن لم توجد مفاتيح. */
    public static String fingerprint(Context c) {
        try {
            List<Provider> ps = Stores.providers(c);
            boolean any = false;
            for (Provider p : ps) if (p.key != null && !p.key.trim().isEmpty()) { any = true; break; }
            if (!any) return "";
            String vault = encrypt(ps);
            return new JSONObject(vault).optString("fp", "");
        } catch (Exception e) {
            return "";
        }
    }

    // ---------- upload ----------

    /** يرفع الخزنة المشفرة إلى keys/heroes-vault.json في مستودع GitHub. يعيد سجل النتيجة. */
    public static String upload(Context c) throws Exception {
        String token = Stores.setting(c, "gh_token");
        String repo = Stores.setting(c, "gh_repo");
        if (token == null || token.trim().isEmpty())
            throw new Exception("سجّل دخول GitHub أولًا من شاشة GitHub 🔑");
        if (repo == null || repo.trim().isEmpty())
            throw new Exception("اختر مستودعًا أولًا من شاشة GitHub 📦");

        String vault = encrypt(Stores.providers(c));
        Github.Entry e = new Github.Entry();
        e.path = "heroes-vault.json";
        e.content = vault;
        List<Github.Entry> files = new ArrayList<>();
        files.add(e);
        Github.CommitResult cr = Github.commitAll(token, repo, files, "keys",
                "HeroesGPT: update encrypted key vault 🔐", null);
        String fp = new JSONObject(vault).optString("fp", "");
        return "✅ رُفعت الخزنة المشفرة إلى " + repo + " → " + VAULT_PATH
                + "\n🔒 بصمة الخزنة: " + fp
                + "\n" + cr.log.toString().trim();
    }

    // ---------- restore ----------

    /** يستعيد المفاتيح: يجرّب المستودع ثم الأصل المدمج، ويدمج مع المزودين الحاليين. */
    public static String restore(Context c) throws Exception {
        String vault = fetchVaultFromGithub(c);
        if (vault == null) vault = fetchVaultFromAsset(c);
        if (vault == null)
            throw new Exception("لا توجد خزنة في المستودع (" + VAULT_PATH + ") — ارفعها أولًا بزر الرفع");

        List<Provider> incoming = decrypt(vault);
        List<Provider> current = Stores.providers(c);
        int updated = 0, added = 0;
        for (Provider np : incoming) {
            boolean hit = false;
            for (Provider p : current) {
                if (p.base != null && p.base.equals(np.base)) {
                    if (p.key == null || p.key.trim().isEmpty()) { p.key = np.key; updated++; }
                    else if (!p.key.equals(np.key)) { p.key = np.key; updated++; }
                    if (p.model == null || p.model.isEmpty()) p.model = np.model;
                    hit = true;
                    break;
                }
            }
            if (!hit) { current.add(np); added++; }
        }
        Stores.saveProviders(c, current);
        String fp = new JSONObject(vault).optString("fp", "");
        return "✅ استُعيدت الخزنة: " + updated + " مفتاحًا حُدِّث، " + added + " مزودًا أُضيف"
                + "\n🔒 بصمة الخزنة: " + fp
                + "\nالمجموع الآن: " + current.size() + " مزودًا";
    }

    /** استعادة صامتة تلقائية عند أول تشغيل إن لم توجد أي مفاتيح. */
    public static void autoRestoreIfEmpty(final Context c) {
        new Thread(() -> {
            try {
                List<Provider> ps = Stores.providers(c);
                boolean anyKey = false;
                for (Provider p : ps) if (p.key != null && !p.key.trim().isEmpty()) { anyKey = true; break; }
                if (anyKey) return;
                restore(c);
            } catch (Exception ignored) {
            }
        }).start();
    }

    private static String fetchVaultFromGithub(Context c) {
        String repo = Stores.setting(c, "gh_repo");
        if (repo == null || repo.trim().isEmpty()) repo = DEFAULT_REPO;
        String[] urls = {
                "https://raw.githubusercontent.com/" + repo + "/main/" + VAULT_PATH,
                "https://raw.githubusercontent.com/" + repo + "/master/" + VAULT_PATH
        };
        for (String u : urls) {
            try {
                HttpURLConnection cn = (HttpURLConnection) new URL(u).openConnection();
                cn.setConnectTimeout(12000);
                cn.setReadTimeout(20000);
                int code = cn.getResponseCode();
                if (code != 200) continue;
                return readAll(cn.getInputStream());
            } catch (Exception ignored) {
            }
        }
        return null;
    }

    private static String fetchVaultFromAsset(Context c) {
        try {
            InputStream in = c.getAssets().open(VAULT_PATH);
            return readAll(in);
        } catch (Exception e) {
            return null;
        }
    }

    private static String readAll(InputStream in) throws Exception {
        ByteArrayOutputStream bos = new ByteArrayOutputStream();
        byte[] buf = new byte[8192];
        int n;
        while ((n = in.read(buf)) > 0) bos.write(buf, 0, n);
        in.close();
        return bos.toString("UTF-8");
    }
}
