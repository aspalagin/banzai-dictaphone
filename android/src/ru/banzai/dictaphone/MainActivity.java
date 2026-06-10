package ru.banzai.dictaphone;

import android.Manifest;
import android.app.Activity;
import android.content.*;
import android.content.pm.PackageManager;
import android.graphics.Typeface;
import android.os.*;
import android.view.*;
import android.widget.*;
import java.io.*;
import java.net.*;

import ru.banzai.dictaphone.domain.RecordingPhase;
import ru.banzai.dictaphone.ui.*;
import ru.banzai.dictaphone.ui.theme.*;

/** Main activity - wires UI components and DictaphoneService. ~195 lines (was 955). */
public class MainActivity extends Activity {
    private static final int REQ_PERMS = 1001;
    private FrameLayout root;
    private RecordButtonView recordButton;
    private StatusCardView statusCard;
    private SettingsPanelView settingsPanel;
    private TextView timerView, resultPanel;
    private final MainViewModel vm = new MainViewModel();
    private final Handler handler = new Handler(Looper.getMainLooper());
    private PreferencesManager prefs;

    private final BroadcastReceiver rcv = new BroadcastReceiver() {
        @Override public void onReceive(Context ctx, Intent i) {
            String s = i.getStringExtra(DictaphoneService.EXTRA_STATUS);
            String d = i.getStringExtra(DictaphoneService.EXTRA_TRANSCRIPT);
            if (s != null) applyStatus(s);
            if (d != null) { vm.updateStatusStep(3); updateStatusCard(); }
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = new PreferencesManager(getSharedPreferences(Defaults.PREFS, MODE_PRIVATE));
        try {
            configureWindow();
            buildUi();
            settingsPanel.loadFromPrefs();
            requestNeededPermissions();
        } catch (Throwable t) {
            LinearLayout m = new LinearLayout(this);
            m.setOrientation(LinearLayout.VERTICAL);
            m.setPadding(dp(16), dp(16), dp(16), dp(16));
            m.setBackgroundColor(ThemeColors.BG);
            TextView tv = new TextView(this);
            String msg = t.getMessage() == null ? "" : "\n" + Theme.shorten(t.getMessage(), 96);
            tv.setText("Банзай Диктофон\nБезопасный режим: " + Theme.shorten(t.getClass().getSimpleName(), 28) + msg);
            tv.setTextSize(20);
            tv.setTextColor(ThemeColors.WARN);
            m.addView(tv);
            setContentView(m);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        try {
            IntentFilter f = new IntentFilter(DictaphoneService.ACTION_EVENT);
            registerReceiver(rcv, f, Build.VERSION.SDK_INT >= 33 ? RECEIVER_NOT_EXPORTED : 0);
        } catch (Throwable t) { applyError("Ошибка", Theme.shorten(t.getClass().getSimpleName(), 22)); }
    }

    @Override
    protected void onStop() {
        try { unregisterReceiver(rcv); } catch (Exception ignored) {}
        super.onStop();
    }

    @Override
    protected void onDestroy() { vm.stopTimer(); super.onDestroy(); }

    private void configureWindow() {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 21) { w.setStatusBarColor(ThemeColors.BG); w.setNavigationBarColor(ThemeColors.BG); }
    }

    private void buildUi() {
        root = new FrameLayout(this); root.setBackgroundColor(ThemeColors.BG);
        LinearLayout main = new LinearLayout(this);
        main.setOrientation(LinearLayout.VERTICAL);
        main.setPadding(dp(20), dp(18), dp(20), dp(14));
        root.addView(main, new FrameLayout.LayoutParams(-1, -1));

        // Header
        LinearLayout hdr = new LinearLayout(this);
        hdr.setOrientation(LinearLayout.HORIZONTAL); hdr.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout left = new LinearLayout(this); left.setOrientation(LinearLayout.VERTICAL);
        left.addView(tv("Банзай Диктофон", 22, ThemeColors.TEXT, Typeface.BOLD), lp(-1, -2));
        LinearLayout chips = new LinearLayout(this);
        chips.setOrientation(LinearLayout.HORIZONTAL); chips.setGravity(Gravity.CENTER_VERTICAL);
        chips.setPadding(0, dp(8), 0, 0);
        chips.addView(chip("● Online", ThemeColors.ACCENT, Theme.argb(28, ThemeColors.ACCENT), Theme.argb(82, ThemeColors.ACCENT)));
        chips.addView(sp(dp(7), 1));
        chips.addView(chip("Yandex Realtime", ThemeColors.TEXT_2, ThemeColors.SURFACE_2, ThemeColors.BORDER));
        chips.addView(sp(dp(7), 1));
        chips.addView(tv(shortVer(), 12, ThemeColors.MUTED, Typeface.NORMAL));
        left.addView(chips, lp(-1, -2));
        hdr.addView(left, lp(0, -2, 1));
        TextView setBtn = tv("⚙", 23, ThemeColors.TEXT_2, Typeface.NORMAL);
        setBtn.setGravity(Gravity.CENTER); setBtn.setBackground(Theme.round(ThemeColors.SURFACE_2, dp(10), ThemeColors.BORDER, 1));
        setBtn.setOnClickListener(new View.OnClickListener() { @Override public void onClick(View v) { showSettings(true); } });
        hdr.addView(setBtn, lp(dp(44), dp(44)));
        main.addView(hdr, lp(-1, -2));

        // Timer
        timerView = tv("Готов к записи", 14, ThemeColors.MUTED, Typeface.NORMAL);
        timerView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams tlp = lp(-1, dp(56)); tlp.setMargins(0, dp(12), 0, 0);
        main.addView(timerView, tlp);

        // Record button
        recordButton = new RecordButtonView(this);
        recordButton.setPhase(RecordingPhase.IDLE);
        recordButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                RecordingPhase p = vm.getPhase();
                if (p == RecordingPhase.RECORDING) stopRecording();
                else if (p == RecordingPhase.IDLE || p == RecordingPhase.DONE || p == RecordingPhase.ERROR) startRecording();
            }
        });
        LinearLayout.LayoutParams rlp = lp(dp(172), dp(194));
        rlp.gravity = Gravity.CENTER_HORIZONTAL; rlp.setMargins(0, dp(4), 0, dp(10));
        main.addView(recordButton, rlp);

        // Status card
        statusCard = new StatusCardView(this);
        LinearLayout.LayoutParams slp = lp(-1, -2); slp.setMargins(0, dp(8), 0, 0);
        main.addView(statusCard, slp);
        updateStatusCard();

        main.addView(sp(1, 1), lp(-1, 0, 1));

        // Result panel
        resultPanel = tv("✓ Отправлено в Telegram: transcript.txt + audio.ogg", 14, ThemeColors.TEXT, Typeface.BOLD);
        resultPanel.setGravity(Gravity.CENTER);
        resultPanel.setPadding(dp(14), 0, dp(14), 0);
        resultPanel.setBackground(Theme.round(Theme.argb(28, ThemeColors.ACCENT), dp(12), Theme.argb(82, ThemeColors.ACCENT), 1));
        resultPanel.setVisibility(View.GONE);
        LinearLayout.LayoutParams rplp = lp(-1, dp(52)); rplp.setMargins(0, dp(12), 0, 0);
        main.addView(resultPanel, rplp);

        // Settings overlay
        settingsPanel = new SettingsPanelView(this, prefs, HttpAudioClient.VERSION);
        settingsPanel.setVisibility(View.GONE);
        settingsPanel.setOnHealthCheckListener(new SettingsPanelView.OnHealthCheckListener() {
            @Override public void onHealthCheck(String url, String token) { checkHealth(url, token); }
        });
        root.addView(settingsPanel, new FrameLayout.LayoutParams(-1, -1));

        setContentView(root);
    }

    // State
    private void requestNeededPermissions() {
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO, Manifest.permission.POST_NOTIFICATIONS}, REQ_PERMS);
        else if (Build.VERSION.SDK_INT >= 23) requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_PERMS);
    }

    private boolean hasMic() { return Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED; }

    private void startRecording() {
        if (!hasMic()) { applyError("Нет доступа к микрофону", "Разрешите микрофон"); requestNeededPermissions(); return; }
        settingsPanel.saveToPrefs();
        vm.setRecordingStartedAt(System.currentTimeMillis());
        applyPhase(RecordingPhase.RECORDING);
        Intent i = new Intent(this, DictaphoneService.class);
        i.setAction(DictaphoneService.ACTION_START);
        i.putExtra(DictaphoneService.EXTRA_URL, prefs.getUrl());
        i.putExtra(DictaphoneService.EXTRA_TOKEN, prefs.getToken());
        try { if (Build.VERSION.SDK_INT >= 26) startForegroundService(i); else startService(i); }
        catch (Exception e) { applyError("Старт не прошёл", e.getMessage() == null ? e.toString() : e.getMessage()); }
    }

    private void stopRecording() {
        Intent i = new Intent(this, DictaphoneService.class); i.setAction(DictaphoneService.ACTION_STOP);
        try { startService(i); vm.resetForStop(); applyPhase(RecordingPhase.STOPPING); }
        catch (Exception e) { applyError("Стоп не прошёл", e.getMessage() == null ? e.toString() : e.getMessage()); }
    }

    private void applyStatus(String s) {
        if (s.startsWith("Ошибка") || s.contains("не прошёл")) { applyError("Ошибка записи", s); return; }
        if (s.contains("Сервер принял") || s.contains("Подключаюсь")) vm.updateStatusStep(1);
        if (s.contains("Первый чанк")) vm.updateStatusStep(2);
        if (s.contains("Идёт запись") && vm.getPhase() != RecordingPhase.RECORDING) applyPhase(RecordingPhase.RECORDING);
        if (s.contains("Останавливаю")) applyPhase(RecordingPhase.STOPPING);
        if (s.contains("Запись остановлена")) applyPhase(RecordingPhase.DONE);
        updateStatusCard();
    }

    private void applyError(String title, String detail) {
        applyPhase(RecordingPhase.ERROR);
        statusCard.setStatus(title, Theme.shorten(detail, 18), "!", ThemeColors.WARN);
    }

    private void applyPhase(RecordingPhase p) {
        vm.setPhase(p);
        recordButton.setPhase(p);
        recordButton.setAlpha(p == RecordingPhase.STOPPING ? 0.72f : 1.0f);
        resultPanel.setVisibility(p == RecordingPhase.DONE ? View.VISIBLE : View.GONE);
        vm.stopTimer();
        if (p == RecordingPhase.RECORDING || p == RecordingPhase.STOPPING) {
            vm.startTimer(new MainViewModel.TimerCallback() {
                @Override public void onTimerTick(String t, RecordingPhase ph) { refreshTimer(t, ph); }
            });
        } else {
            refreshTimer("", p);
        }
        updateStatusCard();
    }

    private void refreshTimer(String t, RecordingPhase p) {
        if (p == RecordingPhase.RECORDING || p == RecordingPhase.STOPPING) {
            timerView.setText(t); timerView.setTextColor(ThemeColors.TEXT); timerView.setTextSize(42); timerView.setTypeface(Typeface.MONOSPACE);
        } else if (p == RecordingPhase.DONE) {
            timerView.setText("Готово · " + t); timerView.setTextColor(ThemeColors.TEXT); timerView.setTextSize(18); timerView.setTypeface(Typeface.DEFAULT_BOLD);
        } else if (p == RecordingPhase.ERROR) {
            timerView.setText("Запись недоступна"); timerView.setTextColor(ThemeColors.WARN); timerView.setTextSize(14); timerView.setTypeface(Typeface.DEFAULT_BOLD);
        } else {
            timerView.setText("Готов к записи"); timerView.setTextColor(ThemeColors.MUTED); timerView.setTextSize(14); timerView.setTypeface(Typeface.DEFAULT);
        }
    }

    private void updateStatusCard() {
        if (statusCard == null) return;
        RecordingPhase p = vm.getPhase();
        if (p == RecordingPhase.ERROR) return;
        int s = vm.getStatusStep();
        if (p == RecordingPhase.STOPPING) statusCard.setStatus("Сохраняю и отправляю", "stop", "☁", ThemeColors.ACCENT);
        else if (p == RecordingPhase.DONE) statusCard.setStatus("Отправлено в Telegram", "txt + ogg", "☁", ThemeColors.ACCENT);
        else if (p == RecordingPhase.RECORDING) {
            if (s >= 3) statusCard.setStatus("Транскрипция активна", "live", "☁", ThemeColors.ACCENT);
            else if (s >= 2) statusCard.setStatus("Первый чанк дошёл", "ok", "☁", ThemeColors.ACCENT);
            else if (s >= 1) statusCard.setStatus("Сервер подключён", "rec", "☁", ThemeColors.ACCENT);
            else statusCard.setStatus("Подключаюсь к серверу", "...", "☁", ThemeColors.ACCENT);
        } else statusCard.setStatus("Сервер подключён", "готово", "☁", ThemeColors.ACCENT);
    }

    private void showSettings(boolean show) {
        if (!show) settingsPanel.saveToPrefs();
        settingsPanel.setVisibility(show ? View.VISIBLE : View.GONE);
    }

    private void checkHealth(String url, String token) {
        settingsPanel.setCheckButtonText("Проверяю...");
        settingsPanel.setHealthStatus("/health - проверяю...", ThemeColors.WARN);
        final String u = url, t = token;
        new Thread(new Runnable() { public void run() {
            String r = runHealthCheck(u, t);
            final String res = r;
            handler.post(new Runnable() { public void run() {
                settingsPanel.setCheckButtonText("↻ Проверить подключение");
                if (res.startsWith("OK")) {
                    settingsPanel.setHealthStatus("/health - 200 OK · yandex_realtime", ThemeColors.ACCENT);
                    statusCard.setStatus("Сервер подключён", "health", "☁", ThemeColors.ACCENT);
                } else settingsPanel.setHealthStatus("/health - " + res, ThemeColors.WARN);
            }});
        }}, "health").start();
    }

    // Health check
    private String runHealthCheck(String url, String token) {
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL(normalize(url) + "/health").openConnection();
            conn.setConnectTimeout(5000); conn.setReadTimeout(5000);
            conn.setRequestProperty("Authorization", "Bearer " + token);
            conn.setRequestProperty("Connection", "close");
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String body = new String(readAll(in), "UTF-8");
            return (code >= 200 && code < 300 && body.contains("\"ok\": true")) ? "OK" : "HTTP " + code;
        } catch (Exception e) { return Theme.shorten(e.getMessage() == null ? e.toString() : e.getMessage(), 42); }
        finally { if (conn != null) conn.disconnect(); }
    }

    // Helpers
    private String normalize(String v) {
        v = (v == null ? "" : v.trim());
        if (v.endsWith("/v1/stream")) v = v.substring(0, v.length() - "/v1/stream".length());
        if (v.startsWith("wss://")) v = "https://" + v.substring(6);
        else if (v.startsWith("ws://")) v = "http://" + v.substring(5);
        while (v.endsWith("/")) v = v.substring(0, v.length() - 1);
        return v;
    }

    private byte[] readAll(InputStream in) throws Exception {
        if (in == null) return new byte[0];
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] c = new byte[4096]; int n;
        while ((n = in.read(c)) >= 0) b.write(c, 0, n);
        return b.toByteArray();
    }

    private String shortVer() {
        String v = HttpAudioClient.VERSION;
        int d = v.indexOf('-');
        return d > 1 ? v.substring(0, d) : v;
    }

    private int dp(int v) { return (int)(v * getResources().getDisplayMetrics().density + 0.5f); }

    private TextView tv(String t, int sp, int color, int style) {
        TextView v = new TextView(this);
        v.setText(t); v.setTextSize(sp); v.setTextColor(color);
        v.setTypeface(Typeface.DEFAULT, style); v.setIncludeFontPadding(true);
        return v;
    }

    private TextView chip(String t, int fg, int bg, int stroke) {
        TextView v = tv(t, 12, fg, Typeface.BOLD);
        v.setGravity(Gravity.CENTER); v.setSingleLine(true);
        v.setPadding(dp(9), 0, dp(9), 0);
        v.setBackground(Theme.round(bg, dp(999), stroke, 1));
        v.setMinHeight(dp(24));
        return v;
    }

    private View sp(int w, int h) { View v = new View(this); v.setLayoutParams(lp(w, h)); return v; }

    private LinearLayout.LayoutParams lp(int w, int h) { return new LinearLayout.LayoutParams(w, h); }
    private LinearLayout.LayoutParams lp(int w, int h, float weight) { LinearLayout.LayoutParams p = new LinearLayout.LayoutParams(w, h); p.weight = weight; return p; }
}
