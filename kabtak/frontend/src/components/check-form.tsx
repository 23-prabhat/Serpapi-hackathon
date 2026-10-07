"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import type { CheckAccepted, Programme } from "@/lib/api/types";
import { pretty, readJson } from "@/lib/client-api";

type Health = {
  worker_ready: boolean;
  live_search_enabled: boolean;
  live_extraction_enabled: boolean;
};

export function CheckForm({ initialProgrammeId }: { initialProgrammeId?: string }) {
  const router = useRouter();
  const [programmes, setProgrammes] = useState<Programme[]>([]);
  const [programmeId, setProgrammeId] = useState(initialProgrammeId ?? "nmmss");
  const [academicYear, setAcademicYear] = useState("2026-27");
  const [applicationType, setApplicationType] = useState("fresh");
  const [applicantGroup, setApplicantGroup] = useState("");
  const [noticeUrl, setNoticeUrl] = useState("");
  const [studyLevel, setStudyLevel] = useState("");
  const [studyYear, setStudyYear] = useState("");
  const [course, setCourse] = useState("");
  const [domicileState, setDomicileState] = useState("");
  const [income, setIncome] = useState("");
  const [save, setSave] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([
      fetch("/api/v1/programmes").then((response) => readJson<Programme[]>(response)),
      fetch("/api/v1/health").then((response) => readJson<Health>(response)),
    ])
      .then(([items, nextHealth]) => {
        setProgrammes(items);
        setHealth(nextHealth);
        const requested = items.find(
          (item) => item.id === initialProgrammeId && item.support_status === "live_supported",
        );
        const selected = requested ?? items.find((item) => item.support_status === "live_supported");
        if (selected) {
          setProgrammeId(selected.id);
          setAcademicYear(selected.supported_cycles.at(-1) ?? "2026-27");
          setApplicationType(selected.application_types[0] ?? "fresh");
        }
      })
      .catch((reason: Error) => setError(reason.message));
  }, [initialProgrammeId]);

  const selected = useMemo(
    () => programmes.find((item) => item.id === programmeId),
    [programmeId, programmes],
  );
  const liveReady = Boolean(
    health?.worker_ready && health.live_search_enabled && health.live_extraction_enabled,
  );

  function selectProgramme(value: string) {
    const item = programmes.find((programme) => programme.id === value);
    setProgrammeId(value);
    if (item) {
      setAcademicYear(item.supported_cycles.at(-1) ?? "2026-27");
      setApplicationType(item.application_types[0] ?? "fresh");
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const hasProfile = Boolean(studyLevel || studyYear || course || domicileState || income);
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
          applicant_group: applicantGroup || null,
          notice_url: noticeUrl || null,
          profile: hasProfile
            ? {
                study_level: studyLevel || null,
                study_year: studyYear ? Number(studyYear) : null,
                course: course || null,
                domicile_state: domicileState || null,
                annual_family_income_inr: income ? Number(income) : null,
              }
            : null,
          save,
        }),
      });
      const accepted = await readJson<CheckAccepted>(response);
      router.push(`/checks/${accepted.check_id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start the check.");
      setSubmitting(false);
    }
  }

  return (
    <section className="workspace form-layout" id="check">
      <div className="section-number">01 / YOUR CHECK</div>
      <form className="check-form brutal-card" onSubmit={submit}>
        <div className="form-heading">
          <div>
            <p className="eyebrow">Start with what you know</p>
            <h2>Which deadline are you checking?</h2>
          </div>
          <span className="step-stamp">LIVE</span>
        </div>

        {health && !liveReady && (
          <div className="state-banner warning-banner" role="status">
            <strong>Live checks are not ready.</strong>
            <span>
              Start the worker and configure SerpApi/Groq, or use an{" "}
              <Link href="/examples">offline historical example</Link>.
            </span>
          </div>
        )}

        <div className="field field-wide">
          <label htmlFor="programme">Programme</label>
          <select
            id="programme"
            value={programmeId}
            onChange={(event) => selectProgramme(event.target.value)}
            required
          >
            {programmes.filter((item) => item.support_status === "live_supported").map((item) => (
              <option
                value={item.id}
                key={item.id}
              >
                {item.name}
              </option>
            ))}
          </select>
          <small>{selected?.provider ?? "Reviewed programme provider"}</small>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="academic-year">Academic year</label>
            <select
              id="academic-year"
              value={academicYear}
              onChange={(event) => setAcademicYear(event.target.value)}
            >
              {(selected?.supported_cycles ?? ["2026-27"]).map((cycle) => (
                <option key={cycle} value={cycle}>{cycle}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="application-type">Application type</label>
            <select
              id="application-type"
              value={applicationType}
              onChange={(event) => setApplicationType(event.target.value)}
            >
              {(selected?.application_types ?? ["fresh", "renewal"]).map((type) => (
                <option key={type} value={type}>{pretty(type)}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="applicant-group">Applicant group <span>optional</span></label>
            <input
              id="applicant-group"
              value={applicantGroup}
              onChange={(event) => setApplicantGroup(event.target.value)}
              placeholder="e.g. hostel residents"
            />
          </div>
          <div className="field">
            <label htmlFor="notice-url">Reviewed official notice URL <span>optional</span></label>
            <input
              id="notice-url"
              type="url"
              value={noticeUrl}
              onChange={(event) => setNoticeUrl(event.target.value)}
              placeholder="https://…"
              aria-describedby="notice-url-help"
            />
            <small id="notice-url-help">
              Currently limited to reviewed sources for this programme. To use another publisher
              notice, <Link href="/link-check">check an official link directly</Link>.
            </small>
          </div>
        </div>

        <details className="profile-panel">
          <summary>Add profile details for a basic eligibility comparison</summary>
          <p>
            Optional and stored locally. Kabtak compares only supported published rules and
            never sends these values to search or Groq.
          </p>
          <div className="field-row">
            <div className="field">
              <label htmlFor="study-level">Study level</label>
              <input id="study-level" value={studyLevel} onChange={(event) => setStudyLevel(event.target.value)} placeholder="undergraduate" />
            </div>
            <div className="field">
              <label htmlFor="study-year">Study year</label>
              <input id="study-year" min="1" type="number" value={studyYear} onChange={(event) => setStudyYear(event.target.value)} />
            </div>
          </div>
          <div className="field-row">
            <div className="field">
              <label htmlFor="course">Course</label>
              <input id="course" value={course} onChange={(event) => setCourse(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="domicile">Domicile state</label>
              <input id="domicile" value={domicileState} onChange={(event) => setDomicileState(event.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="income">Annual family income (INR)</label>
            <input id="income" min="0" type="number" value={income} onChange={(event) => setIncome(event.target.value)} />
          </div>
        </details>

        <label className="check-control">
          <input type="checkbox" checked={save} onChange={(event) => setSave(event.target.checked)} />
          <span>Save this check until I delete it</span>
        </label>
        {!save && <p className="retention-note">Unsaved checks are kept locally for 24 hours.</p>}
        {error && <div className="error-box" role="alert"><strong>Could not start.</strong> {error}</div>}
        <button className="primary-button" type="submit" disabled={submitting || !liveReady}>
          {submitting ? "Starting…" : "Check the deadline"}<span>→</span>
        </button>
        <p className="form-footnote">Live search · reviewed sources · evidence preserved locally</p>
      </form>
    </section>
  );
}
