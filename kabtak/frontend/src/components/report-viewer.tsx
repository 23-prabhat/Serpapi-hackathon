"use client";

import { type RefObject, useEffect, useRef, useState } from "react";

import type {
  Deadline,
  Evidence,
  EvidenceReference,
  Report,
  RunComparison,
} from "@/lib/api/types";
import { formatDateTime, pretty, readJson } from "@/lib/client-api";

type Condition = {
  result?: string;
  reason?: string;
  operator?: string;
  field?: string | null;
  profile_value?: unknown;
  expected_value?: unknown;
  source_text?: string;
  evidence_refs?: EvidenceReference[];
  children?: Condition[];
};

function formatDeadline(deadline: Deadline) {
  const day = new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${deadline.date}T00:00:00+05:30`));
  if (!deadline.time) return day;
  return `${day}, ${deadline.time} ${deadline.timezone ?? "timezone unknown"}`;
}

function refsFrom(value: unknown): EvidenceReference[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is EvidenceReference =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as EvidenceReference).version_id === "string" &&
      typeof (item as EvidenceReference).block_id === "string",
  );
}

function formatFact(value: unknown) {
  if (value === null || value === undefined) return "Not present";
  if (typeof value !== "object") return pretty(String(value));
  const item = value as Record<string, unknown>;
  if (item.date) return `${pretty(String(item.actor ?? "deadline"))} ${pretty(String(item.action ?? ""))}: ${String(item.date)}`;
  if (item.source_text) return String(item.source_text);
  return JSON.stringify(value);
}

export function ReportViewer({
  report,
  comparison,
}: {
  report: Report;
  comparison: RunComparison | null;
}) {
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [loadingEvidence, setLoadingEvidence] = useState(false);
  const [evidenceError, setEvidenceError] = useState("");
  const evidenceInspectorRef = useRef<HTMLElement>(null);
  const deadline = report.student_deadline;

  async function showEvidence(reference: EvidenceReference, runId = report.run_id) {
    setLoadingEvidence(true);
    setEvidenceError("");
    evidenceInspectorRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    evidenceInspectorRef.current?.focus({ preventScroll: true });
    try {
      const response = await fetch(
        `/api/v1/runs/${runId}/evidence/${encodeURIComponent(reference.version_id)}/${encodeURIComponent(reference.block_id)}`,
      );
      setEvidence(await readJson<Evidence>(response));
    } catch (reason) {
      setEvidenceError(reason instanceof Error ? reason.message : "Could not load evidence.");
    } finally {
      setLoadingEvidence(false);
    }
  }

  useEffect(() => {
    const first = deadline?.evidence_refs[0];
    if (!first) return;
    const reference = first;
    let active = true;
    async function loadFirstEvidence() {
      try {
        const response = await fetch(
          `/api/v1/runs/${report.run_id}/evidence/${encodeURIComponent(reference.version_id)}/${encodeURIComponent(reference.block_id)}`,
        );
        const next = await readJson<Evidence>(response);
        if (active) setEvidence(next);
      } catch (reason) {
        if (active) {
          setEvidenceError(
            reason instanceof Error ? reason.message : "Could not load evidence.",
          );
        }
      }
    }
    void loadFirstEvidence();
    return () => {
      active = false;
    };
  }, [deadline, report.run_id]);

  const conflicts = (report.conflicts ?? []) as Array<Record<string, unknown>>;
  const amendments = (report.amendments ?? []) as Array<Record<string, unknown>>;
  const conditions = (report.conditions ?? []) as Condition[];
  const otherDeadlines = report.other_deadlines ?? [];
  const limitations = report.limitations ?? [];
  const requiredDocuments = report.required_documents ?? [];
  const applicationLinks = report.application_links ?? [];
  const factChanges = comparison?.changes ?? [];

  return (
    <div className="report-stack">
      {report.mode === "replay" && (
        <div className="state-banner replay-banner" role="status">
          <strong>Historical replay</strong>
          <span>Offline packaged evidence at a frozen time—not a current opportunity or live search.</span>
        </div>
      )}

      <div className="conclusion-evidence-grid">
        <article className="answer-card brutal-card">
          <span className={`resolution resolution-${report.deadline_resolution}`}>
            {pretty(report.deadline_resolution)}
          </span>
          <p className="answer-label">Student submission deadline</p>
          <h2>{deadline ? formatDeadline(deadline) : "Not established"}</h2>
          {deadline && (
            <p className="deadline-meta">
              {pretty(deadline.timing)} · compared in {deadline.comparison_timezone}
            </p>
          )}
          <p className="report-summary">{report.summary}</p>
          <div className="answer-facts">
            <div><span>Portal</span><strong>{pretty(report.portal_status)}</strong></div>
            <div><span>Eligibility</span><strong>{pretty(report.eligibility)}</strong></div>
            <div><span>Coverage</span><strong>{pretty(report.coverage)}</strong></div>
          </div>
          {deadline && (
            <EvidenceButtons references={deadline.evidence_refs} onSelect={showEvidence} />
          )}
        </article>

        <EvidenceInspector
          evidence={evidence}
          error={evidenceError}
          inspectorRef={evidenceInspectorRef}
          loading={loadingEvidence}
        />
      </div>

      <div className="report-detail-grid">
        <aside className="scope-card brutal-card">
          <p className="eyebrow">Checked scope</p>
          <dl>
            <div><dt>Programme</dt><dd>{report.scope.programme_name}</dd></div>
            <div><dt>Cycle</dt><dd>{report.scope.academic_year}</dd></div>
            <div><dt>Application</dt><dd>{report.scope.application_type}</dd></div>
            {report.scope.applicant_group && <div><dt>Group</dt><dd>{report.scope.applicant_group}</dd></div>}
            <div><dt>Mode</dt><dd>{report.mode}</dd></div>
            <div><dt>Checked at</dt><dd>{formatDateTime(report.reference_time)}</dd></div>
          </dl>
        </aside>

        <section className="report-section" aria-labelledby="requirements-title">
          <p className="eyebrow">Published requirements</p>
          <h3 id="requirements-title">Eligibility conditions</h3>
          {conditions.length === 0 ? (
            <p className="empty-note">No supported eligibility condition was established.</p>
          ) : (
            <div className="condition-list">
              {conditions.map((condition, index) => (
                <ConditionCard
                  condition={condition}
                  key={`${condition.source_text}-${index}`}
                  onEvidence={showEvidence}
                />
              ))}
            </div>
          )}
        </section>
      </div>

      {otherDeadlines.length > 0 && (
        <section className="report-section brutal-card offset-warning">
          <p className="eyebrow">Kept separate on purpose</p>
          <h3>Other actors’ deadlines</h3>
          <div className="fact-list">
            {otherDeadlines.map((item, index) => (
              <article key={`${item.actor}-${item.action}-${item.date}-${index}`}>
                <strong>{pretty(item.actor)} · {pretty(item.action)}</strong>
                <span>{formatDeadline(item)}</span>
                <EvidenceButtons references={item.evidence_refs} onSelect={showEvidence} compact />
              </article>
            ))}
          </div>
        </section>
      )}

      {amendments.length > 0 && (
        <section className="report-section brutal-card offset-info">
          <p className="eyebrow">Explicit changes</p>
          <h3>Amendments applied</h3>
          <div className="fact-list">
            {amendments.map((item, index) => (
              <article key={`${String(item.previous_date)}-${index}`}>
                <strong>{String(item.previous_date)} → {String(item.revised_date)}</strong>
                <span>{pretty(String(item.actor))} {pretty(String(item.action))}</span>
                <EvidenceButtons references={refsFrom(item.evidence_refs)} onSelect={showEvidence} compact />
              </article>
            ))}
          </div>
        </section>
      )}

      {conflicts.length > 0 && (
        <section className="report-section conflict-panel" role="alert">
          <p className="eyebrow">Unresolved evidence</p>
          <h3>Conflicting dates</h3>
          {conflicts.map((conflict, index) => (
            <div key={index}>
              <p>{String(conflict.message ?? "Applicable sources disagree.")}</p>
              {Array.isArray(conflict.candidates) &&
                (conflict.candidates as Array<Record<string, unknown>>).map((candidate, itemIndex) => (
                  <article className="conflict-candidate" key={itemIndex}>
                    <strong>{String(candidate.date)}</strong>
                    <EvidenceButtons references={refsFrom(candidate.evidence_refs)} onSelect={showEvidence} compact />
                  </article>
                ))}
            </div>
          ))}
        </section>
      )}

      <section className="report-section brutal-card next-steps-panel" aria-labelledby="next-steps-title">
        <p className="eyebrow">Published next steps</p>
        <h3 id="next-steps-title">Documents and official links</h3>
        {requiredDocuments.length === 0 && applicationLinks.length === 0 ? (
          <p className="empty-note">No required-document list or official application link was established from the reviewed evidence.</p>
        ) : (
          <div className="fact-list">
            {requiredDocuments.map((item, index) => (
              <article key={`document-${index}`}>
                <strong>Required document</strong>
                <span>{item.source_text}</span>
                <EvidenceButtons references={item.evidence_refs} onSelect={showEvidence} compact />
              </article>
            ))}
            {applicationLinks.map((item, index) => (
              <article key={`${item.url}-${index}`}>
                <strong>Official application link</strong>
                <a className="text-link" href={item.url} target="_blank" rel="noreferrer">{item.source_text} ↗</a>
                <EvidenceButtons references={item.evidence_refs} onSelect={showEvidence} compact />
              </article>
            ))}
          </div>
        )}
      </section>

      {comparison && (
        <section className="change-panel" aria-labelledby="changes-title">
          <p className="eyebrow">Since the previous report</p>
          <h3 id="changes-title">{pretty(comparison.classification)}</h3>
          <p>{comparison.summary}</p>
          <ul>
            <li>Source versions: {comparison.source_versions_changed ? "changed" : "unchanged"}</li>
            <li>Profile: {comparison.profile_changed ? "changed" : "unchanged"}</li>
            <li>Software versions: {comparison.software_versions_changed ? "changed" : "unchanged"}</li>
          </ul>
          {factChanges.length > 0 && (
            <div className="change-list">
              {factChanges.map((change) => (
                <article key={`${change.kind}-${change.fact_key}`}>
                  <strong>{pretty(change.kind)} · {change.fact_key.split(":").at(-1)}</strong>
                  {change.before !== null && change.before !== undefined && <p>Before: {formatFact(change.before)}</p>}
                  {change.after !== null && change.after !== undefined && <p>After: {formatFact(change.after)}</p>}
                  <div className="change-evidence-row">
                    {comparison.previous_run_id && (change.before_evidence ?? []).length > 0 && (
                      <EvidenceButtons
                        references={change.before_evidence ?? []}
                        onSelect={(reference) => showEvidence(reference, comparison.previous_run_id!)}
                        compact
                      />
                    )}
                    {(change.after_evidence ?? []).length > 0 && (
                      <EvidenceButtons references={change.after_evidence ?? []} onSelect={showEvidence} compact />
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {limitations.length > 0 && (
        <section className="limitations">
          <strong>Limits of this check</strong>
          {limitations.map((item) => <p key={item}>{item}</p>)}
        </section>
      )}
    </div>
  );
}

function EvidenceButtons({
  references,
  onSelect,
  compact = false,
}: {
  references: EvidenceReference[];
  onSelect: (reference: EvidenceReference) => void;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "evidence-actions compact" : "evidence-actions"}>
      {references.map((reference, index) => (
        <button
          type="button"
          key={`${reference.version_id}-${reference.block_id}`}
          onClick={() => onSelect(reference)}
        >
          View evidence {index + 1} ↓
        </button>
      ))}
    </div>
  );
}

function ConditionCard({
  condition,
  onEvidence,
}: {
  condition: Condition;
  onEvidence: (reference: EvidenceReference) => void;
}) {
  return (
    <article className={`condition-card condition-${condition.result ?? "unknown"}`}>
      <span className="condition-result">{pretty(condition.result ?? "unknown")}</span>
      <strong>{condition.source_text ?? "Published condition"}</strong>
      {condition.field && (
        <p>
          {pretty(condition.field)}: {String(condition.profile_value ?? "missing")} / required{" "}
          {String(condition.expected_value ?? "see source")}
        </p>
      )}
      <EvidenceButtons references={condition.evidence_refs ?? []} onSelect={onEvidence} compact />
      {condition.children?.map((child, index) => (
        <ConditionCard condition={child} onEvidence={onEvidence} key={index} />
      ))}
    </article>
  );
}

function EvidenceInspector({
  evidence,
  loading,
  error,
  inspectorRef,
}: {
  evidence: Evidence | null;
  loading: boolean;
  error: string;
  inspectorRef: RefObject<HTMLElement | null>;
}) {
  const headers = evidence?.metadata?.headers;
  const tableHeaders = Array.isArray(headers)
    ? headers.filter((item): item is string => typeof item === "string")
    : [];
  return (
    <aside
      className="evidence-inspector brutal-card"
      aria-live="polite"
      ref={inspectorRef}
      tabIndex={-1}
    >
      <p className="eyebrow">Cited passage</p>
      {loading && <p className="evidence-loading">Loading preserved passage…</p>}
      {error && <div className="error-box" role="alert">{error}</div>}
      {!loading && !error && !evidence && (
        <p className="empty-evidence">Select an evidence receipt to inspect its preserved passage.</p>
      )}
      {!loading && evidence && (
        <>
          <div className="evidence-heading">
            <strong>{pretty(evidence.publisher_role)}</strong>
            <span>{evidence.location}</span>
          </div>
          <blockquote>{evidence.text}</blockquote>
          {tableHeaders.length > 0 && (
            <p className="table-headers"><span>Preserved headers</span>{tableHeaders.join(" · ")}</p>
          )}
          <dl className="evidence-provenance">
            <div><dt>Retrieved</dt><dd>{formatDateTime(evidence.retrieved_at)}</dd></div>
            <div><dt>Parse</dt><dd>{pretty(evidence.parse_status)} · {evidence.parser_version}</dd></div>
            <div><dt>Block</dt><dd>{evidence.block_id} · {evidence.kind}</dd></div>
            <div><dt>Source version</dt><dd><code>{evidence.version_id}</code></dd></div>
            <div><dt>Content SHA-256</dt><dd><code>{evidence.content_sha256}</code></dd></div>
          </dl>
          <a href={evidence.source_url} target="_blank" rel="noreferrer">Open original source ↗</a>
        </>
      )}
    </aside>
  );
}
