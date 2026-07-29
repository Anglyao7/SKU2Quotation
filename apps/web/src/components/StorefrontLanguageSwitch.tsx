import { Button, DropdownMenu } from "@radix-ui/themes";
import { Check, Translate } from "@phosphor-icons/react";
import { useLocation, useNavigate } from "react-router-dom";
import { storefrontText } from "../lib/storefrontLocale";
import type { StorefrontLocale } from "../types";

export function StorefrontLanguageSwitch({
  locale,
  onBeforeLocaleChange,
}: {
  locale: StorefrontLocale;
  onBeforeLocaleChange?: () => void;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const t = (source: string) => storefrontText(locale, source);

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
          aria-label={t("选择语言")}
        >
          <Translate size={17} />
          <span>{locale === "en-US" ? "EN" : "中"}</span>
        </Button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Content align="end" sideOffset={8}>
        <DropdownMenu.Item onSelect={() => selectLocale("zh-CN")}>
          <span className="storefront-language-check">
            {locale === "zh-CN" ? <Check /> : null}
          </span>
          中文
        </DropdownMenu.Item>
        <DropdownMenu.Item onSelect={() => selectLocale("en-US")}>
          <span className="storefront-language-check">
            {locale === "en-US" ? <Check /> : null}
          </span>
          English
        </DropdownMenu.Item>
      </DropdownMenu.Content>
    </DropdownMenu.Root>
  );
}
