# Structured-extraction model trial

## Status

Complete. `openai/gpt-oss-120b` on Groq is selected for the initial extraction
adapter. It was the only configured candidate and passed all six labeled
development cases using Groq strict structured output.

## Fixed comparison protocol

Each available candidate model will receive the same preserved blocks for the
six cases in `development-cases.yaml`, the same extraction instructions, and the
same JSON schema version. Applicant profile data is excluded.

Record for every run:

- provider and exact model identifier;
- prompt and schema hashes;
- valid structured output on the first attempt;
- evidence block IDs that exist in the supplied document;
- correct programme, year, application type, actor, action, and date;
- unsupported or conflicting facts left unresolved;
- input/output tokens, calls, latency, and provider-reported cost when available.

## Selection rule

Reject a model if it fabricates evidence IDs, merges different actors, treats a
correction window as a submission extension, or resolves the PM-USP conflict by
recency alone. Among models that pass those gates, choose the lowest-cost model
with the strongest citation support and schema reliability. Record the chosen
identifier and prompt version in this file after the trial.

Held-out cases must not be used for this choice.

## Selected-run record

- Run time: 2026-10-02T16:59:21Z
- Provider: Groq
- Model: `openai/gpt-oss-120b`
- Prompt version: `phase0-deadline-extraction-v1`
- Prompt SHA-256: `fafb6c44e43a1c92cbfbd6d2ed44407c62705314164bf711b26218f61c377978`
- Schema SHA-256: `eda1806cb4891f1dd77ec7bec9ba15e23a2c68769e807c8a7818e3e7cb717610`
- Structured-output mode: strict JSON Schema
- Calls: 6 model calls, 0 SerpApi calls
- Usage: 10,858 prompt tokens; 2,542 completion tokens; 13,400 total tokens
- Provider-reported cost: unavailable; the account is on Groq's free plan
- Model latency measured by the runner: 9,970 ms total

Fifteen earlier bounded API attempts were used while reducing oversized inputs,
handling the free-plan token window, and refining field definitions. They are
recorded separately from the selected fixed-prompt run. No credential or full
prompt is stored in the result artifact.

| Development case | Expected resolution | Result |
| --- | --- | --- |
| NMMSS 2026 actor separation | supported | pass |
| NMMSS 2025 historical extension | supported | pass |
| NOS correction is not submission | insufficient | pass |
| PM-USP renewal conflict | conflicting | pass |
| Pragati deadline roles | supported | pass |
| Top Class ST deadline roles | supported | pass |

The validation checks confirmed that cited block IDs exist, every emitted date
or duration occurs in a cited block, student submission and correction remain
separate, institute and administrator dates remain separate, and the PM-USP
conflict is not resolved merely by choosing the later date. The detailed,
redacted record is in `results/model-trial-results.json`.

This is a development-set choice, not a claim of production accuracy. Phase 2
must add held-out evaluation, broader source templates, and failure regressions.
