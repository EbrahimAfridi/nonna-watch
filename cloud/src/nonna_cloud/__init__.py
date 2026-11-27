"""Nonna Watch, cloud side (Track B).

    defaults  Maria's demo home document and the default settings
    db        connect to Firestore (local emulator or the real project)
    seed      C4: write 14 days of realistic fake history

Nothing here touches audio. It only reads and writes the labels described in
docs/firestore-schema.md.
"""

import sys as _sys

# Windows terminals often print with an old character set that has no "ć", "बचाओ" or "–", and Python
# then crashes on print(). Our scripts print help words and Telegram group names, so switch to UTF-8.
for _stream in (_sys.stdout, _sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")
