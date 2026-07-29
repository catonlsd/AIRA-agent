import { spawn } from "node:child_process";
import { once } from "node:events";
import { resolve } from "node:path";

const ORIGIN = "http://127.0.0.1:3100";
const READY_TEXT = "aira-e2e-ready";

async function waitUntilReady(child: ReturnType<typeof spawn>) {
  const deadline = Date.now() + 120_000;

  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(`E2E server exited before becoming ready (code ${child.exitCode})`);
    }

    try {
      const response = await fetch(`${ORIGIN}/__aira_e2e_health`);
      if (response.ok && (await response.text()) === READY_TEXT) return;
    } catch {
      // The socket is expected to refuse connections while Next prepares.
    }

    await new Promise((resolve) => setTimeout(resolve, 100));
  }

  throw new Error(`E2E server did not become ready at ${ORIGIN}`);
}

/**
 * Start Next outside Playwright's transformed coordinator process, then stop it
 * through an explicit local endpoint. This avoids both transform-hook collisions
 * and Playwright's `taskkill`-based Windows web-server teardown.
 */
export default async function globalSetup() {
  const serverPath = resolve(process.cwd(), "e2e", "server.mjs");
  const child = spawn(process.execPath, [serverPath], {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
    windowsHide: true,
  });

  try {
    await waitUntilReady(child);
  } catch (error) {
    child.kill();
    throw error;
  }

  return async () => {
    const response = await fetch(`${ORIGIN}/__aira_e2e_shutdown`, { method: "POST" });
    if (response.status !== 202) {
      throw new Error(`E2E server rejected shutdown with HTTP ${response.status}`);
    }

    const exited = once(child, "exit");
    let timeoutId: ReturnType<typeof setTimeout>;
    const timeout = new Promise<never>((_, reject) => {
      timeoutId = setTimeout(
        () => reject(new Error("E2E server did not exit after shutdown")),
        10_000,
      );
    });
    try {
      await Promise.race([exited, timeout]);
    } finally {
      clearTimeout(timeoutId!);
    }
  };
}
