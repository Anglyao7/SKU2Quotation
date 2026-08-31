import { Button, DropdownMenu } from "@radix-ui/themes";
import { Check, Translate } from "@phosphor-icons/react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
  storefrontText,
} from "../lib/storefrontLocale";
import type { StorefrontLocale } from "../types";
import { StorefrontFlag } from "./StorefrontFlag";

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
  const t = (source: string) => storefrontText(locale, source);
  const languages = STOREFRONT_LANGUAGE_OPTIONS.filter((language) => (
    (availableLocales || ["zh-CN", "en-US"]).includes(language.code)
  ));
  const currentLanguage = storefrontLanguage(locale);

  if (languages.length < 2) return null;

  const selectLocale = (nextLocale: StorefrontLocale) => {
    if (nextLocale === locale) return;
    onBeforeLocaleChange?.();
    const params = new URLSearchParams(location.search);
    if (nextLocale === "zh-CN") params.delete("lang");
    else params.set("lang", nextLocale);
    const search = params.toString();
    void navigate(
      {
        pathname: location.pathname,
        search: search ? `?${search}` : "",
        hash: location.hash,
      },
      { replace: true, state: location.state },
    );
  };

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger>
        <Button
          className="storefront-language-trigger"
          size="2"
          variant="soft"
          color="gray"
          dir="ltr"
          aria-label={t("选择语言")}
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
  );
}
