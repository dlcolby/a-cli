# Device debug logs

Scratch space for on-device diagnostic traces from `ai_cli/debug_log.py`.
Useful when something crashes or freezes in a-shell in a way that leaves no
catchable traceback — the log is written line-by-line as it happens, so
whatever ran right up to the moment of a freeze/crash is still on disk even
if the app never shuts down cleanly.

## To capture a trace

From inside the repo on-device (`~/Documents/a-cli` or wherever it was
cloned):

```sh
export AIC_DEBUG_LOG=tests/spikes/debug_logs/trace.log
aic
```

Reproduce whatever you were doing, then check the file in:

```sh
lg2 add tests/spikes/debug_logs/trace.log
lg2 commit -m "device trace: <short description of what you were testing>"
lg2 push
```

(No committed `.gitignore` rule excludes `*.log` here — these are meant to
be checked in as scratch artifacts, not left device-local.)

## Notes

- Logging is a strict no-op unless `AIC_DEBUG_LOG` is set — leaving it unset
  costs nothing in normal use.
- Delete/replace `trace.log` freely between test runs; it's disposable
  scratch output, not something that needs history of its own.
