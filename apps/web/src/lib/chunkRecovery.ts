const RECOVERY_STORAGE_KEY = "zhimaoyun.bundle-recovery";
const RECOVERY_COOLDOWN_MS = 45_000;
const RECOVERY_QUERY_KEY = "__atc_release";

const chunkFailurePatterns = [
  /failed to fetch dynamically imported module/i,
  /error loading dynamically imported module/i,
  /importing a module script failed/i,
  /chunkloaderror/i,
  /loading chunk [\w-]+ failed/i,
];

interface RecoveryAttempt {
  attemptedAt: number;
  path: string;
}

function errorMessage(error: unknown) {
  if (error instanceof Error) return `${error.name}: ${error.message}`;
  return String(error ?? "");
}

function readAttempt(): RecoveryAttempt | undefined {
  try {
    const value = window.sessionStorage.getItem(RECOVERY_STORAGE_KEY);
    if (!value) return undefined;
    const parsed = JSON.parse(value) as Partial<RecoveryAttempt>;
    if (
      typeof parsed.attemptedAt !== "number"
      || typeof parsed.path !== "string"
    ) return undefined;
    return { attemptedAt: parsed.attemptedAt, path: parsed.path };
  } catch {
    return undefined;
  }
}

export function isChunkLoadFailure(error: unknown) {
  const message = errorMessage(error);
  return chunkFailurePatterns.some((pattern) => pattern.test(message));
}

export function reloadLatestBundle(force = false) {
  const now = Date.now();
  const currentPath = `${window.location.pathname}${window.location.search}`;
  const previous = readAttempt();
  if (
    !force
    && previous?.path === currentPath
    && now - previous.attemptedAt < RECOVERY_COOLDOWN_MS
  ) return false;

  try {
    window.sessionStorage.setItem(
      RECOVERY_STORAGE_KEY,
      JSON.stringify({ attemptedAt: now, path: currentPath }),
    );
  } catch {
    // Storage may be disabled; navigation still provides one recovery attempt.
  }

  const nextUrl = new URL(window.location.href);
  nextUrl.searchParams.set(
    RECOVERY_QUERY_KEY,
    import.meta.env.VITE_RELEASE_ID || String(now),
  );
  window.location.replace(nextUrl.toString());
  return true;
}

export async function importWithChunkRecovery<T>(
  loader: () => Promise<T>,
): Promise<T> {
  try {
    return await loader();
  } catch (error) {
    if (isChunkLoadFailure(error) && reloadLatestBundle()) {
      return await new Promise<T>(() => undefined);
    }
    throw error;
  }
}

export function installChunkRecovery() {
  window.addEventListener("vite:preloadError", (event) => {
    if (reloadLatestBundle()) event.preventDefault();
  });

  const currentUrl = new URL(window.location.href);
  if (!currentUrl.searchParams.has(RECOVERY_QUERY_KEY)) return;
  currentUrl.searchParams.delete(RECOVERY_QUERY_KEY);
  window.history.replaceState(
    window.history.state,
    "",
    `${currentUrl.pathname}${currentUrl.search}${currentUrl.hash}`,
  );
}
