// Client + pure helpers for the explicit preference-management surface.
//
// The backend returns the product-approved catalogue annotated with the owner's
// current value. The UI renders straight from that — human labels only, never
// raw keys or storage internals. Pure helpers here are unit-tested with
// node --test; the React panel stays a thin shell over them.

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Self-contained auth + scope headers (kept inline so this module stays
// dependency-free for unit tests). Mirrors lib/auth + lib/scope storage keys:
// the bearer token scopes to the account, and the workspace header scopes to a
// workspace when one is active (the backend only honours it for members).
function currentAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = window.localStorage.getItem("aira_auth_token");
    const workspace = window.localStorage.getItem("aira_active_workspace");
    return {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(workspace ? { "X-Workspace-Id": workspace } : {}),
    };
  } catch {
    return {};
  }
}

export type PreferenceOption = { value: string; label: string };

export type PreferenceItem = {
  key: string;
  label: string;
  description: string;
  options: PreferenceOption[];
  value: string | null; // current saved value, or null when unset
};

export type PreferenceScope = { kind: string; label: string; is_workspace: boolean };

export type PreferencesResponse = { preferences: PreferenceItem[]; scope?: PreferenceScope };

// The scope the last preferences response was for (which scope you're editing —
// "Personal" or a workspace). Captured so the card can label it without changing
// the item-returning function signatures.
let _lastScope: PreferenceScope | null = null;

export function lastPreferenceScope(): PreferenceScope | null {
  return _lastScope;
}

/** True when an error is a permission-denied (403) — used to show a calm,
 *  honest note instead of an "offline" state when editing a restricted scope. */
export function isForbiddenError(error: unknown): boolean {
  return error instanceof Error && error.message === "FORBIDDEN";
}

// ── Pure helpers (unit-tested) ───────────────────────────────────────────────

/** Human label for an item's current value, or a calm "Not set" when unset. */
export function selectedLabel(item: PreferenceItem): string {
  if (item.value == null) return "Not set";
  const match = item.options.find((o) => o.value === item.value);
  return match ? match.label : item.value;
}

/** True when this preference has a saved value (drives the "Remove" control). */
export function isSet(item: PreferenceItem): boolean {
  return item.value != null;
}

/** How many preferences the user has actually saved (for the summary line). */
export function savedCount(items: PreferenceItem[]): number {
  return items.filter((i) => i.value != null).length;
}

/** Defensive: drop anything that isn't a well-formed catalogue item, so a
 *  malformed payload can never render raw/unexpected content. */
export function sanitizeItems(items: unknown): PreferenceItem[] {
  if (!Array.isArray(items)) return [];
  return items.filter(
    (i): i is PreferenceItem =>
      !!i &&
      typeof i === "object" &&
      typeof (i as PreferenceItem).key === "string" &&
      typeof (i as PreferenceItem).label === "string" &&
      Array.isArray((i as PreferenceItem).options)
  );
}

// ── API client ───────────────────────────────────────────────────────────────

async function asPreferences(res: Response): Promise<PreferenceItem[]> {
  if (res.status === 403) throw new Error("FORBIDDEN");
  if (!res.ok) throw new Error(`Preferences request failed (${res.status})`);
  const body = (await res.json()) as PreferencesResponse;
  _lastScope = body?.scope ?? null;
  return sanitizeItems(body?.preferences);
}

export async function fetchPreferences(sessionId: string): Promise<PreferenceItem[]> {
  return asPreferences(
    await fetch(`${API_URL}/preferences?session_id=${encodeURIComponent(sessionId)}`, {
      cache: "no-store",
      headers: currentAuthHeaders(),
    })
  );
}

export async function savePreference(
  sessionId: string,
  key: string,
  value: string
): Promise<PreferenceItem[]> {
  return asPreferences(
    await fetch(`${API_URL}/preferences`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...currentAuthHeaders() },
      body: JSON.stringify({ session_id: sessionId, key, value }),
    })
  );
}

export async function removePreference(
  sessionId: string,
  key: string
): Promise<PreferenceItem[]> {
  return asPreferences(
    await fetch(
      `${API_URL}/preferences/${encodeURIComponent(key)}?session_id=${encodeURIComponent(sessionId)}`,
      { method: "DELETE", headers: currentAuthHeaders() }
    )
  );
}

export async function clearAllPreferences(sessionId: string): Promise<PreferenceItem[]> {
  return asPreferences(
    await fetch(`${API_URL}/preferences?session_id=${encodeURIComponent(sessionId)}`, {
      method: "DELETE",
      headers: currentAuthHeaders(),
    })
  );
}
