package ru.banzai.dictaphone;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioFormat;
import android.media.AudioRecord;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.IBinder;

/**
     * Фоновый сервис диктофона с уведомлением.
     * Архитектура:
     *   - поток записи читает микрофон, ресемплит в 24 кГц, кладёт чанки в очередь
     *   - поток отправки внутри HttpAudioClient шлёт чанки HTTP POST на сервер
     *   - остановка ставит recording=false, сбрасывает хвост и шлёт /stop отдельно
     * Запись и остановка не блокируют интерфейс или друг друга.
     */
public class DictaphoneService extends Service {
    static final String ACTION_START = "ru.banzai.dictaphone.START";
    static final String ACTION_STOP  = "ru.banzai.dictaphone.STOP";
    static final String ACTION_EVENT = "ru.banzai.dictaphone.EVENT";
    static final String EXTRA_URL = "url";
    static final String EXTRA_TOKEN = "***";
    static final String EXTRA_STATUS = "status";
    static final String EXTRA_TRANSCRIPT = "transcript";

    private static final String CHANNEL_ID = "dictaphone";
    private static final int NOTIFICATION_ID = 7701;
    private static final int[] SAMPLE_RATES = {24000, 48000, 44100};
    private static final int OUTPUT_RATE = 24000;
    /** 0.5 секунды аудио при 24kHz s16le mono = 24000 байт. */
    private static final int CHUNK_BYTES = OUTPUT_RATE * 2 / 2;

    private volatile boolean recording;
    private Thread worker;
    private AudioRecord currentRecorder;
    private HttpAudioClient currentClient;

    @Override public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String action = intent == null ? "" : intent.getAction();
        if (ACTION_START.equals(action)) {
            String url   = intent.getStringExtra(EXTRA_URL);
            String token = intent.getStringExtra(EXTRA_TOKEN);
            startForeground(NOTIFICATION_ID, notification("Запись запускается"));
            startRecording(url, token);
        } else if (ACTION_STOP.equals(action)) {
            stopRecording();
            stopSelf();
        }
        return START_NOT_STICKY;
    }

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public void onDestroy() {
        stopRecording();
        super.onDestroy();
    }

    private void startRecording(final String url, final String token) {
        if (recording) return;
        recording = true;
        worker = new Thread(new Runnable() {
            @Override public void run() { runRecording(url, token); }
        }, "dictaphone-rec");
        worker.start();
    }

    private void stopRecording() {
        // Остановка не блокирует интерфейс: просто меняет флаг.
        // Поток записи сам завершится, поток отправки в HttpAudioClient сбросит хвост.
        recording = false;
    }

    private void runRecording(String url, String token) {
        AudioRecord recorder = null;
        HttpAudioClient client = null;
        try {
            if (Build.VERSION.SDK_INT >= 23 &&
                checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                publish("Нет разрешения на микрофон", null);
                return;
            }

            // 1. Микрофон
            AudioSetup setup = createRecorder();
            recorder = setup.recorder;
            currentRecorder = recorder;
            publish("Микрофон: " + setup.sampleRate + " Hz / " + setup.sourceName, null);

            // 2. HTTP-сессия
            publish("Подключаюсь к серверу...", null);
            client = new HttpAudioClient(url, token, new HttpAudioClient.Listener() {
                @Override public void onStatus(String s) {
                    publish(s, null);
                }
                @Override public void onTranscriptDelta(String d) { publish(null, d); }
                @Override public void onTranscriptCompleted(String t) { publish(null, t + "\n"); }
                @Override public void onError(String m) { publish("Ошибка: " + m, null); }
            });
            String sessionId = client.start(OUTPUT_RATE, setup.sourceName);
            currentClient = client;
            publish("Сервер принял: " + sessionId + " / " + HttpAudioClient.VERSION, null);
            client.reportStatus("recorder_started rate=" + setup.sampleRate + " src=" + setup.sourceName);

            // 3. Старт записи
            recorder.startRecording();
            if (recorder.getRecordingState() != AudioRecord.RECORDSTATE_RECORDING) {
                client.reportStatus("audiorecord_not_recording state=" + recorder.getRecordingState());
                throw new IllegalStateException("AudioRecord не перешёл в RECORDING state=" + recorder.getRecordingState());
            }
            Thread.sleep(100);
            updateNotification("Идёт запись");
            publish("Идёт запись", null);
            client.reportStatus("recording_loop_start");

            // 4. Буферы
            short[] captureBuf = new short[setup.sampleRate / 10]; // 100 мс
            byte[] resampleBuf = new byte[(captureBuf.length * OUTPUT_RATE / setup.sampleRate + 4) * 2];
            byte[] chunkBuf = new byte[CHUNK_BYTES];
            int chunkFill = 0;
            int zeroReads = 0;
            int totalSamples = 0;
            int errorCount = 0;

            // 5. Цикл — используем READ_NON_BLOCKING чтобы не зависать на Huawei
            while (recording) {
                int samplesRead;
                // READ_NON_BLOCKING: сразу возвращает 0 если данных нет, не блокирует
                if (Build.VERSION.SDK_INT >= 23) {
                    samplesRead = recorder.read(captureBuf, 0, captureBuf.length, AudioRecord.READ_NON_BLOCKING);
                } else {
                    samplesRead = recorder.read(captureBuf, 0, captureBuf.length);
                }
                if (samplesRead > 0) {
                    if (totalSamples == 0) {
                        publish("Микрофон отдаёт аудио", null);
                        client.reportStatus("first_audio_from_mic samples=" + samplesRead);
                    }
                    totalSamples += samplesRead;
                    zeroReads = 0;
                    errorCount = 0;
                    int pcmBytes = resample(captureBuf, samplesRead, setup.sampleRate, resampleBuf);
                    int offset = 0;
                    while (offset < pcmBytes) {
                        int n = Math.min(chunkBuf.length - chunkFill, pcmBytes - offset);
                        System.arraycopy(resampleBuf, offset, chunkBuf, chunkFill, n);
                        chunkFill += n;
                        offset += n;
                        if (chunkFill >= CHUNK_BYTES) {
                            client.enqueueAudio(chunkBuf, chunkFill);
                            chunkFill = 0;
                        }
                    }
                } else if (samplesRead == 0) {
                    // NON_BLOCKING: нет данных прямо сейчас — подождать немного
                    zeroReads++;
                    if (zeroReads == 5) {
                        publish("Жду аудио от микрофона...", null);
                        client.reportStatus("waiting_for_mic zero_reads=5");
                    } else if (zeroReads % 100 == 0) {
                        publish("Микрофон молчит " + (zeroReads / 10) + "с", null);
                        client.reportStatus("mic_silent zero_reads=" + zeroReads + " total_samples=" + totalSamples);
                    }
                    try { Thread.sleep(10); } catch (InterruptedException e) { throw e; }
                } else if (samplesRead < 0) {
                    errorCount++;
                    publish("Ошибка микрофона: " + samplesRead, null);
                    client.reportStatus("mic_error code=" + samplesRead + " count=" + errorCount);
                    if (errorCount >= 3) break;
                    try { Thread.sleep(100); } catch (InterruptedException e) { throw e; }
                }
            }
            // Остаток
            if (chunkFill > 0) {
                client.enqueueAudio(chunkBuf, chunkFill);
            }
            client.reportStatus("recording_loop_end total_samples=" + totalSamples);

        } catch (InterruptedException ignored) {
        } catch (Exception e) {
            String msg = e.getMessage() == null ? e.toString() : e.getMessage();
            publish("Ошибка: " + msg, null);
            if (client != null) client.reportStatus("exception: " + msg);
        } finally {
            recording = false;

            // Микрофон
            if (recorder != null) {
                try { recorder.stop(); } catch (Exception ignored) {}
                try { recorder.release(); } catch (Exception ignored) {}
                if (currentRecorder == recorder) currentRecorder = null;
            }

            // Отправка и /stop: хвост очереди сбрасывается, интерфейс не ждёт сеть.
            if (client != null) {
                publish("Останавливаю отправку...", null);
                client.stop();
                if (currentClient == client) currentClient = null;
            }

            updateNotification("Запись остановлена");
            publish("Запись остановлена", null);
        }
    }

    private void publish(String status, String transcriptDelta) {
        Intent intent = new Intent(ACTION_EVENT);
        if (status != null) intent.putExtra(EXTRA_STATUS, status);
        if (transcriptDelta != null) intent.putExtra(EXTRA_TRANSCRIPT, transcriptDelta);
        sendBroadcast(intent);
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CHANNEL_ID, "Банзай Диктофон", NotificationManager.IMPORTANCE_LOW);
            getSystemService(NotificationManager.class).createNotificationChannel(ch);
        }
    }

    private Notification notification(String text) {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL_ID)
                : new Notification.Builder(this);
        return b.setContentTitle("Банзай Диктофон")
                .setContentText(text)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setOngoing(recording)
                .build();
    }

    private void updateNotification(String text) {
        ((NotificationManager) getSystemService(NOTIFICATION_SERVICE)).notify(NOTIFICATION_ID, notification(text));
    }

    private AudioSetup createRecorder() {
        int[] sources = {MediaRecorder.AudioSource.MIC, MediaRecorder.AudioSource.VOICE_RECOGNITION, MediaRecorder.AudioSource.CAMCORDER};
        for (int src : sources) {
            for (int rate : SAMPLE_RATES) {
                int min = AudioRecord.getMinBufferSize(rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT);
                if (min <= 0) continue;
                int bufSz = Math.max(min, rate / 10 * 2 * 4);
                AudioRecord ar = new AudioRecord(src, rate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, bufSz);
                if (ar.getState() == AudioRecord.STATE_INITIALIZED) {
                    return new AudioSetup(ar, rate, srcName(src));
                }
                ar.release();
            }
        }
        throw new IllegalStateException("Не удалось открыть микрофон");
    }

    private static final class AudioSetup {
        final AudioRecord recorder; final int sampleRate; final String sourceName;
        AudioSetup(AudioRecord r, int sr, String sn) { recorder = r; sampleRate = sr; sourceName = sn; }
    }

    private String srcName(int s) {
        if (s == MediaRecorder.AudioSource.VOICE_RECOGNITION) return "VOICE_RECOGNITION";
        if (s == MediaRecorder.AudioSource.MIC)               return "MIC";
        if (s == MediaRecorder.AudioSource.CAMCORDER)          return "CAMCORDER";
        return "src_" + s;
    }

    private int resample(short[] in, int inSamples, int inRate, byte[] out) {
        int outSamples = Math.max(1, (int)(((long) inSamples * OUTPUT_RATE) / inRate));
        int maxOut = out.length / 2;
        if (outSamples > maxOut) outSamples = maxOut;
        for (int i = 0; i < outSamples; i++) {
            int si = (int)(((long) i * inRate) / OUTPUT_RATE);
            if (si >= inSamples) si = inSamples - 1;
            short s = in[si];
            out[i*2]     = (byte)(s & 0xff);
            out[i*2 + 1] = (byte)((s >> 8) & 0xff);
        }
        return outSamples * 2;
    }
}
