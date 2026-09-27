import { Button, Card, Heading, Select, Text, TextArea, TextField } from "@radix-ui/themes";
import { DownloadSimple, Eye, FileXls, FloppyDisk, Plus, Storefront, Trash } from "@phosphor-icons/react";
import { useMemo, useState } from "react";

import { useLocale } from "../LocaleContext";
import { quoteText } from "../quoteLocalization";
import { STOREFRONT_LANGUAGE_OPTIONS } from "../../lib/storefrontLocale";
import type { QuotePurchaseOrderItem, QuotePurchaseOrderSettings } from "../types";
import type { StorefrontLocale } from "../../types";
import "./PurchaseOrderPanel.css";

const purchaseLabels: Record<StorefrontLocale, [string, string, string, string, string]> = {
  "zh-CN": ["采购单", "采购单号", "供应商", "供应商货号", "地址"],
  "en-US": ["PURCHASE ORDER", "Purchase order No.", "Supplier", "Supplier item No.", "Address"],
  es: ["ORDEN DE COMPRA", "N.º de pedido", "Proveedor", "Ref. proveedor", "Dirección"],
  tr: ["SATIN ALMA SİPARİŞİ", "Sipariş No.", "Tedarikçi", "Tedarikçi ürün kodu", "Adres"],
  ar: ["أمر شراء", "رقم أمر الشراء", "المورّد", "رقم صنف المورّد", "العنوان"],
  ja: ["発注書", "発注番号", "仕入先", "仕入先品番", "住所"],
  ko: ["구매 주문서", "주문 번호", "공급업체", "공급업체 품번", "주소"],
  pt: ["PEDIDO DE COMPRA", "N.º do pedido", "Fornecedor", "Ref. do fornecedor", "Endereço"],
  fr: ["BON DE COMMANDE", "N° de commande", "Fournisseur", "Réf. fournisseur", "Adresse"],
  fa: ["سفارش خرید", "شماره سفارش", "تأمین‌کننده", "کد کالای تأمین‌کننده", "نشانی"],
  ru: ["ЗАКАЗ НА ЗАКУПКУ", "Номер заказа", "Поставщик", "Артикул поставщика", "Адрес"],
};

function purchaseText(locale: StorefrontLocale, key: "title" | "number" | "supplier" | "supplierSku" | "address") {
  return purchaseLabels[locale][{ title: 0, number: 1, supplier: 2, supplierSku: 3, address: 4 }[key]];
}

type PurchaseOrderPanelProps = {
  value: QuotePurchaseOrderSettings;
  onChange: (value: QuotePurchaseOrderSettings) => void;
  readOnly: boolean;
  saving: boolean;
  exporting: boolean;
  exportProgress?: { phase: "saving" | "generating" | "receiving"; receivedBytes?: number; totalBytes?: number };
  dirty: boolean;
  onSave: () => void;
  onExport: () => void;
  onOpenProduct: (itemId: string) => void;
};

function amount(item: QuotePurchaseOrderItem) {
  return item.unitPrice == null ? undefined : item.quantity * item.unitPrice;
}

function money(value: number | undefined, currency: string) {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`;
}

export function PurchaseOrderPanel({
  value,
  onChange,
  readOnly,
  saving,
  exporting,
  exportProgress,
  dirty,
  onSave,
  onExport,
  onOpenProduct,
}: PurchaseOrderPanelProps) {
  const { t } = useLocale();
  const groups = useMemo(() => {
    const result = new Map<string, { name: string; items: QuotePurchaseOrderItem[] }>();
    [...value.items].sort((left, right) => left.position - right.position).forEach((item) => {
      const name = item.supplierName.trim() || t("未指定供应商");
      const key = item.supplierId || `custom:${name.toLocaleLowerCase()}`;
      const current = result.get(key) ?? { name, items: [] };
      current.items.push(item);
      result.set(key, current);
    });
    return [...result.values()];
  }, [t, value.items]);
  const [activeSheet, setActiveSheet] = useState(0);
  const selectedSheetIndex = Math.min(activeSheet, Math.max(groups.length - 1, 0));
  const selectedGroup = groups[selectedSheetIndex];
  const visibleCustomFields = value.customFields.filter((field) => field.label.trim());
  const previewGrid = `40px 78px 118px 120px 220px 180px 85px 75px 100px 65px 110px 180px${visibleCustomFields.map(() => " 160px").join("")}`;
  const previewMinWidth = 1371 + visibleCustomFields.length * 160;
  const hasInvalidCustomFields = value.customFields.some((field) => !field.label.trim())
    || new Set(value.customFields.map((field) => field.label.trim().toLocaleLowerCase()).filter(Boolean)).size
      !== value.customFields.filter((field) => field.label.trim()).length;

  const updateItem = (itemId: string, patch: Partial<QuotePurchaseOrderItem>) => {
    onChange({
      ...value,
      items: value.items.map((item) => item.itemId === itemId ? { ...item, ...patch } : item),
    });
  };

  const changeSupplier = (item: QuotePurchaseOrderItem, supplierId: string) => {
    if (supplierId === "__custom__") {
      updateItem(item.itemId, { supplierId: undefined, supplierName: t("未指定供应商"), supplierSku: undefined, unitPrice: undefined });
      return;
    }
    const option = item.supplierOptions.find((candidate) => candidate.supplierId === supplierId);
    if (!option) return;
    updateItem(item.itemId, {
      supplierId: option.supplierId,
      supplierName: option.supplierName,
      supplierSku: option.supplierSku,
      unitPrice: option.unitPrice,
      currency: option.currency || item.currency,
    });
  };

  const addCustomField = () => {
    if (readOnly || value.customFields.length >= 12) return;
    const number = value.customFields.length + 1;
    onChange({
      ...value,
      customFields: [...value.customFields, {
        id: crypto.randomUUID(),
        label: `${t("自定义字段名称")} ${number}`,
        values: Object.fromEntries(value.items.map((item) => [item.itemId, ""])),
      }],
    });
  };

  const updateCustomField = (fieldId: string, patch: { label?: string; itemId?: string; content?: string }) => {
    onChange({
      ...value,
      customFields: value.customFields.map((field) => field.id !== fieldId ? field : {
        ...field,
        ...(patch.label !== undefined ? { label: patch.label } : {}),
        ...(patch.itemId !== undefined ? { values: { ...field.values, [patch.itemId]: patch.content ?? "" } } : {}),
      }),
    });
  };

  return <div className="purchase-order-workspace">
    <section className="purchase-order-editor">
      <div className="purchase-order-toolbar">
        <div>
          <Text size="1" color="gray">{t("采购单")}</Text>
          <Heading size="5">{t("按供应商制作采购单")}</Heading>
          <Text size="2" color="gray">{t("多供应商将打包为 ZIP")}</Text>
        </div>
        <div className="purchase-order-actions">
          <Button variant="soft" disabled={readOnly || saving || !dirty || hasInvalidCustomFields} loading={saving} onClick={onSave}><FloppyDisk />{t("保存")}</Button>
          <Button color="green" disabled={exporting || hasInvalidCustomFields} loading={exporting} onClick={onExport}><FileXls />{t("导出 Excel")}</Button>
        </div>
      </div>

      {exporting && exportProgress ? <div className="purchase-order-export-progress" role="status" aria-live="polite">
        <span>{exportProgress.phase === "saving" ? t("正在保存…") : exportProgress.phase === "generating" ? t("正在生成 Excel…") : t("导出 Excel")}</span>
        <progress max={exportProgress.totalBytes || 1} value={exportProgress.totalBytes ? exportProgress.receivedBytes || 0 : undefined} />
        {exportProgress.totalBytes ? <small>{Math.round(100 * (exportProgress.receivedBytes || 0) / exportProgress.totalBytes)}%</small> : null}
      </div> : null}

      <Card className="purchase-order-meta">
        <label><Text size="1" color="gray">{t("采购单号")}</Text><TextField.Root value={value.purchaseOrderNumber} disabled={readOnly} onChange={(event) => onChange({ ...value, purchaseOrderNumber: event.target.value })} /></label>
        <label><Text size="1" color="gray">{t("日期")}</Text><TextField.Root type="date" value={value.issueDate} disabled={readOnly} onChange={(event) => onChange({ ...value, issueDate: event.target.value })} /></label>
        <label><Text size="1" color="gray">{t("语言")}</Text><Select.Root value={value.locale} disabled={readOnly} onValueChange={(locale) => onChange({ ...value, locale: locale as StorefrontLocale })}><Select.Trigger aria-label={t("语言")} /><Select.Content position="popper">{STOREFRONT_LANGUAGE_OPTIONS.map((language) => <Select.Item value={language.code} key={language.code}>{language.flag} {language.label}</Select.Item>)}</Select.Content></Select.Root></label>
        <div className="purchase-order-sheet-summary"><Storefront /><div><strong>{groups.length}</strong><span>{t("供应商")}</span></div></div>
      </Card>

      <Card className="purchase-order-custom-fields">
        <div className="purchase-order-custom-fields-heading"><div><Text size="2" weight="medium">{t("自定义商品字段")}</Text><Text size="1" color="gray">{t("字段仅用于当前单据，可自由命名并逐项填写。")}</Text></div><Button size="1" variant="soft" disabled={readOnly || value.customFields.length >= 12} onClick={addCustomField}><Plus />{t("新增字段")}</Button></div>
        {value.customFields.length ? <div className="purchase-order-custom-field-list">{value.customFields.map((field) => <label key={field.id}><span>{t("自定义字段名称")}</span><TextField.Root value={field.label} maxLength={80} disabled={readOnly} onChange={(event) => updateCustomField(field.id, { label: event.target.value })}><TextField.Slot side="right"><button type="button" aria-label={t("删除自定义字段")} disabled={readOnly} onClick={() => onChange({ ...value, customFields: value.customFields.filter((entry) => entry.id !== field.id) })}><Trash /></button></TextField.Slot></TextField.Root></label>)}</div> : null}
      </Card>

      <div className="purchase-order-groups">
        {groups.map((group, groupIndex) => <Card className="purchase-order-group" key={`${group.name}-${groupIndex}`}>
          <div className="purchase-order-group-heading"><div><Text size="1" color="gray">Excel {groupIndex + 1}</Text><Heading size="3">{group.name}</Heading></div><Text size="2" color="gray">{t("{count} 个商品", { count: group.items.length })}</Text></div>
          <div className="purchase-order-lines">
            {group.items.map((item) => {
              const option = item.supplierOptions.find((candidate) => candidate.supplierId === item.supplierId);
              return <div className="purchase-order-line" key={item.itemId}>
                <div className="purchase-order-line-header">
                  <div className="purchase-order-product-identity">
                    {item.imageUrl ? <img src={item.imageUrl} alt="" /> : <span className="purchase-order-image-placeholder">{item.position}</span>}
                    <div><strong>{item.name}</strong><span>{item.skuCode}</span></div>
                  </div>
                  <Button size="1" variant="ghost" color="gray" onClick={() => onOpenProduct(item.itemId)}><Eye />{t("商品详情")}</Button>
                </div>
                <div className="purchase-order-supplier-area">
                  <label className="purchase-order-field purchase-order-field--wide"><span>{t("供应商")}</span><Select.Root value={item.supplierId || "__custom__"} disabled={readOnly} onValueChange={(next) => changeSupplier(item, next)}><Select.Trigger /><Select.Content position="popper">{item.supplierOptions.map((candidate) => <Select.Item key={candidate.supplierId} value={candidate.supplierId}>{candidate.supplierName}{candidate.supplierSku ? ` · ${candidate.supplierSku}` : ""}</Select.Item>)}<Select.Item value="__custom__">{t("未指定 / 手工填写")}</Select.Item></Select.Content></Select.Root></label>
                  <label className="purchase-order-field"><span>{t("供应商名称")}</span><TextField.Root value={item.supplierName} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { supplierId: undefined, supplierName: event.target.value })} /></label>
                  <label className="purchase-order-field"><span>{t("供应商货号")}</span><TextField.Root value={item.supplierSku || ""} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { supplierSku: event.target.value })} /></label>
                  {option ? <div className="purchase-order-supplier-facts"><span>{option.contactName || t("未填写联系人")}</span>{option.phone ? <span>{option.phone}</span> : null}{option.leadTimeDays != null ? <span>{t("交期 {days} 天", { days: option.leadTimeDays })}</span> : null}{option.moq != null ? <span>MOQ {option.moq} {option.moqUnit || ""}</span> : null}</div> : null}
                </div>
                <div className="purchase-order-line-fields">
                  <label className="purchase-order-field purchase-order-field--name"><span>{t("商品名称")}</span><TextField.Root value={item.name} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { name: event.target.value })} /></label>
                  <label className="purchase-order-field purchase-order-field--spec"><span>{t("规格")}</span><TextField.Root value={item.specification} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { specification: event.target.value })} /></label>
                  <label className="purchase-order-field"><span>{t("数量")}</span><TextField.Root type="number" min="0.000001" step="any" value={item.quantity} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { quantity: Number(event.target.value) })} /></label>
                  <label className="purchase-order-field"><span>{t("单位")}</span><TextField.Root value={item.unitCode} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { unitCode: event.target.value })} /></label>
                  <label className="purchase-order-field"><span>{t("采购单价")}</span><TextField.Root type="number" min="0" step="any" value={item.unitPrice ?? ""} disabled={readOnly} onChange={(event) => updateItem(item.itemId, { unitPrice: event.target.value === "" ? undefined : Number(event.target.value) })} /></label>
                  <label className="purchase-order-field"><span>{t("币种")}</span><TextField.Root value={item.currency} disabled={readOnly} maxLength={3} onChange={(event) => updateItem(item.itemId, { currency: event.target.value.toUpperCase() })} /></label>
                  <label className="purchase-order-field purchase-order-field--notes"><span>{t("备注")}</span><TextArea value={item.notes} disabled={readOnly} rows={2} onChange={(event) => updateItem(item.itemId, { notes: event.target.value })} /></label>
                  {value.customFields.map((field) => <label className="purchase-order-field" key={field.id}><span>{field.label || t("未命名字段")}</span><TextField.Root value={field.values[item.itemId] ?? ""} disabled={readOnly} maxLength={2000} onChange={(event) => updateCustomField(field.id, { itemId: item.itemId, content: event.target.value })} /></label>)}
                </div>
              </div>;
            })}
          </div>
        </Card>)}
      </div>
    </section>

    <aside className="purchase-order-preview">
      <div className="purchase-order-preview-heading"><div><Text size="1" color="gray">{t("Excel 预览")}</Text><Heading size="3">{selectedGroup?.name || t("未指定供应商")}</Heading></div><DownloadSimple /></div>
      <div className="purchase-order-sheet">
        <div className="purchase-order-sheet-title">{purchaseText(value.locale, "title")}</div>
        <div className="purchase-order-sheet-meta"><span>{purchaseText(value.locale, "number")}: {value.purchaseOrderNumber}</span><span>{quoteText(value.locale, "date")}: {value.issueDate}</span></div>
        <div className="purchase-order-sheet-supplier">{purchaseText(value.locale, "supplier")}: <strong>{selectedGroup?.name || t("未指定供应商")}</strong></div>
        <Text size="1" color="gray" className="purchase-order-scroll-hint">{t("左右滚动查看全部列")}</Text>
        <div className="purchase-order-preview-table">
          <div className="purchase-order-preview-row is-head" style={{ gridTemplateColumns: previewGrid, minWidth: previewMinWidth }}><span>{quoteText(value.locale, "serial_number")}</span><span>{quoteText(value.locale, "image")}</span><span>SKU</span><span>{purchaseText(value.locale, "supplierSku")}</span><span>{quoteText(value.locale, "product_name")}</span><span>{quoteText(value.locale, "specification")}</span><span>{quoteText(value.locale, "quantity")}</span><span>{quoteText(value.locale, "unit")}</span><span>{quoteText(value.locale, "unit_price")}</span><span>{quoteText(value.locale, "currency")}</span><span>{quoteText(value.locale, "line_total")}</span><span>{quoteText(value.locale, "notes")}</span>{visibleCustomFields.map((field) => <span key={field.id}>{field.label}</span>)}</div>
          {(selectedGroup?.items ?? []).map((item, index) => <div className="purchase-order-preview-row" style={{ gridTemplateColumns: previewGrid, minWidth: previewMinWidth }} key={item.itemId}><span>{index + 1}</span><span>{item.imageUrl ? <img src={item.imageUrl} alt="" /> : "—"}</span><span>{item.skuCode}</span><span>{item.supplierSku || "—"}</span><span>{item.name}</span><span>{item.specification || "—"}</span><span>{item.quantity}</span><span>{item.unitCode}</span><span>{money(item.unitPrice, item.currency)}</span><span>{item.currency}</span><span>{money(amount(item), item.currency)}</span><span>{item.notes || "—"}</span>{visibleCustomFields.map((field) => <span key={field.id}>{field.values[item.itemId] || "—"}</span>)}</div>)}
        </div>
      </div>
      <div className="purchase-order-sheet-tabs">{groups.map((group, index) => <button type="button" className={index === selectedSheetIndex ? "is-active" : ""} key={`${group.name}-${index}`} onClick={() => setActiveSheet(index)}>{group.name}</button>)}</div>
    </aside>
  </div>;
}
