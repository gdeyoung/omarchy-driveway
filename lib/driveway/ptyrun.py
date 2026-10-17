"""PTY-driven subprocess runner for driveway.

Why a PTY: `gio mount` and `rclone authorize` interactively prompt on the
terminal, and interactive prompts usually require a TTY.  Driving them under
a pty lets us feed credentials/token answers programmatically WITHOUT ever
placing secrets in argv (visible to any `ps` on the machine).

Never log the captured output of an authorize run — it contains tokens.
"""

from __future__ import annotations

import os
import pty
import re
import select
import subprocess
import sys
import time

__all__ = ["PtyError", "Expect", "run_expect", "run_capture", "pipe_expect"]


class PtyError(RuntimeError):
    pass


class Expect:
    """One prompt pattern with the text to answer it."""

    __slots__ = ("pattern", "answer", "optional")

    def __init__(self, pattern: str, answer: str, optional: bool = False):
        self.pattern = re.compile(pattern.encode(), re.IGNORECASE)
        self.answer = answer
        self.optional = optional


def pipe_expect(cmd: list[str],
                expects: list[Expect],
                timeout: float = 60.0,
                done_pattern: str = r"$^",
                max_answers: int = 3,
                eof_after: float | None = None) -> tuple[bytes, int]:
    """Pipe-mode expect: gio prompts reliably on pipes (it stayed silent
    under a pty), so drive its User/Domain/Password prompts via stdin.

    Same contract as run_expect.  Secrets only ever cross the pipe.
    max_answers allows re-answering a repeated prompt (auth retry) before
    giving up, so bad credentials surface as an error instead of a hang.
    eof_after: close stdin N seconds in — gio reads EOF as "accept the
    bracketed defaults / anonymous", which empty-line answers do NOT.
    """
    import subprocess as sp
    p = sp.Popen(cmd, stdin=sp.PIPE, stdout=sp.PIPE, stderr=sp.STDOUT)
    out = bytearray()
    from collections import Counter
    answered: Counter = Counter()
    start = time.monotonic()
    last_data = time.monotonic()
    done_re = re.compile(done_pattern.encode()) if done_pattern else None
    QUIET_SEC = 0.3

    assert p.stdin is not None and p.stdout is not None
    import fcntl
    for fh in (p.stdout,):
        fl = fcntl.fcntl(fh, fcntl.F_GETFL)
        fcntl.fcntl(fh, fcntl.F_SETFL, fl | os.O_NONBLOCK)

    try:
        while True:
            if time.monotonic() - start > timeout:
                p.kill()
                raise PtyError(f"timeout after {timeout:.0f}s waiting for {cmd[0]}")
            if eof_after is not None and time.monotonic() - start >= eof_after:
                try:
                    p.stdin.close()
                except OSError:
                    pass
                eof_after = None  # only once
            try:
                chunk = p.stdout.read(65536)
            except BlockingIOError:
                chunk = None
            if chunk:
                out += chunk
                last_data = time.monotonic()
                if done_re and done_re.search(out) and not _tail_partial(out):
                    break
                continue
            if chunk == b"":  # EOF
                break
            # no data: after a quiet window, answer pending prompts
            if time.monotonic() - last_data >= QUIET_SEC:
                tail = bytes(out[-4096:])
                for i, ex in enumerate(expects):
                    if answered[i] >= max_answers:
                        continue
                    if ex.pattern.search(tail):
                        p.stdin.write((ex.answer + "\n").encode())
                        p.stdin.flush()
                        answered[i] += 1
                        break
            if p.poll() is not None:
                # drain remaining
                while True:
                    try:
                        chunk = p.stdout.read(65536)
                    except BlockingIOError:
                        break
                    if not chunk:
                        break
                    out += chunk
                break
            time.sleep(0.05)
    finally:
        try:
            p.stdin.close()
        except OSError:
            pass
    code = p.wait()
    return bytes(out), code


def run_expect(cmd: list[str],
               expects: list[Expect],
               timeout: float = 300.0,
               done_pattern: str = r"$^") -> tuple[bytes, int]:
    """Run cmd under a pty, answering prompts.

    Prompts are matched against the tail of accumulated output.  A prompt is
    "pending" once its pattern matches text that does NOT yet end in a
    newline (i.e. it is still being written / waiting for input); the answer
    is written once the output has been quiet for QUIET_SEC so we do not
    answer a half-printed prompt.

    done_pattern: regex that, when matched, means the program has produced
    its final answer and we can stop reading (or EOF/exits anyway).

    Returns (full_output, exit_status).  Secrets the caller feeds in answers
    or receives in output MUST NOT be logged.
    """
    QUIET_SEC = 0.35
    pid, fd = pty.fork()
    if pid == 0:  # child
        try:
            os.execvp(cmd[0], cmd)
        finally:
            os._exit(127)

    out = bytearray()
    answered: set[int] = set()
    start = time.monotonic()
    last_data = time.monotonic()
    status = None
    done_re = re.compile(done_pattern.encode()) if done_pattern else None

    try:
        while True:
            if time.monotonic() - start > timeout:
                raise PtyError(f"timeout after {timeout:.0f}s waiting for {cmd[0]}")
            ready, _, _ = select.select([fd], [], [], 0.1)
            if ready:
                try:
                    chunk = os.read(fd, 65536)
                except OSError:  # EIO after child exit on Linux
                    chunk = b""
                if chunk:
                    out += chunk
                    last_data = time.monotonic()
                    if done_re and done_re.search(out) and not _tail_partial(out):
                        break
                else:
                    break  # EOF
                continue

            # no data this tick — consider answering pending prompts
            quiet = time.monotonic() - last_data
            if quiet < QUIET_SEC:
                continue
            tail = bytes(out[-4096:])
            progressed = False
            for i, ex in enumerate(expects):
                if i in answered:
                    continue
                if ex.pattern.search(tail):
                    os.write(fd, (ex.answer + "\n").encode())
                    answered.add(i)
                    progressed = True
                    break
            # exit if process gone and nothing new for a while
            waited, wstatus = os.waitpid(pid, os.WNOHANG)
            if waited == pid:
                status = wstatus
                # drain
                while True:
                    ready, _, _ = select.select([fd], [], [], 0.2)
                    if not ready:
                        break
                    try:
                        chunk = os.read(fd, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    out += chunk
                break
            if not progressed and not answered and not expects:
                pass  # pure capture; wait for exit
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            # collect if still running after loop broke on done_pattern
            if status is None:
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    pass
                try:
                    _, status = os.waitpid(pid, 0)
                except ChildProcessError:
                    status = 0

    if status is None:
        return bytes(out), 0
    if os.WIFEXITED(status):
        return bytes(out), os.WEXITSTATUS(status)
    return bytes(out), 128 + os.WTERMSIG(status)


def _tail_partial(out: bytearray) -> bool:
    """True if the buffer ends without a newline (prompt may be partial)."""
    return bool(out) and out[-1:] not in (b"\n", b"\r")


def run_capture(cmd: list[str], timeout: float = 30.0,
                env: dict[str, str] | None = None) -> tuple[bytes, int]:
    """Plain capture (no pty) for non-interactive commands."""
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout,
                           env=env)
        return p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired:
        return b"", 124
