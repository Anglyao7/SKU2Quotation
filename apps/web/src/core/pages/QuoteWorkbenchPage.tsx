import { useUnsavedChanges } from "../UnsavedChanges";
import { acknowledgeEdits, saveState } from "../saveState";
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
  CaretDown,
  Check,
  CheckCircle,
  ClipboardText,
  Columns,
  CurrencyDollar,
  DownloadSimple,
  FilePdf,
  FileText,
  FileXls,
  FloppyDisk,
  ImageSquare,
  Info,
  MagnifyingGlassPlus,
  BookOpen,
  LockKey,
  Palette,
  PaperPlaneTilt,
  Plus,
  SlidersHorizontal,
  ShieldCheck,
  Storefront,
  Trash,
  X,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { optionPackingQuantity } from "../../lib/cartonQuantity";
import { storefrontText } from "../../lib/storefrontLocale";
import { canUseExtendedQuoteDocuments } from "../../lib/subscriptionTier";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  CoreApiError,
  addPublicQuoteDraftItems,
  adjustPublicQuoteDraftPrices,
  convertPublicQuoteDraftCurrency,
  deletePublicQuoteDraftItem,
  deleteProductImage,
  downloadPublicQuoteDraftDocument,
  getProduct,
  getDashboard,
  getMerchantSettings,
  getPublicQuoteDraft,
  getPublicQuoteDraftPurchaseOrder,
  listQuoteExcelTemplates,
  listSkus,
  syncPublicQuoteDraftItemPrice,
  updatePublicQuoteDraftItems,
  updatePublicQuoteDraftPurchaseOrder,
  updatePublicQuoteDraftItemPrice,
  updatePublicQuoteDraftSettings,
  updatePublicQuoteDraftStatus,
  uploadProductGalleryImage,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { ToastNotice, useToast } from "../ToastContext";
import {
  quoteFieldLabel,
  quoteOptionAliases,
  quoteSeparator,
  quoteText,
  quoteUnit,
  proformaText,
} from "../quoteLocalization";
import type {
  MerchantSettings,
  ProductDetail,
  ProformaInvoiceSettings,
  PublicQuoteDraft,
  PublicQuoteDraftItem,
  QuotePurchaseOrderSettings,
  QuoteCustomField,
  QuoteExtraInformation,
  QuoteExcelTemplate,
  QuoteTemplateField,
  DashboardSnapshot,
  SkuListItem,
} from "../types";
import type { StorefrontLocale } from "../../types";
import type { PackingListSettings } from "../types";
import { packingErrors } from "../packingList";
import { PackingListPanel } from "./PackingListPanel";
import { ProformaInvoicePanel } from "./ProformaInvoicePanel";
import { PurchaseOrderPanel } from "./PurchaseOrderPanel";
import { DocumentPreviewModeSwitch } from "./DocumentPreviewModeSwitch";
import type { DocumentPreviewMode } from "../documentExcelPreview";
import { quoteDocumentSearch, quoteDocumentTab, type QuoteDocumentTab } from "../quoteDocumentNavigation";
import { availableQuoteLocales } from "../quoteLocaleAvailability";
import "./QuoteWorkbenchPage.css";

type QuoteDocumentStyle = PublicQuoteDraft["documentStyle"];
type QuoteItemEditField = "unitPrice" | "quantity" | "name" | "description" | "specification" | "category" | "unitCode";
type QuoteItemEdit = Partial<Record<QuoteItemEditField, string>>;
type PreviewPan = { x: number; y: number };
type QuoteItemImagePreview = { src: string; alt: string };
type ExcelPreviewColumn = {
  key: string;
  header: string;
  field?: QuoteTemplateField;
  customFieldId?: string;
  width: number;
};
type QuoteSettingsPayload = {
  locale: StorefrontLocale;
  style: QuoteDocumentStyle;
  templateId: string | null;
  quoteNumber: string;
  visibleColumns: QuoteTemplateField[];
  extraInformation: QuoteExtraInformation[];
  customFields: QuoteCustomField[];
  proformaInvoice: ProformaInvoiceSettings;
  packingList?: PackingListSettings;
};
type QuoteCurrencyOption = {
  currency: string;
  name: string;
  symbol: string;
  rate: number;
};

const PREVIEW_SCALE_MIN = 40;
const PREVIEW_SCALE_MAX = 150;
const PREVIEW_SCALE_STEP = 5;
const MAX_PDF_COLUMNS = 5;
const preferredCurrencyOrder = [
  "CNY", "USD", "EUR", "GBP", "JPY", "KRW", "HKD", "SGD", "AUD", "CAD",
  "CHF", "NZD", "TRY", "SAR", "AED", "INR", "THB", "MYR", "IDR", "PHP",
  "MXN", "BRL", "ZAR",
];

function normalizedCurrency(value: string) {
  const currency = value.trim().toUpperCase();
  return currency === "RMB" ? "CNY" : currency;
}

function compactRate(value: number) {
  return value.toFixed(6).replace(/0+$/, "").replace(/\.$/, "");
}

function normalizedPreviewScale(value: number) {
  return Math.min(PREVIEW_SCALE_MAX, Math.max(PREVIEW_SCALE_MIN, Math.round(value / PREVIEW_SCALE_STEP) * PREVIEW_SCALE_STEP));
}

function quoteSettingsEqual(left: QuoteSettingsPayload | undefined, right: QuoteSettingsPayload) {
  return Boolean(left
    && left.locale === right.locale
    && left.style === right.style
    && left.templateId === right.templateId
    && left.quoteNumber === right.quoteNumber
    && left.visibleColumns.length === right.visibleColumns.length
    && left.visibleColumns.every((field, index) => field === right.visibleColumns[index])
    && left.extraInformation.length === right.extraInformation.length
    && left.extraInformation.every((entry, index) => (
      entry.title === right.extraInformation[index]?.title
      && entry.content === right.extraInformation[index]?.content
    ))
    && JSON.stringify(left.customFields) === JSON.stringify(right.customFields)
    && JSON.stringify(left.proformaInvoice) === JSON.stringify(right.proformaInvoice)
    && JSON.stringify(left.packingList) === JSON.stringify(right.packingList));
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
  { value: "fr", label: "Français", flag: "🇫🇷" },
  { value: "fa", label: "فارسی", flag: "🇮🇷" },
  { value: "ru", label: "Русский", flag: "🇷🇺" },
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
  { value: "sku_code", label: "SKU 编码" },
  { value: "product_name", label: "商品名称" },
  { value: "description", label: "商品描述" },
  { value: "specification", label: "商品规格" },
  { value: "category", label: "商品分类" },
  { value: "tags", label: "商品标签" },
  { value: "product_image", label: "商品图片" },
  { value: "quantity", label: "数量" },
  { value: "unit_code", label: "单位" },
  { value: "packing_quantity", label: "装箱数量" },
  { value: "carton_count", label: "箱数" },
  { value: "carton_dimensions", label: "装箱尺寸" },
  { value: "gross_weight", label: "毛重（kg）" },
  { value: "carton_volume", label: "立方（m³）" },
  { value: "minimum_order_quantity", label: "起订数" },
  { value: "unit_price", label: "单价" },
  { value: "line_total", label: "总价" },
  { value: "total_volume", label: "总立方（m³）" },
  { value: "total_gross_weight", label: "总毛重（kg）" },
  { value: "currency", label: "币种" },
];

const defaultTableFields: QuoteTemplateField[] = [
  "carton_count",
  "serial_number",
  "sku_code",
  "product_name",
  "description",
  "specification",
  "category",
  "tags",
  "product_image",
  "quantity",
  "unit_code",
  "packing_quantity",
  "carton_dimensions",
  "gross_weight",
  "carton_volume",
  "minimum_order_quantity",
  "unit_price",
  "line_total",
  "total_volume",
  "total_gross_weight",
];

const defaultVisibleTableFields: QuoteTemplateField[] = [
  "product_image",
  "product_name",
  "quantity",
  "carton_count",
  "unit_price",
  "line_total",
];

const defaultExcelTableFields: QuoteTemplateField[] = [
  "serial_number",
  "product_image",
  "sku_code",
  "product_name",
  "quantity",
  "unit_code",
  "packing_quantity",
  "carton_dimensions",
  "gross_weight",
  "carton_volume",
  "unit_price",
  "line_total",
  "total_volume",
  "total_gross_weight",
  "description",
  "specification",
  "category",
  "tags",
  "minimum_order_quantity",
  "carton_count",
];

const previewColumnWeights: Partial<Record<QuoteTemplateField, number>> = {
  serial_number: 0.55,
  sku_code: 1.25,
  product_name: 1.8,
  description: 2,
  specification: 1.55,
  category: 1.2,
  tags: 1.3,
  product_image: 1.05,
  quantity: 0.85,
  unit_code: 0.8,
  packing_quantity: 1,
  carton_dimensions: 1.35,
  gross_weight: 1,
  carton_volume: 1,
  minimum_order_quantity: 1,
  unit_price: 1.15,
  line_total: 1.25,
  total_volume: 1.1,
  total_gross_weight: 1.2,
  currency: 0.85,
};

function preferredVisibleColumns(available: QuoteTemplateField[]): QuoteTemplateField[] {
  const preferred = defaultVisibleTableFields.filter((field) => available.includes(field));
  const remaining = available.filter((field) => !preferred.includes(field));
  return [...preferred, ...remaining].slice(0, MAX_PDF_COLUMNS);
}

function spreadsheetColumnName(index: number) {
  let value = Math.max(1, index);
  let name = "";
  while (value > 0) {
    const remainder = (value - 1) % 26;
    name = String.fromCharCode(65 + remainder) + name;
    value = Math.floor((value - 1) / 26);
  }
  return name;
}

function excelPreviewColumnWidth(field?: QuoteTemplateField) {
  if (field === "serial_number") return 64;
  if (field === "product_image") return 104;
  if (field === "product_name") return 220;
  if (field === "description") return 260;
  if (field === "specification") return 210;
  if (field === "sku_code") return 180;
  if (field === "category" || field === "tags") return 160;
  if (field === "carton_dimensions") return 170;
  if (field === "unit_price" || field === "line_total") return 138;
  return 122;
}

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

function fieldLabel(
  field: QuoteTemplateField,
  t: (value: string) => string,
  template: QuoteExcelTemplate | undefined,
  locale: StorefrontLocale,
) {
  const fallback = t(tableFieldMeta.find((option) => option.value === field)?.label ?? field);
  // Mapped system fields use the same localized labels as the generated PDF
  // and Excel files.  A merchant's template header is a layout hint, not a
  // second translation source, otherwise the preview and exported document
  // would disagree when the quote language changes.
  if (FIELD_LABEL_FIELDS.has(field)) return quoteFieldLabel(locale, field, fallback);
  const templateColumn = template?.columns.find((column) => template.columnMappings[column.key] === field);
  return templateColumn?.header?.trim() || fallback;
}

const FIELD_LABEL_FIELDS = new Set<QuoteTemplateField>([
  "carton_count",
  "serial_number",
  "sku_code",
  "product_name",
  "description",
  "specification",
  "category",
  "tags",
  "product_image",
  "quantity",
  "unit_code",
  "packing_quantity",
  "carton_dimensions",
  "gross_weight",
  "carton_volume",
  "minimum_order_quantity",
  "unit_price",
  "line_total",
  "total_volume",
  "total_gross_weight",
  "currency",
  "quote_number",
  "quote_date",
  "customer_name",
  "customer_company",
  "customer_email",
  "customer_phone",
  "notes",
]);

function optionValue(item: PublicQuoteDraftItem, keys: string[], locale?: StorefrontLocale) {
  const values = item.optionValues ?? {};
  const aliases = Object.values(quoteOptionAliases).find((candidates) =>
    keys.some((key) => candidates.some((candidate) => candidate.toLowerCase() === key.toLowerCase())),
  );
  const candidates = [...keys, ...(aliases ?? [])];
  if (locale) {
    for (const field of Object.keys(quoteOptionAliases)) {
      const fieldAliases = quoteOptionAliases[field] ?? [];
      if (keys.some((key) => fieldAliases.some((candidate) => candidate.toLowerCase() === key.toLowerCase()))) {
        candidates.push(quoteFieldLabel(locale, field as QuoteTemplateField));
      }
    }
  }
  const entry = Object.entries(values).find(([key, value]) => {
    if (key.startsWith("_")) return false;
    const normalized = key.replace(/[\s_\-:：]/g, "").toLowerCase();
    return candidates.some((candidate) => normalized === candidate.replace(/[\s_\-:：]/g, "").toLowerCase()) && value !== null && value !== undefined && value !== "";
  });
  if (!entry) return "";
  return Array.isArray(entry[1]) ? entry[1].join(locale ? quoteSeparator(locale) : "、") : String(entry[1]);
}

function money(value: number, currency: string) {
  return `${currency} ${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** Keep the inquiry date stable across locales and time zones in exported previews. */
function quoteDateOnly(value?: string) {
  if (!value) return "—";
  const sourceDate = value.match(/^\d{4}-\d{2}-\d{2}/)?.[0];
  if (sourceDate) return sourceDate;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return `${parsed.getFullYear()}-${String(parsed.getMonth() + 1).padStart(2, "0")}-${String(parsed.getDate()).padStart(2, "0")}`;
}

function displayOptionValue(value: unknown, separator = "、") {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(separator);
  if (value && typeof value === "object") return Object.values(value as Record<string, unknown>).map((entry) => String(entry)).join(separator);
  return value == null ? "" : String(value);
}

function previewValue(item: PublicQuoteDraftItem, field: QuoteTemplateField, locale: StorefrontLocale) {
  switch (field) {
    case "serial_number": return String(item.position);
    case "sku_code": return item.skuCode;
    case "product_name": return item.name;
    case "description": return item.description ?? "";
    case "specification": return item.specification ?? optionValue(item, quoteOptionAliases.specification, locale);
    case "category": return item.category ?? "";
    case "tags": return item.tags.join(quoteSeparator(locale));
    case "product_image": return item.imageUrl ? quoteText(locale, "configured") : "";
    case "quantity": return String(item.quantity);
    case "unit_code": return quoteUnit(locale, item.unitCode);
    case "packing_quantity": return String(optionPackingQuantity(item.optionValues) ?? "");
    case "carton_count": {
      const size = optionPackingQuantity(item.optionValues);
      return size ? String(Number((item.quantity / size).toFixed(6))) : "";
    }
    case "carton_dimensions": return optionValue(item, quoteOptionAliases.carton_dimensions, locale);
    case "gross_weight": return optionValue(item, quoteOptionAliases.gross_weight, locale);
    case "carton_volume": return optionValue(item, quoteOptionAliases.carton_volume, locale);
    case "minimum_order_quantity": return optionValue(item, quoteOptionAliases.minimum_order_quantity, locale);
    case "unit_price": return money(item.unitPrice, item.currency);
    case "line_total": return money(item.lineTotal, item.currency);
    case "total_volume": return optionValue(item, quoteOptionAliases.total_volume, locale);
    case "total_gross_weight": return optionValue(item, quoteOptionAliases.total_gross_weight, locale);
    case "currency": return item.currency;
    default: return "";
  }
}

export function QuoteWorkbenchPage() {
  const { quoteDraftId } = useParams<{ quoteDraftId: string }>();
  const { profile, hasPermission } = useCoreAuth();
  const accountScope = profile?.context.accountScope;
  const isCustomerSubaccount = accountScope === "CUSTOMER_SUBACCOUNT";
  // Supplier, cost and procurement data is internal. Fail closed while the
  // profile is loading or if a future account scope is introduced.
  const canViewSupplierData = accountScope === "STAFF";
  const { t } = useLocale();
  const { notify } = useToast();
  const [draft, setDraft] = useState<PublicQuoteDraft>();
  const [templates, setTemplates] = useState<QuoteExcelTemplate[]>([]);
  const [settings, setSettings] = useState<MerchantSettings>();
  const [locale, setLocale] = useState<StorefrontLocale>("zh-CN");
  const [style, setStyle] = useState<QuoteDocumentStyle>("indigo");
  const [templateId, setTemplateId] = useState<string>("");
  const [quoteNumber, setQuoteNumber] = useState("");
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedDocument = quoteDocumentTab(searchParams);
  const canUseExtendedDocuments = canUseExtendedQuoteDocuments(profile?.context.subscriptionTier);
  const canUsePurchaseOrder = canUseExtendedDocuments && canViewSupplierData;
  // Fail closed while the authenticated profile is loading: only the basic
  // quotation tab is rendered until an Elite subscription is confirmed.
  const activeDocument = canUseExtendedDocuments && (requestedDocument !== "purchase-order" || canUsePurchaseOrder)
    ? requestedDocument
    : "quotation";
  const setActiveDocument = (document: QuoteDocumentTab) => {
    if (!canUseExtendedDocuments && document !== "quotation") return;
    if (document === "purchase-order" && !canUsePurchaseOrder) return;
    setSearchParams((current) => quoteDocumentSearch(current, document), { replace: true });
  };
  const [packingList, setPackingList] = useState<PackingListSettings>();
  const [purchaseOrder, setPurchaseOrder] = useState<QuotePurchaseOrderSettings>();
  const [purchaseOrderLoading, setPurchaseOrderLoading] = useState(false);
  const [purchaseOrderSaving, setPurchaseOrderSaving] = useState(false);
  const [proformaInvoice, setProformaInvoice] = useState<ProformaInvoiceSettings>({
    invoiceNumber: "",
    issueDate: "",
    sellerAddress: "",
    sellerEmail: "",
    sellerPhone: "",
    buyerAddress: "",
    incoterm: "",
    paymentTerms: "",
    deliveryTerms: "",
    shipmentMethod: "",
    portOfLoading: "",
    portOfDestination: "",
    beneficiaryName: "",
    bankName: "",
    bankAddress: "",
    bankAccountNumber: "",
    swiftCode: "",
    freight: 0,
    remarks: "",
  });
  const [previewMode, setPreviewMode] = useState<DocumentPreviewMode>("pdf");
  const [visibleColumns, setVisibleColumns] = useState<QuoteTemplateField[]>(defaultVisibleTableFields);
  const [extraInformation, setExtraInformation] = useState<QuoteExtraInformation[]>([]);
  const [customFields, setCustomFields] = useState<QuoteCustomField[]>([]);
  const [collapsedExtraRows, setCollapsedExtraRows] = useState<Record<number, boolean>>({});
  const [manualOpen, setManualOpen] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [switchingLocale, setSwitchingLocale] = useState<StorefrontLocale>();
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [statusUpdating, setStatusUpdating] = useState<"COMPLETED" | "CANCELLED" | null>(null);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [error, setError] = useState("");
  const [itemEdits, setItemEdits] = useState<Record<string, QuoteItemEdit>>({});
  const [savingItems, setSavingItems] = useState(false);
  const [itemPickerOpen, setItemPickerOpen] = useState(false);
  const [itemPickerQuery, setItemPickerQuery] = useState("");
  const [itemPickerPage, setItemPickerPage] = useState(1);
  const [itemPickerPages, setItemPickerPages] = useState(0);
  const [itemPickerRows, setItemPickerRows] = useState<SkuListItem[]>([]);
  const [itemPickerLoading, setItemPickerLoading] = useState(false);
  const [itemPickerError, setItemPickerError] = useState("");
  const [itemPickerQuantities, setItemPickerQuantities] = useState<Record<string, string>>({});
  const [itemMutationId, setItemMutationId] = useState<string>();
  const [removeItem, setRemoveItem] = useState<PublicQuoteDraftItem>();
  const [bulkPriceOpen, setBulkPriceOpen] = useState(false);
  const [bulkPercentage, setBulkPercentage] = useState("");
  const [bulkSaving, setBulkSaving] = useState(false);
  const [itemsDrawerOpen, setItemsDrawerOpen] = useState(false);
  const [selectedItemId, setSelectedItemId] = useState<string>();
  const [itemImagePreview, setItemImagePreview] = useState<QuoteItemImagePreview>();
  const [priceDrafts, setPriceDrafts] = useState<Record<string, string>>({});
  const [savingItemId, setSavingItemId] = useState<string>();
  const [syncingItemId, setSyncingItemId] = useState<string>();
  const [syncItem, setSyncItem] = useState<PublicQuoteDraftItem>();
  const [productDetails, setProductDetails] = useState<Record<string, ProductDetail | null>>({});
  const [detailLoadingId, setDetailLoadingId] = useState<string>();
  const [managedImageId, setManagedImageId] = useState<string>();
  const [imageManaging, setImageManaging] = useState<"upload" | "delete">();
  const [imageManagementError, setImageManagementError] = useState("");
  const workbenchImageInputRef = useRef<HTMLInputElement>(null);
  const [previewScale, setPreviewScale] = useState(() => (
    typeof window !== "undefined" && window.matchMedia("(max-width: 520px)").matches
      ? PREVIEW_SCALE_MIN
      : 75
  ));
  const [previewPan, setPreviewPan] = useState<PreviewPan>({ x: 0, y: 0 });
  const [previewDragging, setPreviewDragging] = useState(false);
  const [market, setMarket] = useState<DashboardSnapshot["market"]>();
  const [conversionOpen, setConversionOpen] = useState(false);
  const [converting, setConverting] = useState(false);
  const [targetCurrency, setTargetCurrency] = useState("USD");
  const autoSettingsTimer = useRef<number | undefined>(undefined);
  const autoItemsTimer = useRef<number | undefined>(undefined);
  const savedSettingsRef = useRef<QuoteSettingsPayload | undefined>(undefined);
  const acknowledgedSettingsInputRef = useRef<QuoteSettingsPayload | undefined>(undefined);
  const saveBusyRef = useRef(false);
  const failedSettingsRef = useRef<QuoteSettingsPayload | undefined>(undefined);
  const failedItemsRef = useRef<Record<string, QuoteItemEdit> | undefined>(undefined);
  const [saveFailed, setSaveFailed] = useState(false);
  const loadedDraftIdRef = useRef<string | undefined>(undefined);
  const purchaseOrderDraftIdRef = useRef<string | undefined>(undefined);
  const savedPurchaseOrderRef = useRef<string>("");
  const previewViewportRef = useRef<HTMLDivElement>(null);
  const previewSheetRef = useRef<HTMLDivElement>(null);
  const previewDragRef = useRef<{
    pointerId: number;
    pointerX: number;
    pointerY: number;
    panX: number;
    panY: number;
  } | undefined>(undefined);

  const enabledLocaleCodes = useMemo(() => availableQuoteLocales(settings), [settings]);
  const enabledLocales = useMemo(() => {
    const allowed = new Set(enabledLocaleCodes);
    return locales.filter((row) => allowed.has(row.value));
  }, [enabledLocaleCodes]);
  const localeOptions = useMemo(() => (
    enabledLocales.length
      ? enabledLocales
      : locales.filter((row) => row.value === locale)
  ), [enabledLocales, locale]);
  useEffect(() => {
    if (!profile?.context.subscriptionTier || canUseExtendedDocuments) return;
    if (requestedDocument === "quotation") return;
    setSearchParams((current) => quoteDocumentSearch(current, "quotation"), { replace: true });
  }, [canUseExtendedDocuments, profile?.context.subscriptionTier, requestedDocument, setSearchParams]);

  useEffect(() => {
    if (!profile?.context.subscriptionTier) return;
    if (requestedDocument !== "purchase-order" || canUsePurchaseOrder) return;
    setSearchParams((current) => quoteDocumentSearch(current, "quotation"), { replace: true });
  }, [canUsePurchaseOrder, profile?.context.subscriptionTier, requestedDocument, setSearchParams]);

  const readyTemplates = useMemo(() => templates.filter((row) => row.isReady), [templates]);
  const selectedTemplate = useMemo(
    () => readyTemplates.find((template) => template.id === templateId),
    [readyTemplates, templateId],
  );
  const availableColumns = useMemo(() => templateTableFields(selectedTemplate), [selectedTemplate]);
  const activeColumns = useMemo(() => {
    const filtered = visibleColumns
      .filter((field) => availableColumns.includes(field))
      .slice(0, MAX_PDF_COLUMNS);
    return filtered.length ? filtered : preferredVisibleColumns(availableColumns);
  }, [availableColumns, visibleColumns]);
  const currentSettings = useMemo<QuoteSettingsPayload>(() => ({
    locale,
    style,
    templateId: templateId || null,
    quoteNumber: quoteNumber.trim(),
    visibleColumns: [...activeColumns],
    // Empty rows are kept locally while the merchant is typing, but are not
    // sent to the API until both fields are complete (the API validates them).
    extraInformation: extraInformation
      .filter((entry) => entry.title.trim() && entry.content.trim())
      .map((entry) => ({ title: entry.title.trim(), content: entry.content.trim() })),
    customFields: customFields.map((field) => ({
      id: field.id,
      label: field.label.trim(),
      values: Object.fromEntries(Object.entries(field.values).map(([itemId, value]) => [itemId, value.trim()])),
    })),
    proformaInvoice: { ...proformaInvoice },
    packingList,
  }), [activeColumns, customFields, extraInformation, locale, packingList, proformaInvoice, quoteNumber, style, templateId]);
  const latestSettingsRef = useRef(currentSettings);
  latestSettingsRef.current = currentSettings;
  const previewGrid = useMemo(
    () => activeColumns.map((field) => `minmax(0, ${previewColumnWeights[field] ?? 1}fr)`).join(" "),
    [activeColumns],
  );
  const excelPreviewColumns = useMemo<ExcelPreviewColumn[]>(() => {
    const customColumns: ExcelPreviewColumn[] = customFields.filter((field) => field.label.trim()).map((field) => ({
      key: `custom-${field.id}`,
      header: field.label.trim(),
      customFieldId: field.id,
      width: 150,
    }));
    if (selectedTemplate?.columns.length) {
      const templateColumns: ExcelPreviewColumn[] = [...selectedTemplate.columns]
        .sort((left, right) => left.index - right.index)
        .map((column, index) => {
          const field = selectedTemplate.columnMappings[column.key];
          return {
            // The uploaded sheet contributes its product-region columns only;
            // the composed quotation rebases that region to column A.
            key: spreadsheetColumnName(index + 1),
            header: field
              ? fieldLabel(field, t, selectedTemplate, locale)
              : column.header?.trim() || column.key || spreadsheetColumnName(index + 1),
            field,
            width: excelPreviewColumnWidth(field),
          };
        });
      return [...templateColumns, ...customColumns];
    }
    const defaultColumns: ExcelPreviewColumn[] = defaultExcelTableFields.map((field, index) => ({
      key: spreadsheetColumnName(index + 1),
      header: fieldLabel(field, t, undefined, locale),
      field,
      width: excelPreviewColumnWidth(field),
    }));
    return [...defaultColumns, ...customColumns];
  }, [customFields, locale, selectedTemplate, t]);
  // A parent account can inspect a child-owned inquiry, but the child remains
  // the only operator allowed to edit, confirm, or otherwise advance it.
  // Keep this flag at the UI boundary as well as enforcing it in the API so a
  // read-only workbench never sends a mutation that is guaranteed to fail.
  const isReadOnly = Boolean(draft?.readOnly);
  const localeSelectionDisabled = Boolean(draft?.readOnly)
    || saving
    || Boolean(switchingLocale)
    || enabledLocales.length <= 1;
  const documentSellerName = isCustomerSubaccount
    ? profile?.user.displayName?.trim() || ""
    : settings?.name || "";
  const canEditPrices = draft?.status === "PENDING_CONFIRMATION" && !isReadOnly;
  const canManageCatalogImages = accountScope === "STAFF" && hasPermission("product.edit");
  const hasPendingItemEdits = Object.values(itemEdits).some((edit) => Object.keys(edit).length > 0);
  const hasIncompleteExtraInformation = extraInformation.some((entry) => Boolean(entry.title.trim()) !== Boolean(entry.content.trim()));
  const hasIncompleteCustomFields = customFields.some((field) => !field.label.trim());
  const hasDuplicateCustomFieldLabels = new Set(customFields.map((field) => field.label.trim().toLocaleLowerCase()).filter(Boolean)).size
    !== customFields.filter((field) => field.label.trim()).length;
  const hasUnsavedSettings = !quoteSettingsEqual(savedSettingsRef.current, currentSettings) || hasIncompleteExtraInformation || hasIncompleteCustomFields || hasDuplicateCustomFieldLabels;
  const documentSaveState = saveState({ readOnly: Boolean(draft?.readOnly), saving: saving || savingItems, dirty: hasUnsavedSettings || hasPendingItemEdits, failed: saveFailed });
  const saveStatusText = t(({ READ_ONLY: "只读", SAVING: "正在保存…", FAILED: "保存失败", UNSAVED: "未保存", SAVED: "已保存" })[documentSaveState]);
  const purchaseOrderDirty = Boolean(purchaseOrder && JSON.stringify(purchaseOrder) !== savedPurchaseOrderRef.current);
  useUnsavedChanges(Boolean(
    draft
    && (
      (canEditPrices && (hasUnsavedSettings || hasPendingItemEdits || saving || savingItems))
      || (!isReadOnly && activeDocument === "purchase-order" && (purchaseOrderDirty || purchaseOrderSaving))
    )
  ));
  const currencyOptions = useMemo<QuoteCurrencyOption[]>(() => {
    const available = new Map<string, QuoteCurrencyOption>();
    available.set("CNY", { currency: "CNY", name: "人民币", symbol: "¥", rate: 1 });
    for (const row of market?.exchangeRates ?? []) {
      const currency = normalizedCurrency(row.currency);
      if (!row.rate || row.rate <= 0) continue;
      available.set(currency, {
        currency,
        name: row.name,
        symbol: row.symbol,
        rate: row.rate,
      });
    }
    return [...available.values()].sort((left, right) => {
      const leftIndex = preferredCurrencyOrder.indexOf(left.currency);
      const rightIndex = preferredCurrencyOrder.indexOf(right.currency);
      return (leftIndex < 0 ? preferredCurrencyOrder.length : leftIndex)
        - (rightIndex < 0 ? preferredCurrencyOrder.length : rightIndex);
    });
  }, [market?.exchangeRates]);
  const conversionRate = useMemo(() => {
    if (!draft) return undefined;
    const source = normalizedCurrency(draft.currency);
    const target = normalizedCurrency(targetCurrency);
    const sourceRate = currencyOptions.find((row) => row.currency === source)?.rate;
    const targetRate = currencyOptions.find((row) => row.currency === target)?.rate;
    if (!sourceRate || !targetRate || sourceRate <= 0 || targetRate <= 0) return undefined;
    // Market rates are CNY per unit of currency, so source/target gives the
    // amount of target currency represented by one source unit.
    return sourceRate / targetRate;
  }, [currencyOptions, draft, targetCurrency]);
  const canConvertCurrency = Boolean(
    canEditPrices
    && draft
    && normalizedCurrency(draft.currency) !== normalizedCurrency(targetCurrency)
    && conversionRate,
  );
  const conversionRateLabel = conversionRate ? compactRate(conversionRate) : "";
  const canOpenCurrencyConversion = Boolean(
    canEditPrices
    && draft
    && currencyOptions.some((row) => row.currency === normalizedCurrency(draft.currency))
    && currencyOptions.some((row) => row.currency !== normalizedCurrency(draft.currency)),
  );

  const clampPreviewPan = useCallback((next: PreviewPan, scale = previewScale): PreviewPan => {
    const viewport = previewViewportRef.current;
    const sheet = previewSheetRef.current;
    if (!viewport || !sheet) return next;
    const scaleFactor = scale / 100;
    const horizontalOverflow = Math.max(0, (sheet.offsetWidth * scaleFactor - viewport.clientWidth) / 2);
    const verticalOverflow = Math.max(0, (sheet.offsetHeight * scaleFactor - viewport.clientHeight) / 2);
    const edgeAllowance = 28;
    const maxX = horizontalOverflow > 0 ? horizontalOverflow + edgeAllowance : 0;
    const maxY = verticalOverflow > 0 ? verticalOverflow + edgeAllowance : 0;
    return {
      x: Math.min(maxX, Math.max(-maxX, next.x)),
      y: Math.min(maxY, Math.max(-maxY, next.y)),
    };
  }, [previewScale]);

  const changePreviewScale = useCallback((value: number) => {
    const nextScale = normalizedPreviewScale(value);
    setPreviewScale(nextScale);
    window.requestAnimationFrame(() => {
      setPreviewPan((current) => clampPreviewPan(current, nextScale));
    });
  }, [clampPreviewPan]);

  const fitPreviewToViewport = useCallback(() => {
    const viewport = previewViewportRef.current;
    const sheet = previewSheetRef.current;
    if (!viewport || !sheet) return;
    const horizontalScale = (viewport.clientWidth - 64) / sheet.offsetWidth;
    const verticalScale = (viewport.clientHeight - 64) / sheet.offsetHeight;
    const nextScale = normalizedPreviewScale(Math.min(horizontalScale, verticalScale, 1) * 100);
    setPreviewScale(nextScale);
    setPreviewPan({ x: 0, y: 0 });
  }, []);

  const startPreviewPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const interactive = (event.target as HTMLElement).closest("button, input, a, select, textarea");
    if (interactive) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    previewDragRef.current = {
      pointerId: event.pointerId,
      pointerX: event.clientX,
      pointerY: event.clientY,
      panX: previewPan.x,
      panY: previewPan.y,
    };
    setPreviewDragging(true);
  }, [previewPan.x, previewPan.y]);

  const movePreviewPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const drag = previewDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    event.preventDefault();
    setPreviewPan(clampPreviewPan({
      x: drag.panX + event.clientX - drag.pointerX,
      y: drag.panY + event.clientY - drag.pointerY,
    }));
  }, [clampPreviewPan]);

  const endPreviewPan = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (previewDragRef.current?.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    previewDragRef.current = undefined;
    setPreviewDragging(false);
  }, []);

  const handlePreviewWheel = useCallback((event: React.WheelEvent<HTMLDivElement>) => {
    if (!event.ctrlKey && !event.metaKey) return;
    event.preventDefault();
    changePreviewScale(previewScale + (event.deltaY < 0 ? PREVIEW_SCALE_STEP : -PREVIEW_SCALE_STEP));
  }, [changePreviewScale, previewScale]);

  const handlePreviewKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    const panDelta = event.shiftKey ? 72 : 32;
    if (event.key === "+" || event.key === "=") {
      event.preventDefault();
      changePreviewScale(previewScale + PREVIEW_SCALE_STEP);
      return;
    }
    if (event.key === "-") {
      event.preventDefault();
      changePreviewScale(previewScale - PREVIEW_SCALE_STEP);
      return;
    }
    if (event.key === "0" || event.key === "Home") {
      event.preventDefault();
      fitPreviewToViewport();
      return;
    }
    const directions: Partial<Record<string, PreviewPan>> = {
      ArrowLeft: { x: panDelta, y: 0 },
      ArrowRight: { x: -panDelta, y: 0 },
      ArrowUp: { x: 0, y: panDelta },
      ArrowDown: { x: 0, y: -panDelta },
    };
    const direction = directions[event.key];
    if (!direction) return;
    event.preventDefault();
    setPreviewPan((current) => clampPreviewPan({
      x: current.x + direction.x,
      y: current.y + direction.y,
    }));
  }, [changePreviewScale, clampPreviewPan, fitPreviewToViewport, previewScale]);

  useEffect(() => {
    const handleResize = () => setPreviewPan((current) => clampPreviewPan(current));
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [clampPreviewPan]);

  const load = useCallback(async () => {
    if (!quoteDraftId) return;
    setLoading(true);
    setError("");
    setMarket(undefined);
    setPurchaseOrder(undefined);
    purchaseOrderDraftIdRef.current = undefined;
    savedPurchaseOrderRef.current = "";
    try {
      const [nextDraft, nextTemplates, merchantSettings] = await Promise.all([
        getPublicQuoteDraft(quoteDraftId),
        listQuoteExcelTemplates().catch(() => []),
        getMerchantSettings().catch(() => undefined),
      ]);
      const nextReadyTemplates = nextTemplates.filter((template) => template.isReady);
      const nextTemplate = nextReadyTemplates.find((template) => template.id === (nextDraft.quoteTemplateId ?? "")) ?? nextReadyTemplates.find((template) => template.isDefault);
      const nextAvailable = templateTableFields(nextTemplate);
      const nextVisible = (nextDraft.visibleColumns ?? [])
        .filter((field) => nextAvailable.includes(field))
        .slice(0, MAX_PDF_COLUMNS);
      const nextActiveColumns = nextVisible.length ? nextVisible : preferredVisibleColumns(nextAvailable);
      setDraft(nextDraft);
      setTemplates(nextTemplates);
      setSettings(merchantSettings);
      setLocale(nextDraft.locale);
      setStyle(nextDraft.documentStyle);
      setTemplateId(nextDraft.quoteTemplateId ?? "");
      setQuoteNumber(nextDraft.quoteNumber);
      setProformaInvoice(nextDraft.proformaInvoice);
      setPackingList(nextDraft.packingList);
      setVisibleColumns(nextActiveColumns);
      setExtraInformation(nextDraft.extraInformation ?? []);
      setCustomFields(nextDraft.customFields ?? []);
      setCollapsedExtraRows({});
      savedSettingsRef.current = {
        locale: nextDraft.locale,
        style: nextDraft.documentStyle,
        templateId: nextDraft.quoteTemplateId ?? null,
        quoteNumber: nextDraft.quoteNumber.trim(),
        visibleColumns: [...nextActiveColumns],
        extraInformation: (nextDraft.extraInformation ?? []).map((entry) => ({ ...entry })),
        customFields: (nextDraft.customFields ?? []).map((field) => ({ ...field, values: { ...field.values } })),
        proformaInvoice: { ...nextDraft.proformaInvoice },
        packingList: nextDraft.packingList,
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
    if (!itemPickerOpen) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setItemPickerLoading(true);
      setItemPickerError("");
      void listSkus({
        q: itemPickerQuery.trim() || undefined,
        statuses: ["ACTIVE"],
        page: itemPickerPage,
        pageSize: 30,
      })
        .then((page) => {
          if (cancelled) return;
          const published = page.items.filter((row) => row.publicOfferStatus === "PUBLISHED");
          setItemPickerRows(published);
          setItemPickerPages(page.pages);
          setItemPickerQuantities((current) => {
            const next = { ...current };
            for (const row of published) {
              if (next[row.id] !== undefined) continue;
              const packing = Number(row.packingQuantity);
              const moq = Number(row.defaultMoq);
              next[row.id] = String(
                Number.isFinite(packing) && packing > 0
                  ? packing
                  : Number.isFinite(moq) && moq > 0 ? moq : 1,
              );
            }
            return next;
          });
        })
        .catch((reason) => {
          if (!cancelled) setItemPickerError(reason instanceof Error ? reason.message : t("商品库加载失败"));
        })
        .finally(() => {
          if (!cancelled) setItemPickerLoading(false);
        });
    }, itemPickerQuery.trim() ? 260 : 0);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [itemPickerOpen, itemPickerPage, itemPickerQuery, t]);

  useEffect(() => {
    if (
      activeDocument !== "purchase-order"
      || !canUsePurchaseOrder
      || !draft
      || purchaseOrderDraftIdRef.current === draft.id
    ) return;
    let cancelled = false;
    setPurchaseOrderLoading(true);
    setError("");
    void getPublicQuoteDraftPurchaseOrder(draft.id)
      .then((next) => {
        if (cancelled) return;
        setPurchaseOrder(next);
        savedPurchaseOrderRef.current = JSON.stringify(next);
        purchaseOrderDraftIdRef.current = draft.id;
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : t("采购单加载失败"));
      })
      .finally(() => {
        if (!cancelled) setPurchaseOrderLoading(false);
      });
    return () => { cancelled = true; };
  }, [activeDocument, canUsePurchaseOrder, draft, t]);

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
        const size = optionPackingQuantity(draft.items.find((item) => item.id === itemId)?.optionValues);
        if (size && Math.round(value * 1_000_000) % Math.round(size * 1_000_000) !== 0) {
          setError(storefrontText(locale, "数量必须为装箱数 {size} 的整数倍。", { size }));
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
    if (saveBusyRef.current) return undefined;
    saveBusyRef.current = true;
    setSavingItems(true);
    setSaveFailed(false);
    setError("");
    try {
      const next = await updatePublicQuoteDraftItems(draft.id, payload);
      setDraft(next);
      setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
      setItemEdits((current) => acknowledgeEdits(current, itemEdits));
      failedItemsRef.current = undefined;
      return next;
    } catch (reason) {
      failedItemsRef.current = itemEdits;
      setSaveFailed(true);
      setError(reason instanceof Error ? reason.message : t("商品修改保存失败"));
      return undefined;
    } finally {
      saveBusyRef.current = false;
      setSavingItems(false);
    }
  }, [canEditPrices, draft, itemEdits, t]);

  const persistSettings = useCallback(async (target: PublicQuoteDraft, payload: QuoteSettingsPayload, quiet = false) => {
    if (target.readOnly) return target;
    if (!payload.quoteNumber) {
      if (!quiet) setError(t("报价单编号不能为空。"));
      return undefined;
    }
    const proformaIsValid = Boolean(
      payload.proformaInvoice.invoiceNumber.trim()
      && payload.proformaInvoice.issueDate,
    );
    const packingIsValid = !payload.packingList || packingErrors(payload.packingList, target.items, payload.locale).length === 0;
    if (activeDocument === "packing-list" && !packingIsValid) {
      if (!quiet) setError(packingErrors(payload.packingList!, target.items, payload.locale).join("\n"));
      return undefined;
    }
    if (activeDocument === "proforma" && !payload.proformaInvoice.invoiceNumber.trim()) {
      if (!quiet) setError(`${proformaText(payload.locale, "invoice_number")}不能为空。`);
      return undefined;
    }
    if (activeDocument === "proforma" && !payload.proformaInvoice.issueDate) {
      if (!quiet) setError(`${proformaText(payload.locale, "issue_date")}不能为空。`);
      return undefined;
    }
    if (saveBusyRef.current) return undefined;
    saveBusyRef.current = true;
    setSaving(true);
    setSaveFailed(false);
    if (!quiet) setError("");
    try {
      const next = await updatePublicQuoteDraftSettings(target.id, {
        locale: payload.locale,
        style: payload.style,
        templateId: payload.templateId,
        quoteNumber: payload.quoteNumber,
        visibleColumns: payload.visibleColumns,
        extraInformation: payload.extraInformation,
        customFields: payload.customFields,
        // A partially typed required PI field must not block unrelated
        // quotation edits. Leaving the nested object out preserves the last
        // valid PI snapshot on the server until the PI is valid again.
        proformaInvoice: canUseExtendedDocuments && proformaIsValid ? payload.proformaInvoice : undefined,
        packingList: canUseExtendedDocuments && packingIsValid ? payload.packingList : undefined,
      });
      setDraft(next);
      const nextVisibleColumns = (next.visibleColumns.length ? next.visibleColumns : payload.visibleColumns).slice(0, MAX_PDF_COLUMNS);
      // Preserve changes typed while this request was in flight.
      if (quoteSettingsEqual(latestSettingsRef.current, payload)) {
        setQuoteNumber(next.quoteNumber);
        setVisibleColumns(nextVisibleColumns);
        setExtraInformation((current) => current.some((entry) => !entry.title.trim() || !entry.content.trim()) ? current : next.extraInformation ?? payload.extraInformation);
        setCustomFields(next.customFields ?? payload.customFields);
        setProformaInvoice(next.proformaInvoice);
        setPackingList(next.packingList);
      }
      failedSettingsRef.current = undefined;
      acknowledgedSettingsInputRef.current = payload;
      savedSettingsRef.current = {
        ...payload,
        quoteNumber: next.quoteNumber.trim(),
        visibleColumns: [...nextVisibleColumns],
        extraInformation: (next.extraInformation ?? payload.extraInformation).map((entry) => ({ ...entry })),
        customFields: (next.customFields ?? payload.customFields).map((field) => ({ ...field, values: { ...field.values } })),
        proformaInvoice: { ...next.proformaInvoice },
        packingList: next.packingList,
      };
      return next;
    } catch (reason) {
      failedSettingsRef.current = payload;
      setSaveFailed(true);
      const message = reason instanceof Error ? reason.message : t("报价单设置保存失败");
      if (quiet) notify(message, { kind: "error" });
      else setError(message);
      return undefined;
    } finally {
      saveBusyRef.current = false;
      setSaving(false);
    }
  }, [activeDocument, canUseExtendedDocuments, notify, t]);

  const changeDocumentLocale = useCallback(async (value: string) => {
    const nextLocale = value as StorefrontLocale;
    if (
      !draft
      || nextLocale === locale
      || switchingLocale
      || !enabledLocaleCodes.includes(nextLocale)
    ) return;
    const previousLocale = locale;
    const payload = { ...latestSettingsRef.current, locale: nextLocale };
    setLocale(nextLocale);
    setSwitchingLocale(nextLocale);
    const updated = await persistSettings(draft, payload, true);
    if (!updated) setLocale(previousLocale);
    setSwitchingLocale(undefined);
  }, [draft, enabledLocaleCodes, locale, persistSettings, switchingLocale]);

  const save = useCallback(async () => {
    if (!draft) return draft;
    if (draft.readOnly) return draft;
    if (hasIncompleteExtraInformation) {
      setError(t("请完善额外信息的标题和内容。"));
      return undefined;
    }
    if (hasIncompleteCustomFields) {
      setError(t("请填写自定义字段名称。"));
      return undefined;
    }
    if (hasDuplicateCustomFieldLabels) {
      setError(t("自定义字段名称不能重复。"));
      return undefined;
    }
    const edited = await saveAllItemEdits();
    if (!edited) return undefined;
    return persistSettings(edited, currentSettings);
  }, [currentSettings, draft, persistSettings, saveAllItemEdits, hasDuplicateCustomFieldLabels, hasIncompleteCustomFields, hasIncompleteExtraInformation, t]);

  const applyQuoteItemStructure = useCallback((next: PublicQuoteDraft) => {
    const nextSelectedItemId = selectedItemId && next.items.some((item) => item.id === selectedItemId)
      ? selectedItemId
      : undefined;
    setDraft(next);
    setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
    setItemEdits({});
    setCustomFields(next.customFields ?? []);
    setPackingList(next.packingList);
    setProformaInvoice(next.proformaInvoice);
    setSelectedItemId(nextSelectedItemId);
    setItemsDrawerOpen((current) => current && Boolean(nextSelectedItemId));
    setPurchaseOrder(undefined);
    purchaseOrderDraftIdRef.current = undefined;
    savedPurchaseOrderRef.current = "";
    savedSettingsRef.current = {
      locale: next.locale,
      style: next.documentStyle,
      templateId: next.quoteTemplateId ?? null,
      quoteNumber: next.quoteNumber.trim(),
      visibleColumns: [...activeColumns],
      extraInformation: (next.extraInformation ?? []).map((entry) => ({ ...entry })),
      customFields: (next.customFields ?? []).map((field) => ({ ...field, values: { ...field.values } })),
      proformaInvoice: { ...next.proformaInvoice },
      packingList: next.packingList,
    };
    failedItemsRef.current = undefined;
    setSaveFailed(false);
  }, [activeColumns, selectedItemId]);

  const addQuoteItem = useCallback(async (candidate: SkuListItem) => {
    if (!draft || !canEditPrices || itemMutationId) return;
    const rawQuantity = (itemPickerQuantities[candidate.id] ?? "1").trim();
    const quantity = Number(rawQuantity);
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setItemPickerError(t("请输入有效的商品数量。"));
      return;
    }
    const packing = Number(candidate.packingQuantity);
    if (Number.isFinite(packing) && packing > 0) {
      const quantityUnits = Math.round(quantity * 1_000_000);
      const packingUnits = Math.round(packing * 1_000_000);
      if (quantityUnits % packingUnits !== 0) {
        setItemPickerError(storefrontText(locale, "数量必须为装箱数 {size} 的整数倍。", { size: packing }));
        return;
      }
    }
    setItemMutationId(candidate.id);
    setItemPickerError("");
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      const next = await addPublicQuoteDraftItems(saved.id, [{ skuId: candidate.id, quantity }]);
      applyQuoteItemStructure(next);
      notify(t("商品已加入报价单。"), { kind: "success" });
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : t("商品添加失败");
      setItemPickerError(message);
      setError(message);
    } finally {
      setItemMutationId(undefined);
    }
  }, [applyQuoteItemStructure, canEditPrices, draft, itemMutationId, itemPickerQuantities, locale, notify, save, t]);

  const deleteQuoteItem = useCallback(async () => {
    if (!draft || !removeItem || !canEditPrices || itemMutationId) return;
    setItemMutationId(removeItem.id);
    setError("");
    try {
      const saved = await save();
      if (!saved) return;
      const next = await deletePublicQuoteDraftItem(saved.id, removeItem.id);
      applyQuoteItemStructure(next);
      setRemoveItem(undefined);
      notify(t("商品已从报价单移除。"), { kind: "success" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("商品删除失败"));
    } finally {
      setItemMutationId(undefined);
    }
  }, [applyQuoteItemStructure, canEditPrices, draft, itemMutationId, notify, removeItem, save, t]);

  useEffect(() => {
    if (!draft || !canEditPrices || loadedDraftIdRef.current !== draft.id) return;
    if (saving || savingItems || hasPendingItemEdits || hasIncompleteExtraInformation || hasIncompleteCustomFields || hasDuplicateCustomFieldLabels) return;
    if (quoteSettingsEqual(savedSettingsRef.current, currentSettings)) return;
    // The server may preserve an incomplete PI/packing section. Keep it dirty,
    // but do not repeatedly save the same unchanged input while it is incomplete.
    if (quoteSettingsEqual(acknowledgedSettingsInputRef.current, currentSettings)) return;
    if (quoteSettingsEqual(failedSettingsRef.current, currentSettings)) return;
    if (autoSettingsTimer.current) window.clearTimeout(autoSettingsTimer.current);
    autoSettingsTimer.current = window.setTimeout(() => {
      void persistSettings(draft, currentSettings, true);
    }, 650);
    return () => {
      if (autoSettingsTimer.current) window.clearTimeout(autoSettingsTimer.current);
    };
  }, [activeDocument, canEditPrices, currentSettings, draft, persistSettings, saving, savingItems, hasPendingItemEdits, hasIncompleteExtraInformation, hasIncompleteCustomFields, hasDuplicateCustomFieldLabels]);

  useEffect(() => {
    if (!draft || !canEditPrices || !hasPendingItemEdits || saving || savingItems || failedItemsRef.current === itemEdits) return;
    if (autoItemsTimer.current) window.clearTimeout(autoItemsTimer.current);
    autoItemsTimer.current = window.setTimeout(() => {
      void saveAllItemEdits();
    }, 850);
    return () => {
      if (autoItemsTimer.current) window.clearTimeout(autoItemsTimer.current);
    };
  }, [canEditPrices, draft, hasPendingItemEdits, saveAllItemEdits, saving, savingItems, itemEdits]);

  const download = async (type: "pdf" | "xlsx") => {
    if (!draft) return;
    if (activeDocument !== "quotation" && activeDocument !== "proforma" && activeDocument !== "packing-list") return;
    setDownloading(type);
    setError("");
    try {
      // A parent may download a child-owned quote, but must not trigger an
      // implicit settings write while doing so.
      const saved = draft.readOnly ? draft : await save();
      if (!saved) return;
      const documentType = activeDocument === "packing-list" ? "packing_list" : activeDocument === "proforma" ? "proforma_invoice" : "quotation";
      const documentNumber = documentType === "proforma_invoice"
        ? saved.proformaInvoice.invoiceNumber
        : documentType === "packing_list" ? saved.packingList?.packingListNumber || saved.quoteNumber : saved.quoteNumber;
      await downloadPublicQuoteDraftDocument(saved.id, documentNumber, type, documentType);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价文件下载失败"));
    } finally {
      setDownloading(null);
    }
  };

  const savePurchaseOrder = async (): Promise<QuotePurchaseOrderSettings | undefined> => {
    if (!draft || !purchaseOrder || isReadOnly || purchaseOrderSaving) return purchaseOrder;
    if (!purchaseOrder.purchaseOrderNumber.trim()) {
      setError(t("采购单号不能为空。"));
      return undefined;
    }
    if (!purchaseOrder.issueDate) {
      setError(t("采购单日期不能为空。"));
      return undefined;
    }
    if (purchaseOrder.items.some((item) => !item.name.trim() || !item.skuCode.trim() || !item.unitCode.trim() || item.quantity <= 0)) {
      setError(t("采购单商品名称、SKU、数量和单位必须填写完整。"));
      return undefined;
    }
    setPurchaseOrderSaving(true);
    setError("");
    try {
      const next = await updatePublicQuoteDraftPurchaseOrder(draft.id, purchaseOrder);
      setPurchaseOrder(next);
      savedPurchaseOrderRef.current = JSON.stringify(next);
      notify(t("采购单已保存。"), { kind: "success" });
      return next;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("采购单保存失败"));
      return undefined;
    } finally {
      setPurchaseOrderSaving(false);
    }
  };

  const exportPurchaseOrder = async () => {
    if (!draft || !purchaseOrder || downloading) return;
    setDownloading("xlsx");
    setError("");
    try {
      const saved = isReadOnly ? purchaseOrder : await savePurchaseOrder();
      if (!saved) return;
      await downloadPublicQuoteDraftDocument(
        draft.id,
        saved.purchaseOrderNumber,
        "xlsx",
        "purchase_order",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("采购单下载失败"));
    } finally {
      setDownloading(null);
    }
  };

  const confirm = async () => {
    if (!draft || draft.readOnly || !canEditPrices) return;
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

  const updateStatus = async (status: "COMPLETED" | "CANCELLED") => {
    if (!draft || draft.readOnly) return;
    setStatusUpdating(status);
    setError("");
    try {
      const updated = await updatePublicQuoteDraftStatus(draft.id, status);
      setDraft(updated);
      setCancelOpen(false);
      notify(t(status === "COMPLETED" ? "报价已标记为成交。" : "询价已取消。"), { kind: "success" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("订单状态更新失败"));
    } finally {
      setStatusUpdating(null);
    }
  };

  const toggleColumn = (field: QuoteTemplateField, checked: boolean) => {
    if (checked && !visibleColumns.includes(field) && activeColumns.length >= MAX_PDF_COLUMNS) {
      notify(t("PDF 最多显示 {count} 列。", { count: MAX_PDF_COLUMNS }), { kind: "info" });
      return;
    }
    setVisibleColumns((current) => {
      if (checked) return current.includes(field) ? current : [...current, field].slice(0, MAX_PDF_COLUMNS);
      if (current.length <= 1) return current;
      return current.filter((value) => value !== field);
    });
  };

  const changeTemplate = (value: string) => {
    const nextId = value === "default" ? "" : value;
    const nextTemplate = readyTemplates.find((template) => template.id === nextId) ?? readyTemplates.find((template) => template.isDefault);
    setTemplateId(nextId);
    setVisibleColumns(preferredVisibleColumns(templateTableFields(nextTemplate)));
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
    setImageManagementError("");
    // The list itself lives in the editor now.  Opening an item should only
    // show its system record in a focused dialog, without hiding the editor.
    setItemsDrawerOpen(true);
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

  const refreshProductAfterImageMutation = async (productId: string) => {
    const detail = await getProduct(productId);
    setProductDetails((current) => ({ ...current, [productId]: detail }));
    const mainImage = detail.images.find((image) => image.imageRole === "MAIN") ?? detail.images[0];
    setManagedImageId(mainImage?.id);
    if (draft && canEditPrices) {
      const affected = draft.items.filter((item) => item.productId === productId);
      if (affected.length) {
        const next = await updatePublicQuoteDraftItems(
          draft.id,
          affected.map((item) => ({ itemId: item.id, imageUrl: mainImage?.url ?? null })),
        );
        setDraft(next);
      }
    }
    return detail;
  };

  const addWorkbenchProductImage = async (file?: File) => {
    if (!file || !selectedDrawerItem || !selectedProductDetail || !canManageCatalogImages || imageManaging) return;
    setImageManagementError("");
    const supportedExtension = /\.(png|jpe?g|webp)$/i.test(file.name);
    if ((file.type && !file.type.startsWith("image/")) || (!file.type && !supportedExtension)) {
      setImageManagementError(t("请选择 PNG、JPG 或 WebP 图片。"));
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setImageManagementError(t("商品图片不能超过 20 MB。"));
      return;
    }
    if (selectedProductDetail.images.length >= 50) {
      setImageManagementError(t("每个商品最多上传 50 张图片。"));
      return;
    }
    setImageManaging("upload");
    try {
      const uploaded = await uploadProductGalleryImage(selectedDrawerItem.productId, file);
      await refreshProductAfterImageMutation(selectedDrawerItem.productId);
      setManagedImageId(uploaded.id);
      notify(t("商品图片已新增。"), { kind: "success" });
    } catch (reason) {
      setImageManagementError(reason instanceof Error ? reason.message : t("商品图片上传失败"));
    } finally {
      setImageManaging(undefined);
      if (workbenchImageInputRef.current) workbenchImageInputRef.current.value = "";
    }
  };

  const removeWorkbenchProductImage = async (imageId: string) => {
    if (!selectedDrawerItem || !canManageCatalogImages || imageManaging) return;
    if (!window.confirm(t("确认删除这张商品图片？"))) return;
    setImageManagementError("");
    setImageManaging("delete");
    try {
      await deleteProductImage(selectedDrawerItem.productId, imageId);
      await refreshProductAfterImageMutation(selectedDrawerItem.productId);
      notify(t("商品图片已删除。"), { kind: "success" });
    } catch (reason) {
      setImageManagementError(reason instanceof Error ? reason.message : t("商品图片删除失败"));
    } finally {
      setImageManaging(undefined);
    }
  };

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

  const addExtraInformation = () => {
    if (isReadOnly) return;
    setExtraInformation((current) => [...current, { title: "", content: "" }]);
  };

  const updateExtraInformation = (index: number, field: keyof QuoteExtraInformation, value: string) => {
    setExtraInformation((current) => current.map((entry, entryIndex) => (
      entryIndex === index ? { ...entry, [field]: value } : entry
    )));
  };

  const removeExtraInformation = (index: number) => {
    if (isReadOnly) return;
    setExtraInformation((current) => current.filter((_, entryIndex) => entryIndex !== index));
    setCollapsedExtraRows((current) => {
      const next: Record<number, boolean> = {};
      Object.entries(current).forEach(([key, value]) => {
        const entryIndex = Number(key);
        if (entryIndex === index) return;
        next[entryIndex > index ? entryIndex - 1 : entryIndex] = value;
      });
      return next;
    });
  };

  const toggleExtraInformation = (index: number) => {
    setCollapsedExtraRows((current) => ({ ...current, [index]: !current[index] }));
  };

  const addCustomField = () => {
    if (isReadOnly || customFields.length >= 12) return;
    setCustomFields((current) => [...current, {
      id: crypto.randomUUID(),
      label: "",
      values: Object.fromEntries((draft?.items ?? []).map((item) => [item.id, ""])),
    }]);
  };

  const renameCustomField = (fieldId: string, label: string) => {
    setCustomFields((current) => current.map((field) => field.id === fieldId ? { ...field, label } : field));
  };

  const updateCustomFieldValue = (fieldId: string, itemId: string, value: string) => {
    setCustomFields((current) => current.map((field) => field.id === fieldId
      ? { ...field, values: { ...field.values, [itemId]: value } }
      : field));
  };

  const removeCustomField = (fieldId: string) => {
    if (isReadOnly) return;
    setCustomFields((current) => current.filter((field) => field.id !== fieldId));
  };

  const renderCustomFieldManager = () => (
    <div className="quote-custom-field-manager">
      <div className="quote-custom-field-manager-heading">
        <div><Text size="2" weight="medium">{t("自定义商品字段")}</Text><Text size="1" color="gray">{t("字段仅用于当前单据，可自由命名并逐项填写。")}</Text></div>
        <Button size="1" variant="soft" color="blue" disabled={isReadOnly || customFields.length >= 12} onClick={addCustomField}><Plus />{t("新增字段")}</Button>
      </div>
      {customFields.length ? <div className="quote-custom-field-list">{customFields.map((field, index) => (
        <div className="quote-custom-field-definition" key={field.id}>
          <span>{index + 1}</span>
          <TextField.Root value={field.label} maxLength={80} placeholder={t("输入字段名")} disabled={isReadOnly} aria-label={t("自定义字段名称")} onChange={(event) => renameCustomField(field.id, event.target.value)} />
          <IconButton size="1" variant="soft" color="red" disabled={isReadOnly} aria-label={t("删除自定义字段")} onClick={() => removeCustomField(field.id)}><Trash /></IconButton>
        </div>
      ))}</div> : null}
      {hasDuplicateCustomFieldLabels ? <Text size="1" color="red">{t("自定义字段名称不能重复。")}</Text> : null}
    </div>
  );

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

  const openCurrencyConversion = () => {
    if (!draft || !canOpenCurrencyConversion || hasPendingItemEdits) return;
    const source = normalizedCurrency(draft.currency);
    const preferredTarget = source === "CNY" ? "USD" : "CNY";
    const nextTarget = currencyOptions.find((row) => row.currency === preferredTarget)
      ?? currencyOptions.find((row) => row.currency !== source);
    if (!nextTarget) return;
    setTargetCurrency(nextTarget.currency);
    setConversionOpen(true);
  };

  const convertCurrency = async () => {
    if (!draft || !canConvertCurrency || hasPendingItemEdits || converting) return;
    setConverting(true);
    setError("");
    try {
      const sourceCurrency = normalizedCurrency(draft.currency);
      const destinationCurrency = normalizedCurrency(targetCurrency);
      // PI fields are explicitly saved in the split editor. Persist them
      // before conversion so the returned snapshot cannot discard party
      // details or convert a previously saved (rather than edited) freight.
      if (activeDocument === "proforma" && !quoteSettingsEqual(savedSettingsRef.current, currentSettings)) {
        const saved = await save();
        if (!saved) return;
      }
      const next = await convertPublicQuoteDraftCurrency(draft.id, destinationCurrency);
      setDraft(next);
      setProformaInvoice(next.proformaInvoice);
      if (savedSettingsRef.current) {
        savedSettingsRef.current = { ...savedSettingsRef.current, proformaInvoice: { ...next.proformaInvoice } };
      }
      setPriceDrafts(Object.fromEntries(next.items.map((item) => [item.id, item.unitPrice.toFixed(2)])));
      setConversionOpen(false);
      const rateText = conversionRate ? compactRate(conversionRate) : "";
      notify(rateText
        ? t("已按 1 {source} = {rate} {target} 换算本报价单。", {
          source: sourceCurrency,
          rate: rateText,
          target: destinationCurrency,
        })
        : t("报价单已切换为 {target}。", { target: destinationCurrency }), { kind: "success" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("报价币种换算失败"));
    } finally {
      setConverting(false);
    }
  };

  const selectedProductDetail = selectedDrawerItem
    ? productDetails[selectedDrawerItem.productId]
    : undefined;
  const selectedLiveProductImage = selectedProductDetail?.images.find((image) => image.id === managedImageId)
    ?? selectedProductDetail?.images.find((image) => image.imageRole === "MAIN")
    ?? selectedProductDetail?.images[0];
  const selectedDetailImageUrl = selectedLiveProductImage?.url
    ?? selectedProductDetail?.primaryImageUrl
    ?? selectedDrawerItem?.imageUrl;
  const selectedLiveSku = selectedProductDetail?.skus.find((sku) => sku.id === selectedDrawerItem?.skuId);
  const selectedSupplierOffers = canViewSupplierData && selectedProductDetail
    ? (() => {
      const exact = selectedProductDetail.sources.filter((source) => source.skuId === selectedDrawerItem?.skuId);
      return exact.length ? exact : selectedProductDetail.sources;
    })()
    : [];
  const previewTotal = draft
    ? draft.items.reduce((sum, item) => sum + effectiveItem(item).lineTotal, 0)
    : 0;

  const renderPreviewCell = (item: PublicQuoteDraftItem, field: QuoteTemplateField) => {
    const effective = effectiveItem(item);
    if (field === "product_image") {
      return effective.imageUrl
        ? <img className="quote-preview-product-image" src={effective.imageUrl} alt={effective.name} loading="lazy" />
        : <span className="quote-preview-cell">—</span>;
    }
    const value = previewValue(effective, field, locale);
    const multiline = field === "product_name"
      || field === "description"
      || field === "specification"
      || field === "category";
    return <span className={`quote-preview-cell ${multiline ? "quote-preview-cell--multiline" : ""}`} title={value}>{value}</span>;
  };

  const renderExcelPreviewCell = (item: PublicQuoteDraftItem, column: ExcelPreviewColumn) => {
    const effective = effectiveItem(item);
    if (column.customFieldId) return customFields.find((field) => field.id === column.customFieldId)?.values[item.id] ?? "";
    if (!column.field) return null;
    if (column.field === "product_image") {
      return effective.imageUrl
        ? <img className="quote-excel-product-image" src={effective.imageUrl} alt={effective.name} loading="lazy" />
        : null;
    }
    if (column.field === "unit_price") return effective.unitPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (column.field === "line_total") return effective.lineTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return previewValue(effective, column.field, locale);
  };

  const renderExcelPreview = () => {
    if (!draft) return null;
    const columns = excelPreviewColumns;
    const extraRows = extraInformation.filter((entry) => entry.title.trim() && entry.content.trim());
    const itemStartRow = 5;
    const totalRow = itemStartRow + draft.items.length;
    const documentTitle = quoteText(locale, "document_title");
    const documentNumber = quoteNumber;
    const sheetName = quoteText(locale, "sheet_name");
    return (
      <div className="quote-excel-preview-stage">
        <div className="quote-excel-formula-bar" aria-hidden="true">
          <span className="quote-excel-name-box">A1</span>
          <span className="quote-excel-fx">fx</span>
          <span>{documentTitle} · {documentNumber}</span>
        </div>
        <div className="quote-excel-scroll" tabIndex={0} aria-label={`${documentTitle} Excel`}>
          <table className="quote-excel-sheet">
            <colgroup>
              <col className="quote-excel-row-number-column" />
              {columns.map((column) => <col key={column.key} style={{ width: `${column.width}px` }} />)}
            </colgroup>
            <thead>
              <tr>
                <th className="quote-excel-corner" aria-hidden="true" />
                {columns.map((column, index) => <th className="quote-excel-column-name" key={column.key}>{column.key || spreadsheetColumnName(index + 1)}</th>)}
              </tr>
            </thead>
            <tbody>
              <tr className="quote-excel-title-row">
                <th className="quote-excel-row-number">1</th>
                <td colSpan={columns.length}><strong>{documentTitle}</strong></td>
              </tr>
              <tr className="quote-excel-meta-row">
                <th className="quote-excel-row-number">2</th>
                <td colSpan={columns.length}>
                  <div className="quote-excel-meta-grid">
                    <span><small>{quoteText(locale, "merchant")}</small><strong>{documentSellerName || "—"}</strong></span>
                    <span><small>{quoteText(locale, "quote_number")}</small><strong>{documentNumber}</strong></span>
                    <span><small>{quoteText(locale, "customer")}</small><strong>{draft.customerCompany || draft.customerName}</strong></span>
                    <span><small>{quoteText(locale, "date")}</small><strong>{quoteDateOnly(draft.createdAt)}</strong></span>
                    <span><small>{quoteText(locale, "currency")}</small><strong>{draft.currency}</strong></span>
                  </div>
                </td>
              </tr>
              <tr className="quote-excel-blank-row">
                <th className="quote-excel-row-number">3</th>
                <td colSpan={columns.length} />
              </tr>
              <tr className="quote-excel-header-row">
                <th className="quote-excel-row-number">4</th>
                {columns.map((column) => <td key={column.key}>{column.header}</td>)}
              </tr>
              {draft.items.map((item, itemIndex) => (
                <tr className="quote-excel-data-row" key={item.id}>
                  <th className="quote-excel-row-number">{itemStartRow + itemIndex}</th>
                  {columns.map((column) => <td key={`${item.id}-${column.key}`} title={column.field ? previewValue(effectiveItem(item), column.field, locale) : column.customFieldId ? customFields.find((field) => field.id === column.customFieldId)?.values[item.id] ?? "" : ""}>{renderExcelPreviewCell(item, column)}</td>)}
                </tr>
              ))}
              {[{ label: quoteText(locale, "total"), value: previewTotal }].map((row, index) => (
                <tr className="quote-excel-total-row" key={row.label}>
                  <th className="quote-excel-row-number">{totalRow + index}</th>
                  {columns.length > 1 ? <td colSpan={columns.length - 1}>{row.label}</td> : null}
                  <td>{money(row.value, draft.currency)}</td>
                </tr>
              ))}
              {extraRows.map((entry, index) => (
                <tr className="quote-excel-extra-row" key={`${entry.title}-${index}`}>
                  <th className="quote-excel-row-number">{totalRow + index + 1}</th>
                  <td colSpan={columns.length}><strong>{entry.title}</strong><span>{entry.content}</span></td>
                </tr>
              ))}
              {draft.notes ? (
                <tr className="quote-excel-notes-row">
                  <th className="quote-excel-row-number">{totalRow + extraRows.length + 1}</th>
                  <td colSpan={columns.length}><strong>{quoteText(locale, "notes")}</strong><span>{draft.notes}</span></td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <div className="quote-excel-sheet-tabs">
          <button type="button" className="is-active"><FileXls />{sheetName}</button>
          <span>{t("{count} 个商品 · {columns} 列", { count: draft.items.length, columns: columns.length })}</span>
        </div>
      </div>
    );
  };

  const renderOrderItemsEditor = () => {
    if (!draft) return null;
    return (
      <section className="quote-editor-items" aria-label={t("订单商品")}>
        <div className="quote-editor-items-heading">
          <div>
            <Text size="2" weight="medium">{t("订单商品")}</Text>
            <Text size="1" color="gray">{t("报价单商品")}</Text>
          </div>
          <div className="quote-editor-items-heading-actions">
            <Badge color="gray">{draft.items.length}</Badge>
            {canEditPrices ? <Button size="1" variant="soft" onClick={() => setItemPickerOpen(true)}><Plus />{t("添加商品")}</Button> : null}
          </div>
        </div>
        {renderCustomFieldManager()}
        <div className="quote-editor-item-list">
          {draft.items.map((sourceItem) => {
            const item = effectiveItem(sourceItem);
            const edit = itemEdits[sourceItem.id] ?? {};
            const name = edit.name ?? item.name;
            const description = edit.description ?? item.description ?? "";
            const specification = edit.specification ?? item.specification ?? optionValue(item, quoteOptionAliases.specification, locale);
            const category = edit.category ?? item.category ?? "";
            const unitCode = edit.unitCode ?? item.unitCode;
            const quantity = edit.quantity ?? String(item.quantity);
            const price = priceDrafts[item.id] ?? item.unitPrice.toFixed(2);
            return (
              <Card className="quote-editor-item" key={item.id}>
                <button type="button" className="quote-editor-item-summary" onClick={() => void openItemDetails(sourceItem)} aria-label={t("查看商品详情") }>
                  {item.imageUrl ? <img src={item.imageUrl} alt="" loading="lazy" /> : <span className="quote-item-image-placeholder"><ImageSquare size={21} /></span>}
                  <span className="quote-editor-item-summary-copy">
                    <strong title={name}>{name}</strong>
                    <span className="mono-text" title={item.skuCode}>{item.skuCode}</span>
                    <span>{t("第 {position} 项", { position: item.position })}</span>
                    {item.customerNote ? <span className="quote-editor-item-customer-note" title={item.customerNote}>{t("客户商品备注")}：{item.customerNote}</span> : null}
                  </span>
                  <Info className="quote-editor-item-summary-icon" size={17} aria-hidden="true" />
                </button>
                {item.customerNote ? <div className="quote-customer-item-note"><Text size="1" color="amber">{t("客户商品备注")}</Text><Text size="1">{item.customerNote}</Text></div> : null}
                <div className="quote-editor-item-fields">
                  <label className="quote-editor-item-field quote-editor-item-field--wide">
                    <Text size="1" color="gray">{t("商品名称")}</Text>
                    <TextField.Root value={name} disabled={!canEditPrices} aria-label={t("商品名称")} onChange={(event) => updateItemEdit(item.id, "name", event.target.value)} />
                  </label>
                  <label className="quote-editor-item-field">
                    <Text size="1" color="gray">{t("数量")}</Text>
                    <TextField.Root type="number" min={optionPackingQuantity(item.optionValues) || "0.000001"} step={optionPackingQuantity(item.optionValues) || "0.000001"} value={quantity} disabled={!canEditPrices} aria-label={t("数量")} onChange={(event) => updateItemEdit(item.id, "quantity", event.target.value)} />
                    {optionPackingQuantity(item.optionValues) ? <Text size="1" color="gray">{quoteFieldLabel(locale, "packing_quantity")} × {previewValue(item, "packing_quantity", locale)} · {quoteFieldLabel(locale, "carton_count")} × {previewValue(item, "carton_count", locale)}</Text> : null}
                  </label>
                  <label className="quote-editor-item-field">
                    <Text size="1" color="gray">{t("单位")}</Text>
                    <TextField.Root value={unitCode} disabled={!canEditPrices} aria-label={t("单位")} onChange={(event) => updateItemEdit(item.id, "unitCode", event.target.value)} />
                  </label>
                  <label className="quote-editor-item-field">
                    <Text size="1" color="gray">{t("单价")}</Text>
                    <TextField.Root type="number" min="0" step="0.01" value={price} disabled={!canEditPrices} aria-label={t("单价")} onChange={(event) => updateItemEdit(item.id, "unitPrice", event.target.value)}><TextField.Slot side="left">{item.currency}</TextField.Slot></TextField.Root>
                  </label>
                  <div className="quote-editor-item-field quote-editor-item-subtotal">
                    <Text size="1" color="gray">{t("小计")}</Text>
                    <strong>{money(item.lineTotal, item.currency)}</strong>
                  </div>
                  <label className="quote-editor-item-field quote-editor-item-field--wide">
                    <Text size="1" color="gray">{t("商品描述")}</Text>
                    <textarea className="quote-editor-textarea" rows={2} value={description} disabled={!canEditPrices} aria-label={t("商品描述")} onChange={(event) => updateItemEdit(item.id, "description", event.target.value)} />
                  </label>
                  <label className="quote-editor-item-field quote-editor-item-field--wide">
                    <Text size="1" color="gray">{t("商品规格")}</Text>
                    <textarea className="quote-editor-textarea" rows={2} value={specification} disabled={!canEditPrices} aria-label={t("商品规格")} onChange={(event) => updateItemEdit(item.id, "specification", event.target.value)} />
                  </label>
                  <label className="quote-editor-item-field">
                    <Text size="1" color="gray">{t("商品分类")}</Text>
                    <TextField.Root value={category} disabled={!canEditPrices} aria-label={t("商品分类")} onChange={(event) => updateItemEdit(item.id, "category", event.target.value)} />
                  </label>
                  {customFields.map((field) => <label className="quote-editor-item-field" key={field.id}>
                    <Text size="1" color="gray">{field.label || t("未命名字段")}</Text>
                    <TextField.Root value={field.values[item.id] ?? ""} maxLength={2000} disabled={!canEditPrices} aria-label={field.label || t("未命名字段")} onChange={(event) => updateCustomFieldValue(field.id, item.id, event.target.value)} />
                  </label>)}
                  <div className="quote-editor-item-actions">
                    <Button size="1" variant="soft" color="amber" disabled={!canEditPrices || savingItemId === item.id || syncingItemId === item.id} loading={syncingItemId === item.id} onClick={() => requestItemPriceSync(item)}>{t("同步商品库")}</Button>
                    <Button size="1" variant="soft" color="red" disabled={!canEditPrices || Boolean(itemMutationId)} onClick={() => setRemoveItem(sourceItem)}><Trash />{t("移除")}</Button>
                  </div>
                </div>
              </Card>
            );
          })}
          {!draft.items.length ? <div className="quote-editor-items-empty"><ClipboardText size={24} /><Text size="2" color="gray">{t("报价单中暂无商品")}</Text><Button size="2" onClick={() => setItemPickerOpen(true)}><Plus />{t("添加商品")}</Button></div> : null}
        </div>
      </section>
    );
  };

  const renderCustomerRequest = () => {
    if (!draft) return null;
    return (
      <section className="quote-editor-customer-request" aria-label={t("客户填写信息")}>
        <div className="quote-editor-items-heading">
          <div><Text size="2" weight="medium">{t("客户填写信息")}</Text><Text size="1" color="gray">{draft.customerCompany || draft.customerName}</Text></div>
        </div>
        <div className="quote-customer-request-grid">
          <div><span>{t("联系人")}</span><strong>{draft.customerName}</strong></div>
          <div><span>{t("公司名称")}</span><strong>{draft.customerCompany || "—"}</strong></div>
          <div><span>{t("客户邮箱")}</span><strong>{draft.customerEmail || "—"}</strong></div>
          <div><span>{t("联系电话")}</span><strong>{draft.customerPhone || "—"}</strong></div>
          {draft.visitorCountryCode ? <div><span>{t("客户国家")}</span><strong>{draft.visitorCountryCode}</strong></div> : null}
        </div>
        {draft.notes ? <div className="quote-customer-order-note"><Text size="1" color="gray">{t("整单备注")}</Text><Text size="2">{draft.notes}</Text></div> : null}
      </section>
    );
  };

  const updateProformaInvoice = (patch: Partial<ProformaInvoiceSettings>) => {
    setProformaInvoice((current) => ({ ...current, ...patch }));
  };

  const renderQuoteToolbar = () => {
    if (!draft) return null;
    return (
      <section className="quote-workbench-toolbar" aria-label={t("报价单设置")}>
      <div className="quote-workbench-fields">
        <div className="quote-workbench-number">
          <Text size="1" color="gray">{activeDocument === "proforma" ? proformaText(locale, "invoice_number") : t("报价单 ID / 编号")}</Text>
          <div className="quote-number-control"><TextField.Root value={activeDocument === "proforma" ? proformaInvoice.invoiceNumber : quoteNumber} onChange={(event) => activeDocument === "proforma" ? updateProformaInvoice({ invoiceNumber: event.target.value }) : setQuoteNumber(event.target.value)} maxLength={80} disabled={isReadOnly} /></div>
        </div>
        {activeDocument === "quotation" ? <label className="quote-workbench-select"><Text size="1" color="gray">{t("商家报价模板")}</Text><Select.Root value={templateId || "default"} onValueChange={changeTemplate} disabled={isReadOnly}><Select.Trigger /><Select.Content position="popper"><Select.Item value="default">{t("系统默认模板")}</Select.Item>{readyTemplates.filter((template) => !template.isDefault).map((template) => <Select.Item key={template.id} value={template.id}>{template.name}</Select.Item>)}</Select.Content></Select.Root></label> : null}
        <div className="quote-workbench-select">
          <Text size="1" color="gray"><Columns />{t("商品表格列")}</Text>
          <DropdownMenu.Root>
            <DropdownMenu.Trigger>
              <Button variant="soft" color="gray" className="quote-column-trigger" disabled={isReadOnly}><Columns />{t("已选 {count}/{max} 列", { count: activeColumns.length, max: MAX_PDF_COLUMNS })}<CaretDown /></Button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Content align="start" className="quote-column-menu">
              <DropdownMenu.Label>{t("选择 PDF 显示列，最多 {count} 列", { count: MAX_PDF_COLUMNS })}</DropdownMenu.Label>
              {availableColumns.map((field) => {
                const selected = visibleColumns.includes(field);
                return <DropdownMenu.CheckboxItem key={field} checked={selected} disabled={!selected && activeColumns.length >= MAX_PDF_COLUMNS} onCheckedChange={(checked) => toggleColumn(field, checked)} onSelect={(event) => event.preventDefault()}><span>{fieldLabel(field, t, selectedTemplate, locale)}</span>{selected ? <Check /> : null}</DropdownMenu.CheckboxItem>;
              })}
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </div>
        <label className="quote-workbench-select"><Text size="1" color="gray"><Palette />{t("PDF 样式")}</Text><Select.Root value={style} onValueChange={(value) => setStyle(value as QuoteDocumentStyle)} disabled={isReadOnly}><Select.Trigger /><Select.Content position="popper">{styles.map((option) => <Select.Item key={option.value} value={option.value}><span className="quote-style-swatch" style={{ backgroundColor: option.color }} aria-hidden="true" />{t(option.label)}</Select.Item>)}</Select.Content></Select.Root></label>
        <label className="quote-workbench-select"><Text size="1" color="gray">{t("报价语言")}</Text><Select.Root value={locale} onValueChange={(value) => void changeDocumentLocale(value)} disabled={localeSelectionDisabled}><Select.Trigger>{localeLabel(locale)}</Select.Trigger><Select.Content position="popper">{localeOptions.map((option) => <Select.Item key={option.value} value={option.value}>{localeLabel(option.value)}</Select.Item>)}</Select.Content></Select.Root></label>
      </div>
      <div className="quote-workbench-actions">
        <Button variant="soft" color="blue" disabled={!canOpenCurrencyConversion || hasPendingItemEdits || converting} loading={converting} onClick={openCurrencyConversion}><CurrencyDollar />{t("币种")} · {normalizedCurrency(draft.currency)}</Button>
        <Button variant="soft" disabled={!canEditPrices || bulkSaving} onClick={() => setBulkPriceOpen(true)}><SlidersHorizontal />{t("一键调价")}</Button>
        <Text size="1" color="gray" className="quote-autosave-status" aria-live="polite">{saveStatusText}</Text>
        <Button color="blue" disabled={!canEditPrices || saving || savingItems} loading={saving} onClick={() => void save()}><FloppyDisk />{activeDocument === "proforma" ? t("保存") : t("保存报价单")}</Button>
      </div>
      </section>
    );
  };

  const renderEditorPanel = () => (
    <Card className="quote-editor-panel">
      <div className="quote-editor-panel-heading">
        <div>
          <Text size="1" color="gray">{activeDocument === "proforma" ? "PI" : t("报价单设置")}</Text>
          <Heading size="4">{activeDocument === "proforma" ? t("形式发票") : t("编辑报价单")}</Heading>
        </div>
        <Badge color={documentSaveState === "FAILED" ? "red" : documentSaveState === "SAVED" ? "jade" : "amber"}>{saveStatusText}</Badge>
      </div>
      {renderQuoteToolbar()}
      {renderCustomerRequest()}
      {renderOrderItemsEditor()}
      {activeDocument === "quotation" ? <section className="quote-editor-extra">
        <div className="quote-editor-extra-heading"><div><Text size="2" weight="medium">{t("额外信息")}</Text><Text size="1" color="gray">{t("显示在整张报价单的商品列表下方")}</Text></div><Button size="1" variant="soft" color="blue" disabled={isReadOnly || extraInformation.length >= 20} onClick={addExtraInformation}>＋ {t("添加")}</Button></div>
        {extraInformation.map((entry, index) => (
          <div className={`quote-extra-row ${collapsedExtraRows[index] ? "is-collapsed" : ""}`} key={`extra-${index}`}>
            <div className="quote-extra-row-header">
              <button type="button" className="quote-extra-row-toggle" aria-label={collapsedExtraRows[index] ? t("展开") : t("收起")} aria-expanded={!collapsedExtraRows[index]} onClick={() => toggleExtraInformation(index)}>
                <CaretDown className={collapsedExtraRows[index] ? "" : "is-open"} aria-hidden="true" />
              </button>
              <TextField.Root className="quote-extra-title-input" placeholder={t("标题，例如 Deliver")} value={entry.title} disabled={isReadOnly} aria-label={t("额外信息标题")} onChange={(event) => updateExtraInformation(index, "title", event.target.value)} />
              <IconButton size="1" variant="soft" color="red" disabled={isReadOnly} aria-label={t("删除额外信息")} onClick={() => removeExtraInformation(index)}><X size={15} /></IconButton>
            </div>
            {!collapsedExtraRows[index] ? (
              <div className="quote-extra-row-content">
                <textarea className="quote-editor-textarea" rows={2} placeholder={t("内容，例如 7 Days after receipt of deposit")} value={entry.content} disabled={isReadOnly} aria-label={t("额外信息内容")} onChange={(event) => updateExtraInformation(index, "content", event.target.value)} />
              </div>
            ) : null}
          </div>
        ))}
      </section> : null}
    </Card>
  );

  const renderManual = () => (
    <aside className={`quote-workbench-manual ${manualOpen ? "" : "is-collapsed"}`}>
      <button type="button" className="quote-manual-toggle" onClick={() => setManualOpen((open) => !open)} aria-expanded={manualOpen}>
        <span><BookOpen size={18} />{t("使用手册")}</span><CaretDown className={manualOpen ? "is-open" : ""} />
      </button>
      {manualOpen ? (
        <div className="quote-manual-content">
          <Text size="2" weight="medium">{activeDocument === "proforma" ? proformaText(locale, "title") : t("报价单工作台")}</Text>
          {activeDocument === "proforma" ? (
            <ul>
              <li>{proformaText(locale, "seller")} · {proformaText(locale, "buyer")} · {proformaText(locale, "invoice_number")}</li>
              <li>{proformaText(locale, "trade_terms")} · {proformaText(locale, "payment_terms")} · {proformaText(locale, "delivery_terms")}</li>
              <li>{proformaText(locale, "bank_details")} · {proformaText(locale, "freight")} · {proformaText(locale, "remarks")}</li>
              <li>{t("中间可切换 PDF 与 Excel 预览，变更会同步并自动保存。")}</li>
              <li>{t("商品表格列可在左侧设置，空值会保留为空。")}</li>
            </ul>
          ) : (
            <ul>
              <li>{t("左侧设置报价单编号、模板、可见列、语言和样式。")}</li>
              <li>{t("左侧订单商品可直接编辑，点击条目摘要可查看商品资料。")}</li>
              <li>{t("中间可切换 PDF 与 Excel 预览，变更会同步并自动保存。")}</li>
              <li>{t("商品表格列可在左侧设置，空值会保留为空。")}</li>
              <li>{t("额外信息会显示在整张商品列表下方。")}</li>
              <li>{t("完成后可导出 PDF 或 Excel，或通过并通知客户。")}</li>
            </ul>
          )}
        </div>
      ) : null}
    </aside>
  );

  if (loading) return <div className="core-workspace"><CoreLoading label={t("正在打开报价工作台")} /></div>;
  if (error && !draft) return <div className="core-workspace"><CoreError message={error} onRetry={() => void load()} /></div>;
  if (!draft) return null;

  const selectedStyle = styles.find((row) => row.value === style) ?? styles[0];

  const activeDocumentExportable = activeDocument === "quotation" || activeDocument === "proforma" || (activeDocument === "packing-list" && Boolean(packingList));

  return <div className={`core-workspace quote-workbench quote-workbench--${style}`}>
    <Tabs.Root value={activeDocument} onValueChange={(value) => setActiveDocument(value as QuoteDocumentTab)} className="quote-doc-tabs">
      <div className="quote-workbench-header">
        <Tabs.List className="quote-workbench-document-tabs">
          <Tabs.Trigger value="quotation"><FileText />{t("报价单")}</Tabs.Trigger>
          {canUseExtendedDocuments ? <>
            <Tabs.Trigger value="proforma"><FileText />{t("形式发票")}（PI）</Tabs.Trigger>
            <Tabs.Trigger value="sales-contract"><LockKey />{t("销售合同")}</Tabs.Trigger>
            <Tabs.Trigger value="commercial-invoice"><LockKey />{t("商业发票")}（CI）</Tabs.Trigger>
            <Tabs.Trigger value="packing-list"><FileText />{t("装箱单")}</Tabs.Trigger>
            {canUsePurchaseOrder ? <Tabs.Trigger value="purchase-order"><FileXls />{t("采购单")}</Tabs.Trigger> : null}
            <Tabs.Trigger value="customs-declaration"><LockKey />{t("报关单")}</Tabs.Trigger>
          </> : null}
        </Tabs.List>
        <div className="quote-workbench-header-actions">
          {activeDocument !== "packing-list" && activeDocument !== "proforma" && activeDocument !== "purchase-order" ? <DropdownMenu.Root>
            <DropdownMenu.Trigger><Button variant="soft" disabled={!activeDocumentExportable} loading={Boolean(downloading)}><DownloadSimple />{t("导出")}{downloading ? ` ${downloading.toUpperCase()}` : ""}<CaretDown /></Button></DropdownMenu.Trigger>
            <DropdownMenu.Content align="end"><DropdownMenu.Item disabled={!activeDocumentExportable || Boolean(downloading)} onSelect={() => void download("pdf")}><FilePdf />{t("导出为 PDF")}</DropdownMenu.Item><DropdownMenu.Item disabled={!activeDocumentExportable || Boolean(downloading)} onSelect={() => void download("xlsx")}><FileXls />{t("导出为 Excel")}</DropdownMenu.Item></DropdownMenu.Content>
          </DropdownMenu.Root> : null}
          {activeDocument === "quotation" && draft.status === "PENDING_CONFIRMATION" && !isReadOnly ? <Button color="green" disabled={confirming || saving || savingItems} loading={confirming} onClick={() => void confirm()}><PaperPlaneTilt />{t("通过并通知客户")}</Button> : null}
          {draft.status === "CONFIRMED" && !isReadOnly ? <Button color="green" disabled={Boolean(statusUpdating)} loading={statusUpdating === "COMPLETED"} onClick={() => void updateStatus("COMPLETED")}><CheckCircle />{t("标记为已成交")}</Button> : null}
          {(draft.status === "PENDING_CONFIRMATION" || draft.status === "CONFIRMED") && !isReadOnly ? <Button variant="soft" color="red" disabled={confirming || Boolean(statusUpdating)} onClick={() => setCancelOpen(true)}><XCircle />{t("取消询价")}</Button> : null}
          <Button asChild variant="soft" color="gray"><Link to="/console/quotes"><ArrowLeft />{t("返回询价列表")}</Link></Button>
        </div>
      </div>
      {error ? <ToastNotice kind="error" message={error} /> : null}

    <div className={`quote-workbench-grid${activeDocument === "packing-list" || activeDocument === "proforma" || activeDocument === "purchase-order" ? " quote-workbench-grid--packing" : ""}`}>
      {activeDocument !== "packing-list" && activeDocument !== "proforma" && activeDocument !== "purchase-order" ? renderEditorPanel() : null}
      <section className="quote-workbench-main">

    <Card className="quote-status-card">
      <div className="quote-status-main"><Text size="1" color="gray">{t("当前订单状态")}</Text><Badge color={draft.status === "CONFIRMED" || draft.status === "COMPLETED" ? "jade" : draft.status === "CANCELLED" ? "gray" : "amber"}>{t(draft.status)}</Badge></div>
      <div className="quote-status-meta"><span>{t("客户")}: {draft.customerCompany || draft.customerName}</span><span>{t("更新时间")}: {coreDate(draft.updatedAt)}</span><span>{t("有效期")}: {coreDate(draft.validUntil)}</span>{draft.visitorCountryCode ? <span>{t("客户国家")}: {draft.visitorCountryCode}</span> : null}</div>
    </Card>
    {isReadOnly ? <Card className="quote-readonly-notice"><ShieldCheck size={19} /><div><Text size="2" weight="medium">{t("当前为只读查看")}</Text><Text size="1" color="gray">{t("这是子账号提交的询价单，只能由提交该询价的子账号制作、确认和处理。")}</Text></div></Card> : null}

    <AlertDialog.Root open={cancelOpen} onOpenChange={(open) => { if (!statusUpdating) setCancelOpen(open); }}>
      <AlertDialog.Content maxWidth="460px">
        <AlertDialog.Title>{t("取消这条询价？")}</AlertDialog.Title>
        <AlertDialog.Description size="2">{t("取消后这条询价将不能继续修改、确认或标记成交。")}</AlertDialog.Description>
        <div className="quote-sync-confirm-actions">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray" disabled={Boolean(statusUpdating)}>{t("返回")}</Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button color="red" loading={statusUpdating === "CANCELLED"} onClick={() => void updateStatus("CANCELLED")}><XCircle />{t("确认取消")}</Button>
          </AlertDialog.Action>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>

    <AlertDialog.Root open={conversionOpen} onOpenChange={(open) => { if (!converting) setConversionOpen(open); }}>
      <AlertDialog.Content maxWidth="520px" className="quote-currency-dialog">
        <AlertDialog.Title>{t("切换报价币种")}</AlertDialog.Title>
        <AlertDialog.Description size="2">{t("只换算本报价单的单价和合计，不会修改商品库价格。")}</AlertDialog.Description>
        <div className="quote-currency-converter">
          <div className="quote-currency-current">
            <Text size="1" color="gray">{t("当前币种")}</Text>
            <strong>{normalizedCurrency(draft.currency)}</strong>
          </div>
          <span className="quote-currency-arrow" aria-hidden="true">→</span>
          <label className="quote-currency-target">
            <Text size="1" color="gray">{t("目标币种")}</Text>
            <Select.Root value={targetCurrency} onValueChange={setTargetCurrency} disabled={converting}>
              <Select.Trigger aria-label={t("目标币种")} />
              <Select.Content position="popper">
                {currencyOptions.filter((option) => option.currency !== normalizedCurrency(draft.currency)).map((option) => (
                  <Select.Item key={option.currency} value={option.currency}>{option.symbol} {option.currency} · {option.name}</Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </label>
        </div>
        <div className="quote-currency-summary" aria-live="polite">
          {conversionRate ? (
            <>
              <div><span>{t("参考汇率")}</span><strong>1 {normalizedCurrency(draft.currency)} = {conversionRateLabel} {normalizedCurrency(targetCurrency)}</strong></div>
              <div><span>{t("换算后预计合计")}</span><strong>{money(previewTotal * conversionRate, normalizedCurrency(targetCurrency))}</strong></div>
            </>
          ) : <Text size="2" color="red">{t("暂时无法取得当前汇率，请稍后重试。")}</Text>}
        </div>
        <div className="quote-sync-confirm-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={converting}>{t("取消")}</Button></AlertDialog.Cancel>
          <AlertDialog.Action><Button color="blue" disabled={!canConvertCurrency || hasPendingItemEdits || converting} loading={converting} onClick={() => void convertCurrency()}>{t("确认换算")}</Button></AlertDialog.Action>
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

    <Dialog.Root open={itemPickerOpen} onOpenChange={(open) => {
      if (itemMutationId) return;
      setItemPickerOpen(open);
      if (!open) setItemPickerError("");
    }}>
      <Dialog.Content className="quote-item-picker-dialog" maxWidth="880px">
        <div className="quote-item-picker-heading">
          <div><Dialog.Title>{t("添加商品")}</Dialog.Title><Dialog.Description>{t("从当前账号可见的已发布 SKU 中选择")}</Dialog.Description></div>
          <Dialog.Close><IconButton variant="ghost" color="gray" aria-label={t("关闭")}><X /></IconButton></Dialog.Close>
        </div>
        <TextField.Root
          value={itemPickerQuery}
          placeholder={t("搜索商品名称或 SKU 编码")}
          onChange={(event) => { setItemPickerQuery(event.target.value); setItemPickerPage(1); }}
          autoFocus
        >
          <TextField.Slot><MagnifyingGlassPlus /></TextField.Slot>
        </TextField.Root>
        {itemPickerError ? <div className="core-form-error" role="alert">{itemPickerError}</div> : null}
        <div className="quote-item-picker-list" aria-busy={itemPickerLoading}>
          {itemPickerLoading ? <CoreLoading label={t("正在读取商品库")} /> : itemPickerRows.map((candidate) => {
            const alreadyAdded = Boolean(draft?.items.some((item) => item.skuId === candidate.id));
            const price = candidate.publicPrice;
            const quantity = itemPickerQuantities[candidate.id] ?? "1";
            return <div className="quote-item-picker-row" key={candidate.id}>
              {candidate.thumbnailUrl ? <img src={candidate.thumbnailUrl} alt="" loading="lazy" /> : <span className="quote-item-image-placeholder"><ImageSquare /></span>}
              <div className="quote-item-picker-copy">
                <strong>{candidate.productName}</strong>
                <span>{candidate.name !== candidate.productName ? candidate.name : ""}</span>
                <small className="mono-text">{candidate.skuCode}</small>
              </div>
              <div className="quote-item-picker-price">
                <Text size="1" color="gray">{t("当前售价")}</Text>
                <strong>{price == null ? "—" : money(price, candidate.publicCurrency || draft?.currency || "CNY")}</strong>
              </div>
              <label className="quote-item-picker-quantity">
                <Text size="1" color="gray">{t("数量")}</Text>
                <TextField.Root
                  type="number"
                  min={candidate.packingQuantity || "0.000001"}
                  step={candidate.packingQuantity || "0.000001"}
                  value={quantity}
                  disabled={alreadyAdded || itemMutationId === candidate.id}
                  onChange={(event) => setItemPickerQuantities((current) => ({ ...current, [candidate.id]: event.target.value }))}
                />
                {candidate.packingQuantity ? <small>{t("装箱数")} × {candidate.packingQuantity}</small> : null}
              </label>
              <Button
                size="2"
                variant={alreadyAdded ? "soft" : "solid"}
                color={alreadyAdded ? "gray" : "blue"}
                disabled={alreadyAdded || Boolean(itemMutationId) || price == null}
                loading={itemMutationId === candidate.id}
                onClick={() => void addQuoteItem(candidate)}
              >{alreadyAdded ? <><Check />{t("已添加")}</> : <><Plus />{t("添加")}</>}</Button>
            </div>;
          })}
          {!itemPickerLoading && !itemPickerRows.length ? <div className="quote-item-picker-empty"><ImageSquare size={24} /><Text size="2" color="gray">{t("没有找到可添加的已发布 SKU")}</Text></div> : null}
        </div>
        {itemPickerPages > 1 ? <div className="quote-item-picker-pagination">
          <Button size="1" variant="soft" disabled={itemPickerPage <= 1 || itemPickerLoading} onClick={() => setItemPickerPage((page) => Math.max(1, page - 1))}>{t("上一页")}</Button>
          <Text size="1" color="gray">{t("第 {page} / {pages} 页", { page: itemPickerPage, pages: itemPickerPages })}</Text>
          <Button size="1" variant="soft" disabled={itemPickerPage >= itemPickerPages || itemPickerLoading} onClick={() => setItemPickerPage((page) => Math.min(itemPickerPages, page + 1))}>{t("下一页")}</Button>
        </div> : null}
      </Dialog.Content>
    </Dialog.Root>

    <AlertDialog.Root open={Boolean(removeItem)} onOpenChange={(open) => { if (!open && !itemMutationId) setRemoveItem(undefined); }}>
      <AlertDialog.Content maxWidth="460px">
        <AlertDialog.Title>{t("从报价单移除商品")}</AlertDialog.Title>
        <AlertDialog.Description size="2">{removeItem ? t("确认移除 {name}？保存后，预览和导出文件会同步更新。", { name: removeItem.name }) : ""}</AlertDialog.Description>
        <div className="quote-sync-confirm-actions">
          <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={Boolean(itemMutationId)}>{t("取消")}</Button></AlertDialog.Cancel>
          <Button color="red" disabled={!removeItem || Boolean(itemMutationId)} loading={itemMutationId === removeItem?.id} onClick={() => void deleteQuoteItem()}><Trash />{t("确认移除")}</Button>
        </div>
      </AlertDialog.Content>
    </AlertDialog.Root>

    <Dialog.Root open={itemsDrawerOpen} onOpenChange={(open) => { setItemsDrawerOpen(open); if (!open) { setSelectedItemId(undefined); setItemImagePreview(undefined); } }}>
      <Dialog.Content className="quote-item-detail-dialog" aria-describedby="quote-items-drawer-description">
        <div className="quote-items-drawer-header">
          <div>
            <Text size="1" color="gray">{t("商品详情")}</Text>
            <Dialog.Title>{selectedDrawerItem?.name ?? t("正在读取商品详情…")}</Dialog.Title>
            <Dialog.Description id="quote-items-drawer-description">
              {t("查看商品快照、实时资料和本次报价信息。")}
            </Dialog.Description>
          </div>
          <div className="quote-items-drawer-header-actions">
            <Dialog.Close><IconButton variant="ghost" color="gray" aria-label={t("关闭订单商品")}><X size={19} /></IconButton></Dialog.Close>
          </div>
        </div>

        {selectedDrawerItem ? (
          <div className="quote-item-detail-scroll quote-item-detail">
            <div className="quote-item-detail-hero">
              {selectedDetailImageUrl ? (
                <button
                  type="button"
                  className="quote-item-detail-image-trigger"
                  aria-label={t("查看大图")}
                  onClick={() => setItemImagePreview({ src: selectedDetailImageUrl, alt: selectedDrawerItem.name })}
                >
                  <img src={selectedDetailImageUrl} alt={selectedDrawerItem.name} />
                  <span className="quote-item-detail-image-affordance" aria-hidden="true"><MagnifyingGlassPlus weight="bold" /><span>{t("查看大图")}</span></span>
                </button>
              ) : <span className="quote-item-image-placeholder"><ImageSquare size={32} /></span>}
              <div className="quote-item-detail-title">
                <Heading size="4">{selectedDrawerItem.name}</Heading>
                <Text size="1" color="gray" className="mono-text">{selectedDrawerItem.skuCode}</Text>
                {selectedDrawerItem.category ? <Badge color="gray">{selectedDrawerItem.category}</Badge> : null}
              </div>
            </div>
            <div className="quote-item-detail-grid">
              <div><Text size="1" color="gray">{t("商品编码")}</Text><strong className="mono-text">{selectedDrawerItem.skuCode}</strong></div>
              <div><Text size="1" color="gray">{t("数量")}</Text><strong>{selectedDrawerItem.quantity} {quoteUnit(locale, selectedDrawerItem.unitCode)}</strong></div>
              <div><Text size="1" color="gray">{t("本次单价")}</Text><strong>{money(selectedDrawerItem.unitPrice, selectedDrawerItem.currency)}</strong></div>
              <div><Text size="1" color="gray">{t("小计")}</Text><strong className="quote-item-price-total">{money(selectedDrawerItem.lineTotal, selectedDrawerItem.currency)}</strong></div>
              <div><Text size="1" color="gray">{t("版本")}</Text><strong>v{selectedDrawerItem.productVersion} · SKU v{selectedDrawerItem.skuVersion}</strong></div>
            </div>
            {selectedDrawerItem.description ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品描述")}</Text><Text as="p">{selectedDrawerItem.description}</Text></div> : null}
            {selectedDrawerItem.customerNote ? <div className="quote-item-detail-section quote-item-detail-customer-note"><Text size="1" color="amber">{t("客户商品备注")}</Text><Text as="p">{selectedDrawerItem.customerNote}</Text></div> : null}
            {selectedDrawerItem.specification ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品规格")}</Text><Text as="p">{selectedDrawerItem.specification}</Text></div> : null}
            {selectedDrawerItem.tags.length ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("商品标签")}</Text><div className="quote-item-tags">{selectedDrawerItem.tags.map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</div></div> : null}
            {Object.entries(selectedDrawerItem.optionValues).filter(([key]) => !key.startsWith("_")).length ? <div className="quote-item-detail-section"><Text size="1" color="gray">{t("规格参数")}</Text><div className="quote-item-options">{Object.entries(selectedDrawerItem.optionValues).filter(([key]) => !key.startsWith("_")).map(([key, value]) => <div key={key}><span>{key}</span><strong>{displayOptionValue(value, quoteSeparator(locale))}</strong></div>)}</div></div> : null}
            {detailLoadingId === selectedDrawerItem.productId ? <Text size="1" color="gray">{t("正在读取商品详情…")}</Text> : null}
            {selectedProductDetail ? (
              <Card className="quote-live-product-card">
                <div className="quote-live-product-heading"><Info size={17} /><Text size="2" weight="medium">{t("商品库实时资料")}</Text></div>
                <div className="quote-live-image-manager">
                  <div className="quote-live-image-manager-heading">
                    <div><Text size="1" color="gray">{t("商品图片")}</Text><strong>{t("{count} 张", { count: selectedProductDetail.images.length })}</strong></div>
                    {canManageCatalogImages ? (
                      <div className="quote-live-image-actions">
                        <Button size="1" variant="soft" disabled={Boolean(imageManaging) || selectedProductDetail.images.length >= 50} loading={imageManaging === "upload"} onClick={() => workbenchImageInputRef.current?.click()}><Plus />{t("新增图片")}</Button>
                        {selectedLiveProductImage ? <Button size="1" variant="soft" color="red" disabled={Boolean(imageManaging)} loading={imageManaging === "delete"} onClick={() => void removeWorkbenchProductImage(selectedLiveProductImage.id)}><Trash />{t("删除")}</Button> : null}
                      </div>
                    ) : null}
                  </div>
                  {selectedProductDetail.images.length ? (
                    <div className="quote-live-image-gallery" aria-label={t("商品图片列表")}>
                      {selectedProductDetail.images.map((image, index) => (
                        <button
                          key={image.id}
                          type="button"
                          className={image.id === selectedLiveProductImage?.id ? "is-active" : ""}
                          aria-label={t("查看图片 {index}", { index: index + 1 })}
                          aria-pressed={image.id === selectedLiveProductImage?.id}
                          onClick={() => setManagedImageId(image.id)}
                        >
                          <img src={image.url} alt="" />
                          {image.imageRole === "MAIN" ? <span>{t("主图")}</span> : null}
                        </button>
                      ))}
                    </div>
                  ) : <Text size="1" color="gray">{t("暂未上传商品图片")}</Text>}
                  <input ref={workbenchImageInputRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(event) => void addWorkbenchProductImage(event.target.files?.[0])} />
                  {imageManagementError ? <div className="core-form-error" role="alert">{imageManagementError}</div> : null}
                </div>
                <div className="quote-live-product-grid">
                  <div><Text size="1" color="gray">{t("商品名称")}</Text><strong>{selectedProductDetail.name}</strong></div>
                  <div><Text size="1" color="gray">{t("商品编码")}</Text><strong className="mono-text">{selectedProductDetail.productCode || selectedProductDetail.id}</strong></div>
                  <div><Text size="1" color="gray">{t("型号")}</Text><strong>{selectedProductDetail.model || "—"}</strong></div>
                  <div><Text size="1" color="gray">{t("商品分类")}</Text><strong>{selectedProductDetail.category || "—"}</strong></div>
                  <div><Text size="1" color="gray">{t("SKU 数量")}</Text><strong>{selectedProductDetail.skuCount}</strong></div>
                </div>
                {selectedProductDetail.description ? <Text size="2">{selectedProductDetail.description}</Text> : null}
                {selectedLiveSku ? (
                  <div className="quote-live-sku-card">
                    <Text size="1" color="gray">{t("当前 SKU")}</Text>
                    <strong className="mono-text">{selectedLiveSku.skuCode}</strong>
                    {selectedLiveSku.name ? <Text size="1">{selectedLiveSku.name}</Text> : null}
                    {canViewSupplierData && selectedLiveSku.note ? <div className="quote-live-sku-note"><Text size="1" color="gray">{t("备注")}</Text><Text as="p">{selectedLiveSku.note}</Text></div> : null}
                    {Object.keys(selectedLiveSku.optionValues).length ? <Text size="1" color="gray">{Object.entries(selectedLiveSku.optionValues).map(([key, value]) => `${key}: ${String(value)}`).join(quoteSeparator(locale))}</Text> : null}
                  </div>
                ) : null}
                {canViewSupplierData ? <div className="quote-supplier-section">
                  <div className="quote-live-product-heading"><Storefront size={17} /><Text size="2" weight="medium">{t("供应商与采购信息")}</Text></div>
                  {selectedSupplierOffers.length ? <div className="quote-supplier-grid">{selectedSupplierOffers.map((source) => <div className="quote-supplier-card" key={source.supplierProductId}>
                    <div><strong>{source.supplierName}</strong>{source.supplierSku ? <span className="mono-text">{source.supplierSku}</span> : null}</div>
                    <dl>
                      <div><dt>{t("采购价")}</dt><dd>{source.unitPrice == null ? t("未录入") : money(source.unitPrice, source.currency || draft.currency)}</dd></div>
                      <div><dt>{t("交期")}</dt><dd>{source.leadTimeDays == null ? "—" : t("{days} 天", { days: source.leadTimeDays })}</dd></div>
                      <div><dt>{t("价格有效性")}</dt><dd>{t(source.priceValidity)}</dd></div>
                    </dl>
                  </div>)}</div> : <Text size="1" color="gray">{t("当前 SKU 尚未关联供应商。")}</Text>}
                </div> : null}
              </Card>
            ) : null}
          </div>
        ) : <div className="quote-item-detail-empty"><Info size={20} /><Text size="2" color="gray">{t("正在读取商品详情…")}</Text></div>}
      </Dialog.Content>
    </Dialog.Root>

    <Dialog.Root open={Boolean(itemImagePreview)} onOpenChange={(open) => { if (!open) setItemImagePreview(undefined); }}>
      <Dialog.Content className="quote-item-image-preview-dialog">
        <Dialog.Title className="visually-hidden">{itemImagePreview?.alt ?? t("查看大图")}</Dialog.Title>
        <Dialog.Description className="visually-hidden">{t("查看大图")}</Dialog.Description>
        <Dialog.Close>
          <IconButton type="button" className="quote-item-image-preview-close" size="3" variant="soft" color="gray" aria-label={t("关闭图片预览")}>
            <X weight="bold" />
          </IconButton>
        </Dialog.Close>
        <div className="quote-item-image-preview-stage">
          {itemImagePreview ? <img src={itemImagePreview.src} alt={itemImagePreview.alt} /> : null}
        </div>
      </Dialog.Content>
    </Dialog.Root>

    <AlertDialog.Root open={Boolean(syncItem)} onOpenChange={(open) => { if (!open && !syncingItemId) setSyncItem(undefined); }}>
      <AlertDialog.Content maxWidth="460px">
        <AlertDialog.Title>{t("同步商品库价格")}</AlertDialog.Title>
        <AlertDialog.Description size="2">{syncItem ? t("同步后，{name} 的商品库公开价格会改为 {price}。这会影响后续新报价和前台展示，确定继续吗？", { name: syncItem.name, price: money(Number(priceDrafts[syncItem.id] ?? syncItem.unitPrice), syncItem.currency) }) : ""}</AlertDialog.Description>
        <div className="quote-sync-confirm-actions"><AlertDialog.Cancel><Button variant="soft" color="gray" disabled={Boolean(syncingItemId)}>{t("取消")}</Button></AlertDialog.Cancel><AlertDialog.Action><Button color="amber" disabled={!syncItem || Boolean(syncingItemId)} loading={Boolean(syncingItemId)} onClick={() => { if (syncItem) void saveItemPrice(syncItem, true); }}>{t("确认同步")}</Button></AlertDialog.Action></div>
      </AlertDialog.Content>
    </AlertDialog.Root>

      <Tabs.Content value="quotation">
        <div className="quote-preview-mode-toolbar">
          <DocumentPreviewModeSwitch value={previewMode} onChange={setPreviewMode} />
          <Text size="1" color="gray">
            {previewMode === "pdf"
              ? t("PDF 使用已选择的 {count} 列。", { count: activeColumns.length })
              : t("Excel 展示完整字段，并与当前编辑内容同步。")}
          </Text>
        </div>
        {previewMode === "pdf" ? (
        <div className="quote-preview-stage">
          <div
            ref={previewViewportRef}
            className={`quote-preview-viewport${previewDragging ? " is-dragging" : ""}`}
            tabIndex={0}
            aria-label={t("报价单预览，按住拖动查看，使用缩放控件调整大小")}
            onPointerDown={startPreviewPan}
            onPointerMove={movePreviewPan}
            onPointerUp={endPreviewPan}
            onPointerCancel={endPreviewPan}
            onWheel={handlePreviewWheel}
            onKeyDown={handlePreviewKeyDown}
          >
            <div
              className="quote-preview-pan-layer"
              style={{ "--quote-preview-pan-x": `${previewPan.x}px`, "--quote-preview-pan-y": `${previewPan.y}px` } as React.CSSProperties}
            >
              <div ref={previewSheetRef} className="quote-preview-sheet" style={{ "--quote-preview-scale": previewScale / 100 } as React.CSSProperties}>
                <Card className="quote-preview-card" style={{ "--quote-accent": selectedStyle.color } as React.CSSProperties}>
                <div className="quote-preview-header"><div><Heading size="7">{quoteText(locale, "document_title")}</Heading><Text size="2" color="gray">{quoteNumber} · {coreDate(draft.createdAt)}</Text></div></div>
                <div className="quote-preview-meta"><div><span>{quoteText(locale, "customer")}</span><strong>{draft.customerCompany || draft.customerName}</strong></div><div><span>{quoteText(locale, "contact")}</span><strong>{draft.customerName}</strong></div><div><span>{quoteText(locale, "date")}</span><strong>{quoteDateOnly(draft.createdAt)}</strong></div><div><span>{quoteText(locale, "currency")}</span><strong>{draft.currency}</strong></div></div>
                <div className="quote-preview-table">
                  <div className="quote-preview-row quote-preview-head" style={{ gridTemplateColumns: previewGrid }}>{activeColumns.map((field) => <span className="quote-preview-cell" key={field}>{fieldLabel(field, t, selectedTemplate, locale)}</span>)}</div>
                  {draft.items.map((item) => <div className="quote-preview-row" style={{ gridTemplateColumns: previewGrid }} key={item.id}>{activeColumns.map((field) => <span className="quote-preview-cell" key={`${item.id}-${field}`}>{renderPreviewCell(item, field)}</span>)}</div>)}
                  <div className="quote-preview-total"><span>{quoteText(locale, "total")}</span><strong>{money(previewTotal, draft.currency)}</strong></div>
                </div>
                {customFields.some((field) => field.label.trim()) ? <div className="quote-preview-custom-table">
                  <div className="quote-preview-custom-row quote-preview-custom-head"><strong>{quoteText(locale, "product_name")}</strong>{customFields.filter((field) => field.label.trim()).map((field) => <strong key={field.id}>{field.label}</strong>)}</div>
                  {draft.items.map((item) => <div className="quote-preview-custom-row" key={`custom-${item.id}`}><span>{effectiveItem(item).name}</span>{customFields.filter((field) => field.label.trim()).map((field) => <span key={field.id}>{field.values[item.id] || "—"}</span>)}</div>)}
                </div> : null}
                {extraInformation.filter((entry) => entry.title.trim() && entry.content.trim()).length ? (
                  <div className="quote-preview-extra-info">
                    {extraInformation.filter((entry) => entry.title.trim() && entry.content.trim()).map((entry, index) => (
                      <div className="quote-preview-extra-row" key={`${entry.title}-${index}`}><strong>{entry.title}</strong><span>{entry.content}</span></div>
                    ))}
                  </div>
                ) : null}
                {draft.notes ? <Card className="quote-preview-notes"><ClipboardText /><div><Text size="1" color="gray">{quoteText(locale, "notes")}</Text><Text as="div">{draft.notes}</Text></div></Card> : null}
                </Card>
              </div>
            </div>
          </div>
          <div className="quote-preview-zoom" aria-label={t("预览大小")}>
            <Text size="1" color="gray" className="quote-preview-drag-hint">{t("拖动查看")}</Text>
            <button type="button" className="quote-preview-zoom-step" aria-label={t("缩小预览")} onClick={() => changePreviewScale(previewScale - PREVIEW_SCALE_STEP)}>−</button>
            <input type="range" min={PREVIEW_SCALE_MIN} max={PREVIEW_SCALE_MAX} step={PREVIEW_SCALE_STEP} value={previewScale} aria-label={t("预览大小")} onChange={(event) => changePreviewScale(Number(event.target.value))} />
            <button type="button" className="quote-preview-zoom-step" aria-label={t("放大预览")} onClick={() => changePreviewScale(previewScale + PREVIEW_SCALE_STEP)}>+</button>
            <output>{previewScale}%</output>
            <button type="button" className="quote-preview-fit" onClick={fitPreviewToViewport}>{t("适合窗口")}</button>
          </div>
        </div>
        ) : renderExcelPreview()}
      </Tabs.Content>
      <Tabs.Content value="proforma">
        <ProformaInvoicePanel previewMode={previewMode} onPreviewModeChange={setPreviewMode} draft={draft} invoice={proformaInvoice} onChange={updateProformaInvoice} items={draft.items.map(effectiveItem)} customFields={customFields} itemEditor={renderOrderItemsEditor()} locale={locale} sellerName={documentSellerName} accent={selectedStyle.color} readOnly={isReadOnly} saving={saving || savingItems} exporting={downloading} dirty={hasPendingItemEdits || !quoteSettingsEqual(savedSettingsRef.current, currentSettings)} onSave={() => void save()} onExport={(format) => void download(format)} settingsControls={<>
          <div className="packing-field"><span>{t("PDF 样式")}</span><Select.Root value={style} onValueChange={(value) => setStyle(value as QuoteDocumentStyle)} disabled={isReadOnly || saving || Boolean(downloading)}><Select.Trigger aria-label={t("PDF 样式")} /><Select.Content position="popper">{styles.map((option) => <Select.Item key={option.value} value={option.value}>{t(option.label)}</Select.Item>)}</Select.Content></Select.Root></div>
          <div className="packing-field"><span>{quoteText(locale, "language")}</span><Select.Root value={locale} onValueChange={(value) => void changeDocumentLocale(value)} disabled={localeSelectionDisabled || Boolean(downloading)}><Select.Trigger aria-label={t("报价语言")}>{localeLabel(locale)}</Select.Trigger><Select.Content position="popper">{localeOptions.map((option) => <Select.Item key={option.value} value={option.value}>{localeLabel(option.value)}</Select.Item>)}</Select.Content></Select.Root></div>
          <div className="packing-field"><span>{quoteText(locale, "currency")}</span><Button variant="soft" disabled={!canOpenCurrencyConversion || hasPendingItemEdits || saving || Boolean(downloading)} onClick={openCurrencyConversion}>{draft.currency}</Button></div>
        </>} />
      </Tabs.Content>
      <Tabs.Content value="packing-list">
        {packingList ? <PackingListPanel previewMode={previewMode} onPreviewModeChange={setPreviewMode} draft={draft} value={packingList} onChange={setPackingList} customFields={customFields} onCustomFieldChange={updateCustomFieldValue} customFieldManager={renderCustomFieldManager()} locale={locale} sellerName={documentSellerName} readOnly={isReadOnly} saving={saving} onSave={() => void save()} onExport={(format) => void download(format)} exporting={downloading} dirty={!quoteSettingsEqual(savedSettingsRef.current, currentSettings)} languageControl={<Select.Root value={locale} onValueChange={(value) => void changeDocumentLocale(value)} disabled={localeSelectionDisabled || Boolean(downloading)}><Select.Trigger aria-label={t("报价语言")}>{localeLabel(locale)}</Select.Trigger><Select.Content position="popper">{localeOptions.map((option) => <Select.Item key={option.value} value={option.value}>{localeLabel(option.value)}</Select.Item>)}</Select.Content></Select.Root>} /> : <CoreLoading />}
      </Tabs.Content>
      <Tabs.Content value="purchase-order">
        {purchaseOrderLoading || !purchaseOrder ? <CoreLoading label={t("正在读取供应商与采购信息")} /> : <PurchaseOrderPanel
          value={purchaseOrder}
          onChange={setPurchaseOrder}
          readOnly={isReadOnly}
          saving={purchaseOrderSaving}
          exporting={downloading === "xlsx"}
          dirty={purchaseOrderDirty}
          onSave={() => void savePurchaseOrder()}
          onExport={() => void exportPurchaseOrder()}
          onOpenProduct={(itemId) => {
            const item = draft.items.find((candidate) => candidate.id === itemId);
            if (item) void openItemDetails(item);
          }}
        />}
      </Tabs.Content>
      {(["sales-contract", "commercial-invoice", "customs-declaration"] as const).map((value) => <Tabs.Content value={value} key={value}><Card className="quote-coming-soon"><LockKey size={28} /><Heading size="4">{t("该单证将在后续版本开放")}</Heading><Text size="2" color="gray">{t("当前先完成报价单的制作、样式设置和文件导出。")}</Text></Card></Tabs.Content>)}
      </section>
      {activeDocument !== "packing-list" && activeDocument !== "proforma" && activeDocument !== "purchase-order" ? renderManual() : null}
    </div>
    </Tabs.Root>
  </div>;
}
