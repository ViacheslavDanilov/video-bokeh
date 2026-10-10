import { useCallback, useSyncExternalStore } from "react";

/**
 * A yes or no the browser keeps across reloads, for a choice about the page rather than
 * about one sequence.
 *
 * Read through useSyncExternalStore: the server renders `fallback`, and the client switches
 * to what is stored as it hydrates, without a hydration warning. A stored value other than
 * the fallback still shows the fallback for the first paint of a reload. A browser that
 * refuses storage keeps the choice until the reload.
 */

const listeners = new Set<() => void>();
const memory = new Map<string, boolean>();

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
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
