# Firestore schema and security rules (S2)

Owner: Track B (cloud). Status: **draft v1**, open for comments from Ebrahim (hub) and A (Android).
Any change to a field name or type after it is agreed goes into `DECISIONS.md` first.

The rules file that enforces this is [`cloud/firestore.rules`](../cloud/firestore.rules); its tests
are in [`cloud/tests/rules/`](../cloud/tests/rules/).

## Who writes what

| Writer | How it authenticates | Rules apply? |
|---|---|---|
| Hub (laptop, and its Cloud Run copy) | Service-account key via `firebase-admin` | **No.** The Admin SDK bypasses rules, so the hub must follow this document by itself. |
| Routine checks (Cloud Function or hub loop, C5) | Service account | No |
| Seed script (C4) | Service account, or the emulator | No |
| Family app | Google Sign-In (Firebase Auth) | **Yes** |
| Listener in phone-only mode (A10) | Google Sign-In with a family member's account | **Yes** |

## Conventions

- **Times are Firestore `Timestamp`s**, not ISO strings. They sort and filter correctly, and every SDK
  converts them automatically: Python `datetime` (timezone-aware), Kotlin `com.google.firebase.Timestamp`.
  The ISO string in CONTEXT.md is only how an event looks when printed.
- **Room ids** are lowercase snake case: `kitchen`, `bathroom`, `bedroom`, `living_room`.
- **Sound names** are YAMNet's display names, exactly as YAMNet prints them, for example `"Water tap, faucet"`,
  `"Thump, thud"`, `"Television"`.
- **Languages** are ISO 639-1 codes: `it`, `en`, `hi`, `ur`, `bs`.
- **Emails are stored lowercase.** Security rules compare them to the signed-in user's email.
- **The hub picks its own document ids for events and alerts**, so retrying from the offline queue
  overwrites the document instead of adding a duplicate (see each collection below).

## `homes/{homeId}`

One document per person being looked after. `homeId` is short and readable, for example `maria`.

| Field | Type | Example | Notes |
|---|---|---|---|
| `name` | string | `"Maria"` | Used in alert texts: "Maria may need help". |
| `timezone` | string | `"Europe/Rome"` | IANA name. Routine hours are in this zone. |
| `languages` | array of string | `["it", "en"]` | Whisper runs once per language (D5). |
| `helpWords` | map lang → array of string | `{"it": ["aiuto", "aiutami"], "hi": ["bachao", "बचाओ", "madad"]}` | Include script variants and accent-free spellings (`upomoc`). Matching is lowercase. |
| `fineWords` | map lang → array of string | `{"it": ["sto bene", "tutto bene"], "en": ["i'm fine", "i am fine", "i'm okay"]}` | Answers to the voice check that mean "no alert" (E7). |
| `familyContacts` | array of map | `[{"name": "Luca", "phone": "+39...", "role": "son"}]` | Used by the call buttons in the FCM notification. `role` is free text. |
| `memberEmails` | array of string | `["luca@gmail.com"]` | **Who may see this home.** Security rules use this field. Lowercase. |
| `telegramChatId` | string | `"-1001234567890"` | The family group. The bot token is a secret and is **not** stored here. |
| `mode` | string | `"normal"` | `normal` / `visitor` / `away`. In `away` mode the routine and silence checks are off; in `visitor` mode they are relaxed. |
| `settings` | map | see below | Every threshold is a setting (requirements: "Every time and threshold is a setting"). |
| `checkInClip` | map, optional | `{"lang": "it", "mime": "audio/mp4", "base64": "..."}` or `{"storagePath": "..."}` | The recorded "Are you okay?" message. Base64 under Path B (keep it under ~700 KB); a Cloud Storage path under Path A. |

### `settings` map (defaults in brackets)

| Key | Type | Meaning |
|---|---|---|
| `minConfidence` | number [0.3] | The hub drops YAMNet labels below this. |
| `thudSilenceSeconds` | number [10] | Silence after a thud before the voice check starts. |
| `voiceCheckSeconds` | number [30] | How long to wait for an answer. |
| `longSilenceMinutes` | number [45] | No sound for this long at an active hour → voice check. |
| `offlineMinutes` | number [5] | No heartbeat for this long → "listener offline". |
| `waterRunningMinutes` | number [20] | Water for this long → gentle notice. |
| `routineMinDays` | number [7] | Days of history needed before routine checks start. |
| `routineMinShare` | number [0.6] | A room/sound counts as "usual" in an hour if it happened on at least this share of days. |
| `routineGraceMinutes` | number [30] | How late a usual activity may be before "routine missing". |

## `homes/{homeId}/devices/{deviceId}`

One document per listener phone, plus one for the hub itself (so the cloud can notice the hub going silent).
`deviceId` is chosen by the device: for example `listener-kitchen-cmf` or `hub`.

| Field | Type | Example | Notes |
|---|---|---|---|
| `kind` | string | `"listener"` | `listener` or `hub`. |
| `room` | string | `"kitchen"` | Empty for the hub. |
| `lastHeartbeat` | Timestamp | | The hub writes every 5 minutes (D7) and immediately when a listener connects or disconnects. |
| `online` | bool | `true` | The hub's view. The offline check (C5) uses `lastHeartbeat`, not this flag, because a dead hub can't set it to false. |
| `target` | string | `"hub"` | `hub` / `cloud` / `local` (the A10 setting). |
| `battery` | number, optional | `87` | Percentage, if the listener reports it. |

## `homes/{homeId}/events/{eventId}`

One document per sound episode: consecutive identical labels merged into one (D7).

| Field | Type | Example | Notes |
|---|---|---|---|
| `room` | string | `"kitchen"` | |
| `deviceId` | string | `"listener-kitchen-cmf"` | |
| `sound` | string | `"Water tap, faucet"` | YAMNet display name. Never a transcript. |
| `confidence` | number | `0.91` | The highest score in the episode, 0–1. |
| `start` | Timestamp | | |
| `end` | Timestamp | | `end >= start`. |
| `source` | string | `"hub"` | `hub` / `cloud` / `phone` / `seed` (fake history, C4). |

**Document id:** `{deviceId}_{startEpochMillis}`. One device can't start two episodes in the same millisecond,
so retries from the offline queue overwrite instead of duplicating.

**Queries the apps need** (these work without extra indexes):
- Today's timeline: `where("start", ">=", midnight).orderBy("start")`.
- One room: `where("room", "==", "kitchen").where("start", ">=", t)`. Firestore may ask for a composite
  index the first time; the error message contains a link that creates it.

## `homes/{homeId}/alerts/{alertId}`

| Field | Type | Example | Notes |
|---|---|---|---|
| `type` | string | `"help_word"` | One of: `help_word`, `scream`, `crying`, `thud_silence`, `glass`, `long_silence`, `routine_missing`, `listener_offline`, `hub_offline`, `smoke_alarm`, `water_running`. |
| `severity` | string | `"alert"` | `alert` (urgent push) or `notice` (gentle, e.g. water running). |
| `room` | string | `"bathroom"` | Empty if not tied to a room. |
| `time` | Timestamp | | When the cause happened, e.g. the shout. |
| `message` | string | `"Maria may need help. Heard 'aiuto' in the bathroom at 14:03."` | Exactly the text the family received. |
| `detail` | map, optional | `{"word": "aiuto", "lang": "it"}` or `{"routine": "kitchen__water_tap_faucet", "expectedBy": "11:00"}` | Type-specific extra information. |
| `status` | string | `"sent"` | `sent` → `seen` → `resolved`. The family app moves it forward. |
| `answeredBy` | string or null | `"luca@gmail.com"` | Who pressed seen/resolved. |
| `seenAt`, `resolvedAt` | Timestamp or null | | |
| `voiceCheck` | map or null | `{"asked": true, "result": "no_answer"}` | `result`: `fine` / `help` / `no_answer` / `pending`. Null if no voice check ran. |
| `followUp` | string or null | `"She says she's okay"` | Set when she answers after an instant alert. |
| `source` | string | `"hub"` | `hub` / `cloud` / `phone` / `routine`. |
| `timings` | map, optional | `{"capturedMs": ..., "hubReceivedMs": ..., "aiDoneMs": ..., "alertSentMs": ...}` | Epoch milliseconds at each hop, for Experiment 1. `alertReceivedMs` is added by the family app if it can. |

**Document id:** the hub uses `{type}_{room}_{timeEpochMillis}`; the routine checks use
`{type}_{room or key}_{yyyy-mm-dd}` so the same missing routine is reported **once per day**, not every 15 minutes.

## `homes/{homeId}/routines/{routineId}`

Written only by the routine learner (C5). `routineId` is `{room}__{sound slug}`, for example
`kitchen__water_tap_faucet`. The special id `_activity` holds whole-house activity across all rooms,
which is what the long-silence check uses.

| Field | Type | Example | Notes |
|---|---|---|---|
| `room` | string | `"kitchen"` | `"*"` for `_activity`. |
| `sound` | string | `"Water tap, faucet"` | `"*"` for `_activity`. |
| `hourShare` | array of 24 numbers | `[0, 0, ..., 0.93, 0.86, ...]` | For each local hour: the share of days with at least one event in that hour (0–1). |
| `usualFirstMinute` | number or null | `485` | Typical (median) first time of day, as minutes after local midnight (485 = 08:05). Null if it doesn't happen most days. |
| `daysObserved` | number | `14` | |
| `updatedAt` | Timestamp | | |

## `users/{uid}`

One document per signed-in family member, written by the family app itself.

| Field | Type | Notes |
|---|---|---|
| `email` | string | Lowercase. |
| `displayName` | string | |
| `fcmTokens` | array of string | FCM registration tokens of this person's phones. Alerts are pushed to them. |
| `homes` | array of string | Home ids, for convenience. Access is still decided by `homes/{id}.memberEmails`. |

## Security rules, in plain words

1. You must be signed in with a **verified email** (Google Sign-In always gives one).
2. You can read a home, and everything under it, only if your email is in that home's `memberEmails`.
3. Members can change a home's settings, languages, help words, contacts and mode. They **cannot** create
   or delete homes, and cannot remove themselves from `memberEmails` (so nobody locks themselves out by accident).
4. Members can **only move alerts forward**: change `status`, `answeredBy`, `seenAt`, `resolvedAt`. They
   cannot edit the message or invent an alert, except phone-only mode, which may create alerts and events
   with `source == "phone"`.
5. Routines are read-only for everyone except the service account.
6. `users/{uid}` is readable and writable only by that same user.
7. Everything else is denied.
