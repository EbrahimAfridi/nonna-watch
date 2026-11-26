# Listener ↔ hub API contract

Protocol version **1**. Owner: Ebrahim (hub). Used by: the listener app (teammate A).

A change on one side breaks the other, so any change to this file is agreed in the group first and
recorded in `DECISIONS.md`.

## At a glance

- One WebSocket per listener phone: `ws://<hub-ip>:8000/ws/listener`. The Cloud Run copy used for
  the experiments speaks the same protocol at `wss://<service-url>/ws/listener`.
- The phone authenticates with an `Authorization: Bearer <HUB_TOKEN>` header on the WebSocket
  upgrade request.
- The phone sends `hello`, waits for `welcome`, then streams 1-second binary audio frames plus the
  occasional JSON text message. The hub sends JSON text messages back.
- Neither side ever writes audio to disk or logs. The hub keeps a few seconds of audio in memory and
  drops it after analysis.
- Phone-only mode does not use this protocol; it writes to Firestore directly (see
  `docs/firestore-schema.md`).

## Listener settings

| Setting | Example | Notes |
|---|---|---|
| Hub URL | `ws://192.168.43.12:8000/ws/listener` | The hub prints it on start. Hotspot IPs change between sessions. |
| Room | `kitchen` | One of `kitchen`, `bathroom`, `bedroom`, `living_room`, `hallway`. One listener per room. Apps show friendly names; the protocol uses these ids. |
| Token | (secret) | Same value as `HUB_TOKEN` in the hub's `.env`. |

`device_id` is a random UUID the app generates on first launch and keeps. Not a hardware id.

## Connection lifecycle

1. Open the WebSocket with the `Authorization` header. A wrong or missing token makes the hub refuse
   the upgrade with HTTP 403.
2. Send `hello` as the first message.
3. Wait up to 10 s for `welcome`. If it does not arrive, close and reconnect.
4. Stream audio frames and send text messages as described below.
5. Keepalive: OkHttp `pingInterval(20, TimeUnit.SECONDS)`. The hub answers pings automatically, so a
   dead link is noticed within about 40 s.

### Reconnecting

- Back off 1, 2, 4, 8, 16, then 30 s between attempts (cap 30 s, ±20 % jitter). Reset after a
  `welcome`.
- `seq` restarts at 0 on every new connection.
- While disconnected, do not keep audio. Light events may be queued (Room) and sent after reconnect
  with their original `ts_ms`.

### Close codes

| Code | Meaning | Phone should |
|---|---|---|
| 1000 | Normal close (phone stopped listening) | Nothing |
| 1001 | Hub shutting down | Reconnect with backoff |
| 4400 | Bad `hello` (unknown protocol, wrong sample rate, unknown room) or audio before `hello` | Stop and show the close reason |
| 4409 | A newer connection for the same room, or with the same `device_id`, replaced this one | Stop; the newer one is live |
| HTTP 403 on upgrade | Wrong token | Stop and show "wrong token" |
| Anything else, or a network error | | Reconnect with backoff |

## Audio frames (phone → hub, binary)

Every binary message is exactly one frame:

| Bytes | Field | Type | Meaning |
|---|---|---|---|
| 0–7 | `capture_ms` | int64, little-endian | Unix time in ms of the first sample in this frame |
| 8–11 | `seq` | uint32, little-endian | 0 for the first frame of a connection, +1 per frame |
| 12–32011 | `pcm` | 16,000 × int16, little-endian | 1 s of mono audio at 16 kHz |

Total: **32,012 bytes**. A frame of any other length gets an `error` (`bad_frame`) and is dropped;
the connection stays open.

**Recording.** `AudioRecord` with source `VOICE_RECOGNITION`, 16000 Hz, `CHANNEL_IN_MONO`,
`ENCODING_PCM_16BIT`. `VOICE_RECOGNITION` turns off automatic gain control on most phones. With gain
control on, a quiet room is boosted and a thud is squashed, which breaks thud and silence detection.
If a phone refuses 16 kHz, tell Ebrahim rather than resampling on the phone.

**`capture_ms`.** When `read()` returns a full 16,000-sample buffer, use
`System.currentTimeMillis() - 1000`. Keep the phone on automatic network time; Experiment 1 measures
alert latency from this value.

**Real time beats completeness.** If `webSocket.queueSize()` is above 320,000 bytes (10 s of audio),
skip the frame instead of sending it, and still increment `seq` so the hub sees the gap.

**Worked example** for a unit test of the encoder: `capture_ms = 1795698192000`
(2026-11-26 14:03:12 +01:00), `seq = 42`, first samples `0, 1000, -1000`:

```
80 ee f3 17 a2 01 00 00   capture_ms
2a 00 00 00               seq
00 00 e8 03 18 fc ...     pcm
```

Kotlin (OkHttp / Okio):

```kotlin
import java.nio.ByteBuffer
import java.nio.ByteOrder
import okio.ByteString
import okio.ByteString.Companion.toByteString

fun audioFrame(captureMs: Long, seq: Int, samples: ShortArray): ByteString {
    val buffer = ByteBuffer.allocate(12 + samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
    buffer.putLong(captureMs)
    buffer.putInt(seq)
    buffer.asShortBuffer().put(samples)
    return buffer.array().toByteString()
}
```

`ByteBuffer` is big-endian by default. Forgetting `.order(ByteOrder.LITTLE_ENDIAN)` turns the audio
into loud noise on the hub.

Hub side, for reference:
`capture_ms, seq = struct.unpack_from("<qI", frame)` and
`pcm = np.frombuffer(frame, dtype="<i2", offset=12)`.

## Text messages

Rules for both sides:

- UTF-8 JSON objects with a `type` field. Field names are `snake_case`.
- Times are Unix epoch milliseconds, in fields ending in `_ms`.
- Ignore unknown `type` values and unknown fields. Either side can then add optional things without
  breaking the other.

### Phone → hub

**`hello`**: first message, exactly once per connection.

```json
{"type": "hello", "protocol": 1, "device_id": "1f0c6c1e-4b7a-4d0e-9a51-7c2f0d3e8b11",
 "room": "kitchen", "sample_rate": 16000, "app_version": "0.1.0", "device_model": "Nothing A001"}
```

`device_model` is optional; it labels the experiment results.

**`heartbeat`**: every 30 s, and immediately whenever `paused` changes.

```json
{"type": "heartbeat", "ts_ms": 1795698222000, "battery_pct": 87, "charging": true, "paused": false}
```

Experiment 5's battery curve comes from these, so keep sending them while charging too.

**`light`**: only when the state changes.

```json
{"type": "light", "ts_ms": 1795698222000, "state": "bright", "lux": 112.0}
```

`dark` below 10 lux, `bright` above 30 lux; the gap between the two stops flicker. The hub turns it
into a timeline event ("Light on, bedroom, 03:12").

**`ask_played`**: after playing the check-in question.

```json
{"type": "ask_played", "ask_id": "kitchen-1795698192000", "ok": true,
 "started_ms": 1795698192400, "ended_ms": 1795698195900}
```

```json
{"type": "ask_played", "ask_id": "kitchen-1795698192000", "ok": false, "reason": "no_audio_output"}
```

### Hub → phone

**`welcome`**: reply to `hello`.

```json
{"type": "welcome", "protocol": 1, "hub_id": "ebrahim-mac", "hub_time_ms": 1795698192150, "paused": false}
```

Apply `paused` right away; the family may have paused while the phone was offline.

**`checkin_clip`**: after `welcome` if the family has recorded a check-in message, and again whenever
it changes.

```json
{"type": "checkin_clip", "clip_id": "3", "mime": "audio/mp4", "data_b64": "AAAAIGZ0eXBNNEEg..."}
```

```json
{"type": "checkin_clip", "clip_id": null}
```

Save the clip, replacing the previous one. `clip_id: null` means it was deleted: fall back to
text-to-speech. Clips are at most about 15 s / 200 KB.

**`ask`**: play the check-in question now.

```json
{"type": "ask", "ask_id": "kitchen-1795698192000", "reason": "thud",
 "text": "Mamma, stai bene?", "lang": "it-IT"}
```

- Play the saved clip. If there is none, speak `text` with Android `TextToSpeech` in `lang`. Phones
  may lack a voice for some languages (check Urdu and Bosnian on the real phones); the recorded clip
  avoids that problem.
- Play with `AudioAttributes.USAGE_ALARM` so it is audible when the phone is on silent.
- Keep streaming audio while playing. Send `ask_played` when done.
- `reason` is informational: `help_word`, `scream`, `thud`, `glass`, `long_silence`,
  `routine_missed` or `manual`.

**`set_paused`**: the family paused or resumed listening from the family app.

```json
{"type": "set_paused", "paused": true}
```

On `true`: stop `AudioRecord` (Android's microphone indicator turns off, which shows her the mic is
really off), stop sending frames, keep the WebSocket and heartbeats going. On `false`: start
recording again; `seq` continues from where it was.

**`error`**

```json
{"type": "error", "code": "bad_frame", "message": "frame must be 32012 bytes, got 32010"}
```

Codes: `bad_hello`, `bad_frame`, `bad_message`. For logging; only `bad_hello` is followed by a close
(4400).

## Voice check, end to end

1. The hub decides to ask (for example a thud followed by 10 s of silence) and sends `ask`.
2. The phone plays the clip, or text-to-speech, while still streaming.
3. The phone sends `ask_played` with `started_ms` and `ended_ms`.
4. The hub ignores everything heard between sending `ask` and `ended_ms`, because the question
   itself may contain a help word ("hai bisogno di aiuto?") or a fine word ("stai bene?"). It then
   listens for 30 s after `ended_ms`.
5. "Sto bene" / "I'm fine": logged, no alert. A help word, or no answer at all: the family is
   alerted.
6. No `ask_played` within 20 s of `ask`: the hub treats the check as failed and alerts the family.

The hub never sends a second `ask` to a phone before the first one's `ask_played` or its 20 s
timeout.

## Pause

- The older person taps Pause on the listener: the phone stops recording and sends a `heartbeat`
  with `paused: true`.
- The family pauses in the family app: the hub sends `set_paused`.

Either way the hub suppresses silence and routine alerts for that room while it is paused, and the
room shows as "paused", not "offline".

## REST (hub)

Everything except `/health` needs the same bearer token.

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"status": "ok", "hub_id": "...", "version": "...", "uptime_s": 123}` |
| GET | `/devices` | Connected listeners: `device_id`, `room`, `connected_since_ms`, `last_frame_ms`, `frames_received`, `frames_missing`, `battery_pct`, `paused` |
| POST | `/ask?room=kitchen` | Starts a voice check in that room: `{"ask_id": "..."}`. 404 if no listener is connected there; 409 while a voice check is still running there (under a minute). |

```
curl -H "Authorization: Bearer $HUB_TOKEN" http://192.168.43.12:8000/devices
```

## Optional: QR pairing (only if the group agrees)

Typing a URL and a token on two phones before every demo is slow, and the hotspot IP changes. The hub
could print a QR code on start, and the listener could scan it with CameraX plus ML Kit barcode
scanning (on-device and free). That would also tick the CameraX and ML Kit boxes on the professor's
form. Payload:

```json
{"v": 1, "hub": "ws://192.168.43.12:8000/ws/listener", "token": "..."}
```

The room is still picked on the phone.

## Notes for the listener app (Android)

- `ws://` is cleartext, which Android blocks by default. Set `android:usesCleartextTraffic="true"`
  in the listener app's manifest.
- Foreground service with `foregroundServiceType="microphone"`, plus the `RECORD_AUDIO` and
  `FOREGROUND_SERVICE_MICROPHONE` permissions. Start it from the visible activity (the user taps
  Start): Android does not let a service started from the background use the microphone, and
  Android 15 blocks starting it from `BOOT_COMPLETED`. After a reboot, someone opens the app once.
- Battery set to Unrestricted. Hold a partial `WakeLock` and a `WifiLock`
  (`WIFI_MODE_FULL_LOW_LATENCY` on Android 10+) while listening.
- Never write audio to disk or to logs.

## Known limits (security)

- `ws://` on the home network is not encrypted. That is acceptable for the demo on a WPA2 hotspot; a
  real product would use TLS. The Cloud Run copy uses `wss://`.
- `HUB_TOKEN` is a single shared secret. Keep it in the hub's `.env` (gitignored), never in a URL
  (Cloud Run logs request URLs), never in git. Make a new one after the course:
  `python -c "import secrets; print(secrets.token_urlsafe(24))"`.

## Changelog

- Protocol 1 (2026-11-26): first version.
- Protocol 1 clarifications (2026-11-26, D23): 4409 also covers a second phone in the same room;
  `/ask` answers 409 while an ask is pending. The phone's behaviour does not change.
- Protocol 1 clarifications (2026-11-26, D27): while the question plays the hub ignores fine words
  too, not only help words; `/ask` answers 409 for the whole voice check. No change for the phone.
