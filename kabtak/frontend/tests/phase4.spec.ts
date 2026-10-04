import { expect, test, type Page, type Route } from "@playwright/test";

const programme = {
  id: "nmmss",
  name: "National Means-cum-Merit Scholarship Scheme",
  provider: "Ministry of Education",
  supported_cycles: ["2025-26", "2026-27"],
  application_types: ["fresh", "renewal"],
  support_status: "live_supported",
  last_checked_at: "2026-10-03T10:00:00Z",
};

const liveProgrammes = [
  programme,
  {
    ...programme,
    id: "pm-usp-csss",
    name: "PM-USP Central Sector Scheme of Scholarship",
  },
  {
    ...programme,
    id: "aicte-pragati",
    name: "AICTE Pragati Scholarship Scheme for Girl Students",
    supported_cycles: ["2026-27"],
    application_types: ["fresh", "renewal"],
  },
  {
    ...programme,
    id: "national-overseas-scholarship",
    name: "National Overseas Scholarship",
    supported_cycles: ["2025-26", "2026-27"],
    application_types: ["fresh"],
  },
  {
    ...programme,
    id: "top-class-st",
    name: "National Fellowship and Scholarship for Higher Education of ST Students",
    supported_cycles: ["2025-26", "2026-27"],
    application_types: ["fresh", "renewal"],
  },
];

const catalogueProgrammes = [
  ...liveProgrammes,
  {
    ...programme,
    id: "azim-premji-scholarship",
    name: "Azim Premji Scholarship",
    support_status: "coming_soon",
  },
];

const completedRun = {
  id: "run-1",
  check_id: "check-1",
  kind: "live",
  status: "completed",
  stage: "finished",
  reference_time: "2026-10-03T09:55:00Z",
  created_at: "2026-10-03T09:55:00Z",
  started_at: "2026-10-03T09:55:01Z",
  finished_at: "2026-10-03T10:00:00Z",
  heartbeat_at: "2026-10-03T10:00:00Z",
  retry_of_run_id: null,
  report_available: true,
  error: null,
};

const check = {
  id: "check-1",
  programme_id: "nmmss",
  programme_name: programme.name,
  academic_year: "2026-27",
  application_type: "fresh",
  applicant_group: null,
  profile: null,
  notice_url: null,
  saved_at: null,
  created_at: "2026-10-03T09:55:00Z",
  expires_at: "2026-10-04T09:55:00Z",
  latest_completed_run_id: "run-1",
  runs: [completedRun],
};

const evidence = {
  version_id: "version-1",
  block_id: "block-1",
  kind: "table",
  location: "revised schedule",
  text: "Student submission | 31 October 2026",
  metadata: {},
  content_sha256: "a".repeat(64),
  block_sha256: "b".repeat(64),
  retrieved_at: "2026-10-03T09:56:00Z",
  parse_status: "parsed",
  parser_version: "phase2-2",
  source_url: "https://www.pib.gov.in/PressReleasePage.aspx?PRID=1",
  publisher_role: "issuer_release",
};

function report(mode = "live") {
  return {
    run_id: "run-1",
    mode,
    reference_time: "2026-10-03T09:55:00Z",
    coverage: "complete_for_attempted_scope",
    scope: {
      programme_id: "nmmss",
      programme_name: programme.name,
      academic_year: "2026-27",
      application_type: "fresh",
      applicant_group: null,
    },
    deadline_resolution: "supported",
    student_deadline: {
      actor: "student",
      action: "submit",
      date: "2026-10-31",
      time: null,
      timezone: null,
      comparison_timezone: "Asia/Kolkata",
      timing: "date_ahead",
      evidence_refs: [{ version_id: "version-1", block_id: "block-1" }],
    },
    summary: "The student submission date in this notice is 2026-10-31.",
    portal_status: "not_checked",
    eligibility: "not_assessed",
    conditions: [],
    other_deadlines: [],
    conflicts: [],
    amendments: [],
    required_documents: [
      {
        source_text: "Upload the income certificate.",
        evidence_refs: [{ version_id: "version-1", block_id: "block-1" }],
      },
    ],
    application_links: [],
    limitations: mode === "replay" ? ["Historical replay; this is not an open opportunity."] : [],
    provenance: {
      rules_version: "phase3-2",
      schema_version: "4",
      input_mode: mode === "replay" ? "packaged_fixture" : "live_search_and_retrieval",
      model_id: "test",
      prompt_hash: "0".repeat(64),
    },
  };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function tabTo(page: Page, id: string) {
  for (let index = 0; index < 15; index += 1) {
    await page.keyboard.press("Tab");
    if ((await page.evaluate(() => document.activeElement?.id)) === id) return;
  }
  throw new Error(`Keyboard focus never reached #${id}`);
}

test("catalogue is keyboard reachable and has no page overflow at required widths", async ({ page }) => {
  await page.route("**/api/v1/programmes", (route) => json(route, catalogueProgrammes));
  for (const width of [360, 768, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/discover");
    await expect(page.getByText("3 Oct 2026").first()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  await page.goto("/discover");
  await tabTo(page, "catalogue-search");
  await expect(page.locator("#catalogue-search")).toBeFocused();
});

test("all five live programmes can be selected from the check form", async ({ page }) => {
  await page.route("**/api/v1/programmes", (route) => json(route, catalogueProgrammes));
  await page.route("**/api/v1/health", (route) => json(route, {
    worker_ready: true,
    live_search_enabled: true,
    live_extraction_enabled: true,
  }));

  await page.goto("/");
  const select = page.locator("#programme");
  await expect(select.locator("option")).toHaveCount(5);
  await expect(select.locator('option[value="azim-premji-scholarship"]')).toHaveCount(0);
  for (const item of liveProgrammes) {
    await select.selectOption(item.id);
    await expect(select).toHaveValue(item.id);
  }

  await select.selectOption("top-class-st");
  await expect(page.locator("#academic-year option")).toHaveCount(2);
  await expect(page.locator("#application-type option")).toHaveCount(2);

  await select.selectOption("national-overseas-scholarship");
  await expect(page.locator("#academic-year option")).toHaveCount(2);
  await expect(page.locator("#application-type option")).toHaveCount(1);
});

test("localhost is accepted as the configured loopback application's origin", async ({ page }) => {
  await page.goto("/");
  const result = await page.evaluate(async () => {
    const response = await fetch("/api/v1/checks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": "origin-probe" },
      body: "{}",
    });
    return { status: response.status, body: await response.json() };
  });

  expect(result.status).not.toBe(403);
  expect(result.body?.error?.code).not.toBe("ORIGIN_NOT_ALLOWED");
});

test("primary navigation exposes an explicit new-check action", async ({ page }) => {
  await page.goto("/discover");
  const newCheck = page.getByRole("link", { name: "New check" });
  await expect(newCheck).toHaveAttribute("href", "/#check");
  await newCheck.click();
  await expect(page.locator("#check")).toBeVisible();
});

test("offline replay opens its report and exact evidence without keys", async ({ page }) => {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/examples" && route.request().method() === "GET") {
      return json(route, [{
        id: "fixture-1",
        title: "Historical deadline replay",
        description: "Packaged evidence",
        programme_name: programme.name,
        academic_year: "2025-26",
        application_type: "fresh",
        reference_time: "2026-10-02T00:00:00+05:30",
        expected_student_deadline: "2025-09-30",
        source_url: evidence.source_url,
      }]);
    }
    if (url.pathname.endsWith("/replay")) return json(route, { check_id: "check-1", run_id: "run-1", status: "completed", poll_after_ms: 2000 }, 202);
    if (url.pathname === "/api/v1/checks/check-1") return json(route, { ...check, runs: [{ ...completedRun, kind: "replay" }] });
    if (url.pathname.endsWith("/report")) return json(route, report("replay"));
    if (url.pathname.endsWith("/changes")) return json(route, { run_id: "run-1", previous_run_id: null, classification: "initial_report", summary: "First report", outcome_changed: false, source_versions_changed: false, profile_changed: false, software_versions_changed: false, changes: [] });
    if (url.pathname.includes("/evidence/")) return json(route, evidence);
    return json(route, { error: { message: `Unhandled ${url.pathname}` } }, 404);
  });

  await page.goto("/examples");
  await page.getByRole("button", { name: /open offline replay/i }).click();
  await page.waitForURL("**/checks/check-1");
  await expect(page.getByText("Historical replay", { exact: true })).toBeVisible();
  await expect(page.getByText(evidence.text)).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh sources" })).toBeDisabled();
});

test("saved lifecycle exposes evidence, save, refresh, and delete actions", async ({ page }) => {
  let saved = false;
  let refreshed = false;
  let deleted = false;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/checks/check-1" && request.method() === "GET") {
      const queued = { ...completedRun, id: "run-2", kind: "refresh", status: "queued", stage: "queued", report_available: false, finished_at: null };
      return json(route, { ...check, saved_at: saved ? "2026-10-03T10:05:00Z" : null, runs: refreshed ? [queued, completedRun] : [completedRun] });
    }
    if (url.pathname === "/api/v1/checks/check-1" && request.method() === "PATCH") {
      saved = true;
      return json(route, { ...check, saved_at: "2026-10-03T10:05:00Z" });
    }
    if (url.pathname.endsWith("/refresh")) {
      refreshed = true;
      return json(route, { check_id: "check-1", run_id: "run-2", status: "queued", poll_after_ms: 2000 }, 202);
    }
    if (url.pathname === "/api/v1/checks/check-1" && request.method() === "DELETE") {
      deleted = true;
      return route.fulfill({ status: 204, body: "" });
    }
    if (url.pathname.endsWith("/report")) return json(route, report());
    if (url.pathname.endsWith("/changes")) return json(route, { run_id: "run-1", previous_run_id: null, classification: "initial_report", summary: "First report", outcome_changed: false, source_versions_changed: false, profile_changed: false, software_versions_changed: false, changes: [] });
    if (url.pathname.includes("/evidence/")) return json(route, evidence);
    if (url.pathname === "/api/v1/checks" && url.searchParams.get("saved") === "true") return json(route, []);
    return json(route, { error: { message: `Unhandled ${url.pathname}` } }, 404);
  });

  await page.goto("/checks/check-1");
  await expect(page.getByText(evidence.text)).toBeVisible();
  await page.getByRole("button", { name: "View evidence 1 ↓" }).first().click();
  await expect(page.locator(".evidence-inspector")).toBeFocused();
  await expect(page.getByRole("link", { name: "Open original source ↗" })).toHaveAttribute(
    "href",
    evidence.source_url,
  );
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("button", { name: "Unsave" })).toBeVisible();
  await page.getByRole("button", { name: "Refresh sources" }).click();
  await expect(page.getByText("Waiting for worker")).toBeVisible();

  refreshed = false;
  await page.reload();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Delete" }).click();
  await page.waitForURL("**/saved");
  expect(deleted).toBe(true);
});

test("conflicting evidence remains unresolved", async ({ page }) => {
  const conflictReport = {
    ...report(),
    deadline_resolution: "conflicting",
    student_deadline: null,
    summary: "Applicable student dates conflict.",
    conflicts: [{
      message: "Applicable sources disagree.",
      candidates: [
        { actor: "student", action: "submit", date: "2026-10-31", evidence_refs: [{ version_id: "version-1", block_id: "block-1" }] },
        { actor: "student", action: "submit", date: "2026-11-05", evidence_refs: [{ version_id: "version-2", block_id: "block-2" }] },
      ],
    }],
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/v1/checks/check-1") return json(route, check);
    if (url.pathname.endsWith("/report")) return json(route, conflictReport);
    if (url.pathname.endsWith("/changes")) return json(route, { run_id: "run-1", previous_run_id: null, classification: "initial_report", summary: "First report", outcome_changed: false, source_versions_changed: false, profile_changed: false, software_versions_changed: false, changes: [] });
    return json(route, evidence);
  });

  await page.goto("/checks/check-1");
  await expect(page.getByText("Not established")).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "Conflicting dates" })).toBeVisible();
});
