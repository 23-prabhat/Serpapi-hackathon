# Historical replay fixtures

This directory contains permitted, dated, offline fixtures with preserved
evidence blocks, reviewed structured results, expected reports, and frozen
reference times. Replays never make SerpApi, source-site, or model calls.

Each replay validates its packaged extraction against the preserved blocks, runs
the current deterministic reporting rules, and records whether that result still
matches the reviewed expected report. A mismatch is displayed as a replay
regression rather than silently returning the stored answer.

Use the website's `/examples` route to materialize a fixture as an isolated
local check. The resulting report is labeled as a historical replay, keeps its
reference time, supports the normal evidence inspector, and can be saved or
deleted like any other terminal check.
