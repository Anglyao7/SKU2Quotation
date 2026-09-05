import { Badge, Button, Heading, Text } from "@radix-ui/themes";
import { ArrowsOutSimple, Bank, Buildings, FilePdf, FileText, FileXls, FloppyDisk, Minus, Plus, SlidersHorizontal, Truck } from "@phosphor-icons/react";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { StorefrontLocale } from "../../types";
import type { ProformaInvoiceSettings, PublicQuoteDraft, PublicQuoteDraftItem } from "../types";
import { useLocale } from "../LocaleContext";
import { proformaText, quoteText, quoteUnit } from "../quoteLocalization";
import { invoiceLabel, invoiceParties } from "../proformaInvoice";
import { packingStudioText } from "../packingList";
import { buildProformaExcelSheet, excelSheetWidth, type DocumentPreviewMode } from "../documentExcelPreview";
import { DocumentExcelPreview } from "./DocumentExcelPreview";
import { DocumentPreviewModeSwitch } from "./DocumentPreviewModeSwitch";
import "./PackingListPanel.css";
import "./ProformaInvoicePanel.css";

type Props = {
  draft: PublicQuoteDraft; invoice: ProformaInvoiceSettings; onChange: (patch: Partial<ProformaInvoiceSettings>) => void;
  items: PublicQuoteDraftItem[]; itemEditor: ReactNode; locale: StorefrontLocale; sellerName: string; accent: string;
  settingsControls: ReactNode; readOnly: boolean; saving: boolean; exporting: string | null; dirty: boolean;
  onSave: () => void; onExport: (format: "pdf" | "xlsx") => void;
  previewMode: DocumentPreviewMode; onPreviewModeChange: (mode: DocumentPreviewMode) => void;
};
function money(value: number, currency: string) { return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`; }
export function ProformaInvoicePanel({ draft, invoice, onChange, items, itemEditor, locale, sellerName, accent, settingsControls, readOnly, saving, exporting, dirty, onSave, onExport, previewMode, onPreviewModeChange }: Props) {
  const { t } = useLocale();
  const disabled = readOnly || saving || Boolean(exporting);
  const [freightText, setFreightText] = useState(String(invoice.freight));
  useEffect(() => setFreightText(String(invoice.freight)), [invoice.freight]);
  const freightValid = /^\d+(?:\.\d{0,2})?$/.test(freightText.trim()) && Number.isFinite(Number(freightText)) && Number(freightText) >= 0;
  const valid = Boolean(invoice.invoiceNumber.trim() && invoice.issueDate && freightValid);
  const previewRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  useEffect(() => {
    if (!previewRef.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(previewRef.current);
    return () => observer.disconnect();
  }, []);
  const excelSheet = buildProformaExcelSheet(draft, invoice, items, locale, sellerName);
  const previewSheetWidth = previewMode === "excel" ? excelSheetWidth(excelSheet) : 794;
  const scale = zoom === "fit" ? Math.min(1, Math.max(.15, (width - 32) / previewSheetWidth)) : zoom;
  const parties = invoiceParties(invoice, draft, sellerName);
  const subtotal = Number(items.reduce((sum, item) => sum + item.lineTotal, 0).toFixed(2));
  const totals = [[proformaText(locale, "subtotal"), subtotal], [proformaText(locale, "freight"), invoice.freight], [proformaText(locale, "grand_total"), Number((subtotal + invoice.freight).toFixed(2))]] as const;
  const field = (key: keyof ProformaInvoiceSettings, label: string, options: { fallback?: string; wide?: boolean; multiline?: boolean; max?: number; type?: string } = {}) => <label className={`packing-field${options.wide ? " packing-field--wide" : ""}`} key={key}>
    <span>{label}</span>{options.multiline ? <textarea rows={2} maxLength={options.max ?? 2000} disabled={disabled} value={String(invoice[key] ?? options.fallback ?? "")} onChange={(event) => onChange({ [key]: event.target.value })} />
      : <input type={options.type ?? "text"} maxLength={options.max ?? 200} disabled={disabled} value={String(invoice[key] ?? options.fallback ?? "")} onChange={(event) => onChange({ [key]: event.target.value })} />}
  </label>;
  const partyEditor = (side: "seller" | "buyer") => <section className="packing-editor-section" aria-label={packingStudioText(locale, side === "seller" ? 1 : 2)}>
    <h3><Buildings size={18} />{packingStudioText(locale, side === "seller" ? 1 : 2)}</h3>
    <div className="packing-form-grid">
      {field(`${side}Name`, proformaText(locale, side), { fallback: parties[side].name })}
      {field(`${side}Contact`, quoteText(locale, "contact"), { fallback: parties[side].contact })}
      {field(`${side}Phone`, quoteText(locale, "phone"), { fallback: parties[side].phone, max: 80 })}
      {field(`${side}Email`, quoteText(locale, "email"), { fallback: parties[side].email, max: 320 })}
      {side === "seller" ? <>{field("sellerWebsite", invoiceLabel(locale, 0), { max: 500 })}{field("sellerTaxNumber", invoiceLabel(locale, 1), { max: 100 })}</> : null}
      {field(`${side}Address`, proformaText(locale, `${side}_address`), { wide: true, multiline: true })}
    </div>
  </section>;
  const tradeKeys = [["incoterm", "incoterm"], ["paymentTerms", "payment_terms"], ["deliveryTerms", "delivery_terms"], ["shipmentMethod", "shipment_method"], ["portOfLoading", "port_of_loading"], ["portOfDestination", "port_of_destination"]] as const;
  const bankKeys = [["beneficiaryName", "beneficiary_name"], ["bankName", "bank_name"], ["bankAccountNumber", "bank_account_number"], ["swiftCode", "swift_code"], ["bankAddress", "bank_address"]] as const;
  const bankConfigured = Boolean(invoice.bankName || invoice.bankAccountNumber || invoice.swiftCode || invoice.bankAddress || invoice.beneficiaryName);
  return <section className="packing-panel invoice-panel" aria-label={proformaText(locale, "title")} style={{ "--invoice-accent": accent } as CSSProperties}>
    <header className="packing-panel-header"><div className="packing-title"><FileText size={25} /><div><Heading size="5">PI · {proformaText(locale, "title")}</Heading><Text size="2" color="gray">{invoice.invoiceNumber}</Text></div><Badge color={dirty ? "amber" : "green"}>{saving ? t("正在保存…") : dirty ? t("未保存") : t("已保存")}</Badge></div>
      <div className="packing-actions">{!readOnly ? <Button variant="outline" onClick={onSave} disabled={disabled || !valid} loading={saving}><FloppyDisk />{t("保存")}</Button> : null}<Button variant="outline" onClick={() => onExport("xlsx")} disabled={!valid || saving || Boolean(exporting)} loading={exporting === "xlsx"}><FileXls />{t("导出为 Excel")}</Button><Button onClick={() => onExport("pdf")} disabled={!valid || saving || Boolean(exporting)} loading={exporting === "pdf"}><FilePdf />{t("导出为 PDF")}</Button></div>
    </header>
    <div className="packing-studio"><div className="packing-editor" aria-label={t("编辑")}>
      <section className="packing-editor-section"><h3><SlidersHorizontal size={18} />{packingStudioText(locale, 0)}</h3><div className="packing-form-grid">
        {field("invoiceNumber", proformaText(locale, "invoice_number"), { max: 80 })}{field("issueDate", proformaText(locale, "issue_date"), { type: "date" })}{settingsControls}
      </div></section>
      {partyEditor("seller")}{partyEditor("buyer")}
      <section className="packing-editor-section">{itemEditor}</section>
      <section className="packing-editor-section"><h3><Truck size={18} />{proformaText(locale, "trade_terms")}</h3><div className="packing-form-grid">
        {tradeKeys.map(([key, label]) => field(key, proformaText(locale, label), { multiline: key === "paymentTerms" || key === "deliveryTerms", wide: key === "paymentTerms" || key === "deliveryTerms", max: key === "incoterm" ? 120 : key === "paymentTerms" || key === "deliveryTerms" ? 2000 : 200 }))}
        <label className="packing-field"><span>{proformaText(locale, "freight")} · {draft.currency}</span><input inputMode="decimal" value={freightText} aria-invalid={!freightValid} disabled={disabled} onChange={(event) => { const text = event.target.value; setFreightText(text); if (/^\d+(?:\.\d{0,2})?$/.test(text) && Number.isFinite(Number(text))) onChange({ freight: Number(text) }); }} />{!freightValid ? <span className="invoice-field-error">{t("请输入有效的商品价格。")}</span> : null}</label>
      </div></section>
      <section className="packing-editor-section"><h3><Bank size={18} />{proformaText(locale, "bank_details")}</h3><div className="packing-form-grid">{bankKeys.map(([key, label]) => field(key, proformaText(locale, label), { multiline: key === "bankAddress", wide: key === "bankAddress", max: key === "swiftCode" ? 80 : key === "bankAccountNumber" ? 200 : key === "bankAddress" ? 2000 : 300 }))}</div></section>
      <section className="packing-editor-section">{field("remarks", proformaText(locale, "remarks"), { multiline: true, max: 5000 })}</section>
    </div>
    <aside className="packing-preview" aria-label={packingStudioText(locale, 3)}><div className="packing-preview-toolbar"><DocumentPreviewModeSwitch value={previewMode} onChange={onPreviewModeChange} /><span><span className="packing-live-dot" />{packingStudioText(locale, 3)}</span><div><button aria-label={t("缩小预览")} disabled={scale <= .25} onClick={() => setZoom(Math.max(.25, scale - .1))}><Minus size={15} /></button><span className="packing-zoom-value">{Math.round(scale * 100)}%</span><button aria-label={t("放大预览")} disabled={scale >= 1.5} onClick={() => setZoom(Math.min(1.5, scale + .1))}><Plus size={15} /></button><button aria-label={t("适合窗口")} onClick={() => setZoom("fit")}><ArrowsOutSimple size={16} /></button></div></div>
      <div className="packing-preview-scroll" ref={previewRef} tabIndex={0}>{previewMode === "excel" ? <DocumentExcelPreview sheet={excelSheet} scale={scale} accent={accent} /> : <article className="packing-paper invoice-paper" style={{ zoom: scale }} dir={locale === "ar" || locale === "fa" ? "rtl" : "ltr"}>
        <header className="packing-paper-banner"><div><FileText size={32} /><span>PROFORMA INVOICE</span></div><strong>{parties.seller.name || "—"}</strong></header>
        <div className="packing-paper-body"><div className="packing-paper-title"><div><small>{proformaText(locale, "title")}</small><h2>PI</h2></div><div><strong>{invoice.invoiceNumber || "—"}</strong><span>{quoteText(locale, "date")} · {invoice.issueDate || "—"}</span></div></div>
          <div className="packing-paper-parties">{(["seller", "buyer"] as const).map((side) => <section key={side}><h3>{proformaText(locale, side)}</h3><strong>{parties[side].name || "—"}</strong><dl>{[[quoteText(locale, "contact"), parties[side].contact], [quoteText(locale, "phone"), parties[side].phone], [quoteText(locale, "email"), parties[side].email], [proformaText(locale, `${side}_address`), parties[side].address], ...(side === "seller" ? [[invoiceLabel(locale, 0), invoice.sellerWebsite], [invoiceLabel(locale, 1), invoice.sellerTaxNumber]].filter((row) => row[1]) : [])].map(([label, content]) => <div key={label}><dt>{label}</dt><dd>{content || "—"}</dd></div>)}</dl></section>)}</div>
          <table className="packing-paper-table invoice-paper-table"><colgroup>{[5, 44, 16, 17, 18].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}</colgroup><thead><tr>{["#", quoteText(locale, "product_name"), `${quoteText(locale, "quantity")} / ${quoteText(locale, "unit")}`, quoteText(locale, "unit_price"), quoteText(locale, "line_total")].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{items.map((item, index) => <tr key={item.id}><td>{index + 1}</td><td><div className="invoice-product-cell">{item.imageUrl ? <img src={item.imageUrl} alt={item.name} /> : null}<div><strong>{item.name}</strong><small>{item.skuCode}</small>{item.description ? <small>{item.description}</small> : null}</div></div></td><td>{item.quantity} / {quoteUnit(locale, item.unitCode)}</td><td>{money(item.unitPrice, draft.currency)}</td><td>{money(item.lineTotal, draft.currency)}</td></tr>)}</tbody></table>
          <div className="invoice-totals">{totals.map(([label, amount], index) => <div className={index === 2 ? "is-grand-total" : ""} key={label}><span>{label}</span><strong>{money(amount, draft.currency)}</strong></div>)}</div>
          <section className="invoice-trade-grid">{tradeKeys.filter(([key], index) => index < 3 || invoice[key]).map(([key, label]) => <div key={key}><span>{proformaText(locale, label)}</span><strong>{invoice[key] || "—"}</strong></div>)}</section>
          {bankConfigured ? <section className="packing-paper-notes"><h3>{proformaText(locale, "bank_details")}</h3><dl className="invoice-bank">{bankKeys.filter(([key]) => invoice[key] || key === "beneficiaryName").map(([key, label]) => <div key={key}><dt>{proformaText(locale, label)}</dt><dd>{invoice[key] || parties.seller.name || "—"}</dd></div>)}</dl></section> : null}
          {invoice.remarks ? <section className="packing-paper-notes"><h3>{proformaText(locale, "remarks")}</h3><p>{invoice.remarks}</p></section> : null}
          {draft.notes ? <section className="packing-paper-notes"><h3>{quoteText(locale, "notes")}</h3><p>{draft.notes}</p></section> : null}
          {draft.extraInformation?.filter((entry) => entry.title.trim() && entry.content.trim()).map((entry, index) => <section className="packing-paper-notes" key={index}><h3>{entry.title}</h3><p>{entry.content}</p></section>)}
        </div>
      </article>}</div>
    </aside></div>
  </section>;
}
