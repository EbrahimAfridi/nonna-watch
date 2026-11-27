// Security-rules tests (C3). They run against the local Firestore emulator, never a real project.
//
//   cd cloud
//   npm run test:rules
//
// Each test sets up some data with the rules switched off (like the hub or the seed script,
// which use the Admin SDK), then acts as a particular signed-in person and checks that the
// rules allow (assertSucceeds) or block (assertFails) what that person tries to do.

import { readFileSync } from 'node:fs';
import { after, before, beforeEach, describe, test } from 'node:test';
import {
  assertFails,
  assertSucceeds,
  initializeTestEnvironment,
} from '@firebase/rules-unit-testing';
import {
  collection, deleteDoc, doc, getDoc, getDocs, query, setDoc, setLogLevel, Timestamp, updateDoc, where,
} from 'firebase/firestore';

const LUCA = 'luca@gmail.com';     // family member of Maria's home
const EVE = 'eve@gmail.com';       // signed in, but not family

// Denied writes are what many tests expect; don't print each one as a warning.
setLogLevel('silent');

let env;

before(async () => {
  env = await initializeTestEnvironment({
    projectId: 'demo-nonna-watch',
    firestore: {
      rules: readFileSync(new URL('../../firestore.rules', import.meta.url), 'utf8'),
      host: '127.0.0.1',
      port: 8080,
    },
  });
});

after(async () => {
  await env.cleanup();
});

// Fresh data before every test, written with rules disabled (= service account).
beforeEach(async () => {
  await env.clearFirestore();
  await env.withSecurityRulesDisabled(async (ctx) => {
    const db = ctx.firestore();
    await setDoc(doc(db, 'homes/maria'), {
      name: 'Maria',
      timezone: 'Europe/Rome',
      languages: ['it', 'en'],
      helpWords: { it: ['aiuto'], en: ['help'] },
      fineWords: { it: ['sto bene'], en: ["i'm fine"] },
      familyContacts: [{ name: 'Luca', phone: '+390000000', role: 'son' }],
      memberEmails: [LUCA],
      telegramChatId: '-100123',
      mode: 'normal',
      settings: { longSilenceMinutes: 45 },
    });
    await setDoc(doc(db, 'homes/maria/devices/hub'), {
      kind: 'hub', room: '', lastHeartbeat: Timestamp.now(), online: true,
    });
    const t = Timestamp.now();
    await setDoc(doc(db, 'homes/maria/timeline/kitchen_1'), {
      room: 'kitchen', deviceId: 'listener-kitchen', source: 'hub', flushedAt: t, start: t, end: t,
      events: [{ category: 'water', label: 'Water tap, faucet', confidence: 0.9, start: t, end: t }],
    });
    await setDoc(doc(db, 'homes/maria/alerts/a1'), {
      type: 'help_word', severity: 'alert', room: 'bathroom', time: Timestamp.now(),
      message: "Maria may need help. Heard 'aiuto' in the bathroom.", status: 'sent',
      answeredBy: null, seenAt: null, resolvedAt: null, source: 'hub',
    });
    await setDoc(doc(db, 'homes/maria/routines/kitchen__water_tap_faucet'), {
      room: 'kitchen', sound: 'Water tap, faucet', hourShare: Array(24).fill(0),
    });
  });
});

// A signed-in person. Google Sign-In always gives a verified email.
function as(email, uid = email.split('@')[0], verified = true) {
  return env.authenticatedContext(uid, { email, email_verified: verified }).firestore();
}

const luca = () => as(LUCA);
const eve = () => as(EVE);
const nobody = () => env.unauthenticatedContext().firestore();

// A D20 timeline chunk, as phone-only mode would write it.
function phoneChunk(extra = {}) {
  const t = Timestamp.now();
  return {
    room: 'kitchen', deviceId: 'listener-kitchen', source: 'phone', flushedAt: t, start: t, end: t,
    events: [{ category: 'thud', label: 'Thump, thud', confidence: 0.8, start: t, end: t }],
    ...extra,
  };
}

function phoneAlert(extra = {}) {
  return {
    type: 'scream', severity: 'alert', room: 'kitchen', time: Timestamp.now(),
    message: 'A scream was heard in the kitchen.', status: 'sent', source: 'phone', ...extra,
  };
}

describe('homes', () => {
  test('a family member can read their home', async () => {
    await assertSucceeds(getDoc(doc(luca(), 'homes/maria')));
  });

  test('the email check ignores upper/lower case', async () => {
    await assertSucceeds(getDoc(doc(as('Luca@Gmail.com'), 'homes/maria')));
  });

  test('a stranger cannot read the home (M4: "a second Google account cannot read")', async () => {
    await assertFails(getDoc(doc(eve(), 'homes/maria')));
  });

  test('someone not signed in cannot read the home', async () => {
    await assertFails(getDoc(doc(nobody(), 'homes/maria')));
  });

  test('an unverified email is not trusted', async () => {
    await assertFails(getDoc(doc(as(LUCA, 'fake', false), 'homes/maria')));
  });

  test('the "my homes" query works when filtered by my email', async () => {
    const q = query(collection(luca(), 'homes'), where('memberEmails', 'array-contains', LUCA));
    const snap = await assertSucceeds(getDocs(q));
    if (snap.size !== 1) throw new Error(`expected 1 home, got ${snap.size}`);
  });

  test('listing all homes without the filter is blocked', async () => {
    await assertFails(getDocs(collection(luca(), 'homes')));
  });

  test('a member can change settings and help words', async () => {
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria'), {
      'settings.longSilenceMinutes': 60,
      helpWords: { it: ['aiuto', 'aiutami'], en: ['help'] },
    }));
  });

  test('a member can add another family member', async () => {
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria'), {
      memberEmails: [LUCA, 'sara@gmail.com'],
    }));
  });

  test('a member cannot remove themselves (no accidental lock-out)', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria'), { memberEmails: ['sara@gmail.com'] }));
  });

  test('a member cannot add unknown fields', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria'), { isAdmin: true }));
  });

  test('mode must be normal, visitor or away', async () => {
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria'), { mode: 'away' }));
    await assertFails(updateDoc(doc(luca(), 'homes/maria'), { mode: 'party' }));
  });

  test('a stranger cannot change settings', async () => {
    await assertFails(updateDoc(doc(eve(), 'homes/maria'), { 'settings.longSilenceMinutes': 1 }));
  });

  test('nobody can create or delete homes from an app', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/new'), { name: 'x', memberEmails: [LUCA] }));
    await assertFails(deleteDoc(doc(luca(), 'homes/maria')));
  });
});

describe('timeline (D20 chunks)', () => {
  test('a member can read the timeline', async () => {
    await assertSucceeds(getDocs(collection(luca(), 'homes/maria/timeline')));
  });

  test('a stranger cannot read the timeline', async () => {
    await assertFails(getDocs(collection(eve(), 'homes/maria/timeline')));
  });

  test('phone-only mode can add a chunk', async () => {
    await assertSucceeds(setDoc(doc(luca(), 'homes/maria/timeline/p1'), phoneChunk()));
  });

  test('an app cannot pretend to be the hub', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/timeline/p1'), phoneChunk({ source: 'hub' })));
  });

  test('a chunk cannot end before it starts', async () => {
    const start = Timestamp.fromMillis(Date.now());
    const end = Timestamp.fromMillis(Date.now() - 60_000);
    await assertFails(setDoc(doc(luca(), 'homes/maria/timeline/p1'), phoneChunk({ start, end })));
  });

  test('an empty chunk is refused', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/timeline/p1'), phoneChunk({ events: [] })));
  });

  test('unknown fields are refused', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/timeline/p1'), phoneChunk({ audio: 'x' })));
  });

  test('a stranger cannot add to the timeline', async () => {
    await assertFails(setDoc(doc(eve(), 'homes/maria/timeline/p1'), phoneChunk()));
  });

  test('nobody can edit or delete history', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria/timeline/kitchen_1'), { room: 'bathroom' }));
    await assertFails(deleteDoc(doc(luca(), 'homes/maria/timeline/kitchen_1')));
  });
});

describe('alerts', () => {
  test('a member can read alerts', async () => {
    await assertSucceeds(getDoc(doc(luca(), 'homes/maria/alerts/a1')));
  });

  test('a stranger cannot read alerts', async () => {
    await assertFails(getDoc(doc(eve(), 'homes/maria/alerts/a1')));
  });

  test('a member can mark an alert seen, then resolved', async () => {
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'seen', answeredBy: LUCA, seenAt: Timestamp.now(),
    }));
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'resolved', answeredBy: LUCA, resolvedAt: Timestamp.now(),
    }));
  });

  test('status cannot go backwards', async () => {
    await assertSucceeds(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'resolved', answeredBy: LUCA,
    }));
    await assertFails(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'sent', answeredBy: LUCA,
    }));
  });

  test('status must be a known value', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'ignored', answeredBy: LUCA,
    }));
  });

  test('you can only sign an alert with your own email', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      status: 'seen', answeredBy: 'someone-else@gmail.com',
    }));
  });

  test('the alert message cannot be edited', async () => {
    await assertFails(updateDoc(doc(luca(), 'homes/maria/alerts/a1'), {
      message: 'nothing happened', answeredBy: LUCA, status: 'seen',
    }));
  });

  test('phone-only mode can raise a scream alert', async () => {
    await assertSucceeds(setDoc(doc(luca(), 'homes/maria/alerts/p1'), phoneAlert()));
  });

  test('phone-only mode cannot raise a help-word alert (no Whisper on the phone, D4)', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/alerts/p1'), phoneAlert({ type: 'help_word' })));
  });

  test('a new alert must start as "sent"', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/alerts/p1'), phoneAlert({ status: 'resolved' })));
  });

  test('a stranger cannot raise alerts', async () => {
    await assertFails(setDoc(doc(eve(), 'homes/maria/alerts/p1'), phoneAlert()));
  });

  test('nobody can delete an alert', async () => {
    await assertFails(deleteDoc(doc(luca(), 'homes/maria/alerts/a1')));
  });
});

describe('devices', () => {
  const beat = () => ({ kind: 'listener', room: 'kitchen', lastHeartbeat: Timestamp.now(), online: true });

  test('a member can see which listeners are online', async () => {
    await assertSucceeds(getDocs(collection(luca(), 'homes/maria/devices')));
  });

  test('phone-only listener can write its heartbeat', async () => {
    await assertSucceeds(setDoc(doc(luca(), 'homes/maria/devices/listener-kitchen'), beat()));
    await assertSucceeds(setDoc(doc(luca(), 'homes/maria/devices/listener-kitchen'), beat()));
  });

  test("an app cannot overwrite the hub's heartbeat", async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/devices/hub'), beat()));
  });

  test('a stranger cannot write heartbeats', async () => {
    await assertFails(setDoc(doc(eve(), 'homes/maria/devices/listener-kitchen'), beat()));
  });
});

describe('routines', () => {
  test('a member can read routines', async () => {
    await assertSucceeds(getDocs(collection(luca(), 'homes/maria/routines')));
  });

  test('nobody can write routines from an app', async () => {
    await assertFails(setDoc(doc(luca(), 'homes/maria/routines/x'), { room: 'kitchen' }));
  });
});

describe('users', () => {
  test('I can write and read my own user document (FCM tokens)', async () => {
    const db = as(LUCA, 'luca-uid');
    await assertSucceeds(setDoc(doc(db, 'users/luca-uid'), { email: LUCA, fcmTokens: ['t1'] }));
    await assertSucceeds(getDoc(doc(db, 'users/luca-uid')));
  });

  test("I cannot read someone else's user document", async () => {
    await assertFails(getDoc(doc(as(EVE, 'eve-uid'), 'users/luca-uid')));
  });
});
