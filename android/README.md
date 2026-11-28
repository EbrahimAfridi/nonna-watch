# Android

The Kotlin apps of Nonna Watch, in one Gradle project:

- `:listener`: the app on the phones around the house. It records the room and streams the audio
  to the hub (`docs/api-contract.md`).
- `:family`: the family's app (from A7).
- `:core`: code both apps share: the room ids and the protocol (messages and audio frames).

## Setup (once)

1. Install Android Studio. It brings Java, the Android SDK and the emulator.
2. In Android Studio, open the `android` folder (not the repository root). It writes
   `local.properties` with the SDK path. That file is gitignored; never commit it.

## Build and test

In Android Studio, pick the `listener` run configuration and press Run. From a terminal in
`android/` (Windows PowerShell):

```
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat testDebugUnitTest assembleDebug
```

On a Mac: `JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew testDebugUnitTest assembleDebug`.

## Listener: listening (A2)

Fill in the hub settings (next section), pick the room, tap **Start listening** and allow the
microphone (and notifications, on Android 13+). A notification "Listening · Kitchen" appears and
stays while the phone listens; it is Android's rule that a microphone in the background is always
visible. The status line counts the seconds recorded and shows how loud the last second was (0 to
100 %).

- Audio is recorded as the hub expects it: 16 kHz, mono, 16-bit, in one-second chunks, with the
  `VOICE_RECOGNITION` source so the phone does not boost a quiet room.
- Each second goes to the hub and is then thrown away. Nothing is saved on the phone.
- Listening goes on with the screen off and the app closed: the service holds a partial WakeLock
  and a Wi-Fi lock.
- **Stop listening** turns the microphone off; Android's microphone indicator disappears.
- The room cannot change while listening: the hub learns it once, when the phone connects.
- If Android kills the service, it does not come back by itself, because Android gives the
  microphone only to an app started from the screen. Open the app and tap Start again; the same
  after a reboot.

### Set battery to Unrestricted (once on every listener phone)

Phone makers stop apps that run in the background to save battery, and the listener is exactly
such an app. On each listener phone:

1. Long-press the Nonna Listener icon → **App info** (or Settings → Apps → Nonna Listener).
2. **Battery** (on some phones "App battery usage") → **Unrestricted**.

Some makers add their own limits on top. Usually:

- **Samsung:** also Settings → Battery → Background usage limits → **Never sleeping apps** → add
  Nonna Listener.
- **Xiaomi, Redmi, POCO:** also turn on **Autostart** for the app, set its battery saver to **No
  restrictions**, and lock the app in the recent-apps screen (padlock).

For other makers and newer menus, see https://dontkillmyapp.com. Do this before the one-hour
screen-off test (milestone M2) and before the demo.

## Listener: connecting to the hub (A3)

The phone keeps one WebSocket open to the hub, as `docs/api-contract.md` describes: it says
hello, waits for the hub's welcome, then sends one audio frame per second and a heartbeat (battery,
charging, paused) every 30 s.

Settings, filled in once per phone and kept on it:

- **Hub address**: the hub prints it when it starts, for example
  `ws://192.168.43.12:8000/ws/listener`. Hotspot addresses change between sessions, so check it
  each time.
- **Token**: `HUB_TOKEN` from the hub's `hub/.env` (see `hub/README.md`). It is kept only in the
  app's private storage on the phone and never written to the log.
- **Room**: one listener per room.

The second status line shows the link to the hub:

- `connected to <hub> · 40 s sent`: audio is reaching the hub.
- `hub not reachable. Trying again in 8 s`: the phone tries again by itself after 1, 2, 4, 8 and
  16 s, then every 30 s. Audio heard meanwhile is dropped, not kept for later. After Wi-Fi comes
  back it reconnects within 30 s.
- The phone stops for good, and the first line says why, when the hub refuses the token, when
  another phone takes over the same room, or when the hub rejects the hello. Fix the setting and
  tap Start again.

**Pause** turns the microphone off; the link and the heartbeats stay, so the hub shows the room
as paused, not offline. The family can pause and resume from the hub too.

### Connecting the emulator to a hub on the same PC

Start the hub on the PC (`hub/README.md`, "Let phones connect"), then use the address
`ws://10.0.2.2:8000/ws/listener` in the app: `10.0.2.2` is the emulator's name for the PC it runs
on. The hub prints `kitchen connected: Google sdk_gphone…` and then the sounds it hears. A real
phone instead uses the address the hub prints, on the same Wi-Fi or hotspot.

### On the emulator

The emulator's microphone hears nothing until you turn it on, and it is off again after every
emulator start: in the emulator's **⋯** (Extended controls) → **Microphone**, turn on **Virtual
microphone uses host audio input**. On Windows, also allow it under Settings → Privacy & security
→ Microphone → **Let desktop apps access your microphone**.

The emulator is for development only. For the demo, never run it on the hub laptop (D12); use real
phones.

## Listener: the check-in question (A6)

When the hub wants to know if she is all right (for example a thud and then 10 s of silence), it
sends `ask`. The phone then:

1. Plays the family's recorded question if the hub has sent one, otherwise speaks the hub's text
   ("Stai bene?") in the home's language with the phone's text-to-speech.
2. Plays it as an **alarm**, so it is heard when the phone is on silent or vibrate.
3. Keeps streaming the microphone meanwhile.
4. Tells the hub when the question ended (`ask_played`). The hub ignores the question itself and
   listens for 30 s: "sto bene" means no alert; "aiuto", or no answer, alerts the family.

The third status line shows the last question: `Check-in question: played at 14:02:31`, or
`not played, …` and why. When it cannot play, the phone says so at once and the hub alerts the
family straight away instead of waiting 20 s.

| Sent to the hub | Meaning | Fix |
|---|---|---|
| `no_audio_output` | The alarm volume is at zero, or Do Not Disturb is on total silence. | Turn the alarm volume up. |
| `no_voice_for_language` | Text-to-speech has no voice for the home's language. | Settings → System → Languages → Text-to-speech output → the engine's settings → Install voice data. Menu names differ by maker. |
| `no_text_to_speech` | The phone has no text-to-speech. | Install "Speech Services by Google" from the Play Store. |
| `text_to_speech_failed`, `playback_failed` | It started but did not work. | Try the Test button; restart the phone. |
| `timeout` | It had not finished after 20 s, when the hub stops waiting. | Try the Test button. |
| `busy` | The hub asked again while a question was playing. The hub promises not to. | Tell the hub developer. |

### Test the question (no hub needed)

Under **Check-in question**, pick a language and tap **Test the question**. The phone speaks it as
an alarm and shows `played, 1.8 s` or why it could not. It works without a hub and while not
listening. Do this on every listener phone before the demo, especially for Urdu and Bosnian,
which some phones have no voice for (`docs/api-contract.md`). The test always uses the phone's
voice, never the family's recording.

### Test with the hub

1. Start listening with the hub's address and token.
2. On the hub's `/docs` page (`http://<hub address>:8000/docs`), click Authorize, enter the token,
   and run `POST /ask` with your room.
3. The phone speaks the question. The hub prints `asked: Stai bene?`, then `check-in question
   played`, then the result of the check.
4. Stay silent: the check ends with no answer. Say "sto bene": the check ends with fine.

### The family's recording

The hub sends `checkin_clip` after the welcome when the family has recorded a question, and again
when it changes. The phone keeps it in its private storage, replaces it with the next one, and
deletes it when the family deletes theirs (`clip_id: null`). That recording is the family's
message, not sound from the home, which is never saved. Until the family app can record one (A8)
and the hub passes it on (E8), the phone always speaks the text.

### Why the phone's voice goes through a file

The phone's voice is written to a short file in the app's cache and played from the app, then the
file is deleted. Text-to-speech normally plays its sound inside the voice app, and Android 17 may
silence a background app's sound unless it comes from a foreground service the person started on
screen. The listening service is one (the Start button), so sound played from the app itself is
allowed.
