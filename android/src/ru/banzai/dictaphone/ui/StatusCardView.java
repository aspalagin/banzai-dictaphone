package ru.banzai.dictaphone.ui;

import android.content.Context;
import android.util.TypedValue;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

import ru.banzai.dictaphone.ui.theme.Theme;
import ru.banzai.dictaphone.ui.theme.ThemeColors;

/**
 * Status card showing server connection and recording progress.
 * Displays an icon, title, and meta tag.
 */
public final class StatusCardView extends LinearLayout {
    private final TextView icon;
    private final TextView title;
    private final TextView meta;

    public StatusCardView(Context context) {
        super(context);
        setOrientation(HORIZONTAL);
        setGravity(Gravity.CENTER_VERTICAL);
        int pad = dp(14);
        int padV = dp(12);
        setPadding(pad, padV, pad, padV);
        setBackground(Theme.round(ThemeColors.SURFACE, dp(12), ThemeColors.HAIRLINE, 1));

        icon = new TextView(context);
        icon.setText("☁");
        icon.setTextSize(TypedValue.COMPLEX_UNIT_SP, 20);
        icon.setTextColor(ThemeColors.ACCENT);
        icon.setGravity(Gravity.CENTER);
        addView(icon, new LayoutParams(dp(28), dp(28)));

        title = new TextView(context);
        title.setText("Сервер подключён");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 15);
        title.setTextColor(ThemeColors.TEXT);
        title.setTypeface(android.graphics.Typeface.DEFAULT, android.graphics.Typeface.BOLD);
        LayoutParams titleLp = new LayoutParams(0, LayoutParams.WRAP_CONTENT, 1f);
        titleLp.setMarginStart(dp(8));
        titleLp.setMarginEnd(dp(10));
        addView(title, titleLp);

        meta = new TextView(context);
        meta.setText("готово");
        meta.setTextSize(TypedValue.COMPLEX_UNIT_SP, 12);
        meta.setTextColor(ThemeColors.MUTED);
        meta.setTypeface(android.graphics.Typeface.MONOSPACE);
        meta.setGravity(Gravity.CENTER);
        meta.setPadding(dp(10), 0, dp(10), 0);
        meta.setBackground(Theme.round(ThemeColors.SURFACE, dp(999), ThemeColors.BORDER, 1));
        addView(meta, new LayoutParams(LayoutParams.WRAP_CONTENT, dp(28)));
    }

    public void setStatus(String titleText, String metaText, String iconText, int iconColor) {
        title.setText(titleText);
        meta.setText(metaText);
        icon.setText(iconText);
        icon.setTextColor(iconColor);
    }

    private int dp(float value) {
        return (int) (value * getContext().getResources().getDisplayMetrics().density + 0.5f);
    }
}