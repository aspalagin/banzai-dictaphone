package ru.banzai.dictaphone.ui;

import android.content.Context;
import android.graphics.Color;
import android.text.InputType;
import android.text.method.PasswordTransformationMethod;
import android.text.method.SingleLineTransformationMethod;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import ru.banzai.dictaphone.PreferencesManager;
import ru.banzai.dictaphone.ui.theme.Theme;
import ru.banzai.dictaphone.ui.theme.ThemeColors;

/**
 * Settings panel overlay with URL, token fields, health check, and about section.
 */
public final class SettingsPanelView extends LinearLayout {
    private final EditText urlEdit;
    private final EditText tokenEdit;
    private final TextView showTokenButton;
    private final TextView healthView;
    private final TextView checkButton;
    private boolean tokenVisible = false;
    private final PreferencesManager prefs;
    private final String appVersion;

    public interface OnHealthCheckListener {
        void onHealthCheck(String url, String token);
    }

    private OnHealthCheckListener healthListener;

    public SettingsPanelView(Context context, PreferencesManager prefs, String appVersion) {
        super(context);
        this.prefs = prefs;
        this.appVersion = appVersion;
        setOrientation(VERTICAL);
        int pad = dp(20);
        setPadding(pad, dp(18), pad, dp(18));
        setBackgroundColor(ThemeColors.BG);

        addView(buildHeader());
        addView(sectionLabel("СЕРВЕР"));
        addView(fieldLabel("URL сервера"));

        urlEdit = input(false);
        urlEdit.setHint("https://...");
        urlEdit.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addView(urlEdit, new LayoutParams(LayoutParams.MATCH_PARENT, dp(52)));

        addView(fieldLabel("Токен"));
        FrameLayout tokenWrap = new FrameLayout(context);
        tokenEdit = input(true);
        tokenWrap.addView(tokenEdit, new FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT, dp(52)));

        showTokenButton = new TextView(context);
        showTokenButton.setText("Показать");
        showTokenButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        showTokenButton.setTextColor(ThemeColors.TEXT_2);
        showTokenButton.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        showTokenButton.setGravity(Gravity.CENTER);
        showTokenButton.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View v) {
                toggleToken();
            }
        });
        FrameLayout.LayoutParams showLp = new FrameLayout.LayoutParams(dp(82), dp(40), Gravity.RIGHT | Gravity.CENTER_VERTICAL);
        showLp.rightMargin = dp(6);
        tokenWrap.addView(showTokenButton, showLp);

        LayoutParams tokenLp = new LayoutParams(LayoutParams.MATCH_PARENT, dp(52));
        tokenLp.bottomMargin = dp(6);
        addView(tokenWrap, tokenLp);

        TextView hint = new TextView(context);
        hint.setText("Хранится только на устройстве");
        hint.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        hint.setTextColor(ThemeColors.MUTED);
        LayoutParams hintLp = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        hintLp.bottomMargin = dp(14);
        addView(hint, hintLp);

        checkButton = new TextView(context);
        checkButton.setText("↻ Проверить подключение");
        checkButton.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        checkButton.setTextColor(Color.rgb(4, 19, 12));
        checkButton.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        checkButton.setGravity(Gravity.CENTER);
        checkButton.setBackground(Theme.round(ThemeColors.ACCENT, dp(10), ThemeColors.ACCENT, 0));
        checkButton.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View v) {
                if (healthListener != null) {
                    healthListener.onHealthCheck(urlEdit.getText().toString().trim(),
                            tokenEdit.getText().toString().trim());
                }
            }
        });
        addView(checkButton, new LayoutParams(LayoutParams.MATCH_PARENT, dp(52)));

        healthView = new TextView(context);
        healthView.setText("/health - не проверялось");
        healthView.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        healthView.setTextColor(ThemeColors.TEXT_2);
        healthView.setTypeface(android.graphics.Typeface.MONOSPACE);
        healthView.setGravity(Gravity.CENTER_VERTICAL);
        healthView.setPadding(dp(14), 0, dp(14), 0);
        healthView.setBackground(Theme.round(ThemeColors.SURFACE, dp(12), ThemeColors.HAIRLINE, 1));
        LayoutParams healthLp = new LayoutParams(LayoutParams.MATCH_PARENT, dp(48));
        healthLp.topMargin = dp(12);
        healthLp.bottomMargin = dp(24);
        addView(healthView, healthLp);

        addView(sectionLabel("О ПРИЛОЖЕНИИ"));
        LinearLayout info = new LinearLayout(context);
        info.setOrientation(VERTICAL);
        info.setPadding(dp(14), dp(8), dp(14), dp(8));
        info.setBackground(Theme.round(ThemeColors.SURFACE, dp(12), ThemeColors.HAIRLINE, 1));
        LayoutParams infoLp = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        infoLp.topMargin = dp(12);
        addView(info, infoLp);
        info.addView(infoRow("Версия", appVersion));
        info.addView(infoRow("Движок", "Yandex Realtime STT"));
        info.addView(infoRow("Аудио", "Telegram: transcript.txt + audio.ogg"));
    }

    public void setOnHealthCheckListener(OnHealthCheckListener listener) {
        this.healthListener = listener;
    }

    public void loadFromPrefs() {
        urlEdit.setText(prefs.getUrl());
        tokenEdit.setText(prefs.getToken());
    }

    public void saveToPrefs() {
        prefs.saveAll(urlEdit.getText().toString(), tokenEdit.getText().toString());
    }

    public void setHealthStatus(String text, int color) {
        healthView.setText(text);
        healthView.setTextColor(color);
    }

    public void setCheckButtonText(String text) {
        checkButton.setText(text);
    }

    private View buildHeader() {
        LinearLayout header = new LinearLayout(getContext());
        header.setOrientation(HORIZONTAL);
        header.setGravity(Gravity.CENTER_VERTICAL);
        LayoutParams headerLp = new LayoutParams(LayoutParams.MATCH_PARENT, dp(54));
        headerLp.bottomMargin = dp(18);
        addView(header, headerLp);

        TextView title = new TextView(getContext());
        title.setText("Настройки");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 22);
        title.setTextColor(ThemeColors.TEXT);
        title.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        header.addView(title, new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f));

        TextView close = new TextView(getContext());
        close.setText("×");
        close.setTextSize(TypedValue.COMPLEX_UNIT_SP, 28);
        close.setTextColor(ThemeColors.TEXT_2);
        close.setGravity(Gravity.CENTER);
        close.setBackground(Theme.round(ThemeColors.SURFACE_2, dp(10), ThemeColors.BORDER, 1));
        close.setOnClickListener(new android.view.View.OnClickListener() {
            @Override
            public void onClick(android.view.View v) {
                saveToPrefs();
                setVisibility(View.GONE);
            }
        });
        header.addView(close, new LayoutParams(dp(44), dp(44)));
        return header;
    }

    private TextView sectionLabel(String text) {
        TextView label = new TextView(getContext());
        label.setText(text);
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        label.setTextColor(ThemeColors.MUTED);
        label.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        Theme.safeLetterSpacing(label);
        LayoutParams lp = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(18);
        lp.bottomMargin = dp(10);
        label.setLayoutParams(lp);
        return label;
    }

    private TextView fieldLabel(String value) {
        TextView label = new TextView(getContext());
        label.setText(value);
        label.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        label.setTextColor(ThemeColors.TEXT_2);
        label.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        LayoutParams lp = new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(14);
        lp.bottomMargin = dp(8);
        label.setLayoutParams(lp);
        return label;
    }

    private TextView infoRow(String key, String value) {
        TextView row = new TextView(getContext());
        row.setText(key + "     " + value);
        row.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14);
        row.setTextColor(ThemeColors.TEXT_2);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(8), 0, dp(8));
        return row;
    }

    private EditText input(boolean password) {
        EditText view = new EditText(getContext());
        view.setSingleLine(true);
        view.setTextColor(ThemeColors.TEXT);
        view.setHintTextColor(ThemeColors.MUTED);
        view.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        view.setTypeface(android.graphics.Typeface.MONOSPACE);
        view.setPadding(dp(14), 0, password ? dp(92) : dp(14), 0);
        view.setBackground(Theme.round(ThemeColors.SURFACE_2, dp(10), ThemeColors.BORDER, 1));
        if (password) {
            view.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
            view.setTransformationMethod(PasswordTransformationMethod.getInstance());
        }
        return view;
    }

    private void toggleToken() {
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

    private int dp(float value) {
        return (int) (value * getContext().getResources().getDisplayMetrics().density + 0.5f);
    }
}