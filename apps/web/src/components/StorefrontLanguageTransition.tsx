import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { storefrontLanguage } from "../lib/storefrontLocale";
import type { StorefrontLocale } from "../types";

type LanguageTransition = {
  target: StorefrontLocale;
  phase: "loading" | "revealing";
  startedAt: number;
};

type StorefrontLanguageTransitionContextValue = {
  active: boolean;
  begin: (target: StorefrontLocale) => void;
  complete: (locale: StorefrontLocale) => void;
};

const LANGUAGE_TRANSITION_MINIMUM_MS = 520;
const LANGUAGE_TRANSITION_REVEAL_MS = 560;

const StorefrontLanguageTransitionContext = createContext<StorefrontLanguageTransitionContextValue>({
  active: false,
  begin: () => undefined,
  complete: () => undefined,
});

export function useStorefrontLanguageTransition() {
  return useContext(StorefrontLanguageTransitionContext);
}

export function StorefrontLanguageTransitionProvider({ children }: { children: ReactNode }) {
  const [transition, setTransition] = useState<LanguageTransition | null>(null);
  const transitionRef = useRef<LanguageTransition | null>(null);
  const revealTimerRef = useRef<number | undefined>(undefined);
  const finishTimerRef = useRef<number | undefined>(undefined);

  const clearTimers = useCallback(() => {
    if (revealTimerRef.current !== undefined) {
      window.clearTimeout(revealTimerRef.current);
      revealTimerRef.current = undefined;
    }
    if (finishTimerRef.current !== undefined) {
      window.clearTimeout(finishTimerRef.current);
      finishTimerRef.current = undefined;
    }
  }, []);

  useEffect(() => clearTimers, [clearTimers]);

  const begin = useCallback((target: StorefrontLocale) => {
    clearTimers();
    const next: LanguageTransition = {
      target,
      phase: "loading",
      startedAt: performance.now(),
    };
    transitionRef.current = next;
    setTransition(next);
  }, [clearTimers]);

  const complete = useCallback((locale: StorefrontLocale) => {
    const current = transitionRef.current;
    if (!current || current.phase !== "loading" || current.target !== locale) return;

    if (revealTimerRef.current !== undefined) window.clearTimeout(revealTimerRef.current);
    const remaining = Math.max(
      0,
      LANGUAGE_TRANSITION_MINIMUM_MS - (performance.now() - current.startedAt),
    );
    revealTimerRef.current = window.setTimeout(() => {
      const latest = transitionRef.current;
      if (!latest || latest.phase !== "loading" || latest.target !== locale) return;

      const revealing: LanguageTransition = { ...latest, phase: "revealing" };
      transitionRef.current = revealing;
      setTransition(revealing);
      finishTimerRef.current = window.setTimeout(() => {
        if (transitionRef.current?.target !== locale) return;
        transitionRef.current = null;
        setTransition(null);
        finishTimerRef.current = undefined;
      }, LANGUAGE_TRANSITION_REVEAL_MS);
      revealTimerRef.current = undefined;
    }, remaining);
  }, []);

  const contextValue = useMemo<StorefrontLanguageTransitionContextValue>(() => ({
    active: Boolean(transition),
    begin,
    complete,
  }), [begin, complete, transition]);

  return (
    <StorefrontLanguageTransitionContext.Provider value={contextValue}>
      {children}
      {transition && typeof document !== "undefined"
        ? createPortal(
            <div
              className={`storefront-language-transition is-${transition.phase}`}
              role="status"
              aria-live="polite"
              aria-label={`Switching language · ${storefrontLanguage(transition.target).label}`}
            >
              <span className="storefront-language-transition-beam" aria-hidden="true" />
              <span className="visually-hidden">
                Switching language · {storefrontLanguage(transition.target).label}
              </span>
            </div>,
            document.body,
          )
        : null}
    </StorefrontLanguageTransitionContext.Provider>
  );
}
