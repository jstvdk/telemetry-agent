"""A camera-in-a-box container, driven through `docker exec`. Every command is logged.

The container clock is the reference for all label timestamps: the camera writes its logs and
monitoring with that clock, so labels must use it too (the host clock can differ slightly).
"""

import json
import shlex
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

UNIT_PREFIX = "sstcam-"
USER = "sstcam"


class BoxError(RuntimeError):
    pass


@dataclass
class Box:
    name: str
    dry_run: bool = False
    log_file: TextIO | None = None
    runner: Callable[[list[str], str | None], subprocess.CompletedProcess[str]] | None = None
    _t_dry: float = field(default=0.0, repr=False)

    # --- process -----------------------------------------------------------------------------
    def _run(self, argv: list[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        if self.runner is not None:
            return self.runner(argv, stdin)
        return subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=120)

    def _log(self, **rec: Any) -> None:
        if self.log_file is not None:
            self.log_file.write(json.dumps(rec) + "\n")
            self.log_file.flush()

    def sh(
        self,
        cmd: str,
        *,
        root: bool = False,
        check: bool = True,
        stdin: str | None = None,
        action: str = "",
    ) -> str:
        """Run a shell command in the box: as the camera user with its session env (default),
        or as root."""
        inner = ["bash", "-c", cmd] if root else ["ucam", "bash", "-c", cmd]
        argv = ["docker", "exec", *(["-i"] if stdin is not None else []), self.name, *inner]
        t = self.now() if not self.dry_run else self._t_dry
        if self.dry_run:
            self._log(t=t, action=action, cmd=cmd, root=root, dry_run=True)
            return ""
        p = self._run(argv, stdin)
        self._log(
            t=t,
            action=action,
            cmd=cmd,
            root=root,
            rc=p.returncode,
            out=(p.stdout + p.stderr)[-500:],
        )
        if check and p.returncode != 0:
            raise BoxError(
                f"{self.name}: `{cmd}` failed ({p.returncode}): {p.stderr.strip()[-300:]}"
            )
        return p.stdout

    def now(self) -> float:
        """Container clock, seconds since epoch."""
        if self.dry_run:
            return self._t_dry
        p = self._run(["docker", "exec", self.name, "date", "+%s.%N"], None)
        if p.returncode != 0:
            raise BoxError(f"{self.name}: cannot read clock: {p.stderr.strip()}")
        return float(p.stdout.strip())

    def sleep(self, seconds: float) -> None:
        if self.dry_run:
            self._t_dry += seconds
        else:
            time.sleep(max(0.0, seconds))

    # --- helpers -----------------------------------------------------------------------------
    def systemctl(self, *args: str, check: bool = True, action: str = "") -> str:
        return self.sh(
            "systemctl --user " + " ".join(shlex.quote(a) for a in args), check=check, action=action
        )

    def unit(self, short: str) -> str:
        return short if short.startswith(UNIT_PREFIX) else f"{UNIT_PREFIX}{short}.service"

    def unit_props(self, short: str, *props: str) -> dict[str, str]:
        out = self.systemctl("show", self.unit(short), *(f"-p{p}" for p in props), action="probe")
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    def write_file(self, path: str, text: str, action: str = "") -> None:
        self.sh(
            f"cat > {shlex.quote(path)}.tmp && mv {shlex.quote(path)}.tmp {shlex.quote(path)}",
            stdin=text,
            action=action,
        )

    def camera(self, *args: str, action: str = "") -> str:
        return self.sh("sstcam " + " ".join(shlex.quote(a) for a in args), action=action)

    def failed_units(self) -> list[str]:
        out = self.systemctl(
            "list-units",
            "sstcam*",
            "--failed",
            "--plain",
            "--no-legend",
            check=False,
            action="probe",
        )
        return [ln.split()[0] for ln in out.splitlines() if ln.strip()]


def open_log(path: Path) -> TextIO:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.open("a")
