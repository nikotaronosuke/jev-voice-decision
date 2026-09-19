# Owner Decision Log

[日本語](OWNER_DECISIONS.md) | English

Three decisions are worth keeping here because they define the actual model boundary rather than restating feature specs.

## 1. Used Jev for typed decisions, not answer generation

The demo was not built as speech → LLM → generated reply.

Jev is limited to:

- intent: Choice
- needs_response: Noul
- priority: Score

The later action — question queue, request list, feedback, record only — is ordinary deterministic Python.

The ambiguous interpretation is model-owned; the application rule is not.

**Evidence:** [Phase 1](https://github.com/nikotaronosuke/jev-voice-decision/commit/0ed06101a07ac38d30f1fd4a5fb540afee993b94)

## 2. Did not force a classification when confidence is low

A Choice result always has a top option, but taking it at low confidence would mean deciding when the model is unsure.

Below the demo threshold, the app holds the decision for manual review.

The threshold is explicitly labelled a **demo threshold**, not a benchmark-optimized optimum.

**Evidence:** current implementation / README

## 3. Kept Rapid Demo live instead of precomputing results

Precomputing 200 outputs would make the demo smoother but would stop proving live Jev decisions.

Rapid Demo sends the fictional inputs to the real API, displays results as they return, and reduces / pauses new work when rate limits appear.

The priority was showing actual provider behavior rather than perfect playback.

**Evidence:** [Rapid Demo](https://github.com/nikotaronosuke/jev-voice-decision/commit/107f4ca)
