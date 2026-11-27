# Android

The Kotlin apps of Nonna Watch, in one Gradle project:

- `:listener`: the app on the phones around the house. It records the room; from A3 it streams the
  audio to the hub (`docs/api-contract.md`).
- `:family`: the family's app (from A7).
- `:core`: code both apps share, such as the room ids.

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

Pick the room, tap **Start listening** and allow the microphone (and notifications, on Android 13+).
A notification "Listening · Kitchen" appears and stays while the phone listens; it is Android's
rule that a microphone in the background is always visible. The status line counts the seconds
recorded and shows how loud the last second was (0 to 100 %).

- Audio is recorded as the hub expects it: 16 kHz, mono, 16-bit, in one-second chunks, with the
  `VOICE_RECOGNITION` source so the phone does not boost a quiet room.
- It is checked and thrown away. Nothing is saved or sent yet; A3 sends it to the hub.
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

### On the emulator

The emulator's microphone hears nothing until you turn it on, and it is off again after every
emulator start: in the emulator's **⋯** (Extended controls) → **Microphone**, turn on **Virtual
microphone uses host audio input**. On Windows, also allow it under Settings → Privacy & security
→ Microphone → **Let desktop apps access your microphone**.

The emulator is for development only. For the demo, never run it on the hub laptop (D12); use real
phones.
