export function money(value?: number | string | null, currency = "CNY") {
  if (value === null || value === undefined || value === "") return "价格面议";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  try {
    return new Intl.NumberFormat("zh-CN", {
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
  return new Intl.DateTimeFormat("zh-CN", {
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

export function imageFallback(skuCode: string) {
  return `https://picsum.photos/seed/qingwan-${encodeURIComponent(skuCode)}/720/540`;
}

export function initials(name?: string) {
  const source = name?.trim() || "澄湾";
  return source.slice(0, 2).toUpperCase();
}
