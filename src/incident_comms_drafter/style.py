"""House style: load the rules file, apply replacements and report violations."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10 only
    import tomli as tomllib

EXTERNAL_AUDIENCES = ("customers",)


class StyleError(ValueError):
    """The style file is missing or malformed."""


@dataclass(frozen=True)
class BannedPhrase:
    phrase: str
    replace: str = ""  # when set, the phrase is swapped automatically
    reason: str = ""
    audiences: tuple[str, ...] = ()  # empty means every audience


@dataclass(frozen=True)
class Style:
    product: str = ""
    update_interval_minutes: int = 30
    max_length: int = 0  # characters allowed in a customer update; 0 means no limit
    apology: str = "We apologise for the disruption."
    sign_off: str = ""
    banned: tuple[BannedPhrase, ...] = ()
    internal_terms: tuple[str, ...] = ()  # must never reach customers
    components: dict[str, str] = field(default_factory=dict)  # internal name -> public name


# Applied to customer-facing drafts whether or not a style file is given.
_BUILTIN_CUSTOMER_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:will|should) be (?:fixed|resolved|back|restored) (?:by|in|within|shortly|soon)\b"
                r"|\b(?:shortly|very soon|asap|any minute)\b", re.I),
     "promises a resolution time"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[\w-]+\.(?:internal|local|corp|lan)\b", re.I),
     "contains an internal address"),
    (re.compile(r"\b(?:human error|someone (?:forgot|broke|pushed)|(?:his|her|their) (?:mistake|fault))\b", re.I),
     "assigns blame"),
)


def load_style(path: str | Path | None) -> Style:
    """Load a TOML style file; None gives the defaults."""
    if path is None:
        return Style()
    try:
        data = tomllib.loads(Path(path).read_text("utf-8"))
    except OSError as exc:
        raise StyleError(f"cannot read style file {path}: {exc}") from None
    except tomllib.TOMLDecodeError as exc:
        raise StyleError(f"style file {path} is not valid TOML: {exc}") from None

    known = {"product", "update_interval_minutes", "max_length", "apology", "sign_off", "banned",
             "internal_terms", "components"}
    unknown = sorted(set(data) - known)
    if unknown:
        raise StyleError(f"style file {path}: unknown setting(s): {', '.join(unknown)}")
    banned = []
    for number, entry in enumerate(data.get("banned", []), start=1):
        if isinstance(entry, str):
            entry = {"phrase": entry}
        if not isinstance(entry, dict) or not str(entry.get("phrase", "")).strip():
            raise StyleError(f"style file {path}: banned entry {number} needs a phrase")
        audiences = entry.get("audiences", [])
        banned.append(BannedPhrase(str(entry["phrase"]).strip(), str(entry.get("replace", "")),
                                   str(entry.get("reason", "")),
                                   tuple([audiences] if isinstance(audiences, str) else audiences)))
    for key in ("update_interval_minutes", "max_length"):
        if not isinstance(data.get(key, 0), int) or data.get(key, 0) < 0:
            raise StyleError(f"style file {path}: {key} must be a non-negative whole number")
    return Style(
        product=str(data.get("product", "")),
        update_interval_minutes=data.get("update_interval_minutes", 30),
        max_length=data.get("max_length", 0),
        apology=str(data.get("apology", Style.apology)),
        sign_off=str(data.get("sign_off", "")),
        banned=tuple(banned),
        internal_terms=tuple(str(term) for term in data.get("internal_terms", [])),
        components={str(k): str(v) for k, v in data.get("components", {}).items()},
    )


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", re.I)


def _match_case(replacement: str, original: str) -> str:
    return replacement[:1].upper() + replacement[1:] if original[:1].isupper() else replacement


def apply_style(text: str, style: Style, audience: str,
                people: tuple[str, ...] = ()) -> tuple[str, list[str], list[str]]:
    """Apply the house style to a draft.

    Returns the text with automatic replacements made, notes describing those
    replacements, and violations a person has to fix by hand.
    """
    notes: list[str] = []
    violations: list[str] = []
    for rule in style.banned:
        if rule.audiences and audience not in rule.audiences:
            continue
        pattern = _phrase_pattern(rule.phrase)
        if not pattern.search(text):
            continue
        why = f" ({rule.reason})" if rule.reason else ""
        if rule.replace:
            text = pattern.sub(lambda m: _match_case(rule.replace, m.group(0)), text)
            notes.append(f'replaced "{rule.phrase}" with "{rule.replace}"{why}')
        else:
            violations.append(f'banned phrase "{rule.phrase}"{why}')

    if audience in EXTERNAL_AUDIENCES:
        for term in style.internal_terms:
            if _phrase_pattern(term).search(text):
                violations.append(f'internal term "{term}" in a customer-facing draft')
        for pattern, problem in _BUILTIN_CUSTOMER_RULES:
            found = pattern.search(text)
            if found:
                violations.append(f'{problem}: "{found.group(0)}"')
        for person in people:
            names = {person, person.split()[0]} if len(person.split()) > 1 else {person}
            if any(len(name) >= 3 and _phrase_pattern(name).search(text) for name in names):
                violations.append(f'names a person: "{person}"')
        if style.max_length and len(text) > style.max_length:
            violations.append(f"{len(text)} characters; the limit is {style.max_length}")
    return text, notes, violations
