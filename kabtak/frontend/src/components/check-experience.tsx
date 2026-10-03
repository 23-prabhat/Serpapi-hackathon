"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import type {
  ApiError,
  CheckAccepted,
  Deadline,
  Evidence,
  EvidenceReference,
  Programme,
  Report,
  Run,
} from "@/lib/api/types";

const STAGES = [
  ["searching", "Finding reviewed sources"],
  ["fetching", "Saving source snapshots"],
  ["extracting", "Reading deadline claims"],
  ["checking", "Applying deadline rules"],
  ["finalizing", "Building your report"],
] as const;

type Screen = "form" | "running" | "report";

async function readJson<T>(response: Response): Promise<T> {
  const body = (await response.json()) as T & ApiError;
  if (!response.ok) {
    throw new Error(body.error?.message ?? "Something went wrong. Please try again.");
  }
  return body;
}

function pretty(value: string) {
  return value.replaceAll("_", " ");
}

function formatDeadline(deadline: Deadline) {
  const day = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${deadline.date}T00:00:00+05:30`));
  return deadline.time ? `${day}, ${deadline.time}` : day;
}

function formatRetrievedAt(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "Asia/Kolkata",
  });
}

function evidenceTableHeaders(item: Evidence) {
  const headers = item.metadata?.headers;
  return Array.isArray(headers) && headers.every((header) => typeof header === "string")
    ? headers
    : [];
}

export function CheckExperience() {
  const [screen, setScreen] = useState<Screen>("form");
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [programmeId, setProgrammeId] = useState("nmmss");
  const [academicYear, setAcademicYear] = useState("2026-27");
  const [applicationType, setApplicationType] = useState("fresh");
  const [noticeUrl, setNoticeUrl] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [error, setError] = useState("");
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let active = true;
    fetch("/api/v1/programmes")
      .then((response) => readJson<Programme[]>(response))
      .then((items) => {
        if (!active) return;
        setProgrammes(items);
        const firstSupported = items.find(
          (item) => item.support_status === "phase1_supported",
        );
        if (firstSupported) {
          setProgrammeId(firstSupported.id);
          setAcademicYear(firstSupported.supported_cycles.at(-1) ?? "2026-27");
          setApplicationType(firstSupported.application_types[0] ?? "fresh");
        }
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => {
      active = false;
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  async function loadReport(runId: string) {
    const response = await fetch(`/api/v1/runs/${runId}/report`);
    const result = await readJson<Report>(response);
    setReport(result);
    setScreen("report");
    const firstReference = result.student_deadline?.evidence_refs[0];
    if (firstReference) {
      await loadEvidence(runId, firstReference);
    }
  }

  async function pollRun(runId: string, delay = 0) {
    pollTimer.current = setTimeout(async () => {
      try {
        const response = await fetch(`/api/v1/runs/${runId}`);
        const nextRun = await readJson<Run>(response);
        setRun(nextRun);
        if (nextRun.status === "completed") {
          await loadReport(runId);
        } else if (nextRun.status === "failed" || nextRun.status === "interrupted") {
          const message =
            typeof nextRun.error?.message === "string"
              ? nextRun.error.message
              : "The check could not be completed.";
          setError(message);
        } else {
          await pollRun(runId, 2_000);
        }
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Polling failed.");
      }
    }, delay);
  }

  async function submitCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setEvidence(null);
    setReport(null);
    setRun(null);
    setScreen("running");

    try {
      const response = await fetch("/api/v1/checks", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          programme_id: programmeId,
          academic_year: academicYear,
          application_type: applicationType,
          notice_url: noticeUrl || null,
          save: false,
        }),
      });
      const accepted = await readJson<CheckAccepted>(response);
      await pollRun(accepted.run_id, accepted.poll_after_ms);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the check.");
      setScreen("form");
    }
  }

  async function loadEvidence(runId: string, reference: EvidenceReference) {
    setLoadingEvidence(true);
    setError("");
    try {
      const response = await fetch(
        `/api/v1/runs/${runId}/evidence/${encodeURIComponent(reference.version_id)}/${encodeURIComponent(reference.block_id)}`,
      );
      setEvidence(await readJson<Evidence>(response));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not load evidence.");
    } finally {
      setLoadingEvidence(false);
    }
  }

  async function showEvidence(reference: EvidenceReference) {
    if (!report) return;
    await loadEvidence(report.run_id, reference);
  }

  function reset() {
    if (pollTimer.current) clearTimeout(pollTimer.current);
    setError("");
    setEvidence(null);
    setReport(null);
    setRun(null);
    setScreen("form");
  }

  if (screen === "running") {
    const stage = run?.stage ?? "queued";
    const activeIndex = STAGES.findIndex(([key]) => key === stage);
    return (
      <section className="workspace status-layout" aria-live="polite">
        <div className="section-number">02 / CHECKING</div>
        <div className="status-card brutal-card">
          <div className="loader-mark" aria-hidden="true"><span /><span /><span /></div>
          <p className="eyebrow">Live evidence run</p>
          <h2>We’re checking the record.</h2>
          <p className="muted">
            One local worker is searching, preserving, and checking the source trail.
          </p>
          <ol className="stage-list">
            {STAGES.map(([key, label], index) => {
              const done = activeIndex > index || stage === "finished";
              const active = stage === key || (stage === "queued" && index === 0);
              return (
                <li className={done ? "done" : active ? "active" : ""} key={key}>
                  <span>{done ? "✓" : String(index + 1).padStart(2, "0")}</span>
                  {label}
                </li>
              );
            })}
          </ol>
          {error && <ErrorBox message={error} />}
          {error && <button className="secondary-button" onClick={reset} type="button">Back to form</button>}
        </div>
      </section>
    );
  }

  if (screen === "report" && report) {
    const deadline = report.student_deadline;
    const tableHeaders = evidence ? evidenceTableHeaders(evidence) : [];
    return (
      <section className="workspace report-layout">
        <div className="section-number">03 / REPORT</div>
        <div className="report-head">
          <div>
            <p className="eyebrow">{report.scope.programme_name}</p>
            <h2>Your checked answer.</h2>
          </div>
          <button className="secondary-button" onClick={reset} type="button">New check ↗</button>
        </div>

        <div className="conclusion-evidence-grid">
          <article className="answer-card brutal-card">
            <span className={`resolution resolution-${report.deadline_resolution}`}>
              {pretty(report.deadline_resolution)}
            </span>
            <p className="answer-label">Student submission deadline</p>
            <h3>{deadline ? formatDeadline(deadline) : "Not established"}</h3>
            {deadline && <p className="deadline-meta">{pretty(deadline.timing)} · {deadline.comparison_timezone}</p>}
            <div className="answer-facts">
              <div><span>Portal</span><strong>{pretty(report.portal_status)}</strong></div>
              <div><span>Eligibility</span><strong>{pretty(report.eligibility)}</strong></div>
              <div><span>Coverage</span><strong>{pretty(report.coverage)}</strong></div>
            </div>
          </article>

          <aside className="evidence-inspector brutal-card" aria-live="polite">
            <p className="eyebrow">Cited passage</p>
            {loadingEvidence && <p className="evidence-loading">Loading preserved passage…</p>}
            {!loadingEvidence && !evidence && (
              <p className="empty-evidence">No source passage is attached to this conclusion.</p>
            )}
            {!loadingEvidence && evidence && (
              <>
                <div className="evidence-heading">
                  <strong>{pretty(evidence.publisher_role)}</strong>
                  <span>{evidence.location}</span>
                </div>
                <blockquote>{evidence.text}</blockquote>
                {tableHeaders.length > 0 && (
                  <p className="table-headers">
                    <span>Preserved table headers</span>
                    {tableHeaders.join(" · ")}
                  </p>
                )}
                <dl className="evidence-provenance">
                  <div><dt>Retrieved</dt><dd>{formatRetrievedAt(evidence.retrieved_at)}</dd></div>
                  <div><dt>Parse</dt><dd>{pretty(evidence.parse_status)} · {evidence.parser_version}</dd></div>
                  <div><dt>Block</dt><dd>{evidence.block_id} · {evidence.kind}</dd></div>
                  <div><dt>Source version</dt><dd><code>{evidence.version_id}</code></dd></div>
                  <div><dt>Content SHA-256</dt><dd><code>{evidence.content_sha256}</code></dd></div>
                  <div><dt>Block SHA-256</dt><dd><code>{evidence.block_sha256}</code></dd></div>
                </dl>
                <a href={evidence.source_url} target="_blank" rel="noreferrer">
                  Open original source ↗
                </a>
              </>
            )}
          </aside>
        </div>

        <div className="report-detail-grid">
          <aside className="scope-card brutal-card">
            <p className="eyebrow">Checked scope</p>
            <dl>
              <div><dt>Cycle</dt><dd>{report.scope.academic_year}</dd></div>
              <div><dt>Application</dt><dd>{report.scope.application_type}</dd></div>
              <div><dt>Mode</dt><dd>{report.mode}</dd></div>
              <div><dt>As of</dt><dd>{new Date(report.reference_time).toLocaleString("en-IN")}</dd></div>
            </dl>
          </aside>
          <div className="evidence-section">
            <div className="section-title-row">
              <div><p className="eyebrow">Receipts</p><h3>Evidence trail</h3></div>
              <span>{deadline?.evidence_refs.length ?? 0} source block(s)</span>
            </div>
            {deadline?.evidence_refs.map((reference, index) => {
              const active =
                evidence?.version_id === reference.version_id &&
                evidence.block_id === reference.block_id;
              return (
                <button
                  aria-pressed={active}
                  className={`evidence-row${active ? " active" : ""}`}
                  key={`${reference.version_id}-${reference.block_id}`}
                  onClick={() => showEvidence(reference)}
                  type="button"
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <span>{active ? "Showing preserved passage" : "Show preserved passage"}</span>
                  <span>{active ? "OPEN" : "VIEW ↗"}</span>
                </button>
              );
            })}
            {!deadline && <p className="empty-note">No supported student deadline evidence was found.</p>}
          </div>
        </div>

        {report.other_deadlines && report.other_deadlines.length > 0 && (
          <div className="other-deadlines brutal-card">
            <p className="eyebrow">Kept separate on purpose</p>
            <h3>Other actors’ deadlines</h3>
            {report.other_deadlines.map((item, index) => (
              <p key={`${item.actor}-${item.date}-${index}`}>
                <strong>{pretty(item.actor)}</strong> · {pretty(item.action)} · {formatDeadline(item)}
              </p>
            ))}
          </div>
        )}

        {report.limitations && report.limitations.length > 0 && (
          <div className="limitations">
            <strong>Limits of this check</strong>
            {report.limitations.map((item) => <p key={item}>{item}</p>)}
          </div>
        )}

        {error && <ErrorBox message={error} />}
      </section>
    );
  }

  const selected = programmes.find((item) => item.id === programmeId);
  return (
    <section className="workspace form-layout">
      <div className="section-number">01 / YOUR CHECK</div>
      <form className="check-form brutal-card" onSubmit={submitCheck}>
        <div className="form-heading">
          <div><p className="eyebrow">Start with what you know</p><h2>Which deadline are you checking?</h2></div>
          <span className="step-stamp">1–2 MIN</span>
        </div>

        <div className="field field-wide">
          <label htmlFor="programme">Programme</label>
          <select id="programme" value={programmeId} onChange={(event) => setProgrammeId(event.target.value)} required>
            {programmes.length === 0 && <option value="nmmss">NMMSS</option>}
            {programmes.map((item) => (
              <option value={item.id} key={item.id} disabled={item.support_status !== "phase1_supported"}>
                {item.name}{item.support_status !== "phase1_supported" ? " — coming soon" : ""}
              </option>
            ))}
          </select>
          <small>{selected?.provider ?? "Ministry of Education"}</small>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="academic-year">Academic year</label>
            <select id="academic-year" value={academicYear} onChange={(event) => setAcademicYear(event.target.value)}>
              {(selected?.supported_cycles ?? ["2026-27"]).map((cycle) => <option key={cycle} value={cycle}>{cycle}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="application-type">Application type</label>
            <select id="application-type" value={applicationType} onChange={(event) => setApplicationType(event.target.value)}>
              {(selected?.application_types ?? ["fresh", "renewal"]).map((type) => <option key={type} value={type}>{pretty(type)}</option>)}
            </select>
          </div>
        </div>

        <div className="field field-wide">
          <label htmlFor="notice-url">Official notice URL <span>optional</span></label>
          <input id="notice-url" type="url" value={noticeUrl} onChange={(event) => setNoticeUrl(event.target.value)} placeholder="https://…" />
          <small>Use a government or programme source you already trust.</small>
        </div>

        {error && <ErrorBox message={error} />}
        <button className="primary-button" type="submit">Check the deadline <span>→</span></button>
        <p className="form-footnote">Live check · reviewed web sources · evidence preserved locally</p>
      </form>
    </section>
  );
}

function ErrorBox({ message }: { message: string }) {
  return <div className="error-box" role="alert"><strong>Check stopped.</strong> {message}</div>;
}
