# Phase 0 status

**Reference time:** 2026-10-02, Asia/Kolkata

## Source selection

Five programmes are in the selected onboarding set. All have an official issuer
or application-portal source for a 2026-27 cycle that the backend probe parsed.
The registry retains the reviewed `phase0_selected` onboarding marker; the live
support policy now promotes every entry with that marker to `live_supported`.

| Programme | Current-cycle source | Primary proof case | Initial concern |
| --- | --- | --- | --- |
| NMMSS | PIB and NSP | Explicit extension with three actor deadlines | Fresh and renewal are both mentioned |
| PM-USP CSSS | NSP and Ministry of Education | Renewal scope and same-host deadline conflict | September 30 versus October 31 |
| AICTE Pragati | NSP and AICTE | Student/correction/institute/admin separation | Older issuer FAQs must not leak into 2026-27 |
| National Overseas Scholarship | Ministry portal and guidelines | Submission versus correction window | First round has passed |
| Top Class ST | NSP and Ministry of Tribal Affairs | Student/correction/institute/admin separation | Scheme naming changed over time |

Azim Premji Scholarship was reviewed but deferred from the initial five because
direct retrieval returned HTTP 403. Search indexing alone is not sufficient for
backend support.

## Source probe result

The 2026-10-02 run attempted 12 fixed official URLs:

- 10 parsed successfully across all five selected programmes.
- HTML heading/table parsing was verified on the NMMSS PIB releases.
- HTML scholarship-card parsing preserved programme scope with all NSP dates.
- Text-PDF parsing preserved page numbers and tables for PM-USP, Pragati, NOS,
  and Top Class ST documents.
- The NOS portal timed out, so its exact first-round date is not supported by
  the retrieved guideline alone; the case is correctly labeled insufficient.
- The Azim Premji page returned HTTP 403 and remains deferred.
- The 31-page Top Class ST guideline exceeded the 20-page experiment limit and
  is explicitly recorded as partial rather than silently treated as complete.

Machine-readable results are in `results/probe-results.json`. Raw responses and
full blocks remain in ignored `data/phase0/`.

## Credentials and budget

Credentials were verified without recording their values:

- SerpApi reports an active Free Plan with 250 searches remaining at the check.
- Groq authentication succeeds and exposes `openai/gpt-oss-120b`.
- The bounded development ceiling is 40 SerpApi searches and 100 model calls,
  below the observed account allowances. Runtime caps remain four search
  attempts and six model attempts per run.
- The selected fixed-prompt model trial used six Groq calls and 13,400 tokens.
  It made zero SerpApi calls. Fifteen earlier bounded attempts were used for
  input-size, rate-limit, and prompt/schema refinement.
- Free-plan rate limiting was observed, so the trial runner checkpoints each
  completed case and safely resumes unfinished cases.

## Exit criteria

- The fixed prompt/schema trial passes all six labeled development cases.
- `openai/gpt-oss-120b` is selected as the only configured candidate.
- All five selected programmes have reviewed source authority, current-cycle
  scope, parser evidence, and at least one passing development case.
- Phase 0 is complete. The persisted pipeline and later evaluation gates have
  now promoted all five selected programmes to the public live workflow.
