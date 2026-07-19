"""Auto-naming a session from its first exchange, using a cheap/fast model
rather than the (possibly large, expensive) model the user is actually
chatting with. Best-effort only — a naming failure must never break a chat
turn, so callers should swallow exceptions from suggest_title."""

from __future__ import annotations

from .providers.base import Message, Provider

MAX_TITLE_LENGTH = 60


def suggest_title(provider: Provider, cheap_model: str, user_text: str, assistant_text: str) -> str:
    prompt = (
        "Summarize the following exchange as a short session title: 3-6 words, "
        "no punctuation besides spaces, no quotes. Reply with only the title.\n\n"
        f"User: {user_text[:500]}\n"
        f"Assistant: {assistant_text[:500]}"
    )
    chunks = []
    for event in provider.send(
        cheap_model, "You generate concise session titles.", [Message(role="user", content=prompt)], stream=False
    ):
        if event.type == "text_delta" and event.text:
            chunks.append(event.text)
        elif event.type == "error":
            raise RuntimeError(event.error)
    title = "".join(chunks).strip().strip('"').strip("'")
    return title[:MAX_TITLE_LENGTH] or "untitled"
