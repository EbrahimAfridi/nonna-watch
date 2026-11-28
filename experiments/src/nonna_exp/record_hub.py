"""Start the hub and save everything it prints to experiments/hub.log, while still showing it.

    uv run python -m nonna_exp.record_hub                         # runs `nonna-hub serve` in hub/
    uv run python -m nonna_exp.record_hub -- serve --languages it,en,hi

Why not PowerShell's Tee-Object: on Windows PowerShell 5.1 it saves UTF-16, which the timing reader
can't read. This writes plain UTF-8, one line at a time, so the trial runner sees each alert at once.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from nonna_exp import EXPERIMENTS, HUB, hub_env_file


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    args = args or ["serve"]
    uv = shutil.which("uv") or os.environ.get("UV", "uv")
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    log_path = EXPERIMENTS / "hub.log"
    print(f"Saving the hub's output to {log_path}  (Ctrl+C stops the hub)")
    with log_path.open("a", encoding="utf-8") as log, subprocess.Popen(
        [uv, "run", *hub_env_file(), "nonna-hub", *args], cwd=HUB, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    ) as hub:
        try:
            for line in hub.stdout:
                print(line, end="")
                log.write(line)
                log.flush()
        except KeyboardInterrupt:
            hub.terminate()


if __name__ == "__main__":
    main()
