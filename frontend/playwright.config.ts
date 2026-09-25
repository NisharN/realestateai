import { defineConfig, devices } from "@playwright/test";

// End-to-end tests against the demo stack: the FastAPI backend in in-memory
// mode (no Supabase / LLM keys → deterministic template replies) and the Next.js
// frontend in demo mode. Run: npm run e2e (first time: npx playwright install chromium).
const API_PORT = Number(process.env.E2E_API_PORT ?? 8010);
const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 3010);
const PYTHON = process.env.E2E_PYTHON ?? "../backend/venv/bin/python";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port ${API_PORT}`,
      cwd: "../backend",
      url: `http://localhost:${API_PORT}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 60_000,
      env: {
        SUPABASE_URL: "",
        SUPABASE_KEY: "",
        SUPABASE_SERVICE_KEY: "",
        GROQ_API_KEY: "",
        LLM_SECONDARY_API_KEY: "",
        LLM_SECONDARY_BASE_URL: "",
        LLM_OLLAMA_BASE_URL: "",
        REDIS_URL: "",
        CORS_ORIGINS: `http://localhost:${WEB_PORT}`,
      },
    },
    {
      command: `npx next dev --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        NEXT_PUBLIC_API_URL: `http://localhost:${API_PORT}`,
        NEXT_PUBLIC_DEMO_MODE: "true",
      },
    },
  ],
});
