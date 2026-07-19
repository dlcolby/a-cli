"""Spike 4: can a-shell's Python actually spawn/execute anything?

This is the feasibility check behind giving aic an agentic `run_command` tool
(see architecture.md "Known issues" for context). File read/write is already
confirmed working on-device (spike3) — this spike is purely about execution:
subprocess.run, os.system, os.popen, subprocess.Popen, and multiprocessing.
iOS sandboxes third-party apps against arbitrary process spawning, so several
of these are expected to fail; the question is which ones (if any) actually
work inside a-shell specifically, since a-shell implements many of its own
"commands" in-process rather than via fork/exec.

Run from inside a-shell:
  cd ~/Documents/a-cli
  python3 tests/spikes/spike4_execute.py

Nothing here is destructive — every probe either inspects state or runs a
harmless, side-effect-free command (echo / listing the cwd). Read the PASS/FAIL
summary at the end and report it back verbatim.

RESULT (confirmed on-device 2026-07-18): subprocess.run/Popen (incl.
shell=True) and os.system/os.popen all work. os.fork() is NOT safe — it
triggers a Fatal Python error ("PyMutex_Unlock: unlocking mutex that is not
locked") that hangs the whole a-shell app; no exception is raised, so it
can't be caught, and recovery requires a force-quit of a-shell. The
os.fork/multiprocessing probes below are gated behind an env var so this
script no longer hangs a-shell by default — see architecture.md's "Known
issues" section for the full writeup.
"""

import os
import subprocess
import sys


def probe_subprocess_run():
    proc = subprocess.run([sys.executable, "-c", "print('subprocess.run ok')"],
                           capture_output=True, text=True, timeout=10)
    return f"returncode={proc.returncode} stdout={proc.stdout.strip()!r} stderr={proc.stderr.strip()!r}"


def probe_subprocess_popen():
    proc = subprocess.Popen([sys.executable, "-c", "print('popen ok')"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = proc.communicate(timeout=10)
    return f"returncode={proc.returncode} stdout={out.strip()!r} stderr={err.strip()!r}"


def probe_os_system():
    rc = os.system("echo os.system ok")
    return f"returncode={rc}"


def probe_os_popen():
    with os.popen("echo os.popen ok") as p:
        out = p.read()
    return f"stdout={out.strip()!r}"


def probe_os_fork():
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)
    return f"forked child pid={pid}"


def _mp_child(q):
    q.put("mp ok")


def probe_multiprocessing():
    import multiprocessing

    q = multiprocessing.Queue()
    p = multiprocessing.Process(target=_mp_child, args=(q,))
    p.start()
    msg = q.get(timeout=10)
    p.join(timeout=10)
    return f"child said {msg!r}, exitcode={p.exitcode}"


def probe_shell_true():
    proc = subprocess.run("echo shell=True ok", shell=True, capture_output=True, text=True, timeout=10)
    return f"returncode={proc.returncode} stdout={proc.stdout.strip()!r}"


def main():
    results = []

    def probe(label, fn):
        try:
            detail = fn()
            results.append((label, "PASS", detail))
        except Exception as exc:
            results.append((label, "FAIL", f"{type(exc).__name__}: {exc}"))

    probe("subprocess.run([sys.executable, ...])", probe_subprocess_run)
    probe("subprocess.Popen([sys.executable, ...])", probe_subprocess_popen)
    probe("subprocess.run(..., shell=True)", probe_shell_true)
    probe("os.system(...)", probe_os_system)
    probe("os.popen(...)", probe_os_popen)

    if os.environ.get("SPIKE4_INCLUDE_FORK") == "1":
        # DANGER: confirmed to hang a-shell with an unrecoverable Fatal Python
        # error on-device (2026-07-18). Only re-run this deliberately, and be
        # ready to force-quit a-shell afterward. Off by default.
        probe("os.fork()", probe_os_fork)
        probe("multiprocessing.Process", probe_multiprocessing)
    else:
        print("Skipping os.fork()/multiprocessing.Process — confirmed to crash a-shell "
              "(set SPIKE4_INCLUDE_FORK=1 to re-run them deliberately).")

    print("\n=== Spike 4 results (execution feasibility in a-shell) ===")
    for label, status, detail in results:
        print(f"[{status}] {label}\n        {detail}")

    passed = [r for r in results if r[1] == "PASS"]
    print(f"\n{len(passed)}/{len(results)} probes passed.")
    if not passed:
        print("None worked — run_command as a real agentic tool is likely off the table on-device; "
              "read/write-only tools are still viable.")
    else:
        print("At least one execution path works — worth designing run_command around: "
              + ", ".join(label for label, status, _ in results if status == "PASS"))


if __name__ == "__main__":
    main()
