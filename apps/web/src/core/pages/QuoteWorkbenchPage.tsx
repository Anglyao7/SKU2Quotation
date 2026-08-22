import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Dialog,
  DropdownMenu,
  Heading,
  IconButton,
  Select,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  ArrowRight,
  CaretDown,
  Check,
  ClipboardText,
  Columns,
  Copy,
  CurrencyDollar,
  DownloadSimple,
  FilePdf,
  FileText,
  FileXls,
  FloppyDisk,
  ImageSquare,
  Info,
  Package,
  LockKey,
  Palette,
  PaperPlaneTilt,
  SlidersHorizontal,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  CoreApiError,
  adjustPublicQuoteDraftPrices,
  convertPublicQuoteDraftCurrency,
  downloadPublicQuoteDraftDocument,
  getProduct,
  getDashboard,
  getMerchantSettings,
  getPublicQuoteDraft,
  listQuoteExcelTemplates,
  syncPublicQuoteDraftItemPrice,
  updatePublicQuoteDraftItems,
  updatePublicQuoteDraftItemPrice,
  updatePublicQuoteDraftSettings,
  updatePublicQuoteDraftStatus,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { ToastNotice, useToast } from "../ToastContext";
import type {
  MerchantSettings,
  ProductDetail,
  PublicQuoteDraft,
  PublicQuoteDraftItem,
  QuoteExcelTemplate,
  QuoteTemplateField,
  DashboardSnapshot,
} from "../types";
import type { StorefrontLocale } from "../../types";
import "./QuoteWorkbenchPage.css";

type QuoteDocumentStyle = PublicQuoteDraft["documentStyle"];
type QuoteItemEditField = "unitPrice" | "quantity" | "name" | "description" | "specification" | "category" | "unitCode";
type QuoteItemEdit = Partial<Record<QuoteItemEditField, string>>;
type QuoteSettingsPayload = {
  locale: StorefrontLocale;
  style: QuoteDocumentStyle;
  templateId: string | null;
  quoteNumber: string;
  visibleColumns: QuoteTemplateField[];
};

function quoteSettingsEqual(left: QuoteSettingsPayload | undefined, right: QuoteSettingsPayload) {
  return Boolean(left
    && left.locale === right.locale
    && left.style === right.style
    && left.templateId === right.templateId
    && left.quoteNumber === right.quoteNumber
    && left.visibleColumns.length === right.visibleColumns.length
    && left.visibleColumns.every((field, index) => field === right.visibleColumns[index]));
}

const locales: Array<{ value: StorefrontLocale; label: string; flag: string }> = [
  { value: "zh-CN", label: "简体中文", flag: "🇨🇳" },
  { value: "en-US", label: "English", flag: "🇺🇸" },
  { value: "es", label: "Español", flag: "🇪🇸" },
  { value: "tr", label: "Türkçe", flag: "🇹🇷" },
  { value: "ar", label: "العربية", flag: "🇸🇦" },
  { value: "ja", label: "日本語", flag: "🇯🇵" },
  { value: "ko", label: "한국어", flag: "🇰🇷" },
  { value: "pt", label: "Português", flag: "🇵🇹" },
];

const styles: Array<{ value: QuoteDocumentStyle; label: string; color: string }> = [
  { value: "indigo", label: "海军蓝", color: "#314B9B" },
  { value: "emerald", label: "翡翠绿", color: "#087F5B" },
  { value: "gold", label: "鎏金", color: "#B88A25" },
  { value: "slate", label: "石墨灰", color: "#334155" },
  { value: "rose", label: "玫瑰红", color: "#9F3B5B" },
];

const tableFieldMeta: Array<{ value: QuoteTemplateField; label: string }> = [
  { value: "serial_number", label: "序号" },
  { value: "product_name", label: "商品名称" },
  { value: "description", label: "商品描述" },
  { value: "specification", label: "商品规格" },
  { value: "category", label: "商品分类" },
  { value: "tags", label: "商品标签" },
  { value: "product_image", label: "商品图片" },
  { value: "quantity", label: "数量" },
  { value: "unit_code", label: "单位" },
  { value: "packing_quantity", label: "装箱数量" },
  { value: "carton_dimensions", label: "装箱尺寸" },
  { value: "gross_weight", label: "毛重（kg）" },
  { value: "carton_volume", label: "立方（m³）" },
  { value: "unit_price", label: "单价" },
  { value: "line_total", label: "总价" },
  { value: "total_volume", label: "总立方（m³）" },
  { value: "total_gross_weight", label: "总毛重（kg）" },
  { value: "currency", label: "币种" },
];

const defaultTableFields: QuoteTemplateField[] = [
  "serial_number",
  "product_name",
  "quantity",
  "unit_code",
  "unit_price",
  "line_total",
];

function localeLabel(value: StorefrontLocale) {
  const option = locales.find((row) => row.value === value);
  return option ? `${option.flag} ${option.label}` : value;
}

function templateTableFields(template?: QuoteExcelTemplate): QuoteTemplateField[] {
  if (!template) return [...defaultTableFields];
  const mapped = template.columns
    .map((column) => template.columnMappings[column.key])
    .filter((field): field is QuoteTemplateField => Boolean(field))
    .filter((field) => tableFieldMeta.some((option) => option.value === field));
  const unique = [...new Set(mapped)];
  return unique.length ? unique : [...defaultTableFields];
}

function fieldLabel(field: QuoteTemplateField, t: (value: string) => string, template?: QuoteExcelTemplate) {
  const templateColumn = template?.columns.find((column) => template.columnMappings[column.key] === field);
  if (templateColumn?.header?.trim()) return templateColumn.header.trim();
  return t(tableFieldMeta.find((option) => option.value === field)?.label ?? field);
}

function optionValue(item: PublicQuoteDraftItem, keys: string[]) {
  const values = item.optionValues ?? {};
  const entry = Object.entries(values).find(([key, value]) => {
    if (key.startsWith("_")) return false;
    const normalized = key.replace(/[\s_\-:：]/g, "").toLowerCase();
    return keys.some((candidate) => normalized === candidate.replace(/[\s_\-:：]/g, "").toLowerCase()) && value !== null && value !== undefined && value !== "";
  });
  if (!entry) return "";
  return Array.isArray(entry[1]) ? entry[1].join("、") : String(entry[1]);
}

function money(value: number, currency: string) {
  return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function displayOptionValue(value: unknown) {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join("、");
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).map((entry) => String(entry)).join("、");
  return value == null ? "" : String(value);
}

function previewValue(item: PublicQuoteDraftItem, field: QuoteTemplateField) {
  switch (field) {
    case "serial_number": return String(item.position);
    case "product_name": return item.name;
    case "description": return item.description ?? "";
    case "specification": return item.specification ?? optionValue(item, ["规格", "规格名称"]);
    case "category": return item.category ?? "";
    case "tags": return item.tags.join("、");
    case "product_image": return item.imageUrl ? "已配置" : "";
    case "quantity": return String(item.quantity);
    case "unit_code": return item.unitCode;
    case "packing_quantity": return optionValue(item, ["装箱数量", "装箱数", "一箱个数"]);
    case "carton_dimensions": return optionValue(item, ["装箱尺寸", "外箱尺寸", "箱规"]);
    case "gross_weight": return optionValue(item, ["毛重", "箱毛重"]);
    case "carton_volume": return optionValue(item, ["立方", "箱体积", "cbm"]);
    case "unit_price": return money(item.unitPrice, item.currency);
    case "line_total": return money(item.lineTotal, item.currency);
    case "total_volume": return optionValue(item, ["总立方", "总立方数", "total_volume"]);
    case "total_gross_weight": return optionValue(item, ["总毛重", "总毛重kg", "total_gross_weight"]);
    case "currency": return item.currency;
    default: return "";
  }
}

export function QuoteWorkbenchPage() {
  const { quoteDraftId } = useParams<{ quoteDraftId: string }>();
  const { t } = useLocale();
  const { notify } = useToast();
  const [draft, setDraft] = useState<PublicQuoteDraft>();
  const [templates, setTemplates] = useState<QuoteExcelTemplate[]>([]);
  const [settings, setSettings] = useState<MerchantSettings>();
  const [locale, setLocale] = useState<StorefrontLocale>("zh-CN");
  const [style, setStyle] = useState<QuoteDocumentStyle>("indigo");
  const [templateId, setTemplateId] = useState<string>("");
  const [quoteNumber, setQuoteNumber] = useState("");
  const [visibleColumns, setVisibleColumns] = useState<QuoteTemplateField[]>(defaultTableFields);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState("");
  const [itemEdits, setItemEdits] = useState<Record<string, QuoteItemEdit>>({});
  const [savingItems, setSavingItems] = useState(false);
  const [bulkPriceOpen, setBulkPriceOpen] = useState(false);
  const [bulkPercentage, setBulkPercentage] = useState("");
  const [bulkSaving, setBulkSaving] = useState(false);
  const [itemsDrawerOpen, setItemsDrawerOpen] = useState(false);
  const [selectedItemId, setSelectedItemId] = useState<string>();
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [savingItemId, setSavingItemId] = useState<string>();
  const [syncingItemId, setSyncingItemId] = useState<string>();
  const [syncItem, setSyncItem] = useState<PublicQuoteDraftItem>();
  const [productDetails, setProductDetails] = useState<Record<string, ProductDetail | null>>({});
  const [detailLoadingId, setDetailLoadingId] = useState<string>();
  const [market, setMarket] = useState<DashboardSnapshot["market"]>();
  const [conversionOpen, setConversionOpen] = useState(false);
  const [converting, setConverting] = useState(false);
  const autoSettingsTimer = useRef<number | undefined>(undefined);
  const autoItemsTimer = useRef<number | undefined>(undefined);
  const savedSettingsRef = useRef<QuoteSettingsPayload | undefined>(undefined);
  const loadedDraftIdRef = useRef<string | undefined>(undefined);

  const enabledLocales = useMemo(() => {
    const allowed = settings?.storefrontLocales;
    if (!allowed?.length) return locales;
    return locales.filter((row) => allowed.includes(row.value));
  }, [settings?.storefrontLocales]);

  const readyTemplates = useMemo(() => templates.filter((row) => row.isReady), [templates]);
  const selectedTemplate = useMemo(
    () => readyTemplates.find((template) => template.id === templateId) ?? readyTemplates.find((template) => template.isDefault),
    [readyTemplates, templateId],
  );
  const availableColumns = useMemo(() => templateTableFields(selectedTemplate), [selectedTemplate]);
  const activeColumns = useMemo(() => {
    const filtered = visibleColumns.filter((field) => availableColumns.includes(field));
    return filtered.length ? filtered : availableColumns;
  }, [availableColumns, visibleColumns]);
  const currentSettings = useMemo<QuoteSettingsPayload>(() => ({
    locale,
    style,
    templateId: templateId || null,
    quoteNumber: quoteNumber.trim(),
    visibleColumns: [...activeColumns],
  }), [activeColumns, locale, quoteNumber, style, templateId]);
  const previewGrid = useMemo(() => `repeat(${Math.max(activeColumns.length, 1)}, minmax(0, 1fr))`, [activeColumns.length]);
  const canEditPrices = draft?.status === "PENDING_CONFIRMATION";
  const hasPendingItemEdits = Object.values(itemEdits).some((edit) => Object.keys(edit).length > 0);
  const conversionRate = useMemo(() => {
    if (!draft || !market?.exchangeRates?.length) return undefined;
    const source = draft.currency.toUpperCase() === "RMB" ? "CNY" : draft.currency.toUpperCase();
    const sourceRate = source === "CNY"
      ? 1
      : market.exchangeRates.find((row) => row.currency.toUpperCase() === source)?.rate;
    const targetRate = market.exchangeRates.find((row) => row.currency.toUpperCase() === "USD")?.rate;
    if (!sourceRate || !targetRate || sourceRate <= 0 || targetRate <= 0) return undefined;
    // Market rates are CNY per unit of currency, so source/target gives the
    // amount of target currency represented by one source unit.
    return sourceRate / targetRate;
  }, [draft, market]);
  const canConvertToUsd = Boolean(canEditPrices && draft?.currency.toUpperCase() !== "USD" && conversionRate);
  const conversionRateLabel = conversionRate
    ? conversionRate.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")
    : "";

  const load = useCallback(async () => {
    if (!quoteDraftId) return;
    setLoading(true);
    setError("");
    setMarket(undefined);
    try {
      const [nextDraft, nextTemplates, merchantSettings] = await Promise.all([
        getPublicQuoteDraft(quoteDraftId),
        listQuoteExcelTemplates().catch(() => []),
        getMerchantSettings().catch(() => undefined),
      ]);
      const nextReadyTemplates = nextTemplates.filter((template) => template.isReady);
      const nextTemplate = nextReadyTemplates.find((template) => template.id === (nextDraft.quoteTemplateId ?? "")) ?? nextReadyTemplates.find((template) => template.isDefault);
      const nextAvailable = templateTableFields(nextTemplate);
      const nextVisible = (nextDraft.visibleColumns ?? []).filter((field) => nextAvailable.includes(field));
      const nextActiveColumns = nextVisible.length ? nextVisible : nextAvailable;
      setDraft(nextDraft);
      setTemplates(nextTemplates);
      setSettings(merchantSettings);
      setLocale(nextDraft.locale);
      setStyle(nextDraft.documentStyle);
      setTemplateId(nextDraft.quoteTemplateId ?? "");
      setQuoteNumber(nextDraft.quoteNumber);
      setVisibleColumns(nextActiveColumns);
      savedSettingsRef.current = {
        locale: nextDraft.locale,
        style: nextDraft.documentStyle,
        templateId: nextDraft.quoteTemplateId ?? null,
        quoteNumber: nextDraft.quoteNumber.trim(),
        visibleColumns: [...nextActiveColumns],
      };
      loadedDraftIdRef.current = nextDraft.id;
      void getDashboard().then((dashboard) => setMarket(dashboard.market)).catch(() => undefined);
    } catch (reason) {
      if (reason instanceof CoreApiError && reason.status === 404) {
        setError(t("这条询价单不存在或已被删除。"));
      } else {
        setError(reason instanceof Error ? reason.message : t("报价工作台加载失败"));
      }
    } finally {
      setLoading(false);
    }
  }, [quoteDraftId, t]);

  useEffect(() => { void load(); }, [load]);

  useEffect(() => {
    if (!draft) return;
    setPriceDrafts(Object.fromEntries(draft.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
  }, [draft?.id]);

  useEffect(() => {
    if (enabledLocales.length && !enabledLocales.some((row) => row.value === locale)) {
      setLocale(enabledLocales[0].value);
    }
  }, [enabledLocales, locale]);

  const saveAllItemEdits = useCallback(async (): Promise<PublicQuoteDraft | undefined> => {
    if (!draft) return draft;
    const entries = Object.entries(itemEdits).filter(([, edit]) => Object.keys(edit).length > 0);
    if (!entries.length) return draft;
    if (!canEditPrices) {
      setError(t("订单已进入 {status}，商品信息不可再修改。", { status: t(draft.status) }));
      return undefined;
    }
    const payload: Array<{
      itemId: string;
      unitPrice?: number;
      quantity?: number;
      name?: string;
      description?: string | null;
      specification?: string | null;
      category?: string | null;
      unitCode?: string;
    }> = [];
    for (const [itemId, edit] of entries) {
      if (!draft.items.some((item) => item.id === itemId)) continue;
      const row: (typeof payload)[number] = { itemId };
      if (edit.unitPrice !== undefined) {
        const value = Number(edit.unitPrice);
        if (!Number.isFinite(value) || value < 0) {
          setError(t("请输入有效的商品价格。"));
          return undefined;
        }
        row.unitPrice = value;
      }
      if (edit.quantity !== undefined) {
        const value = Number(edit.quantity);
        if (!Number.isFinite(value) || value <= 0) {
          setError(t("请输入有效的商品数量。"));
          return undefined;
        }
        row.quantity = value;
      }
      if (edit.name !== undefined) {
        if (!edit.name.trim()) {
          setError(t("商品名称不能为空。"));
          return undefined;
        }
        row.name = edit.name;
      }
      if (edit.description !== undefined) row.description = edit.description;
      if (edit.specification !== undefined) row.specification = edit.specification;
      if (edit.category !== undefined) row.category = edit.category;
      if (edit.unitCode !== undefined) {
        if (!edit.unitCode.trim()) {
          setError(t("商品单位不能为空。"));
          return undefined;
        }
        row.unitCode = edit.unitCode;
      }
      payload.push(row);
    }
    if (!payload.length) return draft;
    setSavingItems(true);
    setError("");
    try {
      const next = await updatePublicQuoteDraftItems(draft.id, payload);
      setDraft(next);
      setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
      setItemEdits({});
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("商品修改保存失败"));
      return undefined;
    } finally {
      setSavingItems(false);
    }
  }, [canEditPrices, draft, itemEdits, t]);

  const persistSettings = useCallback(async (target: PublicQuoteDraft, payload: QuoteSettingsPayload, quiet = false) => {
    if (!payload.quoteNumber) {
      if (!quiet) setError(t("报价单编号不能为空。"));
      return undefined;
    }
    const previous = savedSettingsRef.current;
    savedSettingsRef.current = payload;
    if (!quiet) {
      setSaving(true);
      setError("");
    }
    try {
      const next = await updatePublicQuoteDraftSettings(target.id, {
        locale: payload.locale,
        style: payload.style,
        templateId: payload.templateId,
        quoteNumber: payload.quoteNumber,
        visibleColumns: payload.visibleColumns,
      });
      setDraft(next);
      setQuoteNumber(next.quoteNumber);
      setVisibleColumns(next.visibleColumns.length ? next.visibleColumns : payload.visibleColumns);
      savedSettingsRef.current = {
        ...payload,
        quoteNumber: next.quoteNumber.trim(),
        visibleColumns: next.visibleColumns.length ? [...next.visibleColumns] : [...payload.visibleColumns],
      };
      return next;
    } catch (reason) {
      savedSettingsRef.current = previous;
      const message = reason instanceof Error ? reason.message : t("报价单设置保存失败");
      if (quiet) notify(message, { kind: "error" });
      else setError(message);
      return undefined;
    } finally {
      if (!quiet) setSaving(false);
    }
  }, [notify, t]);

  const save = useCallback(async () => {
    if (!draft) return draft;
    const edited = await saveAllItemEdits();
    if (!edited) return undefined;
    return persistSettings(edited, currentSettings);
  }, [currentSettings, draft, persistSettings, saveAllItemEdits]);

  useEffect(() => {
    if (!draft || !canEditPrices || loadedDraftIdRef.current !== draft.id) return;
    if (quoteSettingsEqual(savedSettingsRef.current, currentSettings)) return;
    if (autoSettingsTimer.current) window.clearTimeout(autoSettingsTimer.current);
    autoSettingsTimer.current = window.setTimeout(() => {
      void persistSettings(draft, currentSettings, true);
    }, 650);
    return () => {
      if (autoSettingsTimer.current) window.clearTimeout(autoSettingsTimer.current);
    };
  }, [canEditPrices, currentSettings, draft, persistSettings]);

  useEffect(() => {
    if (!draft || !canEditPrices || !hasPendingItemEdits) return;
    if (autoItemsTimer.current) window.clearTimeout(autoItemsTimer.current);
    autoItemsTimer.current = window.setTimeout(() => {
      void saveAllItemEdits();
    }, 850);
    return () => {
      if (autoItemsTimer.current) window.clearTimeout(autoItemsTimer.current);
    };
  }, [canEditPrices, draft, hasPendingItemEdits, saveAllItemEdits]);

  const download = async (type: "pdf" | "xlsx") => {
    if (!draft) return;
    setDownloading(type);
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      await downloadPublicQuoteDraftDocument(saved.id, saved.quoteNumber, type);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价文件下载失败"));
    } finally {
      setDownloading(null);
    }
  };

  const confirm = async () => {
    if (!draft) return;
    setConfirming(true);
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      const confirmed = await updatePublicQuoteDraftStatus(saved.id, "CONFIRMED");
      setDraft(confirmed);
      notify(t("报价已通过，客户现在可以下载 PDF 和 Excel。"), { kind: "success" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价单确认失败"));
    } finally {
      setConfirming(false);
    }
  };

  const copyNumber = async () => {
    try {
      await navigator.clipboard.writeText(quoteNumber);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setError(t("复制失败，请手动选择报价单编号。"));
    }
  };

  const toggleColumn = (field: QuoteTemplateField, checked: boolean) => {
    setVisibleColumns((current) => {
      if (checked) return current.includes(field) ? current : [...current, field];
      if (current.length <= 1) return current;
      return current.filter((value) => value !== field);
    });
  };

  const changeTemplate = (value: string) => {
    const nextId = value === "default" ? "" : value;
    const nextTemplate = readyTemplates.find((template) => template.id === nextId) ?? readyTemplates.find((template) => template.isDefault);
    setTemplateId(nextId);
    setVisibleColumns(templateTableFields(nextTemplate));
  };

  const effectiveItem = useCallback((item: PublicQuoteDraftItem): PublicQuoteDraftItem => {
    const edit = itemEdits[item.id] ?? {};
    const quantity = edit.quantity === undefined ? item.quantity : Number(edit.quantity);
    const unitPrice = edit.unitPrice === undefined ? item.unitPrice : Number(edit.unitPrice);
    const validQuantity = Number.isFinite(quantity) && quantity > 0 ? quantity : item.quantity;
    const validUnitPrice = Number.isFinite(unitPrice) && unitPrice >= 0 ? unitPrice : item.unitPrice;
    return {
      ...item,
      name: edit.name ?? item.name,
      description: edit.description === undefined ? item.description : edit.description,
      specification: edit.specification === undefined ? item.specification : edit.specification,
      category: edit.category === undefined ? item.category : edit.category,
      unitCode: edit.unitCode ?? item.unitCode,
      quantity: validQuantity,
      unitPrice: validUnitPrice,
      lineTotal: Number((validQuantity * validUnitPrice).toFixed(2)),
    };
  }, [itemEdits]);

  const selectedDrawerItemBase = draft?.items.find((item) => item.id === selectedItemId);
  const selectedDrawerItem = selectedDrawerItemBase ? effectiveItem(selectedDrawerItemBase) : undefined;

  const updateItemEdit = (itemId: string, field: QuoteItemEditField, value: string) => {
    setItemEdits((current) => ({
      ...current,
      [itemId]: { ...current[itemId], [field]: value },
    }));
    if (field === "unitPrice") {
      setPriceDrafts((current) => ({ ...current, [itemId]: value }));
    }
  };

  const openItemDetails = useCallback(async (item: PublicQuoteDraftItem) => {
    setSelectedItemId(item.id);
    if (Object.prototype.hasOwnProperty.call(productDetails, item.productId)) return;
    setDetailLoadingId(item.productId);
    try {
      const detail = await getProduct(item.productId);
      setProductDetails((current) => ({ ...current, [item.productId]: detail }));
    } catch {
      // The quote snapshot remains a complete fallback when the live product
      // is no longer readable by the current operator.
      setProductDetails((current) => ({ ...current, [item.productId]: null }));
    } finally {
      setDetailLoadingId(undefined);
    }
  }, [productDetails]);

  const saveItemPrice = async (item: PublicQuoteDraftItem, syncToCatalog: boolean) => {
    if (!draft || !canEditPrices) return;
    const raw = (priceDrafts[item.id] ?? String(item.unitPrice)).trim();
    const unitPrice = Number(raw);
    if (!Number.isFinite(unitPrice) || unitPrice < 0) {
      setError(t("请输入有效的商品价格。"));
      return;
    }
    setError("");
    if (syncToCatalog) setSyncingItemId(item.id);
    else setSavingItemId(item.id);
    try {
      const next = syncToCatalog
        ? await syncPublicQuoteDraftItemPrice(draft.id, item.id, unitPrice)
        : await updatePublicQuoteDraftItemPrice(draft.id, item.id, unitPrice);
      setDraft(next);
      const updated = next.items.find((row) => row.id === item.id);
      if (updated) setPriceDrafts((current) => ({ ...current, [item.id]: updated.unitPrice.toFixed(2) }));
      setItemEdits((current) => {
        const edit = current[item.id];
        if (!edit || edit.unitPrice === undefined) return current;
        const { unitPrice: _savedUnitPrice, ...remaining } = edit;
        if (!Object.keys(remaining).length) {
          const nextEdits = { ...current };
          delete nextEdits[item.id];
          return nextEdits;
        }
        return { ...current, [item.id]: remaining };
      });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t(syncToCatalog ? "同步商品价格失败" : "本次报价价格保存失败"));
    } finally {
      setSavingItemId(undefined);
      setSyncingItemId(undefined);
      if (syncToCatalog) setSyncItem(undefined);
    }
  };

  const requestItemPriceSync = (item: PublicQuoteDraftItem) => {
    const unitPrice = Number((priceDrafts[item.id] ?? String(item.unitPrice)).trim());
    if (!Number.isFinite(unitPrice) || unitPrice < 0) {
      setError(t("请输入有效的商品价格。"));
      return;
    }
    setError("");
    setSyncItem(item);
  };

  const applyBulkPriceAdjustment = async () => {
    if (!draft || !canEditPrices) return;
    const percentage = Number(bulkPercentage.trim());
    if (!Number.isFinite(percentage) || percentage < -100 || percentage > 10000) {
      setError(t("请输入 -100 到 10000 之间的调价百分比。"));
      return;
    }
    setBulkSaving(true);
    setError("");
    try {
      const edited = await saveAllItemEdits();
      if (!edited) return;
      const next = await adjustPublicQuoteDraftPrices(edited.id, percentage);
      setDraft(next);
      setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
      setItemEdits({});
      setBulkPercentage("");
      setBulkPriceOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("批量调价失败"));
    } finally {
      setBulkSaving(false);
    }
  };

  const convertToUsd = async () => {
    if (!draft || !canConvertToUsd || hasPendingItemEdits || converting) return;
    setConverting(true);
    setError("");
    try {
      const next = await convertPublicQuoteDraftCurrency(draft.id, "USD");
      setDraft(next);
      setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
      setConversionOpen(false);
      const rateText = conversionRate ? conversionRate.toFixed(6).replace(/0+$/, "").replace(/\.$/, "") : "";
      notify(rateText
        ? t("已按 1 {source} = {rate} USD 换算本报价单。", { source: draft.currency, rate: rateText })
        : t("报价单已换算为 USD。"), { kind: "success" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价币种换算失败"));
    } finally {
      setConverting(false);
    }
  };

  const selectedProductDetail = selectedDrawerItem
    ? productDetails[selectedDrawerItem.productId]
    : undefined;
  const selectedLiveSku = selectedProductDetail?.skus.find((sku) => sku.id === selectedDrawerItem?.skuId);
  const previewTotal = draft
    ? draft.items.reduce((sum, item) => sum + effectiveItem(item).lineTotal, 0)
    : 0;

  const renderPreviewCell = (item: PublicQuoteDraftItem, field: QuoteTemplateField) => {
    const effective = effectiveItem(item);
    const edit = itemEdits[item.id] ?? {};
    const editableFields: QuoteTemplateField[] = [
      "product_name",
      "description",
      "specification",
      "category",
      "quantity",
      "unit_code",
      "unit_price",
    ];
    if (!canEditPrices || !editableFields.includes(field)) {
      const value = previewValue(effective, field);
      return <span className={`quote-preview-cell ${field === "product_name" || field === "description" || field === "specification" ? "quote-preview-cell--multiline" : ""}`} title={value}>{value}</span>;
    }
    const isNumeric = field === "quantity" || field === "unit_price";
    const editField: QuoteItemEditField = field === "product_name" ? "name" : field === "unit_price" ? "unitPrice" : field === "quantity" ? "quantity" : field === "unit_code" ? "unitCode" : field === "description" ? "description" : field === "specification" ? "specification" : "category";
    const value = edit[editField] ?? (
      field === "product_name" ? item.name
        : field === "description" ? item.description ?? ""
          : field === "specification" ? item.specification ?? optionValue(item, ["规格", "规格名称"])
            : field === "category" ? item.category ?? ""
              : field === "quantity" ? String(item.quantity)
                : field === "unit_code" ? item.unitCode
                  : item.unitPrice.toFixed(2)
    );
    return <TextField.Root className="quote-preview-editor-field" size="1" type={isNumeric ? "number" : "text"} min={field === "quantity" ? "0.000001" : field === "unit_price" ? "0" : undefined} step={field === "quantity" ? "0.000001" : field === "unit_price" ? "0.01" : undefined} value={value} aria-label={fieldLabel(field, t, selectedTemplate)} title={String(value)} onChange={(event) => updateItemEdit(item.id, editField, event.target.value)}>{field === "unit_price" ? <TextField.Slot side="left">{item.currency}</TextField.Slot> : null}</TextField.Root>;
  };

  if (loading) return <div className="core-workspace"><CoreLoading label={t("正在打开报价工作台")} /></div>;
  if (error && !draft) return <div className="core-workspace"><CoreError message={error} onRetry={() => void load()} /></div>;
  if (!draft) return null;

  const selectedStyle = styles.find((row) => row.value === style) ?? styles[0];

  return <div className={`core-workspace quote-workbench quote-workbench--${style}`}>
    <CorePageHeading
      eyebrow={t("多证工作台")}
      title={t("制作报价单")}
      description={t("报价单会按照商家模板生成，客户只会看到你选择的公开字段。")}
      actions={<Button asChild variant="soft" color="gray"><Link to="/console/quotes"><ArrowLeft />{t("返回询价列表")}</Link></Button>}
    />
    {error ? <ToastNotice kind="error" message={error} /> : null}

    <Card className="quote-status-card">
      <div className="quote-status-main"><Text size="1" color="gray">{t("当前订单状态")}</Text><Badge color={draft.status === "CONFIRMED" || draft.status === "COMPLETED" ? "jade" : draft.status === "CANCELLED" ? "gray" : "amber"}>{t(draft.status)}</Badge></div>
      <div className="quote-status-meta"><span>{t("客户")}: {draft.customerCompany || draft.customerName}</span><span>{t("更新时间")}: {coreDate(draft.updatedAt)}</span><span>{t("有效期")}: {coreDate(draft.validUntil)}</span></div>
    </Card>

    <Card className="quote-workbench-toolbar">
      <div className="quote-workbench-fields">
       <div className="quote-workbench-number">
        <Text size="1" color="gray">{t("报价单 ID / 编号")}</Text>
        <div className="quote-number-control"><TextField.Root value={quoteNumber} onChange={(event) => setQuoteNumber(event.target.value)} maxLength={80} /><Button size="1" variant="soft" color="gray" onClick={() => void copyNumber()}><Copy />{copied ? t("已复制") : t("复制")}</Button></div>
       </div>
       <label className="quote-workbench-select"><Text size="1" color="gray">{t("商家报价模板")}</Text><Select.Root value={templateId || "default"} onValueChange={changeTemplate}><Select.Trigger /><Select.Content position="popper"><Select.Item value="default">{t("系统默认模板")}</Select.Item>{readyTemplates.filter((template) => !template.isDefault).map((template) => <Select.Item key={template.id} value={template.id}>{template.name}</Select.Item>)}</Select.Content></Select.Root></label>
       <div className="quote-workbench-select">
         <Text size="1" color="gray"><Columns />{t("商品表格列")}</Text>
         <DropdownMenu.Root>
           <DropdownMenu.Trigger>
             <Button variant="soft" color="gray" className="quote-column-trigger"><Columns />{t("已选 {count} 列", { count: activeColumns.length })}<CaretDown /></Button>
           </DropdownMenu.Trigger>
           <DropdownMenu.Content align="start" className="quote-column-menu">
             <DropdownMenu.Label>{t("选择客户可见列")}</DropdownMenu.Label>
             {availableColumns.map((field) => <DropdownMenu.CheckboxItem key={field} checked={visibleColumns.includes(field)} onCheckedChange={(checked) => toggleColumn(field, checked)} onSelect={(event) => event.preventDefault()}><span>{fieldLabel(field, t, selectedTemplate)}</span>{visibleColumns.includes(field) ? <Check /> : null}</DropdownMenu.CheckboxItem>)}
           </DropdownMenu.Content>
         </DropdownMenu.Root>
       </div>
       <label className="quote-workbench-select"><Text size="1" color="gray"><Palette />{t("PDF 样式")}</Text><Select.Root value={style} onValueChange={(value) => setStyle(value as QuoteDocumentStyle)}><Select.Trigger /><Select.Content position="popper">{styles.map((option) => <Select.Item key={option.value} value={option.value}>{t(option.label)}</Select.Item>)}</Select.Content></Select.Root></label>
       <label className="quote-workbench-select"><Text size="1" color="gray">{t("报价语言")}</Text><Select.Root value={locale} onValueChange={(value) => setLocale(value as StorefrontLocale)}><Select.Trigger /><Select.Content position="popper">{enabledLocales.map((option) => <Select.Item key={option.value} value={option.value}>{localeLabel(option.value)}</Select.Item>)}</Select.Content></Select.Root></label>
      </div>
      <div className="quote-workbench-actions">
        <Button variant="soft" color="blue" disabled={!canConvertToUsd || hasPendingItemEdits || converting} loading={converting} onClick={() => setConversionOpen(true)}><CurrencyDollar />{draft.currency === "USD" ? t("已是 USD") : t("换算为 USD")}</Button>
        {conversionRateLabel && draft.currency.toUpperCase() !== "USD" ? <Text size="1" color="gray" className="quote-fx-rate">1 {draft.currency} = {conversionRateLabel} USD</Text> : null}
        <Button variant="soft" disabled={!canEditPrices || bulkSaving} onClick={() => setBulkPriceOpen(true)}><SlidersHorizontal />{t("一键调价")}</Button>
        <Button variant="soft" onClick={() => { setItemsDrawerOpen(true); setSelectedItemId(undefined); }}><Package />{t("订单商品")}<Badge color="gray">{draft.items.length}</Badge></Button>
        <Text size="1" color="gray" className="quote-autosave-status" aria-live="polite">{saving || savingItems ? t("正在自动保存…") : t("已自动保存")}</Text>
        <Button color="blue" disabled={saving || savingItems} loading={saving} onClick={() => void save()}><FloppyDisk />{t("保存报价单")}</Button>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger><Button variant="soft" loading={Boolean(downloading)}><DownloadSimple />{t("导出")}{downloading ? ` ${downloading.toUpperCase()}` : ""}<CaretDown /></Button></DropdownMenu.Trigger>
          <DropdownMenu.Content align="end"><DropdownMenu.Item disabled={Boolean(downloading)} onSelect={() => void download("pdf")}><FilePdf />{t("导出为 PDF")}</DropdownMenu.Item><DropdownMenu.Item disabled={Boolean(downloading)} onSelect={() => void download("xlsx")}><FileXls />{t("导出为 Excel")}</DropdownMenu.Item></DropdownMenu.Content>
        </DropdownMenu.Root>
        {draft.status === "PENDING_CONFIRMATION" ? <Button color="green" disabled={confirming || saving || savingItems} loading={confirming} onClick={() => void confirm()}><PaperPlaneTilt />{t("通过并通知客户")}</Button> : null}
      </div>
    </Card>

    <AlertDialog.Root open={conversionOpen} onOpenChange={(open) => { if (!converting) setConversionOpen(open); }}>
      <AlertDialog.Content maxWidth="500px">
        <AlertDialog.Title>{t("按汇率换算为 USD")}</AlertDialog.Title>
        <AlertDialog.Description size="2">
          {conversionRate
            ? t("当前汇率为 1 {source} = {rate} USD。将换算本报价单的单价、总价和报价合计，不会修改商品库价格。", {
              source: draft.currency,
              rate: conversionRate.toFixed(6).replace(/0+$/, "").replace(/\.$/, ""),
            })
            : t("暂时无法取得当前汇率，请稍后重试。")}
        </AlertDialog.Description>
        <div className="quote-sync-confirm-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={converting}>{t("取消")}</Button></AlertDialog.Cancel>
          <AlertDialog.Action><Button color="blue" disabled={!canConvertToUsd || hasPendingItemEdits || converting} loading={converting} onClick={() => void convertToUsd()}>{t("确认换算")}</Button></AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>

    <Dialog.Root open={bulkPriceOpen} onOpenChange={(open) => { if (!bulkSaving) setBulkPriceOpen(open); }}>
      <Dialog.Content className="quote-bulk-price-dialog" maxWidth="460px">
        <Dialog.Title>{t("一键调价")}</Dialog.Title>
        <Dialog.Description size="2">{t("对当前报价中的全部商品单价应用百分比。正数表示涨价，负数表示降价。")}</Dialog.Description>
        <div className="quote-bulk-price-form">
          <TextField.Root type="number" step="0.01" min="-100" max="10000" value={bulkPercentage} onChange={(event) => setBulkPercentage(event.target.value)} placeholder={t("例如 20 或 -10")} autoFocus><TextField.Slot side="right">%</TextField.Slot></TextField.Root>
          <div className="quote-bulk-price-presets"><Text size="1" color="gray">{t("快捷幅度")}</Text><div>{["20", "10", "-10", "-20"].map((value) => <Button key={value} size="1" variant="soft" color={value.startsWith("-") ? "red" : "green"} onClick={() => setBulkPercentage(value)}>{value.startsWith("-") ? value : `+${value}`}%</Button>)}</div></div>
        </div>
        <div className="quote-sync-confirm-actions"><Dialog.Close><Button variant="soft" color="gray" disabled={bulkSaving}>{t("取消")}</Button></Dialog.Close><Button color="green" disabled={!canEditPrices || !bulkPercentage.trim()} loading={bulkSaving} onClick={() => void applyBulkPriceAdjustment()}>{t("应用调价")}</Button></div>
      </Dialog.Content>
    </Dialog.Root>

    <Dialog.Root open={itemsDrawerOpen} onOpenChange={(open) => { setItemsDrawerOpen(open); if (!open) setSelectedItemId(undefined); }}>
      <Dialog.Content className="quote-items-drawer" aria-describedby="quote-items-drawer-description">
        <div className="quote-items-drawer-header">
          <div>
            <Text size="1" color="gray">{selectedDrawerItem ? t("商品详情") : t("当前订单")}</Text>
            <Dialog.Title>{selectedDrawerItem ? selectedDrawerItem.name : t("订单商品")}</Dialog.Title>
            <Dialog.Description id="quote-items-drawer-description">
              {selectedDrawerItem ? t("查看商品快照、实时资料和本次报价价格。") : t("本次报价包含 {count} 个商品，可在这里查看详情和调整价格。", { count: draft.items.length })}
            </Dialog.Description>
          </div>
          <div className="quote-items-drawer-header-actions">
            {selectedDrawerItem ? <IconButton variant="ghost" color="gray" onClick={() => setSelectedItemId(undefined)} aria-label={t("返回商品列表")}><ArrowLeft size={19} /></IconButton> : null}
            <Dialog.Close><IconButton variant="ghost" color="gray" aria-label={t("关闭订单商品")}><X size={19} /></IconButton></Dialog.Close>
          </div>
        </div>

        {selectedDrawerItem ? (
          <div className="quote-items-drawer-scroll quote-item-detail">
            <div className="quote-item-detail-hero">
              {selectedDrawerItem.imageUrl ? <img src={selectedDrawerItem.imageUrl} alt={selectedDrawerItem.name} /> : <span className="quote-item-image-placeholder"><ImageSquare size={32} /></span>}
              <div className="quote-item-detail-title">
                <Heading size="4">{selectedDrawerItem.name}</Heading>
                <Text size="1" color="gray" className="mono-text">{selectedDrawerItem.skuCode}</Text>
                {selectedDrawerItem.category ? <Badge color="gray">{selectedDrawerItem.category}</Badge> : null}
              </div>
            </div>
            <Card className="quote-item-price-card">
              <div className="quote-item-price-heading"><div><Text size="2" weight="medium">{t("本次报价价格")}</Text><Text size="1" color="gray">{t("只影响当前报价单，不会自动修改商品库。")}</Text></div><Text size="3" weight="bold" className="quote-item-price-total">{money(selectedDrawerItem.lineTotal, selectedDrawerItem.currency)}</Text></div>
              <div className="quote-item-price-editor">
                <TextField.Root type="number" min="0" step="0.01" value={priceDrafts[selectedDrawerItem.id] ?? selectedDrawerItem.unitPrice.toFixed(2)} disabled={!canEditPrices} onChange={(event) => updateItemEdit(selectedDrawerItem.id, "unitPrice", event.target.value)}><TextField.Slot side="left">{selectedDrawerItem.currency}</TextField.Slot></TextField.Root>
                <Text size="1" color="gray">× {selectedDrawerItem.quantity} {selectedDrawerItem.unitCode}</Text>
              </div>
              <div className="quote-item-price-actions">
                <Button size="2" color="amber" disabled={!canEditPrices || savingItemId === selectedDrawerItem.id || syncingItemId === selectedDrawerItem.id} loading={syncingItemId === selectedDrawerItem.id} onClick={() => requestItemPriceSync(selectedDrawerItem)}>{t("同步到商品库")}</Button>
              </div>
              {!canEditPrices ? <Text size="1" color="gray">{t("订单已进入 {status}，价格不可再修改。", { status: t(draft.status) })}</Text> : null}
            </Card>

            <div className="quote-item-detail-grid">
              <div><Text size="1" color="gray">{t("商品编码")}</Text><strong className="mono-text">{selectedDrawerItem.skuCode}</strong></div>
              <div><Text size="1" color="gray">{t("数量")}</Text><strong>{selectedDrawerItem.quantity} {selectedDrawerItem.unitCode}</strong></div>
              <div><Text size="1" color="gray">{t("版本")}</Text><strong>v{selectedDrawerItem.productVersion} · SKU v{selectedDrawerItem.skuVersion}</strong></div>
            </div>
            {selectedDrawerItem.description ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品描述")}</Text><Text as="p">{selectedDrawerItem.description}</Text></div> : null}
            {selectedDrawerItem.specification ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品规格")}</Text><Text as="p">{selectedDrawerItem.specification}</Text></div> : null}
            {selectedDrawerItem.tags.length ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品标签")}</Text><div className="quote-item-tags">{selectedDrawerItem.tags.map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</div></div> : null}
            {Object.entries(selectedDrawerItem.optionValues).filter(([key]) => !key.startsWith("_")).length ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("规格参数")}</Text><div className="quote-item-options">{Object.entries(selectedDrawerItem.optionValues).filter(([key]) => !key.startsWith("_")).map(([key, value]) => <div key={key}><span>{key}</span><strong>{displayOptionValue(value)}</strong></div>)}</div></div> : null}
            {detailLoadingId === selectedDrawerItem.productId ? <Text size="1" color="gray">{t("正在读取商品详情…")}</Text> : null}
            {selectedProductDetail ? <Card className="quote-live-product-card"><div className="quote-live-product-heading"><Info size={17} /><Text size="2" weight="medium">{t("商品库实时资料")}</Text></div><Text size="1" color="gray">{selectedProductDetail.productCode || selectedProductDetail.id}</Text>{selectedProductDetail.description ? <Text size="2">{selectedProductDetail.description}</Text> : null}{selectedLiveSku?.name ? <Text size="1" color="gray">{t("当前 SKU 名称")}: {selectedLiveSku.name}</Text> : null}</Card> : null}
          </div>
        ) : (
          <div className="quote-items-drawer-scroll">
            <div className="quote-items-drawer-summary"><Text size="2" weight="medium">{t("商品列表")}</Text><Text size="1" color="gray">{t("点击商品可查看完整快照和实时资料。")}</Text></div>
            <div className="quote-item-list">
              {draft.items.map((sourceItem) => {
                const item = effectiveItem(sourceItem);
                return <Card className="quote-item-row" key={item.id} role="button" tabIndex={0} onClick={() => void openItemDetails(sourceItem)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); void openItemDetails(sourceItem); } }}>
                  <div className="quote-item-row-main">
                    {item.imageUrl ? <img src={item.imageUrl} alt={item.name} /> : <span className="quote-item-image-placeholder"><ImageSquare size={26} /></span>}
                    <div className="quote-item-row-copy"><div className="quote-item-row-title"><Text size="2" weight="medium">{item.name}</Text><Badge color="gray">#{item.position}</Badge></div><Text size="1" color="gray" className="mono-text">{item.skuCode}</Text>{item.category ? <Text size="1" color="gray">{item.category}</Text> : null}<Text size="1" color="gray">{t("数量")}: {item.quantity} {item.unitCode}</Text></div>
                    <ArrowRight className="quote-item-row-arrow" size={18} />
                  </div>
                  <div className="quote-item-row-price"><Text size="1" color="gray">{t("本次报价单价")}</Text><div className="quote-item-row-price-control"><TextField.Root type="number" min="0" step="0.01" value={priceDrafts[item.id] ?? item.unitPrice.toFixed(2)} disabled={!canEditPrices} onClick={(event) => event.stopPropagation()} onChange={(event) => updateItemEdit(item.id, "unitPrice", event.target.value)}><TextField.Slot side="left">{item.currency}</TextField.Slot></TextField.Root><Button size="1" variant="soft" color="amber" disabled={!canEditPrices || savingItemId === item.id || syncingItemId === item.id} loading={syncingItemId === item.id} onClick={(event) => { event.stopPropagation(); requestItemPriceSync(item); }}>{t("同步商品库")}</Button></div><Text size="1" color="gray">{t("小计")}: {money(item.lineTotal, item.currency)}</Text></div>
                </Card>;
              })}
            </div>
          </div>
        )}
      </Dialog.Content>
    </Dialog.Root>

    <AlertDialog.Root open={Boolean(syncItem)} onOpenChange={(open) => { if (!open && !syncingItemId) setSyncItem(undefined); }}>
      <AlertDialog.Content maxWidth="460px">
        <AlertDialog.Title>{t("同步商品库价格")}</AlertDialog.Title>
        <AlertDialog.Description size="2">{syncItem ? t("同步后，{name} 的商品库公开价格会改为 {price}。这会影响后续新报价和前台展示，确定继续吗？", { name: syncItem.name, price: money(Number(priceDrafts[syncItem.id] ?? syncItem.unitPrice), syncItem.currency) }) : ""}</AlertDialog.Description>
        <div className="quote-sync-confirm-actions"><AlertDialog.Cancel><Button variant="soft" color="gray" disabled={Boolean(syncingItemId)}>{t("取消")}</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="amber" disabled={!syncItem || Boolean(syncingItemId)} loading={Boolean(syncingItemId)} onClick={() => { if (syncItem) void saveItemPrice(syncItem, true); }}>{t("确认同步")}</Button></AlertDialog.Action></div>
      </AlertDialog.Content>
    </AlertDialog.Root>

    <Tabs.Root defaultValue="quotation" className="quote-doc-tabs">
      <Tabs.List>
        <Tabs.Trigger value="quotation"><FileText />{t("报价单")}</Tabs.Trigger>
        <Tabs.Trigger value="proforma" disabled><LockKey />{t("形式发票")}</Tabs.Trigger>
        <Tabs.Trigger value="sales-contract" disabled><LockKey />{t("销售合同")}</Tabs.Trigger>
        <Tabs.Trigger value="commercial-invoice" disabled><LockKey />{t("商业发票")}</Tabs.Trigger>
        <Tabs.Trigger value="packing-list" disabled><LockKey />{t("装箱单")}</Tabs.Trigger>
      </Tabs.List>
      <Tabs.Content value="quotation">
        <Card className="quote-preview-card" style={{ "--quote-accent": selectedStyle.color } as React.CSSProperties}>
          <div className="quote-preview-header"><div><Text size="1" color="gray">{localeLabel(locale)}</Text><Heading size="7">{t("报价单")}</Heading><Text size="2" color="gray">{quoteNumber} · {coreDate(draft.createdAt)}</Text></div><Badge style={{ background: selectedStyle.color, color: "white" }}>{t(selectedStyle.label)}</Badge></div>
          <div className="quote-preview-meta"><div><span>{t("客户")}</span><strong>{draft.customerCompany || draft.customerName}</strong></div><div><span>{t("联系人")}</span><strong>{draft.customerName}</strong></div><div><span>{t("有效期")}</span><strong>{coreDate(draft.validUntil)}</strong></div><div><span>{t("币种")}</span><strong>{draft.currency}</strong></div></div>
          <div className="quote-preview-editor-toolbar"><div><Text size="2" weight="medium">{t("客户 PDF 预览")}</Text><Text size="1" color="gray">{canEditPrices ? t("直接编辑表格中的价格、数量、名称等字段，系统会自动保存。") : t("报价已确认，当前预览为只读。")}</Text></div><div className="quote-preview-editor-actions">{hasPendingItemEdits ? <Badge color="amber">{savingItems ? t("正在自动保存…") : t("等待自动保存")}</Badge> : null}</div></div>
          <div className="quote-preview-table">
            <div className="quote-preview-row quote-preview-head" style={{ gridTemplateColumns: previewGrid }}>{activeColumns.map((field) => <span className="quote-preview-cell" key={field}>{fieldLabel(field, t, selectedTemplate)}</span>)}</div>
            {draft.items.map((item) => <div className="quote-preview-row" style={{ gridTemplateColumns: previewGrid }} key={item.id}>{activeColumns.map((field) => <span className="quote-preview-cell" key={`${item.id}-${field}`}>{renderPreviewCell(item, field)}</span>)}</div>)}
            <div className="quote-preview-total"><span>{t("报价合计")}</span><strong>{money(previewTotal, draft.currency)}</strong></div>
          </div>
          {draft.notes ? <Card className="quote-preview-notes"><ClipboardText /><div><Text size="1" color="gray">{t("客户备注")}</Text><Text as="div">{draft.notes}</Text></div></Card> : null}
          <div className="quote-preview-footer"><Text size="1" color="gray">{draft.disclaimer}</Text><span>{t("当前语言")}: {localeLabel(locale)}</span></div>
        </Card>
      </Tabs.Content>
      {(["proforma", "sales-contract", "commercial-invoice", "packing-list"] as const).map((value) => <Tabs.Content value={value} key={value}><Card className="quote-coming-soon"><LockKey size={28} /><Heading size="4">{t("该单证将在后续版本开放")}</Heading><Text size="2" color="gray">{t("当前先完成报价单的制作、样式设置和文件导出。")}</Text></Card></Tabs.Content>)}
    </Tabs.Root>
  </div>;
}
