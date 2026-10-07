"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { CheckAccepted } from "@/lib/api/types";
import { readJson } from "@/lib/client-api";

type Health = {
  worker_ready: boolean;
  live_extraction_enabled: boolean;
};

export function LinkCheckForm() {
  const router = useRouter();
  const [programmeName, setProgrammeName] = useState("");
  const [noticeUrl, setNoticeUrl] = useState("");
  const [academicYear, setAcademicYear] = useState("2026-27");
  const [applicationType, setApplicationType] = useState("fresh");
  const [applicantGroup, setApplicantGroup] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [save, setSave] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch("/api/v1/health")
      .then((response) => readJson<Health>(response))
      .then(setHealth)
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const ready = Boolean(health?.worker_ready && health.live_extraction_enabled);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const response = await fetch("/api/v1/checks/link", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({
          programme_name: programmeName,
          notice_url: noticeUrl,
          academic_year: academicYear,
          application_type: applicationType,
          applicant_group: applicantGroup || null,
          profile: null,
          official_source_confirmed: confirmed,
          save,
        }),
      });
      const accepted = await readJson<CheckAccepted>(response);
      router.push(`/checks/${accepted.check_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the link check.");
      setSubmitting(false);
    }
  }

  return (
    <section className="workspace link-workspace" id="link-check">
      <div className="section-number">P1 / GUARDED LINK INTAKE</div>
      <form className="check-form brutal-card" onSubmit={submit}>
        <div className="form-heading">
          <div>
            <p className="eyebrow">Released · one source at a time</p>
            <h2>Check an official notice link.</h2>
          </div>
          <span className="step-stamp link-stamp">P1</span>
        </div>

        <div className="state-banner replay-banner" role="status">
          <strong>Evidence check, not an authority guarantee.</strong>
          <span>
            Kabtak blocks private-network targets, risky redirects, oversized files, and unsupported
            formats. If the publisher or requested scope cannot be established, the result stays unresolved.
          </span>
        </div>

        {health && !ready && (
          <div className="state-banner warning-banner" role="status">
            <strong>Link checks are not ready on this computer.</strong>
            <span>Start the worker and configure the extraction model. SerpApi is not required.</span>
          </div>
        )}

        <div className="field">
          <label htmlFor="link-programme-name">Scholarship name</label>
          <input
            id="link-programme-name"
            value={programmeName}
            onChange={(event) => setProgrammeName(event.target.value)}
            placeholder="Use the name shown in the notice"
            minLength={3}
            maxLength={300}
            required
          />
          <small>The source must contain enough of this name to establish the notice scope.</small>
        </div>

        <div className="field">
          <label htmlFor="link-notice-url">Official public notice URL</label>
          <input
            id="link-notice-url"
            type="url"
            value={noticeUrl}
            onChange={(event) => setNoticeUrl(event.target.value)}
            placeholder="https://publisher.example/notice"
            required
          />
          <small>Public HTML and text-based PDF only. Shorteners, shared drives, logins, and scanned PDFs are rejected.</small>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="link-academic-year">Academic year</label>
            <input
              id="link-academic-year"
              value={academicYear}
              onChange={(event) => setAcademicYear(event.target.value)}
              pattern="\d{4}-\d{2}"
              placeholder="2026-27"
              required
            />
          </div>
          <div className="field">
            <label htmlFor="link-application-type">Application type</label>
            <select
              id="link-application-type"
              value={applicationType}
              onChange={(event) => setApplicationType(event.target.value)}
            >
              <option value="fresh">Fresh</option>
              <option value="renewal">Renewal</option>
            </select>
          </div>
        </div>

        <div className="field">
          <label htmlFor="link-applicant-group">Applicant group <span>optional</span></label>
          <input
            id="link-applicant-group"
            value={applicantGroup}
            onChange={(event) => setApplicantGroup(event.target.value)}
            placeholder="e.g. hostel residents"
            maxLength={200}
          />
        </div>

        <label className="check-control confirmation-control">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
            required
          />
          <span>I found this link on the scholarship publisher or institution website.</span>
        </label>
        <label className="check-control">
          <input type="checkbox" checked={save} onChange={(event) => setSave(event.target.checked)} />
          <span>Save this link check until I delete it</span>
        </label>
        {!save && <p className="retention-note">Unsaved checks are kept locally for 24 hours.</p>}

        {error && <div className="error-box" role="alert"><strong>Could not start.</strong> {error}</div>}
        <button className="primary-button" type="submit" disabled={submitting || !ready || !confirmed}>
          {submitting ? "Starting…" : "Analyse this link"}<span>→</span>
        </button>
        <p className="form-footnote">No search credits used · one source · evidence preserved locally</p>
        <p className="link-form-back"><Link href="/#check">Use the reviewed catalogue instead →</Link></p>
      </form>
    </section>
  );
}
