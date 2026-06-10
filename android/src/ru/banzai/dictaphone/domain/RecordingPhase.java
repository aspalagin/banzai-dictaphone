package ru.banzai.dictaphone.domain;

/**
 * Recording phase enum.
 * Represents the current state of the recording lifecycle.
 */
public enum RecordingPhase {
    /** Idle — ready to start a new recording. */
    IDLE,
    /** Recording — actively capturing audio. */
    RECORDING,
    /** Stopping — final chunks are being sent. */
    STOPPING,
    /** Done — recording complete, transcript sent. */
    DONE,
    /** Error — something went wrong. */
    ERROR
}