"""Command-line interface. Drafts are printed; nothing is ever posted."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .channel import InputError, load_channel, parse_time
from .drafts import AUDIENCES, Draft, build_drafts
from .facts import STAGES, Facts, extract_facts
from .style import StyleError, apply_style, load_style

FOOTER = "DRAFT ONLY - nothing has been sent. A person must review, edit and post this."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="incident-comms-drafter",
        description="Draft status page updates and stakeholder messages from an incident "
                    "channel export. Output is always a draft for a person to review.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="draft an update for one or all audiences")
    draft.add_argument("--channel", required=True, metavar="PATH",
                       help="Slack export (JSON file or directory) or a text transcript")
    draft.add_argument("--audience", choices=(*AUDIENCES, "all"), default="customers")
    draft.add_argument("--stage", choices=(*STAGES, "auto"), default="auto",
                       help="auto (default) reads the stage from the channel")
    draft.add_argument("--severity", help="override the severity read from the channel")
    draft.add_argument("--title", help="override the incident title")
    draft.add_argument("--style", metavar="FILE", help="house style rules (TOML)")
    draft.add_argument("--as-of", metavar="TIME",
                       help="ignore messages after this time (ISO 8601), to redraft an earlier update")
    draft.add_argument("--format", choices=("text", "json"), default="text")
    draft.add_argument("--strict", action="store_true",
                       help="exit with status 1 if any draft has house-style violations")

    check = commands.add_parser("check", help="check any text file against the house style")
    check.add_argument("file", help="text to check, or - for stdin")
    check.add_argument("--style", metavar="FILE", help="house style rules (TOML)")
    check.add_argument("--audience", choices=AUDIENCES, default="customers")
    return parser


def _render_text(draft: Draft, facts: Facts) -> str:
    lines = [f"=== {draft.audience}: {draft.kind} | stage: {draft.stage} ===", "",
             draft.title, "", draft.body, "", "--- review notes ---",
             f"- stage: {facts.stage_source}" if draft.stage == facts.stage
             else f"- stage: set with --stage (the channel suggests {facts.stage})"]
    lines += [f"- {note}" for note in draft.notes]
    lines += [f"- FIX: {violation}" for violation in draft.violations]
    lines.append(FOOTER)
    return "\n".join(lines)


def _draft(args: argparse.Namespace) -> int:
    messages = load_channel(args.channel)
    if args.as_of:
        cutoff = parse_time(args.as_of)
        messages = [message for message in messages if message.time <= cutoff]
    if not messages:
        print("incident-comms-drafter: no messages found in the channel", file=sys.stderr)
        return 1
    style = load_style(args.style)
    facts = extract_facts(messages)
    if args.severity:
        facts.severity = args.severity.upper()
    if args.title:
        facts.title = args.title
    audiences = AUDIENCES if args.audience == "all" else (args.audience,)
    drafts = build_drafts(facts, style, audiences, None if args.stage == "auto" else args.stage)

    if args.format == "json":
        payload = {"facts": {key: (value.isoformat() if hasattr(value, "isoformat") else value)
                             for key, value in asdict(facts).items()},
                   "drafts": [asdict(draft) for draft in drafts], "sent": False}
        print(json.dumps(payload, indent=2))
    else:
        print("\n\n".join(_render_text(draft, facts) for draft in drafts))
    return 1 if args.strict and any(draft.violations for draft in drafts) else 0


def _check(args: argparse.Namespace) -> int:
    text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text("utf-8")
    _, notes, violations = apply_style(text, load_style(args.style), args.audience)
    for note in notes:
        print(f"would be {note}")
    for violation in violations:
        print(f"FIX: {violation}")
    if not notes and not violations:
        print("no house-style problems found")
    return 1 if notes or violations else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _draft(args) if args.command == "draft" else _check(args)
    except (InputError, StyleError, OSError) as exc:
        print(f"incident-comms-drafter: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
