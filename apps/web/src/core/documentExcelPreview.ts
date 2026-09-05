import type { StorefrontLocale } from "../types";
import type { PackingListSettings, ProformaInvoiceSettings, PublicQuoteDraft, PublicQuoteDraftItem } from "./types";
import { packingCalculation, packingNumber, packingParties, packingText } from "./packingList";
import { invoiceLabel, invoiceParties } from "./proformaInvoice";
import { proformaText, quoteFieldLabel, quoteText, quoteUnit } from "./quoteLocalization";

export type DocumentPreviewMode = "pdf" | "excel";
export type ExcelCell = {
  value: string | number | null;
  span?: number;
  label?: boolean;
  imageUrl?: string;
  imageAlt?: string;
  format?: "decimal" | "grouped" | "money";
  currency?: string;
};
export type ExcelRow = {
  kind: "title" | "meta" | "blank" | "header" | "data" | "total" | "grand-total" | "section" | "note";
  cells: ExcelCell[];
  height?: number;
};
export type DocumentExcelSheet = {
  name: string;
  columns: number[];
  rows: ExcelRow[];
  rtl: boolean;
};
const cell = (value: ExcelCell["value"], options: Omit<ExcelCell, "value"> = {}): ExcelCell => ({ value, ...options });
const empty = (count: number) => Array.from({ length: count }, () => cell(null));
const numeric = (value: number | null, format: ExcelCell["format"] = "decimal", currency?: string) => cell(value, { format, currency });
export const excelSheetWidth = (sheet: DocumentExcelSheet) => 42 + sheet.columns.reduce((sum, width) => sum + width * 7 + 5, 0);
export function excelCellText(cell: ExcelCell): string {
  if (cell.value === null) return "";
  if (typeof cell.value !== "number" || !cell.format) return String(cell.value);
  const formatted = cell.value.toLocaleString("en-US", {
    useGrouping: cell.format !== "decimal",
    minimumFractionDigits: cell.format === "money" ? 2 : 0,
    maximumFractionDigits: cell.format === "money" ? 2 : 6,
  });
  return cell.currency ? `${cell.currency} ${formatted}` : formatted;
}

// Keep row order, merged cells and number formats aligned with the XLSX exporters.
// Build from the editor state, not the last saved download, so previews stay live.
export function buildProformaExcelSheet(draft: PublicQuoteDraft, invoice: ProformaInvoiceSettings, items: PublicQuoteDraftItem[], locale: StorefrontLocale, sellerName: string): DocumentExcelSheet {
  const p = (key: string) => proformaText(locale, key);
  const q = (key: string) => quoteText(locale, key);
  const parties = invoiceParties(invoice, draft, sellerName);
  const rows: ExcelRow[] = [{ kind: "title", cells: [cell(p("title"), { span: 9 })], height: 43 }];
  const meta = (leftLabel: string, left: string, rightLabel: string, right: string) => rows.push({ kind: "meta", cells: [cell(leftLabel, { label: true }), cell(left, { span: 3 }), cell(rightLabel, { label: true }), cell(right, { span: 4 })] });
  meta(p("seller"), parties.seller.name, p("invoice_number"), invoice.invoiceNumber);
  meta(p("seller_address"), invoice.sellerAddress || "-", p("issue_date"), invoice.issueDate);
  meta(q("email"), invoice.sellerEmail || "-", q("phone"), invoice.sellerPhone || "-");
  meta(p("buyer"), parties.buyer.name, p("valid_until"), draft.validUntil.slice(0, 10));
  meta(q("contact"), parties.buyer.contact, q("currency"), draft.currency);
  meta(p("buyer_address"), invoice.buyerAddress || "-", q("email"), invoice.buyerEmail ?? (draft.customerEmail || "-"));
  meta(`${p("seller")} · ${q("contact")}`, parties.seller.contact, `${p("buyer")} · ${q("phone")}`, parties.buyer.phone);
  if (invoice.sellerWebsite || invoice.sellerTaxNumber) meta(invoiceLabel(locale, 0), invoice.sellerWebsite || "", invoiceLabel(locale, 1), invoice.sellerTaxNumber || "");
  rows.push({ kind: "blank", cells: empty(9) });
  rows.push({ kind: "header", height: 38, cells: (["serial_number", "product_image", "sku_code", "product_name", "specification", "quantity", "unit_code", "unit_price", "line_total"] as const).map((key) => cell(quoteFieldLabel(locale, key))) });
  for (const item of items) rows.push({ kind: "data", height: 88, cells: [
    cell(item.position), cell(null, { imageUrl: item.imageUrl, imageAlt: item.name }), cell(item.skuCode), cell(item.name), cell(item.specification || ""),
    numeric(item.quantity, "grouped"), cell(quoteUnit(locale, item.unitCode)), numeric(item.unitPrice, "money"), numeric(item.lineTotal, "money"),
  ] });
  const subtotal = Number(items.reduce((sum, item) => sum + item.lineTotal, 0).toFixed(2));
  for (const [label, value] of [["subtotal", subtotal], ["freight", invoice.freight], ["grand_total", subtotal + invoice.freight]] as const) rows.push({ kind: label === "grand_total" ? "grand-total" : "total", cells: [...empty(7), cell(p(label)), numeric(value, "money", draft.currency)] });
  const section = (title: string, entries: [string, string | undefined][]) => {
    const populated = entries.filter(([, value]) => value);
    if (!populated.length) return;
    rows.push({ kind: "blank", cells: empty(9) }, { kind: "section", cells: [cell(title, { span: 9 })] });
    for (const [label, value] of populated) rows.push({ kind: "note", cells: [cell(label, { label: true }), cell(value!, { span: 8 })] });
  };
  section(p("trade_terms"), [[p("incoterm"), invoice.incoterm], [p("payment_terms"), invoice.paymentTerms], [p("delivery_terms"), invoice.deliveryTerms], [p("shipment_method"), invoice.shipmentMethod], [p("port_of_loading"), invoice.portOfLoading], [p("port_of_destination"), invoice.portOfDestination]]);
  if (invoice.beneficiaryName || invoice.bankName || invoice.bankAddress || invoice.bankAccountNumber || invoice.swiftCode) section(p("bank_details"), [[p("beneficiary_name"), invoice.beneficiaryName || parties.seller.name], [p("bank_name"), invoice.bankName], [p("bank_address"), invoice.bankAddress], [p("bank_account_number"), invoice.bankAccountNumber], [p("swift_code"), invoice.swiftCode]]);
  section(p("remarks"), [[p("remarks"), invoice.remarks], [q("notes"), draft.notes]]);
  const extras = draft.extraInformation?.filter((entry) => entry.title.trim() && entry.content.trim()) ?? [];
  if (extras.length) rows.push({ kind: "blank", cells: empty(9) });
  for (const entry of extras) rows.push({ kind: "note", cells: [cell(entry.title.trim(), { label: true }), cell(entry.content.trim(), { span: 8 })] });
  return { name: p("sheet_name").slice(0, 31), columns: [8, 14, 18, 34, 30, 12, 12, 15, 17], rows, rtl: locale === "ar" || locale === "fa" };
}

export function buildPackingExcelSheet(draft: PublicQuoteDraft, settings: PackingListSettings, locale: StorefrontLocale, sellerName: string): DocumentExcelSheet {
  const title = packingText(locale, 0);
  const parties = packingParties(settings, draft, sellerName);
  const rows: ExcelRow[] = [{ kind: "title", cells: [cell(title, { span: 12 })], height: 43 }, { kind: "meta", cells: [cell(`${settings.packingListNumber} · ${settings.issueDate}`, { span: 12 })] }];
  for (const side of ["seller", "buyer"] as const) {
    const party = parties[side];
    const content = [party.name || "—", ...[[quoteText(locale, "contact"), party.contact], [quoteText(locale, "phone"), party.phone], [quoteText(locale, "email"), party.email], [proformaText(locale, `${side}_address`), party.address]].map(([label, value]) => `${label}: ${value || "—"}`)].join("\n");
    rows.push({ kind: "meta", cells: [cell(`${proformaText(locale, side)}: ${content}`, { span: 12 })] });
  }
  const headers = [quoteFieldLabel(locale, "product_image"), packingText(locale, 4), packingText(locale, 1), packingText(locale, 2), quoteFieldLabel(locale, "packing_quantity"), `${quoteFieldLabel(locale, "carton_dimensions")} (cm)`, quoteFieldLabel(locale, "carton_volume"), quoteFieldLabel(locale, "gross_weight"), packingText(locale, 3), packingText(locale, 5), quoteFieldLabel(locale, "total_volume"), quoteFieldLabel(locale, "total_gross_weight")];
  rows.push({ kind: "header", cells: headers.map((value) => cell(value)), height: 48 });
  const packingItems = new Map(settings.items.map((item) => [item.itemId, item]));
  const calculations: ReturnType<typeof packingCalculation>[] = [];
  for (const order of draft.items) {
    const item = packingItems.get(order.id);
    if (!item) continue;
    const calc = packingCalculation(item, order);
    calculations.push(calc);
    const dimensions = [item.cartonLength, item.cartonWidth, item.cartonHeight].map((value) => packingNumber(value));
    rows.push({ kind: "data", height: 88, cells: [cell(null, { imageUrl: order.imageUrl, imageAlt: item.name || order.name }), cell(item.name || order.name), cell(item.articleNumber ?? order.skuCode), cell(item.barcode.trim()), numeric(calc.packing), cell(dimensions.every((value) => value !== null) ? dimensions.join(" × ") : ""), ...[calc.volume, calc.gross, calc.cartons, calc.quantity, calc.totalVolume, calc.totalGrossWeight].map((value) => numeric(value))] });
  }
  const totals = (["cartons", "quantity", "totalVolume", "totalGrossWeight"] as const).map((key) => calculations.some((calc) => calc[key] === null) ? null : calculations.reduce((sum, calc) => sum + (calc[key] ?? 0), 0));
  rows.push({ kind: "grand-total", cells: [cell(quoteText(locale, "total")), ...empty(7), ...totals.map((value) => numeric(value))] });
  if (settings.remarks) rows.push({ kind: "note", cells: [cell(`${quoteText(locale, "notes")}: ${settings.remarks}`, { span: 12 })] });
  return { name: title.slice(0, 31), columns: [14, 32, 22, 20, 16, 26, 17, 17, 13, 16, 19, 20], rows, rtl: locale === "ar" || locale === "fa" };
}
