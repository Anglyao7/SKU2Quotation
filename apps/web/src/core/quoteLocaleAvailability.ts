import type { StorefrontLocale } from "../types";
import type { MerchantSettings } from "./types";

type QuoteLocaleSettings = Pick<
  MerchantSettings,
  "storefrontLocales" | "configuredStorefrontLocales"
>;

export function availableQuoteLocales(
  settings: QuoteLocaleSettings | undefined,
): StorefrontLocale[] {
  if (!settings) return [];
  const configured = new Set(settings.configuredStorefrontLocales);
  return settings.storefrontLocales.filter(
    (locale, index, values) => configured.has(locale) && values.indexOf(locale) === index,
  );
}
