# Firestore schema and security rules (S2)

Owner: Track B (cloud). Status: **v3**, follows decisions D22, D24, D26, D27, D29 and D30. Open for comments
from Ebrahim (hub) and A (Android).
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
- **Room ids** are fixed by the listener protocol (D22): `kitchen`, `bathroom`, `bedroom`, `living_room`, `hallway`.
- **Sounds:** `sound` is the YAMNet display name at the peak (`"Water tap, faucet"`), as D30 says. Events also
  carry `category`, one of the hub's 19 household categories (`water`, `cooking`, `door`, `tv_music`, ...; see
  `hub/nonna_hub/categories.py`). The routine learner prefers it, because one habit shows up under several labels.
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
| `helpWords` | map lang → array of string | `{"it": ["aiuto", "aiutami"], "hi": ["बचाओ", "بچاؤ", "bachao"]}` | Defaults are exactly D24. Hindi and Urdu share one list in both scripts. Matching is whole words, ignoring case and punctuation. |
| `fineWords` | map lang → array of string | `{"it": ["sto bene", "bene"], "en": ["fine", "okay"]}` | Answers to the voice check that mean "no alert". Defaults are exactly D27; any negation still means not fine. |
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
| `offlineMinutes` | number [5] | A listener phone silent this long → "listener offline" (checked by the hub, D29). |
| `heartbeatMinutes` | number [5] | How often the hub writes its heartbeat (D7). The cloud calls the hub offline after `offlineMinutes + heartbeatMinutes`. |
| `waterRunningMinutes` | number [20] | Water for this long → gentle notice. |
| `routineMinDays` | number [7] | Days of history needed before routine checks start. |
| `routineMinShare` | number [0.6] | A room/sound counts as "usual" in an hour if it happened on at least this share of days. |
| `routineGraceMinutes` | number [30] | How late a usual activity may be before "routine missing". |

## `homes/{homeId}/devices/{deviceId}`

One document per listener phone, plus one for the hub itself (so the cloud can notice the hub going silent).
`deviceId` is `listener-{room}` for a listener (one per room, D37), and the hub's `HUB_ID` for a hub
(`hub` by default, D39), so a laptop hub and a Cloud Run hub each have their own. The cloud watches every
document with `kind == "hub"`.

| Field | Type | Example | Notes |
|---|---|---|---|
| `kind` | string | `"listener"` | `listener` or `hub`. |
| `room` | string | `"kitchen"` | Empty for the hub. |
| `lastHeartbeat` | Timestamp | | The hub writes every 5 minutes (D7), for itself and for each listener it hears. |
| `online` | bool | `true` | The hub's view, for the family app to show. Listener-offline alerts come from the hub itself (D29). **The `hub` document is the one the cloud watches:** if its `lastHeartbeat` is older than `offlineMinutes + heartbeatMinutes`, C5 reports `hub_offline`, the one failure the hub can't report. |
| `target` | string | `"hub"` | `hub` / `cloud` / `local` (the A10 setting). |
| `battery` | number, optional | `87` | Percentage, if the listener reports it. |

## `homes/{homeId}/events/{eventId}`

The sound history (the family app's timeline). **Decision D30:** one document per sound event, written by the
hub when the event ends. No batching. Alerts are written at once. A demo and our testing use a few hundred
writes a day against the free 20,000.

| Field | Type | Example | Notes |
|---|---|---|---|
| `room` | string | `"kitchen"` | |
| `deviceId` | string | `"listener-kitchen"` | The listener that heard it. |
| `sound` | string | `"Water tap, faucet"` | YAMNet display name at the peak. Never a transcript (D25). |
| `category` | string | `"water"` | The hub's category for it (`hub/nonna_hub/categories.py`). Optional, but please include it: the routine learner uses it. Without it, the learner falls back to `sound`. |
| `confidence` | number | `0.91` | The peak score, 0–1. |
| `start` | Timestamp | | |
| `end` | Timestamp | | `end >= start`. |
| `source` | string | `"hub"` | `hub` / `cloud` / `phone` / `seed` (fake history, C4). |

**Document id:** `{deviceId}_{startEpochMillis}_{category}` when the hub writes it (D38): one sound window
can start several events at once, such as speech over a TV, and the category keeps them apart. A retry from the
offline queue still overwrites the same document instead of duplicating. The fake history (C4) uses
`{deviceId}_{startEpochMillis}`, one event at a time.

**Queries the apps need:**
- Today's timeline: `events.whereGreaterThanOrEqualTo("start", midnight).orderBy("start")`. No index needed.
- One room: add `.whereEqualTo("room", "kitchen")` (index provided in `cloud/firestore.indexes.json`).

Python helpers: `cloud/src/nonna_cloud/events.py` (`event_id`, `category_of`).

## `homes/{homeId}/alerts/{alertId}`

| Field | Type | Example | Notes |
|---|---|---|---|
| `type` | string | `"help_word"` | From the hub (its `rules.py` names, D26): `help_word`, `scream`, `distress`, `thud`, `glass`, `smoke_alarm`, `water_running`, `offline`, `back_online`. From the cloud checks (C5): `routine_missing`, `long_silence`, `hub_offline`. |
| `severity` | string | `"alert"` | `alert` (urgent push) or `notice` (gentle: `water_running`, `back_online`). |
| `room` | string | `"bathroom"` | Empty if not tied to a room. |
| `time` | Timestamp | | When the cause happened, e.g. the shout. |
| `message` | string | `"Maria may need help. Heard 'aiuto' in the bathroom at 14:03."` | Exactly the text the family received. |
| `detail` | map, optional | `{"word": "aiuto"}` or `{"routine": "kitchen__all", "usual": "08:11", "deadline": "09:30"}` | Type-specific extra information. |
| `status` | string | `"sent"` | `sent` → `seen` → `resolved`. The family app moves it forward. |
| `answeredBy` | string or null | `"luca@gmail.com"` | Who pressed seen/resolved. |
| `seenAt`, `resolvedAt` | Timestamp or null | | |
| `voiceCheck` | map or null | `{"asked": true, "result": "no_answer"}` | `result`: `fine` / `help` / `no_answer` / `not_played` / `pending` (the hub's names, D27). Null if no voice check ran. |
| `followUp` | string or null | `"She says she's okay"` | Set when she answers after an instant alert. |
| `source` | string | `"hub"` | `hub` / `cloud` / `phone` / `routine`. |
| `timings` | map, optional | `{"capturedMs": ..., "hubReceivedMs": ..., "aiDoneMs": ..., "alertSentMs": ...}` | Epoch milliseconds at each hop, for Experiment 1. `alertReceivedMs` is added by the family app if it can. |

**Document id:** the hub uses `{type}_{room}_{timeEpochMillis}`. The routine checks (C5) pick ids so each problem
is reported **once**, not every 15 minutes:
- `routine_missing_{room}_{yyyy-mm-dd}`: once per room per day.
- `long_silence_{lastSoundEpochMillis}`: once per silent stretch.
- `hub_offline_hub_{lastHeartbeatEpochMillis}`: once per hub outage.

## `homes/{homeId}/routines/{routineId}`

Written only by the routine learner (C5), once a day, from the previous 14 days. Ids:
- `{room}__{category}`, e.g. `kitchen__water`: one category in one room (for the app to show).
- `{room}__all`, e.g. `kitchen__all`: any activity in that room. The routine-missing check uses these.
- `_activity`: any activity in the house. The long-silence check uses this.

"Activity" ignores the `tv_music` category, which can play with nobody there.

| Field | Type | Example | Notes |
|---|---|---|---|
| `room` | string | `"kitchen"` | `"*"` for `_activity`. |
| `category` | string | `"water"` | `"*"` for `{room}__all` and `_activity`. |
| `hourShare` | array of 24 numbers | `[0, 0, ..., 0.93, 0.86, ...]` | For each local hour: the share of days with at least one event in that hour (0–1). |
| `usualFirstMinute` | number or null | `485` | Typical (median) first time of day, as minutes after local midnight (485 = 08:05). Null if it doesn't happen on at least `routineMinShare` of days. |
| `latestFirstMinute` | number or null | `530` | How late the first time gets on a normal late day (90th percentile). "Routine missing" fires at `latestFirstMinute + routineGraceMinutes`. |
| `daysObserved` | number | `14` | |
| `updatedAt` | Timestamp | | |
| `learnedFor` | string | `"2026-11-27"` | Local date this was learned for. Lets the hub and a Cloud Function share one learning run per day. |

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
   cannot edit the message or invent an alert, except phone-only mode, which may create events and
   the alerts YAMNet alone can detect (`scream`, `distress`, `thud`, `glass`, `smoke_alarm`) with `source == "phone"`.
5. What an app writes must use one of the five room ids (`kitchen`, `bathroom`, `bedroom`, `living_room`,
   `hallway`, D22); a phone-only listener writes only its own `devices/listener-{room}`, so an app can never
   create or overwrite a hub's document.
6. Routines are read-only for everyone except the service account.
7. `users/{uid}` is readable and writable only by that same user.
8. Everything else is denied.
