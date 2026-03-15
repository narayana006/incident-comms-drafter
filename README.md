# incident-comms-drafter

Draft status page updates and stakeholder messages during an incident from the live incident channel.

> **Project status: planning. There is no working code in this repository yet.**
> This README describes what the project will do. Nothing below can be installed or run today.
> Features are ticked off in the checklist as they are built.

## What it is

A command-line tool and Slack bot.

**The problem it solves:** Customer communication slips during incidents because the people who know what is happening are busy fixing it.

## Who it is for

Incident commanders and communications leads.

## How it will work

1. You point the tool at the incident channel.
2. It reads the latest facts and drafts an update for the audience you choose.
3. A person reviews, edits and sends it; the tool never posts by itself.

## Planned features

Unticked items are not built yet.

- [ ] Reads the incident channel and current severity
- [ ] Drafts status page updates in investigating, identified, monitoring and resolved stages
- [ ] Separate drafts for customers, executives and support
- [ ] House style and banned-phrase rules you define
- [ ] Drafts only: a person approves and sends every message

## Planned usage

This is the intended interface, shown so you can judge the design. **It does not work yet**, and names may change before the first release.

```bash
incident-comms-drafter draft --channel inc-2041 --audience customers
```

## Contributing

Feedback on the design is the most useful contribution right now. Open an issue to suggest a feature, question an approach or describe your use case. Code contributions are welcome once the first version lands.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)
