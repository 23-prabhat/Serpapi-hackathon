# Phase 0 — source and extraction proof

This experiment answers four questions before the full application is built:

1. Can five bounded programmes be tied to reviewed official source policies?
2. Can representative HTML and text PDFs be downloaded and parsed while
   preserving headings, page numbers, and table rows?
3. Can the expected actor, action, academic year, and applicant type be labeled
   independently of an LLM?
4. Are SerpApi and model credentials available for a controlled extraction trial?

## Run the source probe

From `kabtak/backend` after `uv sync --dev`:

```bash
uv run python ../evaluation/phase0/probe_sources.py
uv run pytest ../evaluation/phase0/tests
```

Raw downloads and full parsed blocks go to ignored `kabtak/data/phase0/`.
The committed result contains hashes, parser metrics, outcomes, and only short
candidate excerpts. This is an experiment over fixed reviewed URLs, not the
production URL retriever or a claim that every source is safe to fetch.

## Phase gate

Do not mark a programme supported merely because it returned HTTP 200. The
programme becomes ready only after its source authority, current cycle, expected
facts, evidence locations, and parser behavior have all been reviewed.

## Run the bounded model trial

After configuring `LLM_PROVIDER=groq`, `LLM_MODEL`, and `LLM_API_KEY` in the
backend `.env`, run:

```bash
uv run python ../evaluation/phase0/model_trial.py
```

The trial makes one structured-output request for each of the six development
cases, never calls SerpApi, and refuses to exceed six model calls. It uses the
preserved parsed blocks in `data/phase0/` and writes redacted, reproducible
metrics and structured outputs to `results/model-trial-results.json`.
Completed cases are checkpointed. If Groq's free-plan token window returns HTTP
429, wait for the window to reset and run the same command again; only unfinished
cases are submitted.
