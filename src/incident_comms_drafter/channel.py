"""Read an incident channel from a Slack export or a plain-text transcript."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class InputError(ValueError):
    """The channel file is missing or not in a supported shape."""


@dataclass(frozen=True)
class Message:
    time: datetime
    author: str
    text: str


def parse_time(value: object) -> datetime:
    """ISO 8601 or Unix epoch to an aware UTC datetime; no offset means UTC."""
    text = str(value).strip()
    if re.fullmatch(r"\d{9,11}(\.\d+)?", text):
        return datetime.fromtimestamp(float(text), tz=timezone.utc)
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise InputError(f"unrecognised timestamp: {value!r}") from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_KEPT_SUBTYPES = {None, "", "bot_message", "thread_broadcast", "me_message"}
_METADATA_FILES = {"users.json", "channels.json", "groups.json", "dms.json", "mpims.json",
                   "integration_logs.json", "canvases.json"}


def _clean(text: str, users: dict[str, str]) -> str:
    text = re.sub(r"<@([A-Z0-9]+)(?:\|([^>]+))?>",
                  lambda m: "@" + (m.group(2) or users.get(m.group(1), m.group(1))), text)
    text = re.sub(r"<#[A-Z0-9]+\|([^>]+)>", r"#\1", text)
    text = re.sub(r"<!(here|channel|everyone)>", r"@\1", text)
    text = re.sub(r"<([^>|]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<((?:https?|mailto):[^>]+)>", r"\1", text)
    # Line breaks are kept: a structured update puts one fact on each line.
    return "\n".join(" ".join(line.split()) for line in html.unescape(text).splitlines()).strip()


def _slack_messages(documents: dict[str, object], origin: Path) -> list[Message]:
    users: dict[str, str] = {}
    for name, document in documents.items():
        if name.rsplit("/", 1)[-1] == "users.json" and isinstance(document, list):
            for user in document:
                if isinstance(user, dict) and user.get("id"):
                    users[user["id"]] = (user.get("real_name")
                                         or (user.get("profile") or {}).get("real_name")
                                         or user.get("name") or user["id"])
    messages = []
    for name, document in documents.items():
        if name.rsplit("/", 1)[-1] in _METADATA_FILES:
            continue
        if isinstance(document, dict) and isinstance(document.get("messages"), list):
            document = document["messages"]
        if not isinstance(document, list):
            raise InputError(f"{origin}: {name} is not a list of messages")
        for item in document:
            if not isinstance(item, dict) or item.get("subtype") not in _KEPT_SUBTYPES:
                continue
            if not (item.get("text") or "").strip() or "ts" not in item:
                continue
            profile = item.get("user_profile") or {}
            user_id = item.get("user", "")
            author = (users.get(user_id) or profile.get("real_name") or item.get("user_name")
                      or item.get("username") or user_id)
            messages.append(Message(parse_time(item["ts"]), author, _clean(item["text"], users)))
    return messages


# "[2026-03-14 14:03] priya: text", "2026-03-14T14:03:10Z priya: text"
_TRANSCRIPT_LINE = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?)\]?\s+([^:]{1,60}?):\s+(.*)$")


def _transcript_messages(text: str, origin: Path) -> list[Message]:
    messages: list[Message] = []
    for line in text.splitlines():
        match = _TRANSCRIPT_LINE.match(line)
        if match:
            messages.append(Message(parse_time(match.group(1)), match.group(2).strip(),
                                    match.group(3).strip()))
        elif line.strip() and messages:
            # A line without a timestamp continues the previous message.
            last = messages[-1]
            messages[-1] = Message(last.time, last.author, f"{last.text}\n{line.strip()}")
        elif line.strip():
            raise InputError(f"{origin}: first line is not 'YYYY-MM-DD HH:MM name: message'")
    return messages


def load_channel(path: str | Path) -> list[Message]:
    """Load messages, oldest first.

    Accepts a Slack export (a JSON file of messages or an export directory
    with an optional users.json) or a plain-text transcript with one
    "YYYY-MM-DD HH:MM name: message" line per message.
    """
    path = Path(path)
    try:
        if path.is_dir():
            documents = {file.relative_to(path).as_posix(): json.loads(file.read_text("utf-8"))
                         for file in sorted(path.rglob("*.json"))}
            messages = _slack_messages(documents, path)
        elif path.suffix.lower() == ".json":
            messages = _slack_messages({path.name: json.loads(path.read_text("utf-8"))}, path)
        else:
            messages = _transcript_messages(path.read_text("utf-8"), path)
    except OSError as exc:
        raise InputError(f"cannot read channel {path}: {exc}") from None
    except json.JSONDecodeError as exc:
        raise InputError(f"channel {path} contains invalid JSON: {exc}") from None
    return sorted(messages, key=lambda message: message.time)
