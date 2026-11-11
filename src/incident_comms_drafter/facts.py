"""Extract the current facts of an incident from channel messages."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

from .channel import Message

STAGES = ("investigating", "identified", "monitoring", "resolved")

# "key: value" lines that responders can post to state a fact outright.
# The latest value of each key wins.
_MARKER = re.compile(
    r"^\s*[-*>]?\s*\**(customer impact|impact|status|root cause|cause|workaround|next update|eta"
    r"|severity|sev|stage|components?|affected|title|ask|need)\**\s*[:=]\s*\**\s*(.+?)\s*$", re.I)
_ALIASES = {"root cause": "cause", "eta": "next update", "sev": "severity",
            "component": "components", "affected": "components", "need": "ask"}

_SEVERITY = re.compile(r"\b(sev|p)[- ]?([0-5])\b", re.I)

# Checked in this order for every message; the latest message with a signal sets the stage.
_STAGE_SIGNALS: list[tuple[str, re.Pattern[str]]] = [
    ("resolved", re.compile(
        r"\b(?:resolved|all clear|incident (?:is )?(?:over|closed)|fully recovered|closing "
        r"(?:the |this )?incident)\b", re.I)),
    ("monitoring", re.compile(
        r"\b(?:monitoring|fix (?:is |has been )?(?:deployed|rolled out|live|out)|rolled back"
        r"|rollback (?:is )?(?:complete|done|finished)|recovering|errors? (?:rate )?(?:is |are )?"
        r"(?:dropping|falling|back to normal))\b", re.I)),
    ("identified", re.compile(
        r"\b(?:root cause|identified|found (?:the|it)|caused by|turns out|the (?:issue|problem|bug)"
        r" (?:is|was)|rolling back|reverting)\b", re.I)),
]
_NEGATED = re.compile(
    r"\b(?:not|no|never|isn't|aren't|wasn't|hasn't|haven't|don't|didn't|won't)\b[^.;,]{0,20}$", re.I)
_IMPACT = re.compile(
    r"\b(?:customers?|users?|requests?|orders?|checkouts?|logins?|payments?)\b.*"
    r"(?:\d+(?:\.\d+)?\s?%|\b(?:unable|cannot|can't|failing|failed|errors?|timeouts?|timing out"
    r"|degraded|down|affected|slow)\b)", re.I)


def stage_signal(text: str) -> str | None:
    """Stage implied by one message, or None. Negations and questions do not count."""
    if text.rstrip().endswith("?"):
        return None
    for stage, pattern in _STAGE_SIGNALS:
        match = pattern.search(text)
        if match and not _NEGATED.search(text[:match.start()]):
            return stage
    return None


@dataclass
class Facts:
    stage: str = "investigating"
    stage_source: str = "no stage signal found; assumed investigating"
    severity: str = ""
    title: str = ""
    components: list[str] = field(default_factory=list)
    impact: str = ""  # internal wording
    customer_impact: str = ""  # wording approved for customers
    cause: str = ""
    status: str = ""  # what is being done right now
    workaround: str = ""
    next_update: str = ""
    ask: str = ""
    started: datetime | None = None
    as_of: datetime | None = None
    resolved_at: datetime | None = None
    people: list[str] = field(default_factory=list)


def _quote(message: Message) -> str:
    text = " ".join(message.text.split())
    return f'{message.time:%H:%M} UTC "{text if len(text) <= 80 else text[:77] + "..."}"'


def extract_facts(messages: list[Message]) -> Facts:
    """Read the channel oldest to newest and keep the latest value of every fact."""
    facts = Facts()
    if not messages:
        return facts
    facts.started = messages[0].time
    facts.as_of = messages[-1].time
    for message in messages:
        if message.author and message.author not in facts.people:
            facts.people.append(message.author)
        marked = set()
        for line in message.text.splitlines():
            marker = _MARKER.match(line)
            if not marker:
                continue
            key = marker.group(1).lower()
            key = _ALIASES.get(key, key)
            value = marker.group(2).strip()
            marked.add(key)
            if key == "components":
                facts.components = [part.strip() for part in re.split(r"[,;]", value) if part.strip()]
            elif key == "severity":
                found = _SEVERITY.search(value)
                facts.severity = f"{found.group(1)}{found.group(2)}".upper() if found else value.upper()
            elif key == "stage":
                if value.lower() in STAGES:
                    facts.stage, facts.stage_source = value.lower(), f"stated at {_quote(message)}"
            else:
                setattr(facts, key.replace(" ", "_"), value)

        if "severity" not in marked:
            found = _SEVERITY.search(message.text)
            if found and not re.search(r"\b(?:should|could|might|maybe)\b|\?\s*$", message.text, re.I):
                facts.severity = f"{found.group(1)}{found.group(2)}".upper()
        if "stage" not in marked:
            signal = stage_signal(message.text)
            if signal is None and "cause" in marked and facts.stage == "investigating":
                signal = "identified"  # stating a cause means it has been identified
            if signal:
                facts.stage, facts.stage_source = signal, f"inferred from {_quote(message)}"
        if "impact" not in marked and "customer impact" not in marked and not facts.impact \
                and _IMPACT.search(message.text):
            facts.impact = " ".join(message.text.split())
        if facts.stage == "resolved" and facts.resolved_at is None:
            facts.resolved_at = message.time
        elif facts.stage != "resolved":
            facts.resolved_at = None
    return facts
