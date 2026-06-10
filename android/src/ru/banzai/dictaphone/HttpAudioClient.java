package ru.banzai.dictaphone;

import org.json.JSONObject;


import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * HTTP-клиент диктофона с фоновой очередью отправки.
 * Поток записи кладёт чанки в очередь и не блокируется на сети.
 * Отдельный поток отправки шлёт POST /v1/http/audio/{session_id}.
 */
final class HttpAudioClient {
    public static final String VERSION = "v34-defaults-fix";

    interface Listener {
        void onStatus(String status);
        void onTranscriptDelta(String delta);
        void onTranscriptCompleted(String text);
        void onError(String message);
    }

    private final String baseUrl;
    private final String token;
    private final Listener listener;
    private final LinkedBlockingQueue<byte[]> queue = new LinkedBlockingQueue<>(5);
    private Thread sender;
    private volatile boolean running;
    private volatile String sessionId;
    private volatile boolean statusInFlight;
    private volatile long lastStatusReportMs;
    private int droppedChunks;
    private static final byte[] POISON = new byte[0];

    HttpAudioClient(String url, String token, Listener listener) {
        this.baseUrl = normalize(url);
        this.token = token == null ? "" : token.trim();
        this.listener = listener;
    }

    /** Запускает HTTP-сессию на сервере и стартует поток отправки. */
    String start(int sampleRate, String sourceName) throws Exception {
        String localId = "android-" + System.currentTimeMillis();
        JSONObject body = new JSONObject();
        body.put("type", "start");
        body.put("session_id", localId);
        body.put("device", "android");
        body.put("mode", "dictation");
        body.put("sample_rate", sampleRate);
        body.put("channels", 1);
        body.put("encoding", "pcm_s16le");
        body.put("client_version", VERSION);
        body.put("source", sourceName == null ? "" : sourceName);

        byte[] resp = request("POST", "/v1/http/start", "application/json; charset=utf-8",
                body.toString().getBytes(StandardCharsets.UTF_8), 10000);
        JSONObject json = new JSONObject(new String(resp, StandardCharsets.UTF_8));
        if (!json.optBoolean("ok", false)) {
            throw new IllegalStateException("сервер отклонил старт: " + json.toString());
        }
        sessionId = json.optString("session_id", localId);
        running = true;
        sender = new Thread(new Runnable() {
            @Override public void run() { senderLoop(); }
        }, "dictaphone-sender");
        sender.start();
        return sessionId;
    }

    /** Не блокирующая отправка: кладёт в очередь. */
    void enqueueAudio(byte[] data, int length) {
        if (!running || sessionId == null) return;
        byte[] copy = new byte[length];
        System.arraycopy(data, 0, copy, 0, length);
        if (!queue.offer(copy)) {
            queue.poll();
            if (!queue.offer(copy)) return;
            droppedChunks++;
            if (droppedChunks == 1 || droppedChunks % 100 == 0) {
                publishStatus("Сеть не успевает, пропущено чанков: " + droppedChunks, true);
            }
        }
    }

    /** Отправляет статус на сервер для диагностики без блокировки записи. */
    void reportStatus(final String status) {
        final String sid = sessionId;
        if (sid == null || baseUrl.isEmpty()) return;
        long now = System.currentTimeMillis();
        if (statusInFlight || now - lastStatusReportMs < 800) return;
        statusInFlight = true;
        lastStatusReportMs = now;
        new Thread(new Runnable() {
            @Override public void run() {
                try {
                    byte[] body = ("{\"status\":\"" + status.replace("\\", "\\\\").replace("\"", "\\\"") + "\"}").getBytes(java.nio.charset.StandardCharsets.UTF_8);
                    request("POST", "/v1/http/client-status/" + sid,
                            "application/json; charset=utf-8", body, 5000);
                } catch (Exception ignored) {
                } finally {
                    statusInFlight = false;
                }
            }
        }, "dictaphone-status").start();
    }

    /** Быстро останавливает поток отправки и запускает /stop без ожидания ответа. */
    void stop() {
        String sid = sessionId;
        running = false;
        sessionId = null;
        queue.clear();
        queue.offer(POISON);
        try {
            if (sender != null) {
                sender.interrupt();
                sender.join(500);
                if (sender.isAlive()) {
                    listener.onStatus("Отправка остановлена без ожидания хвоста");
                }
            }
        } catch (InterruptedException ignored) {}

        if (sid != null) {
            final String stopSid = sid;
            new Thread(new Runnable() {
                @Override public void run() {
                    try {
                        request("POST", "/v1/http/stop/" + stopSid, "application/octet-stream",
                                new byte[0], 3000);
                    } catch (Exception e) {
                        publishStatus("Ошибка остановки на сервере: " + e.getMessage(), true);
                    }
                }
            }, "dictaphone-stop").start();
        }
    }

    /* ---- внутреннее ---- */

    private void senderLoop() {
        int sent = 0;
        publishStatus("Отправка запущена " + VERSION, true);
        while (running || !queue.isEmpty()) {
            byte[] chunk;
            try {
                chunk = queue.poll(500, TimeUnit.MILLISECONDS);
            } catch (InterruptedException e) {
                break;
            }
            if (chunk == null) continue;
            if (chunk == POISON) break;
            if (sessionId == null) continue;

            try {
                byte[] resp = requestRaw("POST", "/v1/http/audio/" + sessionId,
                        "application/octet-stream", chunk, 3000);
                sent++;
                if (sent == 1) {
                    publishStatus("Первый чанк дошёл до сервера", true);
                } else if (sent % 50 == 0) {
                    publishStatus("Отправлено чанков: " + sent + " (q=" + queue.size() + ")", true);
                }
                // Парсим ответ: возможно сервер вернёт transcript
                try {
                    JSONObject json = new JSONObject(new String(resp, StandardCharsets.UTF_8));
                    String delta = json.optString("transcript_delta", "");
                    if (delta.length() > 0) listener.onTranscriptDelta(delta);
                } catch (Exception ignored) {}
            } catch (Exception e) {
                if (!running) {
                    break;
                }
                String message = e.getMessage();
                if (message != null && message.contains("session_not_found")) {
                    break;
                }
                publishStatus("HTTP ошибка чанка: " + message, true);
                // Во время записи продолжаем пробовать
            }
        }
        publishStatus("Отправка остановлена, чанков: " + sent, false);
    }

    private void publishStatus(String status, boolean report) {
        listener.onStatus(status);
        if (report) reportStatus(status);
    }

    /** Обычный запрос для JSON. */
    private byte[] request(String method, String path, String contentType, byte[] body, int readTimeoutMs) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(baseUrl + path).openConnection();
        conn.setRequestMethod(method);
        conn.setConnectTimeout(10000);
        conn.setReadTimeout(readTimeoutMs);
        conn.setRequestProperty("Authorization", "Bearer " + token);
        conn.setRequestProperty("Content-Type", contentType);
        conn.setRequestProperty("Connection", "close");
        conn.setUseCaches(false);
        conn.setDoInput(true);
        if (body.length > 0) {
            conn.setDoOutput(true);
            conn.setFixedLengthStreamingMode(body.length);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
                out.flush();
            }
        }

        int code = conn.getResponseCode();
        InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        byte[] respBytes = readAll(in);
        conn.disconnect();
        if (code < 200 || code >= 300) {
            throw new IllegalStateException("HTTP " + code + ": " + new String(respBytes, StandardCharsets.UTF_8));
        }
        return respBytes;
    }

    /** Сырой запрос для аудио: компактный body без JSON/base64, Content-Length явный. */
    private byte[] requestRaw(String method, String path, String contentType, byte[] body, int readTimeoutMs) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(baseUrl + path).openConnection();
        conn.setRequestMethod(method);
        conn.setConnectTimeout(3000);
        conn.setReadTimeout(readTimeoutMs);
        conn.setRequestProperty("Authorization", "Bearer " + token);
        conn.setRequestProperty("Content-Type", contentType);
        conn.setRequestProperty("Connection", "close");
        conn.setUseCaches(false);
        conn.setDoInput(true);
        if (body.length > 0) {
            conn.setDoOutput(true);
            conn.setFixedLengthStreamingMode(body.length);
            try (OutputStream out = conn.getOutputStream()) {
                out.write(body);
                out.flush();
            }
        }

        int code = conn.getResponseCode();
        InputStream in = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
        byte[] respBytes = readAll(in);
        conn.disconnect();
        if (code < 200 || code >= 300) {
            throw new IllegalStateException("HTTP " + code + ": " + new String(respBytes, StandardCharsets.UTF_8));
        }
        return respBytes;
    }

    private byte[] readAll(InputStream in) throws Exception {
        if (in == null) return new byte[0];
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        byte[] chunk = new byte[4096];
        int n;
        while ((n = in.read(chunk)) >= 0) buf.write(chunk, 0, n);
        return buf.toByteArray();
    }

    private String normalize(String url) {
        String v = url == null ? "" : url.trim();
        if (v.startsWith("wss://")) v = "https://" + v.substring(6);
        if (v.startsWith("ws://")) v = "http://" + v.substring(5);
        if (v.endsWith("/v1/stream")) v = v.substring(0, v.length() - "/v1/stream".length());
        while (v.endsWith("/")) v = v.substring(0, v.length() - 1);
        return v;
    }
}
