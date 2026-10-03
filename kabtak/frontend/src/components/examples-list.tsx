"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import type { CheckAccepted, Example } from "@/lib/api/types";
import { formatDateTime, pretty, readJson } from "@/lib/client-api";

export function ExamplesList() {
  const router = useRouter();
  const [examples, setExamples] = useState<Example[]>([]);
  const [runningId, setRunningId] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v1/examples")
      .then((response) => readJson<Example[]>(response))
      .then(setExamples)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  async function replay(exampleId: string) {
    setRunningId(exampleId);
    setError("");
    try {
      const response = await fetch(`/api/v1/examples/${encodeURIComponent(exampleId)}/replay`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      const accepted = await readJson<CheckAccepted>(response);
      router.push(`/checks/${accepted.check_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open the replay.");
      setRunningId("");
    }
  }

  return (
    <main className="page-shell">
      <section className="page-heading">
        <div>
          <p className="eyebrow">No API keys required</p>
          <h1>Historical examples.</h1>
          <p>Replays run current deterministic rules over packaged evidence at a frozen reference time. They do not repeat live search or AI extraction.</p>
        </div>
      </section>
      {error && <div className="error-box" role="alert">{error}</div>}
      <section className="catalogue-grid">
        {examples.map((item) => (
          <article className="catalogue-card brutal-card replay-card" key={item.id}>
            <p className="eyebrow">Historical · {item.academic_year}</p>
            <h2>{item.title}</h2>
            <p>{item.description}</p>
            <dl>
              <div><dt>Scope</dt><dd>{pretty(item.application_type)}</dd></div>
              <div><dt>Frozen time</dt><dd>{formatDateTime(item.reference_time)}</dd></div>
              <div><dt>Expected student date</dt><dd>{item.expected_student_deadline ?? "unresolved"}</dd></div>
            </dl>
            <button className="primary-button" type="button" disabled={Boolean(runningId)} onClick={() => replay(item.id)}>
              {runningId === item.id ? "Opening replay…" : "Open offline replay"}<span>→</span>
            </button>
          </article>
        ))}
      </section>
    </main>
  );
}
