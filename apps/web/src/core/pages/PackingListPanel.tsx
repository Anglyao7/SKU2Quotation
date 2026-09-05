import { Badge, Button, Heading, Text, TextField } from "@radix-ui/themes";
import { ArrowCounterClockwise, ArrowsOutSimple, Buildings, CaretDown, FilePdf, FileXls, FloppyDisk, ImageSquare, Minus, Package, Plus, SlidersHorizontal } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { StorefrontLocale } from "../../types";
import type { PackingListItem, PackingListSettings, PublicQuoteDraft } from "../types";
import { useLocale } from "../LocaleContext";
import { packingCalculation, packingErrors, packingFormat, packingParties, packingStudioText, packingText } from "../packingList";
import { proformaText, quoteFieldLabel, quoteText } from "../quoteLocalization";
import { buildPackingExcelSheet, excelSheetWidth, type DocumentPreviewMode } from "../documentExcelPreview";
import { DocumentExcelPreview } from "./DocumentExcelPreview";
import { DocumentPreviewModeSwitch } from "./DocumentPreviewModeSwitch";
import "./PackingListPanel.css";

type Props = {
  draft: PublicQuoteDraft; value: PackingListSettings; onChange: (value: PackingListSettings) => void;
  locale: StorefrontLocale; sellerName: string; readOnly: boolean; saving: boolean;
  onSave: () => void; dirty: boolean; languageControl: ReactNode;
  onExport: (format: "pdf" | "xlsx") => void; exporting?: string | null;
  previewMode: DocumentPreviewMode; onPreviewModeChange: (mode: DocumentPreviewMode) => void;
};

export function PackingListPanel({ draft, value, onChange, locale, sellerName, readOnly, saving, onSave, dirty, languageControl, onExport, exporting, previewMode, onPreviewModeChange }: Props) {
  const { t } = useLocale();
  const disabled = readOnly || saving || Boolean(exporting);
  const previewRef = useRef<HTMLDivElement>(null);
  const [previewWidth, setPreviewWidth] = useState(800);
  const [zoom, setZoom] = useState<number | "fit">("fit");
  useEffect(() => {
    const container = previewRef.current;
    if (!container) return;
    const observer = new ResizeObserver(([entry]) => setPreviewWidth(entry.contentRect.width));
    observer.observe(container);
    return () => observer.disconnect();
  }, []);
  const excelSheet = useMemo(() => buildPackingExcelSheet(draft, value, locale, sellerName), [draft, value, locale, sellerName]);
  const previewSheetWidth = previewMode === "excel" ? excelSheetWidth(excelSheet) : 1120;
  const scale = zoom === "fit" ? Math.min(1, Math.max(0.15, (previewWidth - 32) / previewSheetWidth)) : zoom;
  const rows = useMemo(() => draft.items.flatMap((order) => {
    const item = value.items.find((row) => row.itemId === order.id);
    return item ? [{ item, order, calc: packingCalculation(item, order) }] : [];
  }), [draft.items, value.items]);
  const parties = packingParties(value, draft, sellerName);
  const errors = packingErrors(value, draft.items, locale);
  const missing = rows.filter(({ calc }) => calc.totalVolume === null || calc.totalGrossWeight === null || calc.packing === null).length;
  const total = (key: "cartons" | "quantity" | "totalVolume" | "totalGrossWeight") => rows.some(({ calc }) => calc[key] === null) ? null : rows.reduce((sum, { calc }) => sum + (calc[key] ?? 0), 0);
  const edit = (itemId: string, patch: Partial<PackingListItem>) => onChange({ ...value, items: value.items.map((row) => row.itemId === itemId ? { ...row, ...patch } : row) });
  const headers = [quoteFieldLabel(locale, "product_image"), packingText(locale, 4), packingText(locale, 1), packingText(locale, 2), quoteFieldLabel(locale, "packing_quantity"), `${quoteFieldLabel(locale, "carton_dimensions")} (cm)`, quoteFieldLabel(locale, "carton_volume"), quoteFieldLabel(locale, "gross_weight"), packingText(locale, 3), packingText(locale, 5), quoteFieldLabel(locale, "total_volume"), quoteFieldLabel(locale, "total_gross_weight")];
  const metrics = [
    { label: packingText(locale, 3), value: total("cartons") }, { label: packingText(locale, 5), value: total("quantity") },
    { label: quoteFieldLabel(locale, "total_volume"), value: total("totalVolume") }, { label: quoteFieldLabel(locale, "total_gross_weight"), value: total("totalGrossWeight") },
  ];
  const itemInput = (row: PackingListItem, field: keyof PackingListItem, label: string, fallback = "") => <label className="packing-field" key={field}>
    <span>{label}</span><input aria-label={`${row.articleNumber || row.itemId} · ${label}`} inputMode={field === "barcode" ? "numeric" : field === "articleNumber" ? "text" : "decimal"}
      value={row[field] ?? fallback} placeholder={fallback || "—"} disabled={disabled}
      aria-invalid={field === "barcode" && Boolean(row.barcode.trim() && !/^\d{13}$/.test(row.barcode.trim()))}
      onChange={(event) => edit(row.itemId, { [field]: event.target.value })} />
  </label>;
  const partyEditor = (side: "seller" | "buyer") => {
    const party = parties[side];
    const fields = [["name", proformaText(locale, side), 200], ["contact", quoteText(locale, "contact"), 200], ["phone", quoteText(locale, "phone"), 100], ["email", quoteText(locale, "email"), 320]] as const;
    return <section className="packing-editor-section" aria-label={packingStudioText(locale, side === "seller" ? 1 : 2)}>
      <h3><Buildings size={18} />{packingStudioText(locale, side === "seller" ? 1 : 2)}</h3>
      <div className="packing-form-grid">{fields.map(([field, label, maxLength]) => <label className="packing-field" key={field}>
        <span>{label}</span><input value={party[field]} maxLength={maxLength} disabled={disabled} inputMode={field === "email" ? "email" : field === "phone" ? "tel" : "text"}
          onChange={(event) => onChange({ ...value, [`${side}${field[0].toUpperCase()}${field.slice(1)}`]: event.target.value })} />
      </label>)}<label className="packing-field packing-field--wide"><span>{proformaText(locale, `${side}_address`)}</span>
        <textarea rows={2} maxLength={2000} value={party.address} disabled={disabled} onChange={(event) => onChange({ ...value, [`${side}Address`]: event.target.value })} />
      </label></div>
    </section>;
  };
  return <section className="packing-panel" aria-label={packingText(locale, 0)}>
    <header className="packing-panel-header">
      <div className="packing-title"><Package size={25} /><div><Heading size="5">{packingText(locale, 0)}</Heading><Text size="2" color="gray">{value.packingListNumber}</Text></div>
        <Badge color={dirty ? "amber" : "green"} aria-live="polite">{saving ? t("正在保存…") : dirty ? t("未保存") : t("已保存")}</Badge>
      </div>
      <div className="packing-actions">
        {!readOnly ? <Button variant="outline" onClick={onSave} disabled={disabled || errors.length > 0} loading={saving}><FloppyDisk />{t("保存")}</Button> : null}
        <Button variant="outline" onClick={() => onExport("xlsx")} disabled={saving || Boolean(exporting) || errors.length > 0} loading={exporting === "xlsx"}><FileXls />{t("导出为 Excel")}</Button>
        <Button onClick={() => onExport("pdf")} disabled={saving || Boolean(exporting) || errors.length > 0} loading={exporting === "pdf"}><FilePdf />{t("导出为 PDF")}</Button>
      </div>
    </header>
    {errors.length > 0 ? <div className="packing-errors" role="alert">{errors.slice(0, 5).map((error, index) => <div key={index}>{error}</div>)}</div> : null}
    <div className="packing-studio">
      <div className="packing-editor" aria-label={t("编辑")}>
        <section className="packing-editor-section">
          <h3><SlidersHorizontal size={18} />{packingStudioText(locale, 0)}</h3>
          <div className="packing-form-grid">
            <label className="packing-field"><span>{packingText(locale, 0)} ID</span><TextField.Root value={value.packingListNumber} maxLength={80} disabled={disabled} onChange={(event) => onChange({ ...value, packingListNumber: event.target.value })} /></label>
            <label className="packing-field"><span>{quoteText(locale, "date")}</span><TextField.Root type="date" value={value.issueDate} disabled={disabled} onChange={(event) => onChange({ ...value, issueDate: event.target.value })} /></label>
            <div className="packing-field packing-field--wide"><span>{quoteText(locale, "language")}</span>{languageControl}</div>
          </div>
        </section>
        {partyEditor("seller")}{partyEditor("buyer")}
        <section className="packing-editor-section packing-product-section" aria-label={packingText(locale, 11)}>
          <h3><Package size={18} />{packingText(locale, 11)}<Badge color="gray">{rows.length}</Badge></h3>
          {missing > 0 ? <Text as="p" size="2" color="amber">{packingText(locale, 9)} · {missing}</Text> : null}
          {rows.map(({ item, order, calc }, index) => <details className="packing-product-editor" key={item.itemId} open={index === 0 ? true : undefined}>
            <summary><span className="packing-editor-image">{order.imageUrl ? <img src={order.imageUrl} alt="" loading="lazy" /> : <ImageSquare size={24} />}</span><span><strong>{item.name || order.name}</strong><small>{item.articleNumber ?? order.skuCode} · {quoteText(locale, "quantity")} {packingFormat(order.quantity)}</small></span><CaretDown size={16} /></summary>
            <div className="packing-form-grid">
              <label className="packing-field packing-field--wide"><span>{headers[1]}</span><textarea rows={2} maxLength={1000} aria-label={`${item.articleNumber || item.itemId} · ${headers[1]}`} value={item.name ?? order.name} disabled={disabled} onChange={(event) => edit(item.itemId, { name: event.target.value })} /></label>
              {itemInput(item, "articleNumber", headers[2], order.skuCode)}{itemInput(item, "barcode", headers[3])}
              {itemInput(item, "packingQuantity", headers[4])}{itemInput(item, "grossWeight", headers[7])}
              <div className="packing-dimensions packing-field--wide">{(["cartonLength", "cartonWidth", "cartonHeight"] as const).map((field, index) => itemInput(item, field, `${headers[5]} · ${["L", "W", "H"][index]}`))}</div>
              {[item.cartonLength, item.cartonWidth, item.cartonHeight].every(Boolean) ? <div className="packing-field"><span>{headers[6]}</span><output>{packingFormat(calc.volume)}</output></div> : itemInput(item, "cartonVolume", headers[6])}
              <div className="packing-cartons">{itemInput(item, "cartonCount", headers[8], calc.automaticCartons === null ? "" : String(calc.automaticCartons))}{item.cartonCount ? <button type="button" disabled={disabled} title={packingText(locale, 12)} aria-label={packingText(locale, 12)} onClick={() => edit(item.itemId, { cartonCount: "" })}><ArrowCounterClockwise /></button> : null}</div>
              {calc.partial || item.lastCartonGrossWeight ? itemInput(item, "lastCartonGrossWeight", packingText(locale, 7)) : null}
              <div className="packing-item-totals packing-field--wide">{[{ label: headers[9], number: calc.quantity }, { label: headers[10], number: calc.totalVolume }, { label: headers[11], number: calc.totalGrossWeight }].map(({ label, number }) => <span key={label}><small>{label}</small><strong>{packingFormat(number)}</strong></span>)}</div>
              {calc.partial && !item.lastCartonGrossWeight ? <Text size="1" color="gray" className="packing-field--wide">{packingText(locale, 17)}</Text> : null}
            </div>
          </details>)}
        </section>
        <section className="packing-editor-section"><label className="packing-field"><span>{quoteText(locale, "notes")}</span><textarea rows={3} maxLength={5000} value={value.remarks} disabled={disabled} onChange={(event) => onChange({ ...value, remarks: event.target.value })} /></label></section>
      </div>
      <aside className="packing-preview" aria-label={packingStudioText(locale, 3)}>
        <div className="packing-preview-toolbar"><DocumentPreviewModeSwitch value={previewMode} onChange={onPreviewModeChange} /><span><span className="packing-live-dot" />{packingStudioText(locale, 3)}</span><div>
          <button type="button" aria-label={t("缩小预览")} disabled={scale <= .25} onClick={() => setZoom(Math.max(.25, scale - .1))}><Minus size={15} /></button>
          <span className="packing-zoom-value">{Math.round(scale * 100)}%</span>
          <button type="button" aria-label={t("放大预览")} disabled={scale >= 1.5} onClick={() => setZoom(Math.min(1.5, scale + .1))}><Plus size={15} /></button>
          <button type="button" aria-label={t("适合窗口")} title={t("适合窗口")} onClick={() => setZoom("fit")}><ArrowsOutSimple size={16} /></button>
        </div></div>
        <div className="packing-preview-scroll" ref={previewRef} tabIndex={0}>
          {previewMode === "excel" ? <DocumentExcelPreview sheet={excelSheet} scale={scale} /> : <article className="packing-paper" style={{ zoom: scale }} dir={locale === "ar" || locale === "fa" ? "rtl" : "ltr"} aria-label={packingText(locale, 0)}>
            <header className="packing-paper-banner"><div><Package size={34} /><span>PACKING LIST</span></div><strong>{parties.seller.name || "—"}</strong></header>
            <div className="packing-paper-body">
              <div className="packing-paper-title"><h2>{packingText(locale, 0)}</h2><div><strong>{value.packingListNumber || "—"}</strong><span>{quoteText(locale, "date")} · {value.issueDate || "—"}</span></div></div>
              <div className="packing-paper-parties">{(["seller", "buyer"] as const).map((side) => <section key={side}>
                <h3>{proformaText(locale, side)}</h3><strong>{parties[side].name || "—"}</strong>
                <dl>{[[quoteText(locale, "contact"), parties[side].contact], [quoteText(locale, "phone"), parties[side].phone], [quoteText(locale, "email"), parties[side].email], [proformaText(locale, `${side}_address`), parties[side].address]].map(([label, content]) => <div key={label}><dt>{label}</dt><dd>{content || "—"}</dd></div>)}</dl>
              </section>)}</div>
              <table className="packing-paper-table">
                <colgroup>{[6, 17, 9, 10, 7, 11, 7, 7, 5, 7, 7, 7].map((width, index) => <col key={index} style={{ width: `${width}%` }} />)}</colgroup>
                <thead><tr>{headers.map((label) => <th key={label} scope="col">{label}</th>)}</tr></thead>
                <tbody>{rows.map(({ item, order, calc }) => <tr key={item.itemId}>
                  <td>{order.imageUrl ? <img src={order.imageUrl} alt={item.name || order.name} loading="lazy" /> : "—"}</td>
                  <td>{item.name || order.name}</td><td>{item.articleNumber ?? order.skuCode}</td><td className="packing-paper-barcode">{item.barcode || "—"}</td>
                  <td>{packingFormat(calc.packing)}</td><td>{[item.cartonLength, item.cartonWidth, item.cartonHeight].every(Boolean) ? `${item.cartonLength} × ${item.cartonWidth} × ${item.cartonHeight}` : "—"}</td>
                  {[calc.volume, calc.gross, calc.cartons, calc.quantity, calc.totalVolume, calc.totalGrossWeight].map((number, index) => <td key={index}>{packingFormat(number)}</td>)}
                </tr>)}</tbody>
                <tfoot><tr><th colSpan={8}>{quoteText(locale, "total")}</th>{metrics.map((metric) => <td key={metric.label}>{packingFormat(metric.value)}</td>)}</tr></tfoot>
              </table>
              <div className="packing-paper-summary">{metrics.map((metric) => <div key={metric.label}><span>{metric.label}</span><strong>{packingFormat(metric.value)}</strong></div>)}</div>
              {value.remarks.trim() ? <section className="packing-paper-notes"><h3>{quoteText(locale, "notes")}</h3><p>{value.remarks}</p></section> : null}
            </div>
          </article>}
        </div>
      </aside>
    </div>
  </section>;
}
