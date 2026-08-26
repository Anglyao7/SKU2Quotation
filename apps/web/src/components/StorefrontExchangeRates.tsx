import { CaretDown, CurrencyDollar, WarningCircle } from "@phosphor-icons/react";
import { Container } from "@radix-ui/themes";
import { useEffect, useId, useMemo, useState } from "react";
import { api } from "../lib/api";
import { storefrontText } from "../lib/storefrontLocale";
import type {
  StorefrontExchangeRate,
  StorefrontExchangeRateSnapshot,
  StorefrontLocale,
} from "../types";

interface StorefrontExchangeRatesProps {
  tenantSlug: string;
  locale: StorefrontLocale;
}

type LoadStatus = "loading" | "ready" | "error";

function numericRate(item: StorefrontExchangeRate) {
  const value = Number(item.rate);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function formatRate(value: number, locale: StorefrontLocale) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 4,
    useGrouping: false,
  }).format(value);
}

function formatObservedAt(value: string, locale: StorefrontLocale) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(locale, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function StorefrontExchangeRates({
  tenantSlug,
  locale,
}: StorefrontExchangeRatesProps) {
  const panelId = useId();
  const [snapshot, setSnapshot] = useState<StorefrontExchangeRateSnapshot | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [open, setOpen] = useState(false);
  const [reloadVersion, setReloadVersion] = useState(0);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    void api.getStoreExchangeRates(tenantSlug)
      .then((result) => {
        if (cancelled) return;
        const hasRates = result.exchange_rates.some((item) => (
          item.currency !== result.base_currency && numericRate(item) !== null
        ));
        if (!hasRates) {
          setStatus("error");
          return;
        }
        setSnapshot(result);
        setStatus("ready");
      })
      .catch(() => {
        if (!cancelled) setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [reloadVersion, tenantSlug]);

  const rates = useMemo(() => (
    (snapshot?.exchange_rates ?? [])
      .filter((item) => item.currency !== snapshot?.base_currency)
      .map((item) => ({ item, value: numericRate(item) }))
      .filter((entry): entry is { item: StorefrontExchangeRate; value: number } => (
        entry.value !== null
      ))
  ), [snapshot]);
  const previewRates = useMemo(() => {
    const order = new Map(["USD", "EUR", "GBP"].map((code, index) => [code, index]));
    return [...rates]
      .sort((left, right) => (
        (order.get(left.item.currency) ?? 99) - (order.get(right.item.currency) ?? 99)
      ))
      .slice(0, 3);
  }, [rates]);
  const observedTime = snapshot
    ? formatObservedAt(snapshot.observed_at, locale)
    : "—";

  const handleTrigger = () => {
    if (status === "error") {
      setSnapshot(null);
      setReloadVersion((current) => current + 1);
      return;
    }
    if (status === "ready") setOpen((current) => !current);
  };

  return (
    <Container size="4" className="storefront-fx-container">
      <section
        className={`storefront-fx${open ? " is-open" : ""}${status === "error" ? " has-error" : ""}`}
        aria-busy={status === "loading"}
      >
        <button
          type="button"
          className="storefront-fx-trigger"
          aria-expanded={status === "ready" ? open : false}
          aria-controls={panelId}
          disabled={status === "loading"}
          onClick={handleTrigger}
        >
          <span className="storefront-fx-icon" aria-hidden="true">
            {status === "error" ? <WarningCircle weight="duotone" /> : <CurrencyDollar weight="duotone" />}
          </span>
          <span className="storefront-fx-summary">
            <strong>{t("实时汇率参考")}</strong>
            <small>
              {status === "loading"
                ? t("正在读取汇率…")
                : status === "error"
                  ? t("汇率暂时不可用，点击重试")
                  : t("更新于 {time}", { time: observedTime })}
            </small>
          </span>
          {status === "ready" ? (
            <span className="storefront-fx-preview" aria-hidden="true">
              {previewRates.map(({ item, value }) => (
                <span key={item.currency}>
                  <b>{item.currency}</b>
                  <em>¥{formatRate(value, locale)}</em>
                </span>
              ))}
            </span>
          ) : null}
          {status === "loading" ? (
            <span className="storefront-fx-loader" aria-hidden="true" />
          ) : status === "ready" ? (
            <CaretDown className="storefront-fx-caret" weight="bold" aria-hidden="true" />
          ) : (
            <span className="storefront-fx-retry">{t("重试")}</span>
          )}
        </button>

        {open && status === "ready" ? (
          <div className="storefront-fx-details" id={panelId}>
            <div className="storefront-fx-grid">
              {rates.map(({ item, value }) => (
                <div className="storefront-fx-rate" key={item.currency}>
                  <span>1 {item.currency}</span>
                  <strong>¥{formatRate(value, locale)} <small>CNY</small></strong>
                </div>
              ))}
            </div>
            <footer className="storefront-fx-footer">
              <span>
                {t("数据日期：{date}", { date: snapshot?.rate_date || "—" })}
                {snapshot?.rate_source ? ` · ${snapshot.rate_source}` : ""}
              </span>
              <span>{t("参考汇率，实际结算以银行或支付渠道为准。")}</span>
            </footer>
          </div>
        ) : null}
      </section>
    </Container>
  );
}
