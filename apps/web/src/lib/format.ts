export function money(value?: number | string | null, currency = "CNY") {
  const locale = document.documentElement.lang || "zh-CN";
  if (value === null || value === undefined || value === "") {
    const labels: Record<string, string> = {
      "zh-CN": "价格面议",
      "en-US": "Price on request",
      es: "Precio a consultar",
      tr: "Fiyat için iletişime geçin",
      ar: "السعر عند الطلب",
      ja: "価格はお問い合わせください",
      ko: "가격 문의",
      pt: "Preço sob consulta",
    };
    return labels[locale] || labels["en-US"];
  }
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  try {
    return new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
      maximumFractionDigits: 2,
    }).format(numeric);
  } catch {
    return `${currency} ${numeric.toFixed(2)}`;
  }
}

export function dateTime(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(document.documentElement.lang || "zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function quoteNumber(quote: { quote_no?: string; number?: string; id: string }) {
  const actual = quote as typeof quote & { quote_number?: string };
  return actual.quote_number || quote.quote_no || quote.number || `QT-${quote.id.slice(0, 8).toUpperCase()}`;
}

export function initials(name?: string) {
  const source = name?.trim() || "智贸云";
  return source.slice(0, 2).toUpperCase();
}

export function primaryCategoryLabel(value?: string | null) {
  return value?.replace("／", "/").split("/", 1)[0]?.trim() || "";
}
