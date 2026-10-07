"use client";

import { useState } from "react";

import type { Deadline, Report } from "@/lib/api/types";
import { buildDeadlineCalendar, calendarFilename } from "@/lib/calendar";

const timingInHindi: Record<Deadline["timing"], string> = {
  date_ahead: "यह तारीख अभी बाकी है।",
  due_today_time_unknown: "अंतिम तिथि आज है, लेकिन सटीक समय उपलब्ध नहीं है।",
  date_passed: "यह अंतिम तिथि बीत चुकी है।",
  before_cutoff: "जाँच के समय अंतिम तिथि बाकी थी।",
  after_cutoff: "जाँच के समय अंतिम तिथि बीत चुकी थी।",
  unknown: "तारीख की वर्तमान स्थिति निश्चित नहीं की जा सकी।",
};

const applicationTypeInHindi: Record<string, string> = {
  fresh: "नया आवेदन",
  renewal: "नवीनीकरण",
  unknown: "आवेदन का प्रकार स्पष्ट नहीं है",
};

function limitationInHindi(value: string): string | null {
  const normalized = value.toLowerCase();
  if (normalized.includes("ocr") || normalized.includes("recognition error")) {
    return "स्कैन किए गए PDF का पाठ OCR से पढ़ा गया है और उसमें पहचान की गलती हो सकती है।";
  }
  if (normalized.includes("partially parsed")) {
    return "स्रोत दस्तावेज़ का केवल कुछ हिस्सा पढ़ा जा सका।";
  }
  if (normalized.includes("could not be used")) {
    return "एक या अधिक संभावित स्रोत उपयोग नहीं किए जा सके।";
  }
  if (normalized.includes("did not search for amendments")) {
    return "इस जाँच ने संशोधित या बढ़ाई गई अंतिम तिथियाँ अलग से नहीं खोजीं।";
  }
  if (normalized.includes("publisher authority")) {
    return "स्रोत प्रकाशित करने वाली संस्था का अधिकार सत्यापित नहीं हो सका।";
  }
  if (normalized.includes("academic year does not match")) {
    return "स्रोत का शैक्षणिक वर्ष चुने गए वर्ष से मेल नहीं खाता।";
  }
  if (normalized.includes("no exact student submission date")) {
    return "छात्र आवेदन की सटीक अंतिम तिथि स्थापित नहीं हो सकी।";
  }
  return null;
}

function hindiDate(value: string) {
  return new Intl.DateTimeFormat("hi-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).format(new Date(`${value}T00:00:00+05:30`));
}

function HindiSummary({ report }: { report: Report }) {
  const deadline = report.student_deadline;
  const limitations = report.limitations ?? [];
  const applicationType = applicationTypeInHindi[report.scope.application_type]
    ?? "आवेदन का प्रकार स्पष्ट नहीं है";
  const mappedLimitations = limitations.map(limitationInHindi);
  const translatedLimitations = Array.from(
    new Set(mappedLimitations.filter((item): item is string => item !== null)),
  );
  const hasPublisherAuthorityConflict = (report.conflicts ?? []).some(
    (item) => typeof item === "object" && item !== null && item.kind === "publisher_authority",
  );
  if (hasPublisherAuthorityConflict) {
    translatedLimitations.push(
      "स्रोत प्रकाशित करने वाली संस्था का अधिकार सत्यापित नहीं हो सका।",
    );
  }
  const untranslatedLimitationCount = mappedLimitations.filter((item) => item === null).length;
  let conclusion = "इस दायरे के लिए छात्र आवेदन की अंतिम तिथि स्थापित नहीं हो सकी।";
  if (report.deadline_resolution === "conflicting") {
    conclusion = "लागू छात्र तिथियों में विरोध है, इसलिए एक अंतिम तिथि नहीं चुनी गई।";
  } else if (deadline) {
    conclusion = `${report.scope.programme_name} के लिए छात्र आवेदन की अंतिम तिथि ${hindiDate(deadline.date)} है।`;
  }

  return (
    <section className="hindi-summary" lang="hi" aria-labelledby="hindi-summary-title">
      <p className="eyebrow">सरल हिंदी सार</p>
      <h3 id="hindi-summary-title">रिपोर्ट का निष्कर्ष</h3>
      <p className="hindi-conclusion">{conclusion}</p>
      {deadline && <p>{timingInHindi[deadline.timing]}</p>}
      <dl>
        <div><dt>शैक्षणिक वर्ष</dt><dd>{report.scope.academic_year}</dd></div>
        <div><dt>आवेदन</dt><dd>{applicationType}</dd></div>
        <div><dt>साक्ष्य कवरेज</dt><dd>{report.coverage === "complete_for_attempted_scope" ? "जाँचे गए दायरे के लिए पूरा" : "आंशिक"}</dd></div>
      </dl>
      {limitations.length > 0 && (
        <div className="hindi-limitations" role="note">
          <strong>महत्वपूर्ण सीमाएँ</strong>
          {translatedLimitations.length > 0 && (
            <ul>{translatedLimitations.map((item) => <li key={item}>{item}</li>)}</ul>
          )}
          {untranslatedLimitationCount > 0 && (
            <p>
              {untranslatedLimitationCount} अतिरिक्त सीमा दर्ज है। पूरी मूल सूची नीचे अंग्रेज़ी में देखें।
            </p>
          )}
        </div>
      )}
      <p className="translation-caution">
        मूल साक्ष्य का अनुवाद नहीं किया गया है। निर्णय लेने से पहले साथ दिखाए गए आधिकारिक अंश को पढ़ें।
      </p>
    </section>
  );
}

export function ReportAccessTools({ report }: { report: Report }) {
  const [showHindi, setShowHindi] = useState(false);
  const canExport = report.deadline_resolution === "supported" && report.student_deadline !== null;

  function downloadCalendar() {
    const calendar = buildDeadlineCalendar(report);
    const url = URL.createObjectURL(new Blob([calendar], { type: "text/calendar;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = calendarFilename(report);
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
  }

  return (
    <div className="access-tools">
      <div className="access-tool-actions" aria-label="Report access tools">
        <button
          className="secondary-button"
          type="button"
          aria-expanded={showHindi}
          aria-controls="hindi-report-summary"
          onClick={() => setShowHindi((value) => !value)}
        >
          {showHindi ? "हिंदी सार छिपाएँ" : "हिंदी में समझें"}
        </button>
        {canExport && (
          <button className="secondary-button" type="button" onClick={downloadCalendar}>
            Add to calendar (.ics)
          </button>
        )}
      </div>
      {showHindi && <div id="hindi-report-summary"><HindiSummary report={report} /></div>}
    </div>
  );
}
