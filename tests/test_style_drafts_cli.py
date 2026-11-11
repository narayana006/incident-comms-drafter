import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from incident_comms_drafter.cli import FOOTER, main
from incident_comms_drafter.drafts import build_drafts
from incident_comms_drafter.facts import Facts
from incident_comms_drafter.style import BannedPhrase, Style, StyleError, apply_style, load_style

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
CHANNEL = str(EXAMPLES / "inc-2041.json")
FULL = str(EXAMPLES / "inc-2041-full.txt")
STYLE = str(EXAMPLES / "house-style.toml")
UTC = timezone.utc


def facts(**overrides):
    base = dict(stage="investigating", severity="SEV2", components=["checkout-api"],
                impact="18% of requests failing", started=datetime(2026, 3, 14, 14, 3, tzinfo=UTC),
                as_of=datetime(2026, 3, 14, 14, 26, tzinfo=UTC), people=["Ada Example"])
    base.update(overrides)
    return Facts(**base)


def test_load_style_example_and_defaults():
    style = load_style(STYLE)
    assert style.product == "Example Shop" and style.max_length == 600
    assert style.components["checkout-api"] == "Checkout"
    assert style.banned[0] == BannedPhrase("outage", "disruption")
    assert style.banned[3].audiences == ("customers",)
    assert load_style(None) == Style()


@pytest.mark.parametrize("content, message", [
    ("product = ", "not valid TOML"),
    ("colour = 'blue'", "unknown setting"),
    ("[[banned]]\nreplace = 'x'", "needs a phrase"),
    ("max_length = -1", "non-negative"),
])
def test_load_style_errors(tmp_path, content, message):
    path = tmp_path / "style.toml"
    path.write_text(content)
    with pytest.raises(StyleError, match=message):
        load_style(path)
    with pytest.raises(StyleError, match="cannot read"):
        load_style(tmp_path / "missing.toml")


def test_apply_style_replacements_and_violations():
    style = Style(banned=(BannedPhrase("outage", "disruption"), BannedPhrase("unfortunately"),
                          BannedPhrase("ASAP", audiences=("executives",))),
                  internal_terms=("orders-db",), max_length=40)
    text, notes, violations = apply_style(
        "Outage on orders-db. Unfortunately Ada says outages will be fixed shortly at 10.0.0.12",
        style, "customers", ("Ada Example",))
    assert text.startswith("Disruption on orders-db.") and "outages" in text  # whole words only
    assert notes == ['replaced "outage" with "disruption"']
    assert violations == [
        'banned phrase "unfortunately"',
        'internal term "orders-db" in a customer-facing draft',
        'promises a resolution time: "will be fixed shortly"',
        'contains an internal address: "10.0.0.12"',
        'names a person: "Ada Example"',
        "90 characters; the limit is 40",
    ]


def test_apply_style_internal_audiences_only_get_banned_phrases():
    style = Style(banned=(BannedPhrase("ASAP", audiences=("executives",)),), internal_terms=("orders-db",))
    assert apply_style("orders-db fixed ASAP by Ada", style, "support", ("Ada",))[2] == []
    assert apply_style("orders-db fixed ASAP", style, "executives")[2] == ['banned phrase "ASAP"']


@pytest.mark.parametrize("stage, expected", [
    ("investigating", "We are investigating an issue affecting Checkout."),
    ("identified", "We have identified the cause of the issue affecting Checkout and are working on a fix."),
    ("monitoring", "A fix has been put in place for the issue affecting Checkout and we are monitoring"),
    ("resolved", "The issue affecting Checkout has been resolved."),
])
def test_customer_wording_per_stage(stage, expected):
    style = Style(components={"checkout-api": "Checkout"})
    draft = build_drafts(facts(stage=stage, resolved_at=datetime(2026, 3, 14, 14, 45, tzinfo=UTC)),
                         style, ("customers",))[0]
    assert draft.body.startswith(expected)
    assert draft.title == f"{stage.capitalize()} - Problems with Checkout"
    if stage == "resolved":
        assert "from 14:03 to 14:45 UTC" in draft.body and "another update" not in draft.body
    else:
        assert draft.body.endswith("We will provide another update by 14:56 UTC.")


def test_customers_never_see_internal_impact_or_cause():
    draft = build_drafts(facts(cause="pool cut to 5 in v2.41.0"), Style(), ("customers",))[0]
    assert "18%" not in draft.body and "v2.41.0" not in draft.body
    assert "Some customers may be experiencing problems with checkout-api." in draft.body
    assert any("generic impact wording" in note for note in draft.notes)
    assert any("map them to customer-facing names" in note for note in draft.notes)


def test_executive_and_support_drafts():
    known = facts(stage="identified", cause="pool cut to 5", status="rolling back", ask="none needed",
                  customer_impact="some purchases fail", workaround="retry", next_update="15:00 UTC")
    executive, support = build_drafts(known, Style(), ("executives", "support"))
    assert executive.title == "[SEV2] checkout-api incident - Identified (as of 14:26 UTC)"
    assert "Duration so far: 23m" in executive.body
    assert "Cause: Pool cut to 5." in executive.body and "Next update: 15:00 UTC" in executive.body
    assert "What customers are seeing: Some purchases fail." in support.body
    assert "  We have identified the cause" in support.body
    assert "promise a time" in support.body

    unknown = build_drafts(Facts(), Style(), ("executives",))[0]
    assert "Cause: Not yet known." in unknown.body and "Severity: not stated" in unknown.body
    assert unknown.notes == ["no impact statement found in the channel"]


def test_support_brief_inherits_customer_violations():
    risky = facts(customer_impact="checkout will be fixed shortly")
    support = build_drafts(risky, Style(), ("support",))[0]
    assert support.violations == ['in the customer wording: promises a resolution time: "will be fixed shortly"']


def test_build_drafts_rejects_unknown_stage():
    with pytest.raises(ValueError):
        build_drafts(facts(), Style(), stage="panicking")


def test_cli_matches_committed_drafts(capsys):
    assert main(["draft", "--channel", CHANNEL, "--style", STYLE, "--audience", "customers"]) == 0
    assert capsys.readouterr().out == (EXAMPLES / "drafts" / "customers-identified.txt").read_text()
    assert main(["draft", "--channel", CHANNEL, "--style", STYLE, "--audience", "all"]) == 0
    assert capsys.readouterr().out == (EXAMPLES / "drafts" / "all-identified.txt").read_text()
    assert main(["draft", "--channel", FULL, "--style", STYLE]) == 0
    assert capsys.readouterr().out == (EXAMPLES / "drafts" / "customers-resolved.txt").read_text()


def test_cli_every_draft_says_it_was_not_sent(capsys):
    main(["draft", "--channel", CHANNEL, "--audience", "all"])
    assert capsys.readouterr().out.count(FOOTER) == 3
    main(["draft", "--channel", CHANNEL, "--format", "json"])
    assert json.loads(capsys.readouterr().out)["sent"] is False


def test_cli_strict_as_of_and_overrides(capsys):
    args = ["draft", "--channel", FULL, "--style", STYLE, "--audience", "executives"]
    assert main([*args, "--as-of", "2026-03-14T14:27:00Z", "--strict"]) == 1
    assert 'FIX: banned phrase "should be fixed soon" (never promise timing)' in capsys.readouterr().out
    assert main([*args, "--as-of", "2026-03-14T14:10:00Z", "--strict", "--severity", "sev1",
                 "--title", "Checkout down", "--stage", "identified"]) == 0
    out = capsys.readouterr().out
    assert "[SEV1] Checkout down - Identified (as of 14:07 UTC)" in out
    assert "- stage: set with --stage (the channel suggests investigating)" in out


def test_cli_errors(tmp_path, capsys):
    assert main(["draft", "--channel", str(tmp_path / "missing.json")]) == 2
    assert main(["draft", "--channel", CHANNEL, "--style", str(tmp_path / "missing.toml")]) == 2
    assert main(["draft", "--channel", CHANNEL, "--as-of", "2020-01-01T00:00:00Z"]) == 1
    assert "no messages found" in capsys.readouterr().err


def test_cli_check(tmp_path, capsys):
    assert main(["check", str(EXAMPLES / "bad-update.txt"), "--style", STYLE]) == 1
    out = capsys.readouterr().out
    assert 'would be replaced "outage" with "disruption"' in out
    assert 'FIX: assigns blame: "someone pushed"' in out
    clean = tmp_path / "ok.txt"
    clean.write_text("We are investigating an issue affecting Checkout.")
    assert main(["check", str(clean), "--style", STYLE]) == 0
    assert "no house-style problems found" in capsys.readouterr().out
