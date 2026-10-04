# Phase 5 evaluation

This evaluation freezes 20 questions over official scholarship notices: 12
development cases and 8 held-out cases. NMMSS, PM-USP, and NOS source families are
development data; Pragati and Top Class ST are held out. No source, copy, or
amendment chain crosses the split.

The committed source file contains bounded, manually reviewed passages from the
preserved Phase 0 downloads. The system path runs the production Groq structured
extractor once per document/requested application-type pair and then the current
deterministic report rules. The baseline sends each case and the same source blocks
to a single summarization prompt using the same configured Groq model and output
requirements. Neither path uses SerpApi. Measured outcomes and limitations are in
[`report.md`](report.md).

From `kabtak/backend`:

```bash
uv run python ../evaluation/phase5/run_evaluation.py --mode all
uv run python ../evaluation/phase5/run_evaluation.py --mode all --offline
uv run pytest ../evaluation/phase5/tests
```

The online command checkpoints completed calls. The offline command reproduces
the deterministic system result from committed extraction outputs and reads the
committed baseline result without credentials, network calls, or changes to the
tracked result artifacts.
