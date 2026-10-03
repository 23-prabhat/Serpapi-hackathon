"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";

import type { Programme } from "@/lib/api/types";
import { formatDateTime, pretty, readJson } from "@/lib/client-api";

export function Catalogue() {
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [error, setError] = useState("");

  useEffect(() => {
    fetch("/api/v1/programmes")
      .then((response) => readJson<Programme[]>(response))
      .then(setProgrammes)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return programmes.filter((item) => {
      const matchesText = !needle || `${item.name} ${item.provider}`.toLocaleLowerCase().includes(needle);
      const matchesStatus = status === "all" || item.support_status === status;
      return matchesText && matchesStatus;
    });
  }, [programmes, query, status]);

  return (
    <main className="page-shell">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Reviewed local catalogue</p>
          <h1>Browse scholarships.</h1>
          <p>Catalogue metadata helps you choose. It does not establish that a portal is open or that you are eligible.</p>
        </div>
      </section>
      <section className="filter-bar" aria-label="Catalogue filters">
        <div className="field">
          <label htmlFor="catalogue-search">Programme or provider</label>
          <input id="catalogue-search" type="search" value={query} onChange={(event) => setQuery(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="catalogue-status">Availability</label>
          <select id="catalogue-status" value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="all">All reviewed entries</option>
            <option value="phase1_supported">Live check available</option>
            <option value="coming_soon">Catalogue only</option>
          </select>
        </div>
      </section>
      {error && <div className="error-box" role="alert">{error}</div>}
      <section className="catalogue-grid" aria-live="polite">
        {filtered.map((item, index) => {
          const supported = item.support_status === "phase1_supported";
          return (
            <article className="catalogue-card brutal-card" key={item.id}>
              <span className="card-index">{String(index + 1).padStart(2, "0")}</span>
              <p className="eyebrow">{supported ? "Live check available" : "Reviewed · catalogue only"}</p>
              <h2>{item.name}</h2>
              <p>{item.provider}</p>
              <dl>
                <div><dt>Cycles</dt><dd>{item.supported_cycles.join(", ")}</dd></div>
                <div><dt>Applications</dt><dd>{item.application_types.map(pretty).join(", ")}</dd></div>
                <div>
                  <dt>Last check</dt>
                  <dd>{item.last_checked_at ? formatDateTime(item.last_checked_at) : "Not checked yet"}</dd>
                </div>
              </dl>
              {supported ? (
                <Link className="card-link" href={`/?programme=${encodeURIComponent(item.id)}#check`}>Check this programme →</Link>
              ) : (
                <span className="disabled-action">Live processing not enabled yet</span>
              )}
            </article>
          );
        })}
        {filtered.length === 0 && <p className="empty-note">No reviewed programme matches these filters.</p>}
      </section>
    </main>
  );
}
