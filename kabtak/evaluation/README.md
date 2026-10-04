# Evaluation

This directory contains development and held-out case manifests, bounded preserved
inputs, evaluation runners, and versioned results. Copies and amendment chains stay
in the same split.

`phase0/` contains the initial source-access and extraction experiment. Its raw
downloads are written under ignored `data/phase0/`; only bounded probe metrics,
source metadata, and manually labeled expected decisions belong in Git.

`phase5/` is the reproducible release evaluation. It contains 12 development and
8 held-out real-notice cases, the production-pipeline runner, a same-model
single-prompt baseline, critical regression checks, and the measured report.
