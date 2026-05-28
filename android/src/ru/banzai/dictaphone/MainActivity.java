package ru.banzai.dictaphone;

import android.Manifest;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.text.method.SingleLineTransformationMethod;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

public class MainActivity extends Activity {
    private static final int REQ_PERMS = 1001;

    private static final int C_BG = Color.rgb(14, 17, 22);
    private static final int C_SURFACE = Color.rgb(22, 27, 34);
    private static final int C_SURFACE_2 = Color.rgb(28, 35, 45);
    private static final int C_BORDER = Color.rgb(35, 43, 54);
    private static final int C_HAIRLINE = Color.rgb(26, 32, 41);
    private static final int C_TEXT = Color.rgb(232, 237, 242);
    private static final int C_TEXT_2 = Color.rgb(155, 166, 179);
    private static final int C_MUTED = Color.rgb(97, 108, 122);
    private static final int C_ACCENT = Color.rgb(61, 220, 151);
    private static final int C_REC = Color.rgb(255, 91, 87);
    private static final int C_WARN = Color.rgb(245, 178, 61);

    private enum Phase {
        IDLE,
        RECORDING,
        STOPPING,
        DONE,
        ERROR
    }

    private FrameLayout root;
    private LinearLayout settingsPanel;
    private EditText urlEdit;
    private EditText tokenEdit;
    private TextView statusView;
    private TextView statusTitle;
    private TextView statusMeta;
    private TextView statusIcon;
    private TextView timerView;
    private TextView recordHintView;
    private TextView resultPanel;
    private TextView healthView;
    private TextView checkButton;
    private TextView showTokenButton;
    private RecordButtonView recordButton;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private Phase phase = Phase.IDLE;
    private long recordingStartedAt;
    private int statusStep;
    private boolean tokenVisible;

    private final Runnable timerTick = new Runnable() {
        @Override
        public void run() {
            refreshTimer();
            if (phase == Phase.RECORDING || phase == Phase.STOPPING) {
                handler.postDelayed(this, 500);
            }
        }
    };

    private final BroadcastReceiver receiver = new BroadcastReceiver() {
        @Override
        public void onReceive(Context context, Intent intent) {
            String status = intent.getStringExtra(DictaphoneService.EXTRA_STATUS);
            String delta = intent.getStringExtra(DictaphoneService.EXTRA_TRANSCRIPT);
            if (status != null) {
                applyStatus(status);
            }
            if (delta != null) {
                statusStep = Math.max(statusStep, 3);
                updateStatusCard();
            }
        }
    };

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        try {
            configureWindow();
            buildUi();
            loadPrefs();
            requestNeededPermissions();
        } catch (Throwable t) {
            try {
                buildFallbackUi(t);
                loadPrefs();
            } catch (Throwable ignored) {
                TextView fatal = new TextView(this);
                fatal.setText("Банзай Диктофон\nОшибка запуска UI\n" + t.getClass().getSimpleName());
                fatal.setTextSize(18);
                fatal.setTextColor(Color.WHITE);
                fatal.setPadding(24, 24, 24, 24);
                fatal.setBackgroundColor(Color.BLACK);
                setContentView(fatal);
            }
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        try {
            IntentFilter filter = new IntentFilter(DictaphoneService.ACTION_EVENT);
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            } else {
                registerReceiver(receiver, filter);
            }
        } catch (Throwable t) {
            applyError("Ошибка запуска", "receiver: " + shorten(t.getClass().getSimpleName(), 22));
        }
    }

    @Override
    protected void onStop() {
        try {
            unregisterReceiver(receiver);
        } catch (Exception ignored) {
        }
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacks(timerTick);
        super.onDestroy();
    }

    private void configureWindow() {
        Window window = getWindow();
        if (Build.VERSION.SDK_INT >= 21) {
            window.setStatusBarColor(C_BG);
            window.setNavigationBarColor(C_BG);
        }
    }

    private void buildUi() {
        root = new FrameLayout(this);
        root.setBackgroundColor(C_BG);

        LinearLayout main = new LinearLayout(this);
        main.setOrientation(LinearLayout.VERTICAL);
        main.setPadding(dp(20), dp(18), dp(20), dp(14));
        root.addView(main, new FrameLayout.LayoutParams(-1, -1));

        main.addView(buildHeader(), new LinearLayout.LayoutParams(-1, -2));

        timerView = text("Готов к записи", 14, C_MUTED, Typeface.NORMAL);
        timerView.setGravity(Gravity.CENTER);
        LinearLayout.LayoutParams timerLp = new LinearLayout.LayoutParams(-1, dp(56));
        timerLp.setMargins(0, dp(12), 0, 0);
        main.addView(timerView, timerLp);

        recordButton = new RecordButtonView(this);
        recordButton.setPhase(phase);
        recordButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                if (phase == Phase.RECORDING) {
                    stopRecording();
                } else if (phase == Phase.IDLE || phase == Phase.DONE || phase == Phase.ERROR) {
                    startRecording();
                }
            }
        });
        LinearLayout.LayoutParams recordLp = new LinearLayout.LayoutParams(dp(172), dp(194));
        recordLp.gravity = Gravity.CENTER_HORIZONTAL;
        recordLp.setMargins(0, dp(4), 0, dp(10));
        main.addView(recordButton, recordLp);

        LinearLayout.LayoutParams statusLp = new LinearLayout.LayoutParams(-1, -2);
        statusLp.setMargins(0, dp(8), 0, 0);
        main.addView(buildStatusCard(), statusLp);
        main.addView(space(1, 1), new LinearLayout.LayoutParams(-1, 0, 1));

        resultPanel = text("✓ Отправлено в Telegram: transcript.txt + audio.ogg", 14, C_TEXT, Typeface.BOLD);
        resultPanel.setGravity(Gravity.CENTER);
        resultPanel.setPadding(dp(14), 0, dp(14), 0);
        resultPanel.setBackground(round(argb(28, C_ACCENT), dp(12), argb(82, C_ACCENT), 1));
        resultPanel.setVisibility(View.GONE);
        LinearLayout.LayoutParams resultLp = new LinearLayout.LayoutParams(-1, dp(52));
        resultLp.setMargins(0, dp(12), 0, 0);
        main.addView(resultPanel, resultLp);

        settingsPanel = buildSettingsPanel();
        settingsPanel.setVisibility(View.GONE);
        root.addView(settingsPanel, new FrameLayout.LayoutParams(-1, -1));

        setContentView(root);
    }

    private View buildHeader() {
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);

        LinearLayout left = new LinearLayout(this);
        left.setOrientation(LinearLayout.VERTICAL);

        TextView title = text("Банзай Диктофон", 22, C_TEXT, Typeface.BOLD);
        left.addView(title, new LinearLayout.LayoutParams(-1, -2));

        LinearLayout chips = new LinearLayout(this);
        chips.setOrientation(LinearLayout.HORIZONTAL);
        chips.setGravity(Gravity.CENTER_VERTICAL);
        chips.setPadding(0, dp(8), 0, 0);
        chips.addView(chip("● Online", C_ACCENT, argb(28, C_ACCENT), argb(82, C_ACCENT)));
        chips.addView(space(dp(7), 1));
        chips.addView(chip("Yandex Realtime", C_TEXT_2, C_SURFACE_2, C_BORDER));
        chips.addView(space(dp(7), 1));
        chips.addView(text(shortVersion(), 12, C_MUTED, Typeface.NORMAL));
        left.addView(chips, new LinearLayout.LayoutParams(-1, -2));

        header.addView(left, new LinearLayout.LayoutParams(0, -2, 1));

        TextView settings = text("⚙", 23, C_TEXT_2, Typeface.NORMAL);
        settings.setGravity(Gravity.CENTER);
        settings.setBackground(round(C_SURFACE_2, dp(10), C_BORDER, 1));
        settings.setContentDescription("Настройки");
        settings.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                showSettings(true);
            }
        });
        header.addView(settings, new LinearLayout.LayoutParams(dp(44), dp(44)));

        return header;
    }

    private View buildStatusCard() {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setPadding(dp(14), dp(12), dp(14), dp(12));
        card.setBackground(round(C_SURFACE, dp(12), C_HAIRLINE, 1));

        statusIcon = text("☁", 20, C_ACCENT, Typeface.NORMAL);
        statusIcon.setGravity(Gravity.CENTER);
        card.addView(statusIcon, new LinearLayout.LayoutParams(dp(28), dp(28)));

        statusTitle = text("Сервер подключён", 15, C_TEXT, Typeface.BOLD);
        LinearLayout.LayoutParams titleLp = new LinearLayout.LayoutParams(0, -2, 1);
        titleLp.setMargins(dp(8), 0, dp(10), 0);
        card.addView(statusTitle, titleLp);

        statusMeta = text("готово", 12, C_MUTED, Typeface.NORMAL);
        statusMeta.setGravity(Gravity.CENTER);
        statusMeta.setTypeface(Typeface.MONOSPACE);
        statusMeta.setPadding(dp(10), 0, dp(10), 0);
        statusMeta.setBackground(round(C_SURFACE, dp(999), C_BORDER, 1));
        card.addView(statusMeta, new LinearLayout.LayoutParams(-2, dp(28)));
        return card;
    }

    private LinearLayout buildSettingsPanel() {
        LinearLayout panel = new LinearLayout(this);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setPadding(dp(20), dp(18), dp(20), dp(18));
        panel.setBackgroundColor(C_BG);

        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        TextView title = text("Настройки", 22, C_TEXT, Typeface.BOLD);
        header.addView(title, new LinearLayout.LayoutParams(0, -2, 1));
        TextView close = text("×", 28, C_TEXT_2, Typeface.NORMAL);
        close.setGravity(Gravity.CENTER);
        close.setBackground(round(C_SURFACE_2, dp(10), C_BORDER, 1));
        close.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                savePrefs();
                showSettings(false);
            }
        });
        header.addView(close, new LinearLayout.LayoutParams(dp(44), dp(44)));
        panel.addView(header, new LinearLayout.LayoutParams(-1, dp(54)));

        TextView section = text("СЕРВЕР", 12, C_MUTED, Typeface.BOLD);
        safeLetterSpacing(section);
        LinearLayout.LayoutParams sectionLp = new LinearLayout.LayoutParams(-1, -2);
        sectionLp.setMargins(0, dp(18), 0, dp(10));
        panel.addView(section, sectionLp);

        panel.addView(fieldLabel("URL сервера"));
        urlEdit = input(false);
        urlEdit.setHint("https://...");
        urlEdit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        panel.addView(urlEdit, new LinearLayout.LayoutParams(-1, dp(52)));

        panel.addView(fieldLabel("Токен"));
        FrameLayout tokenWrap = new FrameLayout(this);
        tokenEdit = input(true);
        tokenWrap.addView(tokenEdit, new FrameLayout.LayoutParams(-1, dp(52)));
        showTokenButton = text("Показать", 12, C_TEXT_2, Typeface.BOLD);
        showTokenButton.setGravity(Gravity.CENTER);
        showTokenButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                toggleTokenVisible();
            }
        });
        FrameLayout.LayoutParams showLp = new FrameLayout.LayoutParams(dp(82), dp(40), Gravity.RIGHT | Gravity.CENTER_VERTICAL);
        showLp.setMargins(0, 0, dp(6), 0);
        tokenWrap.addView(showTokenButton, showLp);
        LinearLayout.LayoutParams tokenLp = new LinearLayout.LayoutParams(-1, dp(52));
        tokenLp.setMargins(0, 0, 0, dp(6));
        panel.addView(tokenWrap, tokenLp);

        TextView hint = text("Хранится только на устройстве", 12, C_MUTED, Typeface.NORMAL);
        LinearLayout.LayoutParams hintLp = new LinearLayout.LayoutParams(-1, -2);
        hintLp.setMargins(0, 0, 0, dp(14));
        panel.addView(hint, hintLp);

        checkButton = text("↻ Проверить подключение", 16, Color.rgb(4, 19, 12), Typeface.BOLD);
        checkButton.setGravity(Gravity.CENTER);
        checkButton.setBackground(round(C_ACCENT, dp(10), C_ACCENT, 0));
        checkButton.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                checkHealth();
            }
        });
        panel.addView(checkButton, new LinearLayout.LayoutParams(-1, dp(52)));

        healthView = text("/health - не проверялось", 14, C_TEXT_2, Typeface.NORMAL);
        healthView.setTypeface(Typeface.MONOSPACE);
        healthView.setGravity(Gravity.CENTER_VERTICAL);
        healthView.setPadding(dp(14), 0, dp(14), 0);
        healthView.setBackground(round(C_SURFACE, dp(12), C_HAIRLINE, 1));
        LinearLayout.LayoutParams healthLp = new LinearLayout.LayoutParams(-1, dp(48));
        healthLp.setMargins(0, dp(12), 0, dp(24));
        panel.addView(healthView, healthLp);

        TextView about = text("О ПРИЛОЖЕНИИ", 12, C_MUTED, Typeface.BOLD);
        safeLetterSpacing(about);
        panel.addView(about, new LinearLayout.LayoutParams(-1, -2));
        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setPadding(dp(14), dp(8), dp(14), dp(8));
        info.setBackground(round(C_SURFACE, dp(12), C_HAIRLINE, 1));
        LinearLayout.LayoutParams infoLp = new LinearLayout.LayoutParams(-1, -2);
        infoLp.setMargins(0, dp(12), 0, 0);
        panel.addView(info, infoLp);
        info.addView(infoRow("Версия", HttpAudioClient.VERSION));
        info.addView(infoRow("Движок", "Yandex Realtime STT"));
        info.addView(infoRow("Аудио", "Telegram: transcript.txt + audio.ogg"));

        return panel;
    }

    private void buildFallbackUi(Throwable cause) {
        LinearLayout main = new LinearLayout(this);
        main.setOrientation(LinearLayout.VERTICAL);
        main.setPadding(dp(16), dp(16), dp(16), dp(16));
        main.setBackgroundColor(C_BG);

        TextView title = text("Банзай Диктофон", 24, C_TEXT, Typeface.BOLD);
        main.addView(title, new LinearLayout.LayoutParams(-1, -2));

        statusView = text("Безопасный режим UI: " + shorten(cause.getClass().getSimpleName(), 28), 14, C_WARN, Typeface.BOLD);
        statusView.setPadding(0, dp(10), 0, dp(14));
        main.addView(statusView, new LinearLayout.LayoutParams(-1, -2));

        urlEdit = input(false);
        urlEdit.setHint("HTTPS URL");
        urlEdit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        main.addView(fieldLabel("Сервер"));
        main.addView(urlEdit, new LinearLayout.LayoutParams(-1, dp(52)));

        tokenEdit = input(true);
        tokenEdit.setHint("Токен");
        main.addView(fieldLabel("Токен"));
        main.addView(tokenEdit, new LinearLayout.LayoutParams(-1, dp(52)));

        LinearLayout buttons = new LinearLayout(this);
        buttons.setOrientation(LinearLayout.HORIZONTAL);
        LinearLayout.LayoutParams buttonsLp = new LinearLayout.LayoutParams(-1, dp(56));
        buttonsLp.setMargins(0, dp(14), 0, dp(14));
        main.addView(buttons, buttonsLp);

        TextView start = text("Записать", 16, Color.rgb(4, 19, 12), Typeface.BOLD);
        start.setGravity(Gravity.CENTER);
        start.setBackground(round(C_ACCENT, dp(10), C_ACCENT, 0));
        start.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                startRecording();
            }
        });
        buttons.addView(start, new LinearLayout.LayoutParams(0, -1, 1));

        TextView stop = text("Стоп", 16, C_TEXT, Typeface.BOLD);
        stop.setGravity(Gravity.CENTER);
        stop.setBackground(round(argb(38, C_REC), dp(10), argb(120, C_REC), 1));
        stop.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View view) {
                stopRecording();
            }
        });
        LinearLayout.LayoutParams stopLp = new LinearLayout.LayoutParams(0, -1, 1);
        stopLp.setMargins(dp(12), 0, 0, 0);
        buttons.addView(stop, stopLp);

        main.addView(space(1, 1), new LinearLayout.LayoutParams(-1, 0, 1));

        setContentView(main);
    }

    private TextView fieldLabel(String value) {
        TextView label = text(value, 13, C_TEXT_2, Typeface.BOLD);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(14), 0, dp(8));
        label.setLayoutParams(lp);
        return label;
    }

    private TextView infoRow(String key, String value) {
        TextView row = text(key + "     " + value, 14, C_TEXT_2, Typeface.NORMAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(8), 0, dp(8));
        return row;
    }

    private EditText input(boolean password) {
        EditText view = new EditText(this);
        view.setSingleLine(true);
        view.setTextColor(C_TEXT);
        view.setHintTextColor(C_MUTED);
        view.setTextSize(15);
        view.setTypeface(Typeface.MONOSPACE);
        view.setPadding(dp(14), 0, password ? dp(92) : dp(14), 0);
        view.setBackground(round(C_SURFACE_2, dp(10), C_BORDER, 1));
        if (password) {
            view.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            view.setTransformationMethod(PasswordTransformationMethod.getInstance());
        }
        return view;
    }

    private void safeLetterSpacing(TextView view) {
        if (Build.VERSION.SDK_INT >= 21) {
            try {
                view.setLetterSpacing(0.08f);
            } catch (Throwable ignored) {
            }
        }
    }

    private String shortVersion() {
        String version = HttpAudioClient.VERSION;
        if (version.startsWith("v")) {
            int dash = version.indexOf('-');
            if (dash > 1) {
                return version.substring(0, dash);
            }
        }
        return version;
    }

    private void loadPrefs() {
        SharedPreferences prefs = getSharedPreferences(Defaults.PREFS, MODE_PRIVATE);
        String savedUrl = prefs.getString(Defaults.KEY_URL, Defaults.DEFAULT_URL);
        if (savedUrl == null || savedUrl.trim().isEmpty() || Defaults.isOldUrl(savedUrl)) {
            savedUrl = Defaults.DEFAULT_URL;
            prefs.edit().putString(Defaults.KEY_URL, savedUrl).apply();
        }
        urlEdit.setText(savedUrl);
        tokenEdit.setText(prefs.getString(Defaults.KEY_TOKEN, Defaults.DEFAULT_TOKEN));
        setPhase(Phase.IDLE);
        if (statusView != null) {
            statusView.setText("Готов " + HttpAudioClient.VERSION);
        }
        updateStatusCard();
    }

    private void savePrefs() {
        getSharedPreferences(Defaults.PREFS, MODE_PRIVATE)
                .edit()
                .putString(Defaults.KEY_URL, urlEdit.getText().toString().trim())
                .putString(Defaults.KEY_TOKEN, tokenEdit.getText().toString().trim())
                .apply();
    }

    private void requestNeededPermissions() {
        if (Build.VERSION.SDK_INT >= 33) {
            requestPermissions(new String[]{
                    Manifest.permission.RECORD_AUDIO,
                    Manifest.permission.POST_NOTIFICATIONS
            }, REQ_PERMS);
        } else if (Build.VERSION.SDK_INT >= 23) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_PERMS);
        }
    }

    private boolean hasMicPermission() {
        return Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
    }

    private void startRecording() {
        if (!hasMicPermission()) {
            applyError("Нет доступа к микрофону", "Разрешите микрофон");
            requestNeededPermissions();
            return;
        }
        savePrefs();
        statusStep = 0;
        recordingStartedAt = System.currentTimeMillis();
        setPhase(Phase.RECORDING);
        if (statusView != null) {
            statusView.setText("Запускаю запись");
        }
        if (statusTitle != null) {
            statusTitle.setText("Запускаю запись");
        }
        if (statusMeta != null) {
            statusMeta.setText("start");
        }

        Intent intent = new Intent(this, DictaphoneService.class);
        intent.setAction(DictaphoneService.ACTION_START);
        intent.putExtra(DictaphoneService.EXTRA_URL, urlEdit.getText().toString().trim());
        intent.putExtra(DictaphoneService.EXTRA_TOKEN, tokenEdit.getText().toString().trim());
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(intent);
            } else {
                startService(intent);
            }
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.toString() : e.getMessage();
            applyError("Старт не прошёл", msg);
        }
    }

    private void stopRecording() {
        Intent intent = new Intent(this, DictaphoneService.class);
        intent.setAction(DictaphoneService.ACTION_STOP);
        try {
            startService(intent);
            setPhase(Phase.STOPPING);
            if (statusView != null) {
                statusView.setText("Останавливаю запись");
            }
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.toString() : e.getMessage();
            applyError("Стоп не прошёл", msg);
        }
    }

    private void applyStatus(String status) {
        if (statusView != null) {
            statusView.setText(status);
        }
        if (status.startsWith("Ошибка") || status.contains("не прошёл")) {
            applyError("Ошибка записи", status);
            return;
        }
        if (status.contains("Сервер принял") || status.contains("Подключаюсь")) {
            statusStep = Math.max(statusStep, 1);
        }
        if (status.contains("Первый чанк")) {
            statusStep = Math.max(statusStep, 2);
        }
        if (status.contains("Идёт запись") && phase != Phase.RECORDING) {
            setPhase(Phase.RECORDING);
        }
        if (status.contains("Останавливаю")) {
            setPhase(Phase.STOPPING);
        }
        if (status.contains("Запись остановлена")) {
            setPhase(Phase.DONE);
        }
        updateStatusCard();
    }

    private void applyError(String title, String detail) {
        setPhase(Phase.ERROR);
        if (statusTitle != null) {
            statusTitle.setText(title);
        }
        if (statusMeta != null) {
            statusMeta.setText(shorten(detail, 18));
        }
        if (statusIcon != null) {
            statusIcon.setText("!");
            statusIcon.setTextColor(C_WARN);
        }
        if (statusView != null) {
            statusView.setText(detail);
        }
    }

    private void setPhase(Phase next) {
        phase = next;
        if (recordButton != null) {
            recordButton.setPhase(next);
            recordButton.setAlpha(next == Phase.STOPPING ? 0.72f : 1.0f);
        }
        if (resultPanel != null) {
            resultPanel.setVisibility(next == Phase.DONE ? View.VISIBLE : View.GONE);
        }
        refreshTimer();
        updateStatusCard();
        handler.removeCallbacks(timerTick);
        if (next == Phase.RECORDING || next == Phase.STOPPING) {
            handler.post(timerTick);
        }
    }

    private void refreshTimer() {
        if (timerView == null) {
            return;
        }
        if (phase == Phase.RECORDING || phase == Phase.STOPPING) {
            long elapsed = Math.max(0, System.currentTimeMillis() - recordingStartedAt);
            timerView.setText(formatElapsed(elapsed));
            timerView.setTextColor(C_TEXT);
            timerView.setTextSize(42);
            timerView.setTypeface(Typeface.MONOSPACE);
        } else if (phase == Phase.DONE) {
            long elapsed = Math.max(0, System.currentTimeMillis() - recordingStartedAt);
            timerView.setText("Готово · " + formatElapsed(elapsed));
            timerView.setTextColor(C_TEXT);
            timerView.setTextSize(18);
            timerView.setTypeface(Typeface.DEFAULT_BOLD);
        } else if (phase == Phase.ERROR) {
            timerView.setText("Запись недоступна");
            timerView.setTextColor(C_WARN);
            timerView.setTextSize(14);
            timerView.setTypeface(Typeface.DEFAULT_BOLD);
        } else {
            timerView.setText("Готов к записи");
            timerView.setTextColor(C_MUTED);
            timerView.setTextSize(14);
            timerView.setTypeface(Typeface.DEFAULT);
        }
    }

    private void updateStatusCard() {
        if (statusTitle == null) {
            return;
        }
        if (phase == Phase.ERROR) {
            return;
        }
        statusIcon.setText("☁");
        statusIcon.setTextColor(C_ACCENT);
        if (phase == Phase.STOPPING) {
            statusTitle.setText("Сохраняю и отправляю");
            statusMeta.setText("stop");
        } else if (phase == Phase.DONE) {
            statusTitle.setText("Отправлено в Telegram");
            statusMeta.setText("txt + ogg");
        } else if (phase == Phase.RECORDING) {
            if (statusStep >= 3) {
                statusTitle.setText("Транскрипция активна");
                statusMeta.setText("live");
            } else if (statusStep >= 2) {
                statusTitle.setText("Первый чанк дошёл");
                statusMeta.setText("ok");
            } else if (statusStep >= 1) {
                statusTitle.setText("Сервер подключён");
                statusMeta.setText("rec");
            } else {
                statusTitle.setText("Подключаюсь к серверу");
                statusMeta.setText("...");
            }
        } else {
            statusTitle.setText("Сервер подключён");
            statusMeta.setText("готово");
        }
    }

    private void showSettings(boolean show) {
        if (!show) {
            savePrefs();
        }
        settingsPanel.setVisibility(show ? View.VISIBLE : View.GONE);
    }

    private void toggleTokenVisible() {
        tokenVisible = !tokenVisible;
        if (tokenVisible) {
            tokenEdit.setTransformationMethod(SingleLineTransformationMethod.getInstance());
            showTokenButton.setText("Скрыть");
        } else {
            tokenEdit.setTransformationMethod(PasswordTransformationMethod.getInstance());
            showTokenButton.setText("Показать");
        }
        tokenEdit.setSelection(tokenEdit.getText().length());
    }

    private void checkHealth() {
        savePrefs();
        checkButton.setText("Проверяю...");
        healthView.setText("/health - проверяю...");
        healthView.setTextColor(C_WARN);
        new Thread(new Runnable() {
            @Override
            public void run() {
                final String result = runHealthCheck();
                handler.post(new Runnable() {
                    @Override
                    public void run() {
                        checkButton.setText("↻ Проверить подключение");
                        if (result.startsWith("OK")) {
                            healthView.setText("/health - 200 OK · yandex_realtime");
                            healthView.setTextColor(C_ACCENT);
                            statusTitle.setText("Сервер подключён");
                            statusMeta.setText("health");
                            statusIcon.setTextColor(C_ACCENT);
                        } else {
                            healthView.setText("/health - " + result);
                            healthView.setTextColor(C_WARN);
                        }
                    }
                });
            }
        }, "dictaphone-health").start();
    }

    private String runHealthCheck() {
        HttpURLConnection conn = null;
        try {
            String base = normalizeBaseUrl(urlEdit.getText().toString().trim());
            conn = (HttpURLConnection) new URL(base + "/health").openConnection();
            conn.setConnectTimeout(5000);
            conn.setReadTimeout(5000);
            conn.setRequestProperty("Authorization", "Bearer " + tokenEdit.getText().toString().trim());
            conn.setRequestProperty("Connection", "close");
            int code = conn.getResponseCode();
            InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            String body = new String(readAll(in), "UTF-8");
            if (code >= 200 && code < 300 && body.contains("\"ok\": true")) {
                return "OK";
            }
            return "HTTP " + code;
        } catch (Exception e) {
            return shorten(e.getMessage() == null ? e.toString() : e.getMessage(), 42);
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }

    private byte[] readAll(InputStream in) throws Exception {
        if (in == null) return new byte[0];
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = in.read(chunk)) >= 0) {
            buf.write(chunk, 0, n);
        }
        return buf.toByteArray();
    }

    private String normalizeBaseUrl(String value) {
        String v = value == null ? "" : value.trim();
        if (v.endsWith("/v1/stream")) {
            v = v.substring(0, v.length() - "/v1/stream".length());
        }
        if (v.startsWith("wss://")) {
            v = "https://" + v.substring(6);
        } else if (v.startsWith("ws://")) {
            v = "http://" + v.substring(5);
        }
        while (v.endsWith("/")) {
            v = v.substring(0, v.length() - 1);
        }
        return v;
    }

    private TextView text(String value, int sp, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setTypeface(Typeface.DEFAULT, style);
        view.setIncludeFontPadding(true);
        return view;
    }

    private TextView chip(String value, int fg, int bg, int stroke) {
        TextView view = text(value, 12, fg, Typeface.BOLD);
        view.setGravity(Gravity.CENTER);
        view.setSingleLine(true);
        view.setPadding(dp(9), 0, dp(9), 0);
        view.setBackground(round(bg, dp(999), stroke, 1));
        view.setMinHeight(dp(24));
        return view;
    }

    private View space(int width, int height) {
        View view = new View(this);
        view.setLayoutParams(new LinearLayout.LayoutParams(width, height));
        return view;
    }

    private GradientDrawable round(int color, int radius, int strokeColor, int strokeWidth) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(radius);
        if (strokeWidth > 0) {
            d.setStroke(dp(strokeWidth), strokeColor);
        }
        return d;
    }

    private int argb(int alpha, int rgb) {
        return Color.argb(alpha, Color.red(rgb), Color.green(rgb), Color.blue(rgb));
    }

    private String shorten(String value, int max) {
        if (value == null) return "";
        if (value.length() <= max) return value;
        return value.substring(0, Math.max(0, max - 1)) + "…";
    }

    private String formatElapsed(long elapsedMs) {
        long seconds = elapsedMs / 1000;
        long minutes = seconds / 60;
        seconds = seconds % 60;
        return String.format("%02d:%02d", minutes, seconds);
    }

    private int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    private static final class RecordButtonView extends View {
        private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Paint icon = new Paint(Paint.ANTI_ALIAS_FLAG);
        private Phase phase = Phase.IDLE;
        private float density;

        RecordButtonView(Context context) {
            super(context);
            density = getResources().getDisplayMetrics().density;
            setClickable(true);
        }

        void setPhase(Phase phase) {
            this.phase = phase;
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            super.onDraw(canvas);
            float cx = getWidth() / 2f;
            float cy = getWidth() / 2f;
            float r = Math.min(getWidth(), getHeight()) / 2f - dp(3);

            int face = C_SURFACE_2;
            int edge = C_ACCENT;
            int iconColor = C_ACCENT;
            String label = "Записать";
            if (phase == Phase.RECORDING) {
                face = Color.rgb(43, 29, 35);
                edge = C_REC;
                iconColor = C_REC;
                label = "Стоп";
            } else if (phase == Phase.STOPPING) {
                face = C_SURFACE;
                edge = C_BORDER;
                iconColor = C_TEXT_2;
                label = "Сохраняю";
            } else if (phase == Phase.DONE) {
                label = "Новая запись";
            } else if (phase == Phase.ERROR) {
                face = C_SURFACE;
                edge = C_WARN;
                iconColor = C_WARN;
                label = "Повторить";
            }

            fill.setColor(argb(34, edge));
            canvas.drawCircle(cx, cy + dp(8), r + dp(5), fill);
            fill.setColor(face);
            canvas.drawCircle(cx, cy, r, fill);
            stroke.setStyle(Paint.Style.STROKE);
            stroke.setStrokeWidth(dp(1.3f));
            stroke.setColor(edge);
            canvas.drawCircle(cx, cy, r - dp(1), stroke);

            icon.setColor(iconColor);
            icon.setStrokeWidth(dp(4));
            icon.setStyle(Paint.Style.STROKE);
            icon.setStrokeCap(Paint.Cap.ROUND);
            icon.setStrokeJoin(Paint.Join.ROUND);
            if (phase == Phase.RECORDING) {
                icon.setStyle(Paint.Style.FILL);
                canvas.drawRoundRect(new RectF(cx - dp(13), cy - dp(31), cx + dp(13), cy - dp(5)), dp(4), dp(4), icon);
            } else {
                RectF mic = new RectF(cx - dp(10), cy - dp(37), cx + dp(10), cy - dp(7));
                canvas.drawRoundRect(mic, dp(10), dp(10), icon);
                canvas.drawArc(new RectF(cx - dp(21), cy - dp(25), cx + dp(21), cy + dp(9)), 20, 140, false, icon);
                canvas.drawLine(cx, cy + dp(9), cx, cy + dp(25), icon);
                canvas.drawLine(cx - dp(10), cy + dp(25), cx + dp(10), cy + dp(25), icon);
            }

            text.setColor(C_TEXT);
            text.setTextSize(dp(16));
            text.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
            text.setTextAlign(Paint.Align.CENTER);
            canvas.drawText(label, cx, cy + dp(42), text);
        }

        private int dp(float value) {
            return (int) (value * density + 0.5f);
        }

        private int argb(int alpha, int rgb) {
            return Color.argb(alpha, Color.red(rgb), Color.green(rgb), Color.blue(rgb));
        }
    }
}
