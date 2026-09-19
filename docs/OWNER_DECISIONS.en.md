# Owner Decision Log

[日本語](OWNER_DECISIONS.md) | English

Jev Voice Decision is not a demo where speech is sent to an AI to generate a reply.

The design goal is narrower:

> turn ambiguous Japanese utterances into **small typed decisions that software can use directly**, then return control to ordinary deterministic code.

This document records the project-owner decisions behind that boundary.

---

## 1. Ask Jev for decisions, not generated answers

### Problem

The obvious voice-AI demo architecture is:

```text
speech → LLM → generated reply
```

But many software systems do not need prose.
They need small branching decisions such as:

- is this a question?
- does it need a response?
- how urgent is it?

### Decision

Jev returns typed primitives only:

- **Choice**
- **Noul**
- **Score**

The output is used as structured decision data rather than user-facing generated prose.

**Evidence:** Japanese README / [Phase 1](https://github.com/nikotaronosuke/jev-voice-decision/commit/0ed06101a07ac38d30f1fd4a5fb540afee993b94)

---

## 2. Keep model judgement separate from deterministic action rules

### Problem

After Jev classifies an utterance, the model could also decide what operational action to perform.

That would make the action policy less visible and less deterministic.

### Decision

Jev handles the ambiguous interpretation.

Plain Python handles the action.

Examples:

- question + response required → question queue
- request → request list
- impression → feedback
- other → record only

The model does not own the whole workflow.

**Evidence:** `app/actions.py` / Japanese README

---

## 3. Treat low confidence as a reason to abstain

### Problem

A Choice result always has a top option.

Always selecting the top option would make every utterance look automatically classifiable,
even when the distribution is weak or ambiguous.

### Decision

Below the demo confidence threshold, the app chooses:

> **hold / manual review**

Abstention is a normal safe outcome, not a failure of the demo.

---

## 4. Do not present the demo threshold as a validated optimum

### Problem

A threshold such as 0.5 can easily be mistaken for a benchmark-derived optimal cutoff.

### Decision

The code and README explicitly call it a **demo threshold**.

The UI shows:

- Jev's output distribution
- confidence
- typed decision

It does not claim benchmark accuracy or display a "validated" success rate.

This repository demonstrates the software pattern, not an optimized classifier.

---

## 5. Keep audio local and send only the final transcript to Jev

### Problem

Uploading raw audio would make the pipeline simpler,
but Jev only needs the text used for the decision.

### Decision

Speech recognition runs locally with Parakeet JA.

Only the final transcript is sent to Jev.

Raw PCM audio is not sent to the decision provider.

The UI explicitly tells the user that audio is processed locally.

**Evidence:** [voice-mode implementation](https://github.com/nikotaronosuke/jev-voice-decision/commit/75d503c4e0af91a4fe54a5f425137681fe32598d)

---

## 6. Use push-to-talk instead of always-on listening

### Problem

Always-on listening looks more "real time," but it adds responsibilities unrelated to the core experiment:

- unclear recording boundaries
- irrelevant audio collection
- voice activity / segmentation logic
- additional privacy surface

### Decision

Voice Mode is explicit push-to-talk:

> start recording → stop → transcribe → decide

The demo focuses on the decision boundary instead of building a continuous listening system.

---

## 7. Send one final decision request instead of streaming every partial transcript

### Problem

Sending each partial STT update to Jev would create:

- more API calls
- decisions that oscillate with partial recognition changes
- multiple decision events for one utterance

### Decision

The app waits for the final transcript and sends it **once**.

Speech-recognition progress and the software decision event remain separate concepts.

---

## 8. Keep the Jev context intentionally small

### Problem

It is always possible to add more context:

- history
- user profile
- previous comments
- additional metadata

That might improve some decisions, but it also expands the privacy surface and makes the experiment harder to interpret.

### Decision

The request context is intentionally minimal:

- channel
- language
- utterance

The first question was whether the decision task could work with only the context it actually needs.

---

## 9. Do not persist audio, transcript, decision, or session history

### Problem

Persistence would enable replay, analytics, and later dataset construction.

But none of those were required to prove this demo.

### Decision

The app does not persist:

- audio
- transcript
- Jev response
- API request
- session history

Data lives in process memory and disappears when the process ends.

The STT worker also does not receive the API credential.

Provider error bodies are not exposed directly in the UI.

---

## 10. Do not fake the Rapid Demo with precomputed results

### Problem

A 200-item demo could be made extremely smooth by precomputing decisions and replaying them.

That would no longer demonstrate live Jev decisions.

### Decision

Rapid Demo sends fictional comments to the real API and renders results as they return.

Results are not precomputed or persisted.

Concurrency is bounded, and rate-limit responses reduce / pause new work rather than triggering uncontrolled parallel calls.

**Evidence:** [Rapid Demo](https://github.com/nikotaronosuke/jev-voice-decision/commit/107f4ca)

---

## 11. Do not turn this demo into an accuracy / latency / cost ranking

### Problem

A public model demo invites claims such as:

- more accurate than model X
- faster than model Y
- cheaper than model Z

This repository did not run a controlled comparative benchmark that would support those claims.

### Decision

The README explicitly excludes:

- model ranking
- accuracy benchmark
- latency ranking
- cost ranking
- "N× faster" claims

The demonstrated claim is narrower:

> Japanese speech can be transcribed locally, converted into Jev typed decisions, and connected to deterministic application actions.

That is enough for this repository.

---

## What this project prioritizes

Jev Voice Decision prioritizes:

- typed decisions over answer generation
- deterministic application rules after model judgement
- abstention over forced classification
- honest demo thresholds
- local audio processing
- explicit recording boundaries
- one final decision event per utterance
- minimal provider context
- no unnecessary history persistence
- real API demo behavior instead of precomputed playback
- no performance claims without a benchmark

AI-assisted implementation was used during development.

The important design choice is **keeping the model's responsibility small enough to reason about**.
