package ru.banzai.dictaphone;

import android.content.SharedPreferences;

/**
 * Type-safe wrapper around SharedPreferences for dictaphone settings.
 * Must be in ru.banzai.dictaphone to access package-private Defaults.
 */
public final class PreferencesManager {
    private final SharedPreferences prefs;

    public PreferencesManager(SharedPreferences prefs) {
        this.prefs = prefs;
    }

    public String getUrl() {
        String value = prefs.getString(Defaults.KEY_URL, Defaults.DEFAULT_URL);
        if (value == null || value.trim().isEmpty() || Defaults.isOldUrl(value)) {
            value = Defaults.DEFAULT_URL;
            prefs.edit().putString(Defaults.KEY_URL, value).apply();
        }
        return value;
    }

    public void setUrl(String url) {
        prefs.edit().putString(Defaults.KEY_URL, url).apply();
    }

    public String getToken() {
        return prefs.getString(Defaults.KEY_TOKEN, Defaults.DEFAULT_TOKEN);
    }

    public void setToken(String token) {
        prefs.edit().putString(Defaults.KEY_TOKEN, token).apply();
    }

    public void saveAll(String url, String token) {
        prefs.edit()
                .putString(Defaults.KEY_URL, url.trim())
                .putString(Defaults.KEY_TOKEN, token.trim())
                .apply();
    }
}
