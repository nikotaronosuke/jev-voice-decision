[日本語](README.md) | English

# Jev Voice Decision

Jev Voice Decision is a Windows demo that turns Japanese speech into typed decisions with [TypeSafe](https://typesafe.ai/) Jev.

Japanese speech
→ local Parakeet JA STT
→ Jev typed decisions
→ deterministic Python actions.

It also demonstrates abstention when confidence is low.

> **Why these choices?** Read the [Owner Decision Log](docs/OWNER_DECISIONS.en.md) — model responsibility, abstention, local STT, minimal context, and non-persistence.

## What it does

- Three Jev questions are sent in one call: **Choice** (main intent: question / impression / request / other), **Noul** (does it need a reply?) and **Score** (priority on a 4-level rubric). Jev returns a selected option, the full probability distribution and a confidence value, never free text.
- Plain Python rules turn those decisions into an action (question queue, request list, feedback, record only). The rules are deterministic and shown on screen.
- When the Choice confidence is below the demo threshold, the app holds the decision and routes it to manual review instead of guessing.
- Audio stays local. Speech is transcribed on the machine (NVIDIA Parakeet JA via NeMo in WSL) and only the finalized transcript is sent to Jev. Nothing is written to disk.
- **Rapid Demo** sends 200 fictional Japanese inputs to the real Jev API with bounded concurrency and shows the results as they arrive. Nothing is precomputed.

## Demo video

A 30-second screen recording (voice input, the 200-item Rapid Demo and an abstention case) is attached to the [GitHub Release](https://github.com/nikotaronosuke/jev-voice-decision/releases). The GIF at the top of the Japanese README is taken from the same recording at real speed.

## Setup

See the Japanese README for the full instructions. In short: `TYPESAFE_API_KEY` in the environment (or an untracked `.env`), `uv pip install -e ".[dev]"`, then `scripts\run.ps1`. Voice Mode additionally needs a NeMo environment in WSL and a Parakeet JA checkpoint, configured through `JVD_PARAKEET_*` variables (see `.env.example`).

## License

MIT License. See [LICENSE](LICENSE).
