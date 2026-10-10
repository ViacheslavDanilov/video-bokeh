import { useCallback, useSyncExternalStore } from "react";

/**
 * A yes or no the browser keeps across reloads, for a choice about the page rather than
 * about one sequence.
 *
 * Read through useSyncExternalStore: the server renders `fallback`, the client switches to
 * what is stored once it hydrates, and neither a flash of the wrong state nor a hydration
 * warning comes with it. A browser that refuses storage keeps the choice until the reload.
 */

const listeners = new Set<() => void>();
const memory = new Map<string, boolean>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  // Another tab of the page changing it.
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function read(key: string, fallback: boolean): boolean {
  try {
    const stored = localStorage.getItem(key);
    if (stored !== null) return stored === "1";
  } catch {
    // Storage blocked: fall through to what this page load remembers.
  }
  return memory.get(key) ?? fallback;
}

export function useStoredFlag(
  key: string,
  fallback: boolean,
): [boolean, (value: boolean) => void] {
  const value = useSyncExternalStore(
    subscribe,
    () => read(key, fallback),
    () => fallback,
  );
  const set = useCallback(
    (next: boolean) => {
      memory.set(key, next);
      try {
        localStorage.setItem(key, next ? "1" : "0");
      } catch {
        // Kept in memory instead.
      }
      listeners.forEach((listener) => listener());
    },
    [key],
  );
  return [value, set];
}
