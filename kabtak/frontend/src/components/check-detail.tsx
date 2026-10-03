"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type {
  Check,
  CheckAccepted,
  Report,
  Run,
  RunComparison,
} from "@/lib/api/types";
import { formatDateTime, pretty, readJson } from "@/lib/client-api";
import { ReportViewer } from "@/components/report-viewer";

const STAGES = [
  ["searching", "Finding reviewed sources"],
  ["fetching", "Saving source snapshots"],
  ["extracting", "Reading deadline claims"],
  ["checking", "Applying decision rules"],
  ["finalizing", "Committing the report"],
] as const;

export function CheckDetail({ checkId }: { checkId: string }) {
  const router = useRouter();
  const [check, setCheck] = useState<Check | null>(null);
  const [selectedRunId, setSelectedRunId] = useState("");
  const [report, setReport] = useState<Report | null>(null);
  const [reportRunId, setReportRunId] = useState("");
  const [comparison, setComparison] = useState<RunComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState("");
  const [pollingError, setPollingError] = useState("");

  const loadCheck = useCallback(async () => {
    const response = await fetch(`/api/v1/checks/${encodeURIComponent(checkId)}`);
    const next = await readJson<Check>(response);
    setCheck(next);
    setSelectedRunId((current) => {
      if (current && next.runs.some((run) => run.id === current)) return current;
      return (
        next.runs.find((run) => run.status === "queued" || run.status === "running")?.id ??
        next.latest_completed_run_id ??
        next.runs[0]?.id ??
        ""
      );
    });
    return next;
  }, [checkId]);

  useEffect(() => {
    let active = true;
    async function loadInitialCheck() {
      try {
        const response = await fetch(`/api/v1/checks/${encodeURIComponent(checkId)}`);
        const next = await readJson<Check>(response);
        if (!active) return;
        setCheck(next);
        setSelectedRunId(
          next.runs.find((run) => run.status === "queued" || run.status === "running")?.id ??
            next.latest_completed_run_id ??
            next.runs[0]?.id ??
            "",
        );
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load check.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void loadInitialCheck();
    return () => {
      active = false;
    };
  }, [checkId]);

  const selectedRun = useMemo(
    () => check?.runs.find((run) => run.id === selectedRunId) ?? null,
    [check, selectedRunId],
  );
  const activeRun = check?.runs.find(
    (run) => run.status === "queued" || run.status === "running",
  );
  const activeRunId = activeRun?.id;

  useEffect(() => {
    if (!activeRunId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const pollingStartedAt = Date.now();
    const clearTimer = () => {
      if (timer) clearTimeout(timer);
      timer = null;
    };
    const schedule = () => {
      if (cancelled || document.visibilityState === "hidden") return;
      const elapsed = Date.now() - pollingStartedAt;
      timer = setTimeout(poll, elapsed >= 30_000 ? 5_000 : 2_000);
    };
    const poll = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        await loadCheck();
        if (!cancelled) setPollingError("");
      } catch (reason) {
        if (!cancelled) {
          setPollingError(
            reason instanceof Error ? reason.message : "Status polling was interrupted.",
          );
        }
      }
      schedule();
    };
    const onVisibilityChange = () => {
      clearTimer();
      if (document.visibilityState === "visible" && !cancelled) {
        timer = setTimeout(poll, 0);
      }
    };
    document.addEventListener("visibilitychange", onVisibilityChange);
    schedule();
    return () => {
      cancelled = true;
      clearTimer();
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [activeRunId, loadCheck]);

  useEffect(() => {
    if (!selectedRun?.report_available) return;
    let active = true;
    Promise.all([
      fetch(`/api/v1/runs/${selectedRun.id}/report`).then((response) =>
        readJson<Report>(response),
      ),
      fetch(`/api/v1/runs/${selectedRun.id}/changes`)
        .then((response) => readJson<RunComparison>(response))
        .catch(() => null),
    ])
      .then(([nextReport, nextComparison]) => {
        if (!active) return;
        setReport(nextReport);
        setReportRunId(selectedRun.id);
        setComparison(nextComparison);
      })
      .catch((reason: Error) => active && setError(reason.message));
    return () => {
      active = false;
    };
  }, [selectedRun]);

  async function updateSaved(save: boolean) {
    setMutating(true);
    setError("");
    try {
      const response = await fetch(`/api/v1/checks/${checkId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ save }),
      });
      setCheck(await readJson<Check>(response));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this check.");
    } finally {
      setMutating(false);
    }
  }

  async function startOperation(path: string) {
    setMutating(true);
    setError("");
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      const accepted = await readJson<CheckAccepted>(response);
      await loadCheck();
      setSelectedRunId(accepted.run_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start a new run.");
    } finally {
      setMutating(false);
    }
  }

  async function deleteCheck() {
    if (!window.confirm("Delete this check, its profile, run history, and reports?")) return;
    setMutating(true);
    setError("");
    try {
      const response = await fetch(`/api/v1/checks/${checkId}`, { method: "DELETE" });
      if (!response.ok) await readJson(response);
      router.push("/saved");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not delete this check.");
      setMutating(false);
    }
  }

  if (loading) {
    return <main className="page-shell"><p className="loading-state">Loading check…</p></main>;
  }
  if (!check) {
    return (
      <main className="page-shell">
        <div className="error-box" role="alert">{error || "This check is unavailable."}</div>
        <Link className="text-link" href="/">Start another check</Link>
      </main>
    );
  }

  return (
    <main className="page-shell check-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">{check.programme_name}</p>
          <h1>{check.academic_year} · {pretty(check.application_type)}</h1>
          <p>
            {check.saved_at ? "Saved locally until you delete it." : "Stored locally for 24 hours."}
          </p>
        </div>
        <div className="action-row">
          <button
            className="secondary-button"
            type="button"
            disabled={mutating}
            onClick={() => updateSaved(!check.saved_at)}
          >
            {check.saved_at ? "Unsave" : "Save"}
          </button>
          <button
            className="secondary-button"
            type="button"
            disabled={mutating || Boolean(activeRun) || check.runs.some((run) => run.kind === "replay")}
            onClick={() => startOperation(`/api/v1/checks/${check.id}/refresh`)}
          >
            Refresh sources
          </button>
          <button className="danger-button" type="button" disabled={mutating || Boolean(activeRun)} onClick={deleteCheck}>
            Delete
          </button>
        </div>
      </section>

      {error && <div className="error-box" role="alert"><strong>Action stopped.</strong> {error}</div>}
      {pollingError && (
        <div className="state-banner warning-banner" role="status">
          <strong>Status polling paused.</strong><span>{pollingError} The run itself was not cancelled.</span>
        </div>
      )}

      {selectedRun && (selectedRun.status === "queued" || selectedRun.status === "running") && (
        <RunProgress run={selectedRun} />
      )}

      {selectedRun && (selectedRun.status === "failed" || selectedRun.status === "interrupted") && (
        <section className="failure-state brutal-card">
          <p className="eyebrow">{pretty(selectedRun.status)}</p>
          <h2>This run did not produce a report.</h2>
          <p>{String(selectedRun.error?.message ?? "The worker stopped before completion.")}</p>
          <button
            className="primary-button"
            type="button"
            disabled={mutating || Boolean(activeRun)}
            onClick={() => startOperation(`/api/v1/runs/${selectedRun.id}/retry`)}
          >
            Retry as a new run <span>→</span>
          </button>
        </section>
      )}

      {selectedRun?.report_available && report && reportRunId === selectedRun.id && (
        <ReportViewer report={report} comparison={comparison} />
      )}

      <section className="history-section" aria-labelledby="history-title">
        <div className="section-title-row">
          <div><p className="eyebrow">Immutable attempts</p><h2 id="history-title">Run history</h2></div>
          <span>{check.runs.length} run(s)</span>
        </div>
        <div className="history-list">
          {check.runs.map((run) => (
            <button
              type="button"
              aria-pressed={run.id === selectedRunId}
              className={run.id === selectedRunId ? "history-row active" : "history-row"}
              key={run.id}
              onClick={() => setSelectedRunId(run.id)}
            >
              <span>{pretty(run.kind)}</span>
              <strong>{pretty(run.status)}</strong>
              <span>{formatDateTime(run.reference_time)}</span>
              <span>{run.report_available ? "View report ↗" : pretty(run.stage)}</span>
            </button>
          ))}
        </div>
      </section>
    </main>
  );
}

function RunProgress({ run }: { run: Run }) {
  const activeIndex = STAGES.findIndex(([key]) => key === run.stage);
  return (
    <section className="status-card brutal-card" aria-live="polite">
      <div className="loader-mark" aria-hidden="true"><span /><span /><span /></div>
      <p className="eyebrow">{run.status === "queued" ? "Waiting for worker" : "Live evidence run"}</p>
      <h2>We’re checking the record.</h2>
      <p className="muted">You can close this page. The persisted run will continue locally.</p>
      <ol className="stage-list">
        {STAGES.map(([key, label], index) => {
          const done = activeIndex > index || run.stage === "finished";
          const active = run.stage === key || (run.stage === "queued" && index === 0);
          return (
            <li className={done ? "done" : active ? "active" : ""} key={key}>
              <span>{done ? "✓" : String(index + 1).padStart(2, "0")}</span>{label}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
