"""Spike 3: OneDrive folder round-trip + placeholder-file materialization.

Run this from INSIDE the bookmarked OneDrive folder:
  cd <bookmarked-folder>
  python3 ~/Documents/a-cli/tests/spikes/spike3_onedrive.py

It writes a-cli-test.txt here — check on your PC that it shows up in OneDrive
with the right content. Then, separately: create a file called
pc-created.txt in the same OneDrive folder from your PC, wait for it to show
as synced, and re-run this script — it'll try to read that file and report
whether it got real content, empty content, or an error (placeholder-file
behavior that hasn't downloaded yet).
"""

from pathlib import Path

test_file = Path("a-cli-test.txt")
test_file.write_text("hello from a-shell")
print(f"Wrote {test_file.resolve()} — check this appears in OneDrive on your PC.")

pc_file = Path("pc-created.txt")
if pc_file.exists():
    try:
        content = pc_file.read_text()
        print(f"Read pc-created.txt: {content!r}")
    except Exception as exc:
        print(f"Error reading pc-created.txt: {exc!r}")
else:
    print("pc-created.txt not found yet — create it on your PC in this same folder, "
          "wait for sync, then re-run this script.")
