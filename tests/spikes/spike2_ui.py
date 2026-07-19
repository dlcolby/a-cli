"""Spike 2: does prompt_toolkit's completion dropdown work in a-shell's
terminal, and specifically can you SELECT an item by tapping it with your
finger (vs. needing the keyboard's arrow keys + return)?

Run: python3 tests/spikes/spike2_ui.py

Type "alpha" to trigger a dropdown with THREE candidates (alpha1, alpha2,
alphabeta) still visible at once, confirming multi-item filtering (not just
single-item auto-complete). Try tapping "alpha2" specifically — the middle
one — to confirm you can pick a specific item out of several, not just
whichever one happens to be first/highlighted.
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

session = PromptSession(
    completer=WordCompleter(["alpha1", "alpha2", "alphabeta", "beta1", "beta2", "gamma"]),
    complete_while_typing=True,
    mouse_support=True,
)
text = session.prompt("test> ")
print("You typed:", text)
