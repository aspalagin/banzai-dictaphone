package ru.banzai.dictaphone.ui.theme;

import android.graphics.Color;

/**
 * All color constants for the Banzai Dictaphone UI.
 * Replaces scattered C_* constants from MainActivity.
 */
public final class ThemeColors {
    private ThemeColors() {}

    public static final int BG          = Color.rgb(14, 17, 22);
    public static final int SURFACE     = Color.rgb(22, 27, 34);
    public static final int SURFACE_2   = Color.rgb(28, 35, 45);
    public static final int BORDER      = Color.rgb(35, 43, 54);
    public static final int HAIRLINE    = Color.rgb(26, 32, 41);
    public static final int TEXT        = Color.rgb(232, 237, 242);
    public static final int TEXT_2      = Color.rgb(155, 166, 179);
    public static final int MUTED       = Color.rgb(97, 108, 122);
    public static final int ACCENT      = Color.rgb(61, 220, 151);
    public static final int REC         = Color.rgb(255, 91, 87);
    public static final int WARN        = Color.rgb(245, 178, 61);

    /** Accent on dark surface: REC inside SURFACE. */
    public static final int REC_FACE    = Color.rgb(43, 29, 35);
}