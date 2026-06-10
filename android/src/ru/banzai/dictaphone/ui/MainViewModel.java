package ru.banzai.dictaphone.ui;

import android.os.Handler;
import android.os.Looper;

import ru.banzai.dictaphone.domain.RecordingPhase;
import ru.banzai.dictaphone.ui.theme.ThemeColors;

/**
 * ViewModel for MainActivity — holds all UI state.
 * NOT AndroidX ViewModel (no onSaveInstanceState needed for this app).
 * Plain state holder with timer formatting and phase logic.
 */
public final class MainViewModel {
    private RecordingPhase phase = RecordingPhase.IDLE;
    private long recordingStartedAt;
    private int statusStep;
    private String healthStatus = "/health - не проверялось";
    private int healthStatusColor = ThemeColors.TEXT_2;
    private boolean settingsVisible;
    private String url = "";
    private String token = "";
    private boolean tokenVisible;

    private final Handler handler;
    private Runnable timerCallback;
    private boolean timerRunning;

    public interface TimerCallback {
        void onTimerTick(String formattedTime, RecordingPhase phase);
    }

    private TimerCallback timerCallbackRef;

    public MainViewModel() {
        this.handler = new Handler(Looper.getMainLooper());
    }

    public RecordingPhase getPhase() { return phase; }

    public void setPhase(RecordingPhase phase) {
        this.phase = phase;
        if (timerCallbackRef != null) {
            timerCallbackRef.onTimerTick(getFormattedElapsed(), phase);
        }
    }

    public long getRecordingStartedAt() { return recordingStartedAt; }
    public void setRecordingStartedAt(long t) { this.recordingStartedAt = t; }

    public int getStatusStep() { return statusStep; }
    public void updateStatusStep(int step) { this.statusStep = Math.max(this.statusStep, step); }

    public String getHealthStatus() { return healthStatus; }
    public void setHealthStatus(String status, int color) {
        this.healthStatus = status;
        this.healthStatusColor = color;
    }
    public int getHealthStatusColor() { return healthStatusColor; }

    public boolean isSettingsVisible() { return settingsVisible; }
    public void setSettingsVisible(boolean visible) { this.settingsVisible = visible; }

    public String getUrl() { return url; }
    public void setUrl(String url) { this.url = url; }

    public String getToken() { return token; }
    public void setToken(String token) { this.token = token; }

    public boolean isTokenVisible() { return tokenVisible; }
    public void toggleTokenVisible() { this.tokenVisible = !tokenVisible; }

    public void startTimer(TimerCallback callback) {
        this.timerCallbackRef = callback;
        this.timerRunning = true;
        tickTimer();
    }

    public void stopTimer() {
        this.timerRunning = false;
        this.timerCallbackRef = null;
        if (timerCallback != null) {
            handler.removeCallbacks(timerCallback);
            timerCallback = null;
        }
    }

    private void tickTimer() {
        if (!timerRunning || timerCallbackRef == null) return;
        timerCallbackRef.onTimerTick(getFormattedElapsed(), phase);
        timerCallback = new Runnable() {
            @Override
            public void run() {
                tickTimer();
            }
        };
        handler.postDelayed(timerCallback, 500);
    }

    public String getFormattedElapsed() {
        long elapsed = Math.max(0, System.currentTimeMillis() - recordingStartedAt);
        long seconds = elapsed / 1000;
        long minutes = seconds / 60;
        seconds = seconds % 60;
        return String.format("%02d:%02d", minutes, seconds);
    }

    public void resetForNewRecording() {
        this.phase = RecordingPhase.IDLE;
        this.statusStep = 0;
        this.recordingStartedAt = 0;
    }

    public void resetForStop() {
        this.phase = RecordingPhase.STOPPING;
    }

    public void resetForDone() {
        this.phase = RecordingPhase.DONE;
    }

    public void resetForError(String title, String detail) {
        this.phase = RecordingPhase.ERROR;
    }
}