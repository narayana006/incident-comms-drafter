"""Fixed wording for each stage and audience, filled in with the extracted facts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

from .facts import STAGES, Facts
from .style import Style, apply_style

AUDIENCES = ("customers", "executives", "support")

_KIND = {"customers": "status page update", "executives": "executive summary",
         "support": "support team brief"}


@dataclass
class Draft:
    audience: str
    stage: str
    kind: str
    title: str
    body: str
    notes: list[str] = field(default_factory=list)  # things the reviewer should know
    violations: list[str] = field(default_factory=list)  # house-style problems to fix by hand


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def _join(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _duration(delta: timedelta) -> str:
    minutes = max(int(delta.total_seconds() // 60), 0)
    hours, minutes = divmod(minutes, 60)
    if hours and minutes:
        return f"{hours}h {minutes}m"
    return f"{hours}h" if hours else f"{minutes}m"


def _next_update(facts: Facts, style: Style) -> str:
    if facts.next_update:
        return facts.next_update
    if facts.as_of is None:
        return f"within {style.update_interval_minutes} minutes"
    return f"{facts.as_of + timedelta(minutes=style.update_interval_minutes):%H:%M} UTC"


def _customer_draft(facts: Facts, style: Style, stage: str, notes: list[str]) -> tuple[str, str]:
    public = [style.components.get(name, name) for name in facts.components]
    unmapped = [name for name in facts.components if style.components and name not in style.components]
    if unmapped:
        notes.append(f"no customer-facing name configured for: {', '.join(unmapped)}")
    elif facts.components and not style.components:
        notes.append("component names are used as written in the channel; map them to "
                     "customer-facing names in a style file")
    where = _join(public) or style.product or "our service"
    title = facts.title or (f"Problems with {_join(public)}" if public else "Service disruption")

    if facts.customer_impact:
        impact = _sentence(facts.customer_impact)
    else:
        impact = f"Some customers may be experiencing problems with {where}."
        notes.append('no "customer impact:" line in the channel; used generic impact wording'
                     + (" (the internal impact statement is not shown to customers)" if facts.impact else ""))
    workaround = f" Workaround: {_sentence(facts.workaround)}" if facts.workaround else ""
    later = f" We will provide another update by {_next_update(facts, style)}."

    if stage == "investigating":
        body = f"We are investigating an issue affecting {where}. {impact}{workaround}{later}"
    elif stage == "identified":
        body = (f"We have identified the cause of the issue affecting {where} and are working on "
                f"a fix. {impact}{workaround}{later}")
    elif stage == "monitoring":
        body = (f"A fix has been put in place for the issue affecting {where} and we are monitoring "
                f"the results. {impact}{later}")
    else:
        window = ""
        if facts.started and facts.resolved_at:
            window = f" The issue lasted from {facts.started:%H:%M} to {facts.resolved_at:%H:%M} UTC."
            notes.append(f"start time is the first channel message ({facts.started:%H:%M} UTC); "
                         "correct it if the impact began earlier")
        body = (f"The issue affecting {where} has been resolved.{window} {style.apology}").strip()
    if style.sign_off:
        body += f"\n\n{style.sign_off}"
    return f"{stage.capitalize()} - {title}", body


def _internal_header(facts: Facts, stage: str) -> list[str]:
    lines = [f"Status: {stage.capitalize()}" + (f" | Severity: {facts.severity}" if facts.severity else
                                               " | Severity: not stated")]
    if facts.started and facts.as_of:
        end = facts.resolved_at if stage == "resolved" and facts.resolved_at else facts.as_of
        lines.append(f"Started: {facts.started:%Y-%m-%d %H:%M} UTC | Duration so far: "
                     f"{_duration(end - facts.started)}" if stage != "resolved" else
                     f"Started: {facts.started:%Y-%m-%d %H:%M} UTC | Resolved: {end:%H:%M} UTC | "
                     f"Duration: {_duration(end - facts.started)}")
    return lines


def _executive_draft(facts: Facts, style: Style, stage: str, notes: list[str]) -> tuple[str, str]:
    name = facts.title or (f"{_join(facts.components)} incident" if facts.components else "Incident")
    as_of = f" (as of {facts.as_of:%H:%M} UTC)" if facts.as_of else ""
    severity = f"[{facts.severity}] " if facts.severity else ""
    lines = _internal_header(facts, stage)
    lines.append(f"Customer impact: {_sentence(facts.impact or facts.customer_impact) or 'Not yet stated in the channel.'}")
    lines.append(f"Cause: {_sentence(facts.cause) or 'Not yet known.'}")
    lines.append(f"Current action: {_sentence(facts.status) or 'Not stated in the channel.'}")
    if facts.workaround:
        lines.append(f"Workaround: {_sentence(facts.workaround)}")
    lines.append(f"Asks: {_sentence(facts.ask) or 'None at this time.'}")
    if stage != "resolved":
        lines.append(f"Next update: {_next_update(facts, style)}")
    if not facts.impact and not facts.customer_impact:
        notes.append("no impact statement found in the channel")
    return f"{severity}{name} - {stage.capitalize()}{as_of}", "\n".join(lines)


def _support_draft(facts: Facts, style: Style, stage: str, notes: list[str],
                   customer_body: str) -> tuple[str, str]:
    name = facts.title or (f"{_join(facts.components)} incident" if facts.components else "Incident")
    seeing = _sentence(facts.customer_impact or facts.impact) or "Not yet stated in the channel."
    lines = _internal_header(facts, stage)
    lines += ["", f"What customers are seeing: {seeing}",
              f"Workaround: {_sentence(facts.workaround) or 'None available yet.'}", "",
              "What you can tell customers (matches the status page draft):",
              *[f"  {line}" if line else "" for line in customer_body.splitlines()], "",
              "Please do not:",
              "  - promise a time by which this will be fixed",
              "  - share details of the cause beyond the wording above"]
    if stage != "resolved":
        lines += ["", f"Next update: {_next_update(facts, style)}"]
    return f"Support brief: {name} - {stage.capitalize()}", "\n".join(lines)


def build_drafts(facts: Facts, style: Style, audiences: tuple[str, ...] = AUDIENCES,
                 stage: str | None = None) -> list[Draft]:
    """Draft one message per audience for the given (or detected) stage."""
    stage = stage or facts.stage
    if stage not in STAGES:
        raise ValueError(f"unknown stage: {stage}")
    people = tuple(facts.people)
    drafts = []
    customer_notes: list[str] = []
    customer_title, customer_body = _customer_draft(facts, style, stage, customer_notes)
    customer_body, replaced, customer_violations = apply_style(customer_body, style, "customers", people)
    customer_title, _, title_violations = apply_style(customer_title, style, "customers", people)
    for audience in audiences:
        notes: list[str] = []
        if audience == "customers":
            title, body = customer_title, customer_body
            notes, violations = customer_notes + replaced, customer_violations + [
                v for v in title_violations if v not in customer_violations]
        else:
            if audience == "executives":
                title, body = _executive_draft(facts, style, stage, notes)
            elif audience == "support":
                title, body = _support_draft(facts, style, stage, notes, customer_body)
            else:
                raise ValueError(f"unknown audience: {audience}")
            body, replaced_here, violations = apply_style(body, style, audience, people)
            title = apply_style(title, style, audience, people)[0]
            notes += replaced_here
            if audience == "support":
                violations = violations + [f"in the customer wording: {v}" for v in customer_violations]
        drafts.append(Draft(audience, stage, _KIND[audience], title, body, notes, violations))
    return drafts
