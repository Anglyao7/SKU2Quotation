import type { ProformaInvoiceSettings, PublicQuoteDraft } from "./types";
import type { StorefrontLocale } from "../types";

export function invoiceParties(invoice: ProformaInvoiceSettings, draft: PublicQuoteDraft, sellerName: string) {
  return {
    seller: { name: invoice.sellerName ?? sellerName, contact: invoice.sellerContact ?? "", phone: invoice.sellerPhone, email: invoice.sellerEmail, address: invoice.sellerAddress },
    buyer: { name: invoice.buyerName ?? (draft.customerCompany || draft.customerName), contact: invoice.buyerContact ?? draft.customerName, phone: invoice.buyerPhone ?? draft.customerPhone ?? "", email: invoice.buyerEmail ?? draft.customerEmail ?? "", address: invoice.buyerAddress },
  };
}
const labels: Record<StorefrontLocale, [string, string]> = {
  "zh-CN": ["官网", "税号"], "en-US": ["Website", "Tax ID"], es: ["Sitio web", "Identificación fiscal"], tr: ["Web sitesi", "Vergi numarası"],
  ar: ["الموقع الإلكتروني", "الرقم الضريبي"], ja: ["ウェブサイト", "税務番号"], ko: ["웹사이트", "납세자 번호"], pt: ["Site", "Número fiscal"],
  fr: ["Site web", "Numéro fiscal"], fa: ["وب‌سایت", "شناسه مالیاتی"],
};
export function invoiceLabel(locale: StorefrontLocale, index: number) { return labels[locale]?.[index] ?? labels["en-US"][index]; }
