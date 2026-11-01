"use client";

/**
 * Data-fetching and interaction hooks.
 *
 * Written against React 19's rules rather than around them. Two patterns that used to be
 * idiomatic are now correctly flagged by the compiler-aware lint, and both have proper
 * replacements:
 *
 * * The "latest ref" trick (`ref.current = callback` during render) is a render-phase
 *   side effect. `useEffectEvent` does the same job — a stable function that always sees
 *   the current props — without writing during render.
 *
 * * Reading external state (matchMedia, storage) with `setState` inside an effect causes a
 *   cascading render on every mount. `useSyncExternalStore` is what that API is for, and
 *   it also gives a correct server snapshot so hydration does not mismatch.
 *
 * `useResource` derives `loading` from a request key rather than storing it, so fetching
 * needs no `setState` in the effect body at all.
 */

import {
  useCallback,
  useEffect,
  useEffectEvent,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

import { ApiError, NetworkError } from "./api";

type FetchError = ApiError | NetworkError;

function normaliseError(caught: unknown): FetchError {
  if (caught instanceof ApiError || caught instanceof NetworkError) return caught;
  return new NetworkError(caught);
}

export interface ResourceState<T> {
  data: T | null;
  loading: boolean;
  error: FetchError | null;
  /** Re-run the fetch. The previous data stays visible while it refetches. */
  reload: () => void;
  /** Replace the data locally, for an optimistic update after a mutation. */
  setData: (next: T | ((previous: T | null) => T)) => void;
}

interface Settled<T> {
  key: string;
  data: T | null;
  error: FetchError | null;
}

/**
 * Fetch a resource on mount and whenever `deps` change.
 *
 * `loading` is derived — it is true whenever the key we want is not the key we have — so
 * the effect never has to set it. That also makes "refetching while showing stale data"
 * fall out naturally rather than needing a second flag.
 *
 * `enabled: false` defers the fetch, for a parameter that is not known yet.
 */
export function useResource<T>(
  fetcher: () => Promise<T>,
  deps: readonly unknown[] = [],
  options: { enabled?: boolean } = {},
): ResourceState<T> {
  const enabled = options.enabled ?? true;
  const [nonce, setNonce] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);
  const [override, setOverride] = useState<{ key: string; data: T } | null>(null);

  // A stable identity for "which request should be in flight". Deps are serialised
  // because they are almost always primitives (ids, filters) and a stable string is what
  // the comparison below needs.
  const requestKey = useMemo(
    () => `${nonce}:${JSON.stringify(deps)}`,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nonce, ...deps],
  );

  const load = useEffectEvent(async (key: string, signal: AbortSignal) => {
    try {
      const result = await fetcher();
      if (!signal.aborted) setSettled({ key, data: result, error: null });
    } catch (caught) {
      if (signal.aborted) return;
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      // Keep whatever data we had: a failed refetch should not blank the page.
      setSettled((previous) => ({
        key,
        data: previous?.data ?? null,
        error: normaliseError(caught),
      }));
    }
  });

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    void load(requestKey, controller.signal);
    return () => controller.abort();
    // `load` is an effect event: stable by construction, and must not be a dependency.
  }, [enabled, requestKey]);

  const data = override?.key === requestKey ? override.data : (settled?.data ?? null);
  const error = settled?.key === requestKey ? settled.error : null;
  const loading = enabled && settled?.key !== requestKey;

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  const setData = useCallback(
    (next: T | ((previous: T | null) => T)) => {
      setOverride((previous) => {
        const base = previous?.key === requestKey ? previous.data : null;
        const resolved =
          typeof next === "function" ? (next as (p: T | null) => T)(base) : next;
        return { key: requestKey, data: resolved };
      });
    },
    [requestKey],
  );

  return { data, loading, error, reload, setData };
}

export interface MutationState<TArgs extends unknown[], TResult> {
  run: (...args: TArgs) => Promise<TResult | null>;
  pending: boolean;
  error: FetchError | null;
  /** Field-level errors from the backend, keyed by field name. */
  fieldErrors: Record<string, string>;
  reset: () => void;
}

/**
 * Wrap a mutation so every call site gets the same pending and error handling.
 *
 * Returns `null` rather than throwing on failure, so a handler can read
 * `const result = await run(); if (!result) return;` instead of wrapping every call in a
 * try/catch. The error is on `error` either way.
 */
export function useMutation<TArgs extends unknown[], TResult>(
  action: (...args: TArgs) => Promise<TResult>,
  options: { onSuccess?: (result: TResult) => void; onError?: (error: Error) => void } = {},
): MutationState<TArgs, TResult> {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<FetchError | null>(null);

  // `useEffectEvent` is not available here: `run` is called from a click handler, not
  // from an effect. Refs updated *in an effect* (never during render) give the same
  // "always current" behaviour while keeping `run`'s identity stable, which matters
  // because callers pass inline closures on every render.
  const actionRef = useRef(action);
  const optionsRef = useRef(options);
  useEffect(() => {
    actionRef.current = action;
    optionsRef.current = options;
  });

  const run = useCallback(async (...args: TArgs) => {
    setPending(true);
    setError(null);
    try {
      const result = await actionRef.current(...args);
      optionsRef.current.onSuccess?.(result);
      return result;
    } catch (caught) {
      const normalised = normaliseError(caught);
      setError(normalised);
      optionsRef.current.onError?.(normalised);
      return null;
    } finally {
      setPending(false);
    }
  }, []);

  const fieldErrors = useMemo(
    () => (error instanceof ApiError ? error.fieldErrors : {}),
    [error],
  );

  const reset = useCallback(() => setError(null), []);

  return { run, pending, error, fieldErrors, reset };
}

/** Debounce a value, so a search input does not fire a request per keystroke. */
export function useDebounced<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

// =====================================================================================
// External state
// =====================================================================================

const noopSubscribe = () => () => {};

/**
 * Whether we are past hydration.
 *
 * Needed by anything that portals into `document.body`. `useSyncExternalStore` with a
 * `false` server snapshot gives the correct answer in one render, where a
 * `useState`+`useEffect` pair causes a second.
 */
export function useIsClient(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}

function subscribeToQuery(query: string) {
  return (onChange: () => void) => {
    const media = window.matchMedia(query);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  };
}

export function useMediaQuery(query: string): boolean {
  const subscribe = useMemo(() => subscribeToQuery(query), [query]);
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    // Server snapshot: assume the query does not match, so the initial HTML never depends
    // on a viewport the server cannot know.
    () => false,
  );
}

/**
 * Whether the viewer has asked for reduced motion.
 *
 * Every non-trivial animation in COMPASS is gated on this. Motion here explains something
 * — a step advancing, a node connecting — so it is reduced to near-instant rather than
 * removed, but that is the viewer's call to make, not ours.
 */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

// A single listener set, so every `useLocalPreference` for the same key stays in step
// within the tab. The native `storage` event only fires for *other* tabs.
const storageListeners = new Set<() => void>();

function subscribeToStorage(onChange: () => void) {
  storageListeners.add(onChange);
  window.addEventListener("storage", onChange);
  return () => {
    storageListeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

function readPreference(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    // Private mode or blocked storage. The caller's fallback stands.
    return null;
  }
}

/**
 * A per-viewer UI preference backed by `localStorage`.
 *
 * For conveniences only — a remembered tab, a collapsed section. Never for state that has
 * to persist reliably or be shared between people, which belongs on the server. Every
 * access is wrapped because storage throws in a private window.
 */
export function useLocalPreference<T extends string>(
  key: string,
  fallback: T,
): [T, (value: T) => void] {
  const storageKey = `compass.${key}`;
  const stored = useSyncExternalStore(
    subscribeToStorage,
    () => readPreference(storageKey),
    () => null,
  );

  const update = useCallback(
    (next: T) => {
      try {
        window.localStorage.setItem(storageKey, next);
      } catch {
        /* Non-fatal: the value simply will not persist. */
      }
      // Notify in-tab subscribers; `storage` only fires cross-tab.
      for (const listener of storageListeners) listener();
    },
    [storageKey],
  );

  return [(stored as T | null) ?? fallback, update];
}

function readSessionFlag(key: string): boolean {
  try {
    return window.sessionStorage.getItem(key) === "dismissed";
  } catch {
    return false;
  }
}

/**
 * A dismissal that lasts for the browsing session.
 *
 * Used by the demo banner: someone demoing for an hour should not have to look at it the
 * whole time, but it returns on the next visit.
 */
export function useSessionDismissal(key: string): [boolean, () => void] {
  const storageKey = `compass.${key}`;
  const dismissed = useSyncExternalStore(
    subscribeToStorage,
    () => readSessionFlag(storageKey),
    () => false,
  );

  const dismiss = useCallback(() => {
    try {
      window.sessionStorage.setItem(storageKey, "dismissed");
    } catch {
      /* Non-fatal. */
    }
    for (const listener of storageListeners) listener();
  }, [storageKey]);

  return [dismissed, dismiss];
}

// =====================================================================================
// Interaction
// =====================================================================================

/** Close on Escape. Shared so every overlay behaves identically. */
export function useEscapeKey(onEscape: () => void, active = true): void {
  const handle = useEffectEvent(() => onEscape());

  useEffect(() => {
    if (!active) return;
    const listener = (event: KeyboardEvent) => {
      if (event.key === "Escape") handle();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
    // `handle` is an effect event and must not be listed as a dependency.
  }, [active]);
}

/**
 * Trap focus inside an element while it is open, and restore it on close.
 *
 * Without this, a keyboard user tabbing inside a dialog walks out into the page behind
 * it — disorienting, and a WCAG 2.4.3 failure.
 */
export function useFocusTrap<T extends HTMLElement>(active: boolean) {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    if (!active || !ref.current) return;
    const container = ref.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;

    const selector = [
      "a[href]",
      "button:not([disabled])",
      "input:not([disabled]):not([type='hidden'])",
      "select:not([disabled])",
      "textarea:not([disabled])",
      "[tabindex]:not([tabindex='-1'])",
    ].join(",");

    const focusables = () =>
      Array.from(container.querySelectorAll<HTMLElement>(selector)).filter(
        (element) => element.offsetParent !== null,
      );

    focusables()[0]?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = focusables();
      if (elements.length === 0) return;
      const first = elements[0]!;
      const last = elements[elements.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    container.addEventListener("keydown", onKeyDown);
    return () => {
      container.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [active]);

  return ref;
}

/** Lock body scroll while an overlay is open. */
export function useScrollLock(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [active]);
}

/**
 * State that resets when a key changes — a navigation, a selected id.
 *
 * Adjusting state during render against a stored key is React's own recommendation for
 * this, and it avoids the cascading render that `useEffect(() => setOpen(false), [key])`
 * produces on every navigation.
 */
export function useResetOnChange<T>(
  key: string,
  initial: T,
): [T, (value: T | ((previous: T) => T)) => void] {
  const [state, setState] = useState<{ key: string; value: T }>({ key, value: initial });

  const value = state.key === key ? state.value : initial;

  const set = useCallback(
    (next: T | ((previous: T) => T)) => {
      setState((previous) => {
        const base = previous.key === key ? previous.value : initial;
        return {
          key,
          value: typeof next === "function" ? (next as (p: T) => T)(base) : next,
        };
      });
    },
    [key, initial],
  );

  return [value, set];
}

/** Click or tap outside an element. Used to dismiss popovers. */
export function useOutsideClick<T extends HTMLElement>(
  active: boolean,
  onOutside: () => void,
) {
  const ref = useRef<T | null>(null);
  const handle = useEffectEvent(() => onOutside());

  useEffect(() => {
    if (!active) return;
    const listener = (event: MouseEvent | TouchEvent) => {
      if (!ref.current?.contains(event.target as Node)) handle();
    };
    document.addEventListener("mousedown", listener);
    document.addEventListener("touchstart", listener);
    return () => {
      document.removeEventListener("mousedown", listener);
      document.removeEventListener("touchstart", listener);
    };
    // `handle` is an effect event and must not be listed as a dependency.
  }, [active]);

  return ref;
}
