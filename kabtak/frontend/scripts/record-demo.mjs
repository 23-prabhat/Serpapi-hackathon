import { mkdir, rename, rm } from "node:fs/promises";
import path from "node:path";

import { chromium } from "@playwright/test";

const baseURL = process.env.DEMO_BASE_URL ?? "http://127.0.0.1:3000";
const outputDirectory = path.resolve(process.cwd(), "../demo");
const temporaryDirectory = path.join(outputDirectory, ".recording");
const outputPath = path.join(outputDirectory, "kabtak-local-demo.webm");

await mkdir(temporaryDirectory, { recursive: true });
await rm(outputPath, { force: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1280, height: 720 },
  recordVideo: {
    dir: temporaryDirectory,
    size: { width: 1280, height: 720 },
  },
});
const page = await context.newPage();
const video = page.video();

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /know the date/i }).waitFor();
  await page.waitForTimeout(2_000);

  await page.getByRole("link", { name: /try an offline example/i }).click();
  await page.getByRole("heading", { name: /historical examples/i }).waitFor();
  await page.waitForTimeout(2_000);

  await page.getByRole("button", { name: /open offline replay/i }).click();
  await page.waitForURL(/\/checks\//);
  await page.getByText("Historical replay", { exact: true }).waitFor();
  await page.getByRole("heading", { name: /30 september 2025/i }).waitFor();
  await page.waitForTimeout(3_000);

  await page.getByText("Cited passage", { exact: true }).scrollIntoViewIfNeeded();
  await page.waitForTimeout(3_000);

  await page.getByRole("heading", { name: "Other actors’ deadlines" }).scrollIntoViewIfNeeded();
  await page.waitForTimeout(3_000);

  await page.getByRole("heading", { name: "Run history" }).scrollIntoViewIfNeeded();
  await page.waitForTimeout(2_000);
} finally {
  await context.close();
  await browser.close();
}

if (!video) {
  throw new Error("Playwright did not create a video artifact.");
}

await rename(await video.path(), outputPath);
await rm(temporaryDirectory, { recursive: true, force: true });
console.log(`Recorded ${outputPath}`);
