package ru.banzai.dictaphone.ui;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.util.TypedValue;
import android.view.View;

import ru.banzai.dictaphone.domain.RecordingPhase;
import ru.banzai.dictaphone.ui.theme.Theme;
import ru.banzai.dictaphone.ui.theme.ThemeColors;

/**
 * Custom circular record/stop button.
 * Renders a microphone or stop icon based on the current phase.
 */
public final class RecordButtonView extends View {
    private RecordingPhase phase = RecordingPhase.IDLE;
    private float density;

    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint stroke = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint icon = new Paint(Paint.ANTI_ALIAS_FLAG);

    public RecordButtonView(Context context) {
        super(context);
        density = context.getResources().getDisplayMetrics().density;
        setClickable(true);
    }

    public void setPhase(RecordingPhase phase) {
        this.phase = phase;
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        float cx = getWidth() / 2f;
        float cy = getWidth() / 2f;
        float r = Math.min(getWidth(), getHeight()) / 2f - dp(3);

        int face = ThemeColors.SURFACE_2;
        int edge = ThemeColors.ACCENT;
        int iconColor = ThemeColors.ACCENT;
        String label = "Записать";

        if (phase == RecordingPhase.RECORDING) {
            face = ThemeColors.REC_FACE;
            edge = ThemeColors.REC;
            iconColor = ThemeColors.REC;
            label = "Стоп";
        } else if (phase == RecordingPhase.STOPPING) {
            face = ThemeColors.SURFACE;
            edge = ThemeColors.BORDER;
            iconColor = ThemeColors.TEXT_2;
            label = "Сохраняю";
        } else if (phase == RecordingPhase.DONE) {
            label = "Новая запись";
        } else if (phase == RecordingPhase.ERROR) {
            face = ThemeColors.SURFACE;
            edge = ThemeColors.WARN;
            iconColor = ThemeColors.WARN;
            label = "Повторить";
        }

        // Glow ring
        fill.setColor(Theme.argb(34, edge));
        canvas.drawCircle(cx, cy + dp(8), r + dp(5), fill);

        // Face circle
        fill.setColor(face);
        canvas.drawCircle(cx, cy, r, fill);

        // Border stroke
        stroke.setStyle(Paint.Style.STROKE);
        stroke.setStrokeWidth(dp(1.3f));
        stroke.setColor(edge);
        canvas.drawCircle(cx, cy, r - dp(1), stroke);

        // Icon
        icon.setColor(iconColor);
        icon.setStrokeWidth(dp(4));
        icon.setStyle(Paint.Style.STROKE);
        icon.setStrokeCap(Paint.Cap.ROUND);
        icon.setStrokeJoin(Paint.Join.ROUND);
        if (phase == RecordingPhase.RECORDING) {
            // Square stop icon
            icon.setStyle(Paint.Style.FILL);
            canvas.drawRoundRect(
                    new RectF(cx - dp(13), cy - dp(31), cx + dp(13), cy - dp(5)),
                    dp(4), dp(4), icon);
        } else {
            // Microphone icon
            RectF mic = new RectF(cx - dp(10), cy - dp(37), cx + dp(10), cy - dp(7));
            canvas.drawRoundRect(mic, dp(10), dp(10), icon);
            canvas.drawArc(
                    new RectF(cx - dp(21), cy - dp(25), cx + dp(21), cy + dp(9)),
                    20, 140, false, icon);
            canvas.drawLine(cx, cy + dp(9), cx, cy + dp(25), icon);
            canvas.drawLine(cx - dp(10), cy + dp(25), cx + dp(10), cy + dp(25), icon);
        }

        // Label
        text.setColor(ThemeColors.TEXT);
        text.setTextSize(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 16, getContext().getResources().getDisplayMetrics()));
        text.setTypeface(Typeface.create(Typeface.DEFAULT, Typeface.BOLD));
        text.setTextAlign(Paint.Align.CENTER);
        canvas.drawText(label, cx, cy + dp(42), text);
    }

    private int dp(float value) {
        return (int) (value * density + 0.5f);
    }
}