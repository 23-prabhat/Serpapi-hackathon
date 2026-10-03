"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import type { Check } from "@/lib/api/types";
import { formatDateTime, pretty, readJson } from "@/lib/client-api";

export function SavedChecks() {
  const [checks, setChecks] = useState<Check[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v1/checks?saved=true")
      .then((response) => readJson<Check[]>(response))
      .then(setChecks)
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <main className="page-shell">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Local workspace</p>
          <h1>Saved checks.</h1>
          <p>Each refresh creates a new immutable report. Open a check to compare its history.</p>
        </div>
        <Link className="secondary-button link-button" href="/#check">New check</Link>
      </section>
      {error && <div className="error-box" role="alert">{error}</div>}
      {loading && <p className="loading-state">Loading saved checks…</p>}
      {!loading && checks.length === 0 && (
        <section className="empty-state brutal-card">
          <p className="eyebrow">Nothing saved yet</p>
          <h2>Keep a deadline trail here.</h2>
          <p>Save a check from its report page, or save it when you first submit the form.</p>
          <Link className="card-link" href="/#check">Start a check →</Link>
        </section>
      )}
      <section className="saved-list">
        {checks.map((check) => {
          const latest = check.runs[0];
          return (
            <article className="saved-card brutal-card" key={check.id}>
              <div>
                <p className="eyebrow">{check.academic_year} · {pretty(check.application_type)}</p>
                <h2>{check.programme_name}</h2>
                <p>Saved {check.saved_at ? formatDateTime(check.saved_at) : "locally"}</p>
              </div>
              <dl>
                <div><dt>Latest run</dt><dd>{latest ? pretty(latest.status) : "none"}</dd></div>
                <div><dt>History</dt><dd>{check.runs.length} run(s)</dd></div>
              </dl>
              <Link className="card-link" href={`/checks/${check.id}`}>Open check →</Link>
            </article>
          );
        })}
      </section>
    </main>
  );
}
