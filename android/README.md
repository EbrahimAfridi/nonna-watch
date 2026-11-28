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

Until A6, the phone does not play the "Are you okay?" question. The hub then counts the check as
failed and alerts the family after 20 s, which is the safe side.

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
