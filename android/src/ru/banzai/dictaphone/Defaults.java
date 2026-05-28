package ru.banzai.dictaphone;

final class Defaults {
    static final String PREFS = "banzai_dictaphone";
    static final String KEY_URL = "url";
    static final String KEY_TOKEN = "token";
    static final String DEFAULT_URL = "";
    static final String OLD_URL = "";
    static final String OLD_URL_2 = "";
    static final String DEFAULT_TOKEN = "";

    private Defaults() {}

    static boolean isOldUrl(String url) {
        String value = url == null ? "" : url.trim();
        while (value.endsWith("/")) value = value.substring(0, value.length() - 1);
        if (DEFAULT_URL.equals(value)) return false;
        return OLD_URL.equals(value)
                || OLD_URL_2.equals(value)
                || value.endsWith(".trycloudflare.com");
    }
}
