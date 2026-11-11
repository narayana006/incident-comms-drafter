# incident-comms-drafter

Draft the status page update, the executive summary and the support brief for an incident from an export of the incident channel, and check each draft against your house style.

**Status:** first working version (v0.1.0). It works from a file: a Slack export or a plain-text transcript of the channel. It reads the stage, severity and facts from the channel, drafts for customers, executives and support in all four stages, and applies house-style and banned-phrase rules. It does not connect to Slack yet (so `--channel` takes a path, not a channel name), and there is no Slack bot. Wording comes from fixed templates, not a language model.

It only ever prints drafts. There is no code path that posts anywhere; a person reviews, edits and sends every message.

## Why

During an incident the people who know what is happening are busy fixing it, so the status page goes stale and executives and support ask in the channel. Most of what those audiences need is already in the channel. This tool pulls it out and puts it into the right shape for each audience, with customer-safe wording kept separate from internal detail.

## Install

Requires Python 3.10 or newer. No dependencies on Python 3.11+; on 3.10 it installs `tomli` to read the style file.

```bash
pip install git+https://github.com/narayana006/incident-comms-drafter
```

## Quick start

The repository ships a fictional incident channel, captured part-way through the incident, and a house-style file.

```bash
git clone https://github.com/narayana006/incident-comms-drafter
cd incident-comms-drafter
incident-comms-drafter draft --channel examples/inc-2041.json \
  --style examples/house-style.toml --audience customers
```

```text
=== customers: status page update | stage: identified ===

Identified - Checkout errors

We have identified the cause of the issue affecting Checkout and are working on a fix. Some customers are seeing an error when they try to complete a purchase. Workaround: Retrying the payment after a minute usually succeeds. We will provide another update by 14:56 UTC.

The Example Shop team

--- review notes ---
- stage: inferred from 14:26 UTC "status: rolling back checkout-api to v2.40.3, should be fixed soon"
DRAFT ONLY - nothing has been sent. A person must review, edit and post this.
```

The same moment for executives (`--audience executives`; `--audience all` prints all three, see [examples/drafts/all-identified.txt](examples/drafts/all-identified.txt)):

```text
=== executives: executive summary | stage: identified ===

[SEV2] Checkout errors - Identified (as of 14:26 UTC)

Status: Identified | Severity: SEV2
Started: 2026-03-14 14:03 UTC | Duration so far: 23m
Customer impact: About 18% of checkout requests are failing with 503, 12 support tickets so far.
Cause: The orders-db connection pool was cut from 50 to 5 per pod in v2.41.0.
Current action: Rolling back checkout-api to v2.40.3, should be fixed soon.
Workaround: Retrying the payment after a minute usually succeeds.
Asks: None at this time.
Next update: 14:56 UTC

--- review notes ---
- stage: inferred from 14:26 UTC "status: rolling back checkout-api to v2.40.3, should be fixed soon"
- FIX: banned phrase "should be fixed soon" (never promise timing)
DRAFT ONLY - nothing has been sent. A person must review, edit and post this.
```

Note what happened there: the customer draft says "Checkout", not `checkout-api`, and leaves out the 18% figure and the cause; the executive summary keeps them. The engineer's "should be fixed soon" was copied into the executive summary and flagged, because the example house style bans promising timing.

Forty minutes later, from the full transcript:

```bash
incident-comms-drafter draft --channel examples/inc-2041-full.txt --style examples/house-style.toml
```

```text
=== customers: status page update | stage: resolved ===

Resolved - Checkout errors

The issue affecting Checkout has been resolved. The issue lasted from 14:03 to 14:45 UTC. We apologize for the disruption.

The Example Shop team

--- review notes ---
- stage: inferred from 14:45 UTC "Error rate back to normal for 10 minutes. Incident resolved."
- start time is the first channel message (14:03 UTC); correct it if the impact began earlier
- replaced "apologise" with "apologize" (US spelling)
DRAFT ONLY - nothing has been sent. A person must review, edit and post this.
```

## How facts are read from the channel

The most reliable input is a `key: value` line posted in the channel by whoever is running the incident. Each may be on its own line of a longer message, and the latest value wins:

```text
[2026-03-14 14:07] Mei Okafor: title: Checkout errors
components: checkout-api
impact: about 18% of checkout requests are failing with 503, 12 support tickets so far
customer impact: some customers are seeing an error when they try to complete a purchase
workaround: retrying the payment after a minute usually succeeds
```

| Line | Used for |
| --- | --- |
| `title:` | Headline of every draft. |
| `components:` (or `affected:`) | Comma-separated list. Mapped to customer-facing names by the style file. |
| `impact:` | Internal impact statement. Executives and support only. |
| `customer impact:` | The impact wording approved for customers. Without it, customers get a generic sentence and the review notes say so. |
| `cause:` (or `root cause:`) | Executives only. Never shown to customers. |
| `status:` | What is being done right now. Executives only. |
| `workaround:` | All audiences (customers see it while the incident is being investigated or fixed). |
| `next update:` (or `eta:`) | Otherwise the last message time plus the style's update interval. |
| `severity:` (or `sev:`), `stage:` | Override what would otherwise be inferred. |
| `ask:` (or `need:`) | What you need from executives. Executives only. |

Without those lines the tool falls back to keyword rules:

- **Stage** is taken from the latest message that signals one: "resolved" / "all clear" means resolved; "fix deployed", "rollback is complete", "monitoring" means monitoring; "root cause", "turns out", "rolling back" means identified; otherwise investigating. Negations ("not resolved yet") and questions are ignored. The review notes always quote the message the stage came from.
- **Severity** is the latest `SEV0`-`SEV5` or `P0`-`P5` mentioned outside a question.
- **Impact** is the first message that mentions customers, users or requests together with a failure word or a percentage.

## Commands

### `draft`

```
incident-comms-drafter draft --channel PATH [--audience customers|executives|support|all]
                             [--stage auto|investigating|identified|monitoring|resolved]
                             [--style FILE] [--severity SEV] [--title TEXT] [--as-of TIME]
                             [--format text|json] [--strict]
```

- `--channel` is a Slack export (a JSON file of messages, or an export directory with `users.json`) or a text transcript with one `YYYY-MM-DD HH:MM name: message` line per message. Lines without a timestamp continue the previous message.
- `--as-of 2026-03-14T14:10:00Z` ignores later messages, to see what the draft would have been at that point.
- `--format json` prints the extracted facts and the drafts, for a script or bot to pick up. It always includes `"sent": false`.
- `--strict` exits with status 1 if any draft has a house-style violation, so a wrapper can refuse to offer it for posting.

Lines in the review notes that start with `FIX:` are problems a person must resolve before sending.

### `check`

Checks any text against the house style, for updates written by hand:

```bash
incident-comms-drafter check examples/bad-update.txt --style examples/house-style.toml
```

```text
would be replaced "outage" with "disruption"
FIX: banned phrase "unfortunately"
FIX: internal term "orders-db" in a customer-facing draft
FIX: promises a resolution time: "will be fixed shortly"
FIX: assigns blame: "someone pushed"
```

Exit status is 1 when anything is found. Use `-` to read from stdin and `--audience` to choose which rules apply.

## House style file

TOML; every setting is optional. The annotated example is [examples/house-style.toml](examples/house-style.toml).

| Setting | Meaning |
| --- | --- |
| `product` | Used when no component is named. |
| `update_interval_minutes` | Gap promised before the next update (default 30). |
| `max_length` | Character limit for a customer update (default: none). |
| `apology`, `sign_off` | Closing sentence of a resolved update; line appended to every customer update. |
| `[components]` | Internal component name to customer-facing name. |
| `internal_terms` | Words that must never appear in a customer-facing draft. |
| `[[banned]]` | `phrase`, plus optional `replace` (swap it automatically), `reason`, and `audiences` (limit the rule to some audiences). Whole words, case-insensitive. |

Customer-facing drafts are also checked against built-in rules whether or not you supply a file: no promised resolution time ("will be fixed shortly"), no internal addresses, no blame ("human error", "someone pushed"), and no names of people who posted in the channel.

## Features

- [x] Reads an incident channel export (Slack JSON or text transcript) and the current severity
- [x] Drafts status page updates for the investigating, identified, monitoring and resolved stages
- [x] Separate drafts for customers, executives and support
- [x] House style and banned-phrase rules you define, plus a `check` command for hand-written text
- [x] Drafts only: a person approves and sends every message
- [ ] Read a live Slack channel by name
- [ ] Slack bot that offers the draft in the channel
- [ ] Optional rewording by a language model behind the same house-style checks

## Limitations

- Templates are fixed English sentences. The drafts are correct and plain rather than polished; expect to edit them.
- Stage, severity and impact inference is keyword matching and can be wrong, especially in a noisy channel. Structured `key: value` lines are far more reliable, and `--stage` overrides the guess.
- The incident start time is the time of the first message in the export, which is usually a few minutes after the real start. The resolved draft says so in its review notes.
- Free text from the channel (`customer impact:`, `workaround:`) goes into the customer draft as written. The style checks catch listed terms and common mistakes, not everything that should stay internal.
- One channel is one incident. Times are shown in UTC.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Contributing

Issues and pull requests are welcome. Reports of a stage or severity that was inferred wrongly are especially useful: include the message text (anonymised) and what it should have been.

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
