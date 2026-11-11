import json
from datetime import datetime, timezone

import pytest

from incident_comms_drafter.channel import InputError, Message, load_channel
from incident_comms_drafter.facts import extract_facts, stage_signal

UTC = timezone.utc


def msg(minute, text, author="Ada Example"):
    return Message(datetime(2026, 3, 14, 14, minute, tzinfo=UTC), author, text)


def test_slack_json_file_and_directory(tmp_path):
    messages = [
        {"type": "message", "subtype": "channel_join", "user": "U1", "ts": "1773496800.000001", "text": "joined"},
        {"type": "message", "user": "U2", "ts": "1773496920.000003", "text": "second <@U1>"},
        {"type": "message", "user": "U1", "ts": "1773496860.000002", "text": "impact: a &amp; b\nstatus: <https://x.example.com|looking>"},
    ]
    single = tmp_path / "channel.json"
    single.write_text(json.dumps(messages))
    loaded = load_channel(single)
    assert [m.author for m in loaded] == ["U1", "U2"]  # sorted by time, join skipped
    assert loaded[0].text == "impact: a & b\nstatus: looking"

    export = tmp_path / "export"
    (export / "inc-1").mkdir(parents=True)
    (export / "users.json").write_text(json.dumps([{"id": "U1", "real_name": "Ada Example"}]))
    (export / "inc-1" / "2026-03-14.json").write_text(json.dumps(messages))
    loaded = load_channel(export)
    assert loaded[0].author == "Ada Example" and loaded[1].text == "second @Ada Example"


def test_text_transcript_with_continuation_lines(tmp_path):
    path = tmp_path / "inc.txt"
    path.write_text("[2026-03-14 14:03] Ada Example: first\n"
                    "2026-03-14T14:05:30Z bo: impact: logins failing\n"
                    "status: restarting\n\n")
    loaded = load_channel(path)
    assert loaded[0] == Message(datetime(2026, 3, 14, 14, 3, tzinfo=UTC), "Ada Example", "first")
    assert loaded[1].author == "bo" and loaded[1].text == "impact: logins failing\nstatus: restarting"


def test_channel_errors(tmp_path):
    with pytest.raises(InputError, match="cannot read"):
        load_channel(tmp_path / "missing.txt")
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    with pytest.raises(InputError, match="invalid JSON"):
        load_channel(bad)
    text = tmp_path / "notes.txt"
    text.write_text("just some notes\n")
    with pytest.raises(InputError, match="first line is not"):
        load_channel(text)


@pytest.mark.parametrize("text, stage", [
    ("Incident resolved, thanks all", "resolved"),
    ("not resolved yet", None),
    ("is it resolved?", None),
    ("Fix deployed, monitoring error rates", "monitoring"),
    ("rollback is complete", "monitoring"),
    ("turns out the pool size was cut", "identified"),
    ("rolling back now", "identified"),
    ("still digging through logs", None),
])
def test_stage_signal(text, stage):
    assert stage_signal(text) == stage


def test_markers_latest_value_wins_and_aliases():
    facts = extract_facts([
        msg(1, "sev: 3\nimpact: some logins slow\ncomponent: auth-api"),
        msg(2, "**Impact:** 40% of logins failing\n- affected: auth-api, session-cache\nETA: 15:00 UTC"),
        msg(3, "root cause: expired signing key\nneed: approval to rotate keys\nSeverity = SEV1"),
    ])
    assert facts.severity == "SEV1"
    assert facts.impact == "40% of logins failing"
    assert facts.components == ["auth-api", "session-cache"]
    assert facts.next_update == "15:00 UTC"
    assert facts.cause == "expired signing key" and facts.ask == "approval to rotate keys"
    assert facts.stage == "identified"  # a stated cause implies identified
    assert facts.people == ["Ada Example"]
    assert facts.started.minute == 1 and facts.as_of.minute == 3


def test_heuristics_without_markers():
    facts = extract_facts([
        msg(1, "paged, looks like a P2"),
        msg(2, "should this be a SEV1?"),
        msg(3, "about 30% of users can't log in", "Bo Sample"),
        msg(4, "customers also see slow search"),
        msg(5, "turns out the signing key expired"),
    ])
    assert facts.severity == "P2"  # the question does not change it
    assert facts.impact == "about 30% of users can't log in"  # first statement is kept
    assert facts.stage == "identified" and "14:05" in facts.stage_source
    assert facts.people == ["Ada Example", "Bo Sample"]
    assert facts.customer_impact == "" and facts.cause == ""


def test_stage_progression_explicit_stage_and_reopen():
    messages = [msg(1, "looking"), msg(2, "fix deployed, monitoring"), msg(3, "incident resolved")]
    facts = extract_facts(messages)
    assert facts.stage == "resolved" and facts.resolved_at.minute == 3
    reopened = extract_facts(messages + [msg(4, "stage: investigating\nerrors are back")])
    assert reopened.stage == "investigating" and reopened.resolved_at is None
    assert "stated at 14:04" in reopened.stage_source
    ignored = extract_facts([msg(1, "stage: celebrating")])
    assert ignored.stage == "investigating"


def test_no_messages():
    facts = extract_facts([])
    assert facts.stage == "investigating" and facts.started is None
