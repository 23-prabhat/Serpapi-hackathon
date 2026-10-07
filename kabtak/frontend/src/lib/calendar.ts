import type { Report } from "@/lib/api/types";

function escapeIcs(value: string) {
  return value
    .replaceAll("\\", "\\\\")
    .replaceAll("\n", "\\n")
    .replaceAll(",", "\\,")
    .replaceAll(";", "\\;");
}

function compactDate(value: string) {
  return value.replaceAll("-", "");
}

function nextDate(value: string) {
  const date = new Date(`${value}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function compactTimestamp(value: Date) {
  return value.toISOString().replaceAll("-", "").replaceAll(":", "").replace(/\.\d{3}Z$/, "Z");
}

function deadlineTimestampUtc(date: string, time: string, timezone: string | null | undefined) {
  if (timezone !== "UTC" && timezone !== "Asia/Kolkata") return null;
  const [year, month, day] = date.split("-").map(Number);
  const [hour, minute, second = 0] = time.split(":").map(Number);
  if (
    [year, month, day, hour, minute, second].some((value) => !Number.isInteger(value))
    || hour < 0
    || hour > 23
    || minute < 0
    || minute > 59
    || second < 0
    || second > 59
  ) {
    return null;
  }
  const offsetMinutes = timezone === "Asia/Kolkata" ? 330 : 0;
  const timestamp = new Date(
    Date.UTC(year, month - 1, day, hour, minute - offsetMinutes, second),
  );
  return compactTimestamp(timestamp);
}

function foldIcsLine(line: string) {
  const chunks: string[] = [];
  let chunk = "";
  for (const character of line) {
    if (new TextEncoder().encode(chunk + character).length > 73) {
      chunks.push(chunk);
      chunk = character;
    } else {
      chunk += character;
    }
  }
  chunks.push(chunk);
  return chunks.join("\r\n ");
}

export function calendarFilename(report: Report) {
  const name = report.scope.programme_name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
  return `${name || "scholarship"}-deadline.ics`;
}

export function buildDeadlineCalendar(report: Report, now = new Date()) {
  const deadline = report.student_deadline;
  if (!deadline || report.deadline_resolution !== "supported") {
    throw new Error("A supported student deadline is required for calendar export.");
  }

  const exactTimestamp = deadline.time
    ? deadlineTimestampUtc(deadline.date, deadline.time, deadline.timezone)
    : null;
  const summary = `${report.scope.programme_name} — student application deadline`;
  const publishedTiming = deadline.time
    ? exactTimestamp
      ? `Published time: ${deadline.time} ${deadline.timezone}`
      : `Published time: ${deadline.time}; timezone was not established or supported, so this is exported as an all-day event`
    : "Published as a date without an exact time";
  const description = [
    `Academic cycle: ${report.scope.academic_year}`,
    `Application type: ${report.scope.application_type}`,
    publishedTiming,
    `Checked by Kabtak at ${report.reference_time}`,
    "Confirm the deadline on the cited official source before submitting.",
  ].join("\n");
  const date = compactDate(deadline.date);
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Kabtak//Scholarship deadline//EN",
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "BEGIN:VEVENT",
    `UID:kabtak-${escapeIcs(report.run_id)}@local`,
    `DTSTAMP:${compactTimestamp(now)}`,
    `SUMMARY:${escapeIcs(summary)}`,
    `DESCRIPTION:${escapeIcs(description)}`,
  ];

  if (exactTimestamp) {
    lines.push(`DTSTART:${exactTimestamp}`);
  } else {
    lines.push(`DTSTART;VALUE=DATE:${date}`);
    lines.push(`DTEND;VALUE=DATE:${compactDate(nextDate(deadline.date))}`);
  }

  lines.push("STATUS:CONFIRMED", "TRANSP:TRANSPARENT", "END:VEVENT", "END:VCALENDAR", "");
  return lines.map(foldIcsLine).join("\r\n");
}
