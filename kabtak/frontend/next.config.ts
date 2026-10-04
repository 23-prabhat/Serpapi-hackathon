import type { NextConfig } from "next";
import { existsSync } from "node:fs";
import { loadEnvFile } from "node:process";
import { resolve } from "node:path";

// Next.js normally loads environment files from this frontend directory. Load
// the monorepo-level file too so the browser proxy and backend share one source.
// Existing process variables and frontend/.env.local remain valid overrides.
const sharedEnvPath = resolve(process.cwd(), "..", ".env");
if (existsSync(sharedEnvPath)) {
  loadEnvFile(sharedEnvPath);
}

const nextConfig: NextConfig = {
  /* config options here */
  reactCompiler: true,
};

export default nextConfig;
