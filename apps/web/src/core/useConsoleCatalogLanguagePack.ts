import { useEffect, useMemo, useState } from "react";
import type { CatalogLanguagePack, StorefrontLocale } from "../types";
import { getConsoleCatalogLanguagePack } from "./api";
import { useCoreAuth } from "./AuthContext";
import { useLocale } from "./LocaleContext";

interface ConsoleLanguagePackState {
  key: string;
  pack?: CatalogLanguagePack;
  error?: string;
}

export function useConsoleCatalogLanguagePack() {
  const { profile } = useCoreAuth();
  const { locale } = useLocale();
  const tenantId = profile?.context.tenantId || "";
  const key = `${tenantId}:${locale}`;
  const isSourceLocale = locale === "zh-CN";
  const [state, setState] = useState<ConsoleLanguagePackState>({
    key: isSourceLocale ? key : "",
  });

  useEffect(() => {
    let cancelled = false;
    if (!tenantId || isSourceLocale) {
      setState({ key });
      return () => { cancelled = true; };
    }
    setState({ key: "" });
    void getConsoleCatalogLanguagePack(locale)
      .then((pack) => {
        if (!cancelled) setState({ key, pack });
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setState({
            key,
            error: reason instanceof Error ? reason.message : "语言包读取失败。",
          });
        }
      });
    return () => { cancelled = true; };
  }, [isSourceLocale, key, locale, tenantId]);

  return useMemo(() => ({
    locale: locale as StorefrontLocale,
    pack: state.key === key ? state.pack : undefined,
    loading: Boolean(tenantId && !isSourceLocale && state.key !== key),
    error: state.key === key ? state.error : undefined,
  }), [isSourceLocale, key, locale, state, tenantId]);
}
