import { Button, DropdownMenu } from "@radix-ui/themes";
import { Check, Translate } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLocation, useNavigate, useNavigation } from "react-router-dom";
import {
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
  storefrontText,
} from "../lib/storefrontLocale";
import type { StorefrontLocale } from "../types";
import { StorefrontFlag } from "./StorefrontFlag";

type LanguageTransition = {
  target: StorefrontLocale;
  phase: "loading" | "revealing";
  startedAt: number;
};

const LANGUAGE_TRANSITION_MINIMUM_MS = 520;
const LANGUAGE_TRANSITION_REVEAL_MS = 280;

export function StorefrontLanguageSwitch({
  locale,
  availableLocales,
  onBeforeLocaleChange,
}: {
  locale: StorefrontLocale;
  availableLocales?: StorefrontLocale[];
  onBeforeLocaleChange?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const navigation = useNavigation();
  const [transition, setTransition] = useState<LanguageTransition | null>(null);
  const revealTimerRef = useRef<number | undefined>(undefined);
  const finishTimerRef = useRef<number | undefined>(undefined);
  const t = (source: string) => storefrontText(locale, source);
  const languages = STOREFRONT_LANGUAGE_OPTIONS.filter((language) => (
    (availableLocales || ["zh-CN", "en-US"]).includes(language.code)
  ));
  const currentLanguage = storefrontLanguage(locale);

  useEffect(() => () => {
    if (revealTimerRef.current !== undefined) window.clearTimeout(revealTimerRef.current);
    if (finishTimerRef.current !== undefined) window.clearTimeout(finishTimerRef.current);
  }, []);

  useEffect(() => {
    if (!transition || transition.phase !== "loading") return;
    if (navigation.state !== "idle" || locale !== transition.target) return;

    const remaining = Math.max(
      0,
      LANGUAGE_TRANSITION_MINIMUM_MS - (performance.now() - transition.startedAt),
    );
    revealTimerRef.current = window.setTimeout(() => {
      setTransition((current) => (
        current?.target === transition.target
          ? { ...current, phase: "revealing" }
          : current
      ));
      finishTimerRef.current = window.setTimeout(() => {
        setTransition((current) => (
          current?.target === transition.target ? null : current
        ));
      }, LANGUAGE_TRANSITION_REVEAL_MS);
    }, remaining);

    return () => {
      if (revealTimerRef.current !== undefined) {
        window.clearTimeout(revealTimerRef.current);
        revealTimerRef.current = undefined;
      }
    };
  }, [locale, navigation.state, transition]);

  if (languages.length < 2) return null;

  const selectLocale = (nextLocale: StorefrontLocale) => {
    if (nextLocale === locale || transition) return;
    setTransition({
      target: nextLocale,
      phase: "loading",
      startedAt: performance.now(),
    });
    onBeforeLocaleChange?.();
    const params = new URLSearchParams(location.search);
    if (nextLocale === "zh-CN") params.delete("lang");
    else params.set("lang", nextLocale);
    const search = params.toString();
    // Let the light sweep paint before the route loader starts fetching the
    // selected language package. Otherwise a slow response looks like a dead click.
    window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        void navigate(
          {
            pathname: location.pathname,
            search: search ? `?${search}` : "",
            hash: location.hash,
          },
          { replace: true, state: location.state },
        );
      });
    });
  };

  return (
    <>
      <DropdownMenu.Root modal={false}>
        <DropdownMenu.Trigger>
          <Button
            className="storefront-language-trigger"
            size="2"
            variant="soft"
            color="gray"
            dir="ltr"
            aria-label={t("选择语言")}
            disabled={Boolean(transition)}
          >
            <Translate size={17} />
            <StorefrontFlag locale={currentLanguage.code} className="storefront-language-flag" />
            <span>{currentLanguage.shortLabel}</span>
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" sideOffset={8} className="storefront-language-menu">
          {languages.map((language) => (
            <DropdownMenu.Item
              key={language.code}
              onSelect={() => selectLocale(language.code)}
              dir="ltr"
            >
              <span className="storefront-language-check">
                {locale === language.code ? <Check /> : null}
              </span>
              <StorefrontFlag locale={language.code} className="storefront-language-flag" />
              <span lang={language.code} dir={language.direction}>{language.label}</span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Root>
      {transition && typeof document !== "undefined"
        ? createPortal(
            <div
              className={`storefront-language-transition is-${transition.phase}`}
              role="status"
              aria-live="polite"
              aria-label={`${t("选择语言")} · ${storefrontLanguage(transition.target).label}`}
            >
              <span className="storefront-language-transition-beam" aria-hidden="true" />
              <span className="visually-hidden">
                {t("选择语言")} · {storefrontLanguage(transition.target).label}
              </span>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
