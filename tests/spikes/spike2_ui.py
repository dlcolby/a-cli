"""Spike 2: does prompt_toolkit's completion dropdown work in a-shell's
terminal, and specifically can you SELECT an item by tapping it with your
finger (vs. needing the keyboard's arrow keys + return)?

Run: python3 spikes/spike2_ui.py

Type a letter (e.g. "a") to trigger the dropdown showing alpha/beta/gamma,
then try tapping "alpha" directly. Report back: did the dropdown appear at
all, and did tapping work or did you need arrow keys?
"""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

session = PromptSession(
    completer=WordCompleter(["alpha", "beta", "gamma"]),
    complete_while_typing=True,
    mouse_support=True,
)
text = session.prompt("test> ")
print("You typed:", text)
