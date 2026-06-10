package ru.banzai.dictaphone.ui.theme;

import android.content.res.Resources;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.widget.TextView;

/**
 * UI utility helpers: dp conversion, color helpers, drawables.
 * Replaces inline utility methods from MainActivity.
 */
public final class Theme {
    private Theme() {}

    private static float getDensity() {
        return Resources.getSystem().getDisplayMetrics().density;
    }

    /** Convert dp to pixels using the default display density. */
    public static int dp(int value) {
        return (int) (value * getDensity() + 0.5f);
    }

    /** Convert float dp to pixels. */
    public static int dp(float value) {
        return (int) (value * getDensity() + 0.5f);
    }

    /**
     * Add an alpha channel to an RGB color.
     * E.g. argb(128, Color.RED) makes it 50% transparent.
     */
    public static int argb(int alpha, int rgb) {
        return Color.argb(alpha, Color.red(rgb), Color.green(rgb), Color.blue(rgb));
    }

    /**
     * Create a rounded rectangle drawable.
     * @param color       fill color (with alpha if needed)
     * @param radius      corner radius in dp
     * @param strokeColor border color (0 for no border)
     * @param strokeWidth border width in dp (0 for no border)
     */
    public static GradientDrawable round(int color, int radius, int strokeColor, int strokeWidth) {
        GradientDrawable d = new GradientDrawable();
        d.setColor(color);
        d.setCornerRadius(radius);
        if (strokeWidth > 0) {
            d.setStroke(dp(strokeWidth), strokeColor);
        }
        return d;
    }

    /**
     * Set letter spacing on API 21+. Silently ignored on older versions.
     */
    public static void safeLetterSpacing(TextView view) {
        if (Build.VERSION.SDK_INT >= 21) {
            try {
                view.setLetterSpacing(0.08f);
            } catch (Throwable ignored) {}
        }
    }

    /**
     * Shorten a string to at most max characters, appending ellipsis.
     */
    public static String shorten(String value, int max) {
        if (value == null) return "";
        if (value.length() <= max) return value;
        return value.substring(0, Math.max(0, max - 1)) + "…";
    }
}