"""One background pipeline run at a time, as a separate process.

The run is ``python -m pattom.cli pipeline run`` with the same interpreter, so
it uses the repository's .venv (and its GPU PyTorch) and the same checks as
the command line. Its output lines are kept for the page to show.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MAX_LINES = 2000


@dataclass
class Job:
    command: list[str]
    started: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    lines: list[str] = field(default_factory=list)
    returncode: int | None = None
    dropped: int = 0  # lines trimmed from the front of a long log
    process: subprocess.Popen | None = field(default=None, repr=False)

    @property
    def state(self) -> str:
        if self.returncode is None:
            return "running"
        return "done" if self.returncode == 0 else "failed"

    def as_dict(self, since: int = 0) -> dict:
        """since counts lines from the start of the run, trimmed lines included."""
        return {"state": self.state, "started": self.started, "returncode": self.returncode,
                "command": " ".join(self.command[2:]), "lines": self.lines[max(0, since - self.dropped):],
                "n_lines": self.dropped + len(self.lines)}


class JobRunner:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.job: Job | None = None
        self._lock = threading.Lock()

    def start(self, args: list[str]) -> Job:
        with self._lock:
            if self.job and self.job.state == "running":
                raise RuntimeError("a run is already going; wait for it or stop it")
            cmd = [sys.executable, "-m", "pattom.cli", *args]
            env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.Popen(cmd, cwd=self.repo_root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace", env=env)
            job = Job(cmd, process=proc)
            self.job = job
        threading.Thread(target=self._follow, args=(job,), daemon=True).start()
        return job

    def _follow(self, job: Job) -> None:
        assert job.process and job.process.stdout
        for line in job.process.stdout:
            job.lines.append(line.rstrip("\n"))
            if len(job.lines) > MAX_LINES:
                extra = len(job.lines) - MAX_LINES
                del job.lines[:extra]
                job.dropped += extra
        job.returncode = job.process.wait()

    def stop(self) -> bool:
        job = self.job
        if job and job.state == "running" and job.process:
            job.process.terminate()
            job.lines.append("-- stopped from the app --")
            return True
        return False
