# Phase 5 evaluation report

**Evaluation date:** October 3–4, 2026  
**Model:** `openai/gpt-oss-120b` through Groq  
**Evaluation kind:** held-out-informed regression  
**External discovery calls:** 0 SerpApi calls

## Scope and method

The frozen manifest contains 20 real-notice questions: 12 development cases and
8 held-out cases. The questions use synthetic applicant profiles where a profile
is needed. NMMSS, PM-USP, and NOS documents are development data; AICTE Pragati
and Top Class ST documents are held out. Copies and conflicting PM-USP passages
remain in one split. The set covers five programmes, four government providers,
HTML release/scheme-card/announcement templates, and a PDF guideline excerpt.

The system path sends each unique document/requested-application-type pair through
the production structured extractor, validates its evidence, and applies the
current deterministic deadline and eligibility rules. Repeated profile and timing
questions reuse the same extraction, resulting in 11 logical model inputs.

The baseline is a single-prompt summarizer. Each of the 20 cases is an independent
call over the same source blocks, configured model, deadline-role definitions, and
structured output requirements. It does not use the system's extraction cache or
deterministic rules. Neither path uses live search in this evaluation.

## Results

Outcomes are mutually exclusive. `correct` means a supported answer passed every
ground-truth and citation check. `incorrect` means a supported answer failed one
or more checks. `unresolved` means the path returned conflicting or insufficient.
`failed` means no valid output was produced. Ground-truth matches count correctly
handled conflicts and insufficiency as matches even though they remain unresolved.

| Path | Cases | Correct | Incorrect | Unresolved | Failed | Ground-truth matches | Answered accuracy | Answerable coverage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Kabtak system | 20 | 17 | 0 | 3 | 0 | 20/20 | 100% (17/17) | 100% (17/17) |
| Single-prompt baseline | 20 | 8 | 3 | 7 | 2 | 11/20 | 72.73% (8/11) | 64.71% (11/17) |

The system's three unresolved cases are expected: the two official PM-USP pages
conflict for renewal, the supplied PM-USP passages do not establish a fresh
deadline, and the NOS guideline gives durations but no exact date. Development
ground truth matched 12/12 and held-out regression ground truth matched 8/8.

The baseline's three incorrect answers omitted or misclassified required report
facts. Four answerable cases were unresolved, and two Top Class ST calls failed
after bounded provider retries. The three genuinely unanswerable development cases
were correctly unresolved.

## Computation

| Path | Logical model inputs | Successful response attempts recorded | Prompt tokens | Completion tokens | Total tokens | Recorded model time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Kabtak system | 11 | 14 | 30,855 | 9,063 | 39,918 | 35.543 s |
| Single-prompt baseline | 20 | 18 successful outputs | 18,775 | 5,751 | 24,526 | 171.212 s for recorded case attempts |

The system uses fewer logical calls because extraction is reusable, but its strict
schema and corrective validation retries consume more tokens. Provider-reported
token totals exclude rejected HTTP 429 attempts. The baseline made 20 logical case
attempts; two ended as failures after retries, so they have no token usage record.
Groq did not return a cost figure, and no cost is inferred.

## Citation support review

All 20 system reports passed automatic reference-existence and date-in-cited-block
checks. The 11 unique structured extractions were then manually compared with the
bounded passages. Student submission, student correction, institution
verification, administrator verification, conflict candidates, and inclusive
income thresholds were entailed by their cited passages. Manual support result:
**20/20 system cases supported**.

All 18 baseline outputs that were produced also cited existing blocks containing
their reported dates. This is only a support finding; it does not make the nine
baseline ground-truth mismatches correct. The two failed baseline cases emitted no
claims to inspect.

## Severe gaps fixed

Held-out inspection informed material changes, so the final numbers are explicitly
regression results rather than untouched held-out estimates.

1. The HTML parser discarded NSP's active academic year because it was inside
   navigation. It now preserves only a bounded `Academic Year YYYY-YY` document
   context before removing page chrome.
2. Evidence validation rejected NSP's unqualified fresh schedule convention. It
   now accepts the reviewed template only when a student-application field is
   present and no renewal qualifier occurs.
3. NSP `DNO/SNO/MNO Verification` is now validated as administrator verification,
   and `Defective Application Verification` as student correction.
4. The production extraction prompt now defines those NSP roles and requires every
   listed schedule field. The first completed system pass was 13 correct, 4
   incorrect, and 3 unresolved (16/20 ground-truth matches). After the disclosed
   prompt fix and a full-cache invalidation, the regression pass reached the final
   17 correct, 0 incorrect, and 3 unresolved result.
5. Groq 429 handling now observes bounded reset hints, and the extraction completion
   ceiling was reduced to fit the reviewed outputs within the free-tier token
   window.

## Critical verification

- Backend, Phase 0, and Phase 5: 86 tests passed; 81% application coverage.
- Critical rules: actor separation, scope isolation, amendments, conflicts,
  date-only timing, eligibility unknowns, and evidence rejection passed.
- Job recovery: stale work becomes interrupted, a fresh run stays active, and an
  old owner token cannot overwrite recovered state.
- Refresh/retry/deletion: idempotent refresh, active-run exclusion, retry, cascade
  deletion, shared-source retention, and cleanup passed.
- Frontend: ESLint, TypeScript, and the Next.js production build passed.
- Browser: 4 Playwright tests passed for required widths/keyboard access,
  historical replay and evidence, save-refresh-delete, and unresolved conflict.
- Offline reproduction returned the same system and baseline summaries with no
  external calls.

## Support decision and limitations

At the time this frozen evaluation was run, NMMSS was the only public live
programme. After the recorded evaluation, PM-USP, NOS, Pragati, and Top Class ST
were promoted through the shared live admission/search/pipeline path using their
already reviewed policies and passing evaluation cases. This note records the
later product change without rewriting the frozen result. Azim Premji remains
deferred because stable direct retrieval was not available.

Limitations:

- Twenty questions are drawn from seven bounded official documents, so repeated
  profile/timing questions are not 20 independent source discoveries.
- This measures extraction and deterministic decisions over preserved passages;
  it does not measure whether live search rediscovers every source today.
- The final held-out result is a regression result because held-out cases informed
  parser and prompt fixes. A new untouched set is needed for an unbiased estimate.
- NOS duration facts are visible in the source but the production report schema
  currently reports only that no exact deadline was established.
- Provider rate limits caused two baseline failures and make live runtime
  nondeterministic. Offline reproduction avoids this but does not retest Groq.
- Citation review establishes support for these bounded claims, not general source
  truth, programme eligibility, user adoption, or measured time savings.

Machine-readable inputs and results are in `cases.yaml`, `sources.yaml`, and the
`results/` directory. See `README.md` for online and offline commands.
