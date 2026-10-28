/**
 * Visual check harness.
 *
 * Logs in as each demo role against the running API, then saves a full-page
 * screenshot of every page in that role's portal at each viewport width into
 * web/screenshots/<role>/<page>--<width>.png.
 *
 *   make dev                      # api 8000, registry 8001, web 3000
 *   cd web && npm run screenshots
 *   npm run screenshots -- student aicte_officer   # only these targets
 *
 * Nothing here is part of the shipped app: it exists so a design change can be
 * reviewed as pixels rather than as diffs.
 */
import { mkdir, readFile, rm } from "node:fs/promises";
import path from "node:path";
import { chromium, type Browser, type Page } from "playwright";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WEB_URL = process.env.WEB_URL ?? "http://localhost:3000";
const OUT_DIR = path.join(__dirname, "..", "screenshots");
// Every account has its own password, written by `make reset` to this gitignored file.
const CREDENTIALS_CSV = path.join(__dirname, "..", "..", "demo_credentials.csv");
let passwords: Map<string, string> | null = null;

async function passwordFor(username: string): Promise<string> {
  if (!passwords) {
    const text = await readFile(CREDENTIALS_CSV, "utf-8").catch(() => {
      throw new Error(`${CREDENTIALS_CSV} not found — run the reset first.`);
    });
    passwords = new Map(
      text
        .trim()
        .split(/\r?\n/)
        .slice(1)
        .map((line) => line.split(","))
        .map(([user, , password]) => [user, password] as [string, string]),
    );
  }
  const password = passwords.get(username);
  if (!password) throw new Error(`no password for ${username} in demo_credentials.csv`);
  return password;
}

/** 1440 is the judging laptop, 768 a tablet, 390 a phone (student portal). */
const DESKTOP = [1440, 768];
const WITH_PHONE = [1440, 768, 390];

interface Target {
  /** Folder name, and the demo username to sign in as (null = signed out). */
  name: string;
  username: string | null;
  widths: number[];
  /** Page paths; `label` names the file, `path` may be filled in at runtime. */
  pages: ShotPage[];
}

interface ShotPage {
  label: string;
  path: string;
  /** Optional interaction to run before the shot, e.g. opening a second step. */
  prepare?: (page: Page) => Promise<void>;
}

const TARGETS: Target[] = [
  {
    name: "public",
    username: null,
    widths: WITH_PHONE,
    pages: [
      { label: "login-role", path: "/login" },
      {
        label: "login-account",
        path: "/login",
        // Step 2 has no URL of its own, so pick a role to get there.
        prepare: async (page) => {
          await page.getByRole("button", { name: /^Student/ }).click();
          await page.getByLabel("Demo account").waitFor({ timeout: 5000 });
        },
      },
      { label: "verify-qr", path: "/verify" },
    ],
  },
  {
    name: "institution",
    username: "rathnapura1_admin",
    widths: DESKTOP,
    pages: [
      { label: "dashboard", path: "/institution" },
      { label: "upload", path: "/institution/upload" },
      { label: "students", path: "/institution/students" },
      { label: "seat-matrix", path: "/institution/seat-matrix" },
      { label: "flags", path: "/institution/flags" },
      {
        label: "flag-detail",
        path: "/institution/flags",
        prepare: async (page) => {
          await page.locator("tbody tr").first().click();
          await page.getByRole("dialog").waitFor({ timeout: 5000 });
        },
      },
      { label: "uploads", path: "/institution/uploads" },
    ],
  },
  {
    name: "aicte_officer",
    username: "aicte_officer1",
    widths: DESKTOP,
    pages: [
      { label: "overview", path: "/aicte" },
      { label: "flags", path: "/aicte/flags" },
      {
        label: "flag-case",
        path: "/aicte/flags",
        prepare: async (page) => {
          await page.locator("tbody tr").first().click();
          await page.getByRole("dialog").waitFor({ timeout: 5000 });
        },
      },
      { label: "institutions", path: "/aicte/institutions" },
      { label: "institution-detail", path: "" },
      { label: "reports", path: "/aicte/reports" },
    ],
  },
  {
    name: "aicte_viewer",
    username: "aicte_viewer1",
    widths: DESKTOP,
    pages: [
      { label: "overview", path: "/aicte" },
      { label: "institutions", path: "/aicte/institutions" },
      { label: "reports", path: "/aicte/reports" },
    ],
  },
  {
    name: "student",
    username: "student_mismatch",
    widths: WITH_PHONE,
    pages: [
      { label: "home", path: "/student" },
      { label: "records", path: "/student/records" },
      { label: "access-log", path: "/student/access-log" },
      { label: "consents", path: "/student/consents" },
      { label: "id-card", path: "/student/id-card" },
    ],
  },
  {
    // A second student, chosen because this account actually has pending
    // consent requests and a revoked one — the states worth looking at.
    name: "student_consents",
    username: "student_pending",
    widths: WITH_PHONE,
    pages: [
      { label: "home", path: "/student" },
      { label: "consents", path: "/student/consents" },
      { label: "access-log", path: "/student/access-log" },
    ],
  },
  {
    name: "verifier",
    username: "verifier_demo",
    widths: DESKTOP,
    pages: [
      { label: "new-request", path: "/verifier" },
      { label: "requests", path: "/verifier/requests" },
      { label: "verify-qr", path: "/verify" },
    ],
  },
  {
    name: "admin",
    username: "admin",
    widths: DESKTOP,
    pages: [
      { label: "demo-controls", path: "/admin" },
      { label: "audit", path: "/admin/audit" },
    ],
  },
];

interface Session {
  token: string;
  user: unknown;
}

async function signIn(username: string): Promise<Session> {
  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password: await passwordFor(username) }),
  });
  if (!response.ok) throw new Error(`login failed for ${username}: ${response.status}`);
  const body = (await response.json()) as { access_token: string; user: unknown };
  return { token: body.access_token, user: body.user };
}

async function apiGet<T>(token: string, path: string): Promise<T | null> {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) return null;
  return (await response.json()) as T;
}

/** Fill in the detail-page paths, which need ids only the API knows. */
async function resolveDetailPages(target: Target, token: string) {
  if (target.name !== "aicte_officer") return;

  const institutions = await apiGet<{ items: { id: number }[] }>(
    token,
    "/aicte/institutions?page=1&page_size=1&sort=-open_flags_total",
  );

  const institutionId = institutions?.items?.[0]?.id;

  for (const page of target.pages) {
    if (page.label === "institution-detail" && institutionId !== undefined) {
      page.path = `/aicte/institutions/${institutionId}`;
    }
  }
}

/** Wait until the page has stopped loading data, so no skeleton is captured. */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle").catch(() => {});
  await page
    .waitForFunction(() => document.querySelectorAll('[aria-busy="true"]').length === 0, null, {
      timeout: 8000,
    })
    .catch(() => {});
  // Recharts animates in; give it a beat to finish.
  await page.waitForTimeout(600);
}

async function shoot(browser: Browser, target: Target, width: number, problems: string[]) {
  const session = target.username ? await signIn(target.username) : null;
  const context = await browser.newContext({
    viewport: { width, height: width >= 1440 ? 900 : width >= 768 ? 1024 : 844 },
    deviceScaleFactor: 1,
    isMobile: width < 768,
    hasTouch: width < 768,
  });

  if (session) {
    // The app keeps its JWT in sessionStorage; seeding it skips the login flow.
    await context.addInitScript(
      ([token, user]) => {
        try {
          sessionStorage.setItem("apaar.token", JSON.stringify(token));
          sessionStorage.setItem("apaar.user", JSON.stringify(user));
        } catch {
          /* private window — the screenshot run will just land on /login */
        }
      },
      [session.token, session.user] as [string, unknown],
    );
  }

  const page = await context.newPage();
  page.on("pageerror", (error) => problems.push(`${target.name} ${width}px: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") problems.push(`${target.name} ${width}px: ${message.text()}`);
  });

  const dir = path.join(OUT_DIR, target.name);
  await mkdir(dir, { recursive: true });

  for (const entry of target.pages) {
    if (!entry.path) {
      problems.push(`${target.name}: no path resolved for "${entry.label}" — skipped`);
      continue;
    }
    const file = path.join(dir, `${entry.label}--${width}.png`);
    try {
      await page.goto(`${WEB_URL}${entry.path}`, { waitUntil: "domcontentloaded", timeout: 30000 });
      await settle(page);
      if (entry.prepare) {
        await entry.prepare(page);
        await settle(page);
      }
      await page.screenshot({ path: file, fullPage: true });
      console.log(`  ${path.relative(path.join(__dirname, ".."), file)}`);
    } catch (error) {
      problems.push(`${target.name} ${entry.label} ${width}px: ${(error as Error).message}`);
    }
  }

  await context.close();
}

/**
 * Prefer Playwright's own Chromium, and fall back to the Chrome already on the
 * machine — so a teammate can run this without a 150 MB browser download.
 */
async function launchBrowser(): Promise<Browser> {
  try {
    return await chromium.launch();
  } catch (error) {
    console.log("Bundled Chromium unavailable; falling back to system Chrome.");
    try {
      return await chromium.launch({ channel: "chrome" });
    } catch {
      throw error;
    }
  }
}

async function main() {
  const only = process.argv.slice(2);
  const targets = only.length > 0 ? TARGETS.filter((t) => only.includes(t.name)) : TARGETS;
  if (targets.length === 0) {
    throw new Error(`No target matched ${only.join(", ")}. Known: ${TARGETS.map((t) => t.name).join(", ")}`);
  }

  const health = await fetch(`${API_URL}/health`).catch(() => null);
  if (!health?.ok) throw new Error(`API not reachable at ${API_URL}. Run 'make dev' first.`);

  if (only.length === 0) await rm(OUT_DIR, { recursive: true, force: true });

  const browser = await launchBrowser();
  const problems: string[] = [];
  try {
    for (const target of targets) {
      console.log(`\n${target.name}:`);
      if (target.username) {
        const session = await signIn(target.username);
        await resolveDetailPages(target, session.token);
      }
      for (const width of target.widths) await shoot(browser, target, width, problems);
    }
  } finally {
    await browser.close();
  }

  if (problems.length > 0) {
    console.log(`\n${problems.length} problem(s):`);
    for (const problem of [...new Set(problems)]) console.log(`  ! ${problem}`);
  } else {
    console.log("\nNo page errors.");
  }
  console.log(`\nScreenshots in ${OUT_DIR}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
