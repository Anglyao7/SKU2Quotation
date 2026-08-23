import { Badge, Button, Card, Checkbox, Dialog, DropdownMenu, Heading, Progress, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { ArrowDown, ArrowUp, ArrowsClockwise, CaretDown, CaretLeft, CaretRight, CheckCircle, DotsThree, DownloadSimple, FileArrowUp, FileXls, Folders, ImageSquare, MagnifyingGlass, PencilSimple, Plus, PushPin, PushPinSlash, Sparkle, Tag, Trash, Translate, Warning, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  batchDeleteProducts,
  batchDeleteSkus,
  batchUpdateSkuCategory,
  batchUpdateSkuPinned,
  batchUpdateSkuStatus,
  createCatalogImportBatch,
  createManualProduct,
  createProductTemplateImport,
  createSkus,
  deleteAllProducts,
  detectFile,
  downloadProductMainImage,
  exportSkuCatalog,
  getDeleteAllProductsJob,
  getMerchantSettings,
  getImport,
  getProduct,
  listCatalogImportBatches,
  listCategories,
  listProductCatalog,
  listPublicCatalogOffers,
  PRODUCT_TEMPLATE_DOWNLOAD_URL,
  rollbackCatalogImportBatch,
  retryCatalogTranslationProduct,
  updateSku,
  uploadProductMainImage,
  upsertPublicCatalogOffer,
  CoreApiError,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { removeImportItem, resetFailedImportItem, selectUniqueImportFiles } from "../importQueueState";
import { useLocale } from "../LocaleContext";
import { CatalogShareDialog, type CatalogShareTarget } from "../components/CatalogShareDialog";
import { ImageEnhancementDialog, type ImageEnhancementTarget } from "../components/ImageEnhancementDialog";
import { primaryCategoryLabel } from "../../lib/format";
import { storefrontLanguage } from "../../lib/storefrontLocale";
import { api } from "../../lib/api";
import type { ProductTag, StorefrontLocale } from "../../types";
import type { CatalogImportBatch, CatalogImportRollbackResult, CoreProduct, FileDetection, ImportJob, ProductCategory, ProductDetail, ProductListPage, ProductSku, PublicCatalogOffer, SkuListItem } from "../types";
import { useToast } from "../ToastContext";

const emptyProductPage: ProductListPage = { items: [], page: 1, pageSize: 50, total: 0, pages: 0 };
const SKU_PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
const SKU_PAGE_SIZE_STORAGE_KEY = "ai-trade-cloud:sku-page-size";
const UNCLASSIFIED_CATEGORY_VALUE = "__unclassified__";
const SKU_TEMPLATE_MARKER_KEY = "_sku2quotation";
const SKU_PACKING_QUANTITY_KEY = "装箱数";
const SKU_PACKING_QUANTITY_KEYS = new Set([
  SKU_PACKING_QUANTITY_KEY,
  "一箱个数",
  "packing_quantity",
  "units_per_carton",
]);
type BulkSkuAction = "pin" | "unpin" | "activate" | "deactivate" | "category";
type ProductStatus = "DRAFT" | "IN_REVIEW" | "ACTIVE" | "ARCHIVED";
type ImportQueueStatus = "checking" | "ready" | "uploading" | "processing" | "published" | "failed";

interface ImportQueueItem {
  id: string;
  file: File;
  detection?: FileDetection;
  status: ImportQueueStatus;
  progress: number;
  job?: ImportJob;
  error?: string;
}

function initialSkuPageSize() {
  if (typeof window === "undefined") return 50;
  const stored = Number(window.localStorage.getItem(SKU_PAGE_SIZE_STORAGE_KEY));
  return SKU_PAGE_SIZE_OPTIONS.find((option) => option === stored) ?? 50;
}

const skuStatusLabel: Record<ProductSku["status"], string> = {
  ACTIVE: "在售",
  DRAFT: "草稿",
  INACTIVE: "已下架",
  ARCHIVED: "已归档",
};

const productStatusLabel: Record<ProductStatus, string> = {
  ACTIVE: "在售",
  DRAFT: "草稿",
  IN_REVIEW: "待审核",
  ARCHIVED: "已归档",
};

const offerStatusLabel: Record<NonNullable<SkuListItem["publicOfferStatus"]>, string> = {
  PUBLISHED: "公开价已发布",
  DRAFT: "公开价草稿",
  SUSPENDED: "公开价已暂停",
};

const importStatusLabel: Record<ImportJob["status"], string> = {
  scanning: "读取文件",
  parsing: "导入中",
  needs_review: "待复核",
  published: "已完成",
  failed: "导入失败",
};

const importStageLabel: Record<string, string> = {
  READING_WORKBOOK: "正在读取工作簿",
  VALIDATING_ROWS: "正在校验商品数据",
  LOADING_CATALOG: "正在读取现有商品库",
  PLANNING_CHANGES: "正在计算商品变更",
  APPLYING_PRODUCTS: "正在写入商品",
  FINALIZING: "正在完成导入",
  COMPLETED: "商品导入完成",
  VALIDATION_FAILED: "数据校验未通过",
  FAILED: "商品导入失败",
};

const deleteAllStageLabel: Record<string, string> = {
  QUEUED: "删除任务已排队",
  COUNTING: "正在统计商品数据",
  HIDING_OFFERS: "正在停止前台展示",
  ARCHIVING_SKUS: "正在归档 SKU",
  ARCHIVING_PRODUCTS: "正在归档商品",
  FINALIZING: "正在完成删除",
  COMPLETED: "全部商品删除完成",
  FAILED: "全部商品删除失败",
};

const PRODUCT_UPLOAD_RETRY_DELAYS_MS = [1_500, 4_000, 8_000] as const;
const PRODUCT_UPLOAD_MAX_BYTES = 250 * 1024 * 1024;

const waitForDeletePoll = () => new Promise<void>((resolve) => {
  window.setTimeout(resolve, 900);
});

const waitForProductUploadRetry = (delayMs: number) => new Promise<void>((resolve) => {
  window.setTimeout(resolve, delayMs);
});

function isRetryableProductUploadError(reason: unknown) {
  if (!(reason instanceof CoreApiError)) return true;
  return reason.status === 0
    || reason.status === 408
    || reason.status === 425
    || reason.status === 429
    || reason.status >= 500;
}

function exportImportIssues(job: ImportJob) {
  const escape = (value: string | number | undefined) => {
    const text = value === undefined ? "" : String(value);
    return `"${text.replaceAll("\"", "\"\"")}"`;
  };
  const rows = [
    ["Excel 行号", "字段", "错误代码", "原值", "失败原因", "修改建议"],
    ...job.resultDetails.issues.map((issue) => [
      issue.rowNumber ?? "",
      issue.column,
      issue.code,
      issue.value ?? "",
      issue.message,
      issue.suggestion ?? "",
    ]),
  ];
  const content = `\uFEFF${rows.map((row) => row.map((value) => escape(value)).join(",")).join("\r\n")}`;
  const blob = new Blob([content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${job.filename.replace(/\.xlsx$/i, "")}-导入失败明细.csv`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function SkuThumbnail({ sku, label }: { sku: SkuListItem; label: string }) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [sku.thumbnailUrl]);

  return (
    <span
      className={`core-sku-image-state ${sku.imageStatus.toLowerCase()}`}
      title={label}
    >
      {sku.thumbnailUrl && !imageFailed ? (
        <img
          src={sku.thumbnailUrl}
          alt={`${sku.name || sku.productName} · ${sku.skuCode}`}
          loading="lazy"
          decoding="async"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <ImageSquare aria-hidden="true" />
      )}
    </span>
  );
}

function ProductThumbnail({ product, label }: { product: CoreProduct; label: string }) {
  const [imageFailed, setImageFailed] = useState(false);

  useEffect(() => {
    setImageFailed(false);
  }, [product.primaryImageUrl]);

  return (
    <span
      className={`core-sku-image-state ${product.imageStatus.toLowerCase()}`}
      title={label}
    >
      {product.primaryImageUrl && !imageFailed ? (
        <img
          src={product.primaryImageUrl}
          alt={product.name}
          loading="lazy"
          decoding="async"
          onError={() => setImageFailed(true)}
        />
      ) : (
        <ImageSquare aria-hidden="true" />
      )}
    </span>
  );
}

function skuStatusColor(status: ProductSku["status"]): "jade" | "amber" | "gray" {
  if (status === "ACTIVE") return "jade";
  if (status === "DRAFT") return "amber";
  return "gray";
}

function skuPrice(row: SkuListItem) {
  if (row.publicPrice === undefined) return "未设置";
  return `${row.publicCurrency ?? ""} ${row.publicPrice.toLocaleString(document.documentElement.lang || "zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
}

function getSkuPackingQuantity(optionValues: ProductSku["optionValues"]) {
  for (const key of SKU_PACKING_QUANTITY_KEYS) {
    const value = optionValues[key];
    if (value !== undefined && value !== null && String(value).trim()) return String(value).trim();
  }
  return "";
}

function withSkuPackingQuantity(
  optionValues: ProductSku["optionValues"],
  packingQuantity: string,
) {
  const next = { ...optionValues };
  SKU_PACKING_QUANTITY_KEYS.forEach((key) => delete next[key]);
  if (packingQuantity.trim()) next[SKU_PACKING_QUANTITY_KEY] = packingQuantity.trim();
  return next;
}

function visibleSkuOptions(optionValues: ProductSku["optionValues"]) {
  return Object.entries(optionValues).filter(([key, value]) => (
    key !== SKU_TEMPLATE_MARKER_KEY
    && !SKU_PACKING_QUANTITY_KEYS.has(key)
    && value !== ""
    && value !== undefined
    && value !== null
  ));
}

function skuUpdatedDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(document.documentElement.lang || "zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

type PaginationItem = number | "leading-ellipsis" | "trailing-ellipsis";

function skuPaginationItems(page: number, pages: number): PaginationItem[] {
  if (pages <= 7) return Array.from({ length: pages }, (_, index) => index + 1);
  const items: PaginationItem[] = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(pages - 1, page + 1);
  if (start > 2) items.push("leading-ellipsis");
  for (let current = start; current <= end; current += 1) items.push(current);
  if (end < pages - 1) items.push("trailing-ellipsis");
  items.push(pages);
  return items;
}

export function ProductsPage() {
  const { hasPermission, profile } = useCoreAuth();
  const { locale, t } = useLocale();
  const { notify } = useToast();
  const canEdit = hasPermission("product.edit");
  const canDelete = canEdit;
  const canImport = hasPermission("product.import")
    && hasPermission("product.edit")
    && hasPermission("catalog.publish");
  const canCreate = canEdit && hasPermission("catalog.publish");
  const [params, setParams] = useSearchParams();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState<"" | ProductStatus>("");
  const [missingImagesOnly, setMissingImagesOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSkuPageSize);
  const [result, setResult] = useState<ProductListPage>(emptyProductPage);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [managedTags, setManagedTags] = useState<ProductTag[]>([]);
  const [selected, setSelected] = useState<ProductDetail>();
  const [selectedSkuId, setSelectedSkuId] = useState<string | undefined>(params.get("sku") ?? undefined);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(canImport && params.get("import") === "1");
  const [createOpen, setCreateOpen] = useState(false);
  const [importTab, setImportTab] = useState("upload");
  const [importFiles, setImportFiles] = useState<ImportQueueItem[]>([]);
  const [importBatches, setImportBatches] = useState<CatalogImportBatch[]>([]);
  const [importBatchesLoading, setImportBatchesLoading] = useState(false);
  const [rollbackBatchId, setRollbackBatchId] = useState("");
  const [rollbackCategoryId, setRollbackCategoryId] = useState("");
  const [rollbackTarget, setRollbackTarget] = useState<CatalogImportBatch>();
  const [rollbackBusy, setRollbackBusy] = useState(false);
  const [rollbackError, setRollbackError] = useState("");
  const [rollbackResult, setRollbackResult] = useState<CatalogImportRollbackResult>();
  const [importDragActive, setImportDragActive] = useState(false);
  const [lastImport, setLastImport] = useState<ImportJob>();
  const [loadedWarningJobId, setLoadedWarningJobId] = useState<string>();
  const [importBusy, setImportBusy] = useState(false);
  const [importSubmitStage, setImportSubmitStage] = useState<"idle" | "checking" | "uploading" | "processing">("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [importError, setImportError] = useState("");
  const [importPollingError, setImportPollingError] = useState("");
  const [selectedProductIds, setSelectedProductIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [singleDeleteTarget, setSingleDeleteTarget] = useState<SkuListItem>();
  const [singleDeleteBusy, setSingleDeleteBusy] = useState(false);
  const [singleDeleteError, setSingleDeleteError] = useState("");
  const [bulkAction, setBulkAction] = useState<BulkSkuAction>();
  const [bulkCategoryId, setBulkCategoryId] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [deleteAllDialogOpen, setDeleteAllDialogOpen] = useState(false);
  const [deleteAllPassword, setDeleteAllPassword] = useState("");
  const [deleteAllBusy, setDeleteAllBusy] = useState(false);
  const [deleteAllError, setDeleteAllError] = useState("");
  const [deleteAllProgress, setDeleteAllProgress] = useState(0);
  const [deleteAllStage, setDeleteAllStage] = useState("QUEUED");
  const [bulkError, setBulkError] = useState("");
  const [bulkNotice, setBulkNotice] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [translationLocale, setTranslationLocale] = useState<StorefrontLocale>("en-US");
  const [translatingProductId, setTranslatingProductId] = useState<string>();
  const [shareTarget, setShareTarget] = useState<CatalogShareTarget>();
  const [imageEnhancementTargets, setImageEnhancementTargets] = useState<ImageEnhancementTarget[]>([]);
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await listProductCatalog({
        q: debouncedQuery.trim() || undefined,
        categoryId: categoryId || undefined,
        statuses: status ? [status] : undefined,
        missingImagesOnly,
        page,
        pageSize,
      });
      if (sequence === loadSequence.current) setResult(next);
    } catch (reason) {
      if (sequence === loadSequence.current) {
        setError(reason instanceof Error ? reason.message : t("SKU 商品库加载失败"));
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [categoryId, debouncedQuery, missingImagesOnly, page, pageSize, status, t]);

  const loadCategories = useCallback(async () => {
    setCategories(await listCategories());
  }, []);
  const loadImportBatches = useCallback(async () => {
    setImportBatchesLoading(true);
    try {
      const batches = await listCatalogImportBatches();
      setImportBatches(batches);
      setRollbackError("");
      setRollbackBatchId((current) => (
        current && batches.some((batch) => batch.id === current)
          ? current
          : batches.find((batch) => batch.status !== "REVOKED")?.id ?? ""
      ));
    } catch (reason) {
      setRollbackError(reason instanceof Error ? reason.message : t("导入批次加载失败"));
    } finally {
      setImportBatchesLoading(false);
    }
  }, [t]);
  useEffect(() => { void loadCategories().catch(() => setCategories([])); }, [loadCategories]);
  useEffect(() => {
    void getMerchantSettings().then((settings) => {
      const preferred = settings.storefrontDefaultLocale !== "zh-CN"
        ? settings.storefrontDefaultLocale
        : settings.storefrontLocales.find((value) => value !== "zh-CN") ?? "en-US";
      setTranslationLocale(preferred);
    }).catch(() => undefined);
  }, []);
  useEffect(() => {
    void api.getProductTags("", 200)
      .then((response) => setManagedTags(response.tags))
      .catch(() => setManagedTags([]));
  }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 240);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    setSelectedProductIds(new Set());
    setDeleteDialogOpen(false);
    setBulkAction(undefined);
    setBulkError("");
  }, [categoryId, debouncedQuery, missingImagesOnly, status]);

  const refreshCurrentImport = useCallback(async () => {
    if (!lastImport?.id) return undefined;
    const next = await getImport(lastImport.id);
    setLastImport(next);
    setImportFiles((current) => current.map((item) => (
      item.job?.id === next.id
        ? {
            ...item,
            job: next,
            progress: next.progress,
            status: next.status === "published" ? "published" : next.status === "failed" ? "failed" : "processing",
          }
        : item
    )));
    setImportPollingError("");
    if (next.status === "published") {
      await load();
      await loadCategories().catch(() => undefined);
      await loadImportBatches().catch(() => undefined);
    }
    return next;
  }, [lastImport?.id, load, loadCategories, loadImportBatches]);

  const activeImportJobIds = useMemo(
    () => importFiles
      .filter((item) => item.job && ["scanning", "parsing"].includes(item.job.status))
      .map((item) => item.job!.id)
      .join(","),
    [importFiles],
  );
  useEffect(() => {
    if (!importOpen || !activeImportJobIds) return;
    let cancelled = false;
    let timer = 0;
    const poll = () => {
      timer = window.setTimeout(() => {
        const jobIds = activeImportJobIds.split(",").filter(Boolean);
        void Promise.all(jobIds.map((jobId) => getImport(jobId)))
          .then(async (jobs) => {
            if (cancelled) return;
            const jobsById = new Map(jobs.map((job) => [job.id, job]));
            setImportFiles((current) => current.map((item) => {
              const job = item.job ? jobsById.get(item.job.id) : undefined;
              if (!job) return item;
              return {
                ...item,
                job,
                progress: job.progress,
                status: job.status === "published" ? "published" : job.status === "failed" ? "failed" : "processing",
                error: job.errorMessage,
              };
            }));
            setLastImport((current) => current ? jobsById.get(current.id) ?? current : current);
            setImportPollingError("");
            if (jobs.some((job) => job.status === "published")) {
              await Promise.all([
                load(),
                loadCategories().catch(() => undefined),
                loadImportBatches().catch(() => undefined),
              ]);
            }
            if (!cancelled && jobs.some((job) => ["scanning", "parsing"].includes(job.status))) poll();
          })
          .catch((reason) => {
            setImportPollingError(reason instanceof Error ? t("状态刷新失败，系统将继续重试：{message}", { message: reason.message }) : t("状态刷新失败，系统将继续重试。"));
            if (!cancelled) poll();
          });
      }, 1800);
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeImportJobIds, importOpen, load, loadCategories, loadImportBatches, t]);

  useEffect(() => {
    const requested = params.get("import") === "1";
    if (requested && canImport) {
      setImportOpen(true);
      return;
    }
    if (requested && !canImport) {
      setImportOpen(false);
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("import");
        return next;
      }, { replace: true });
    }
  }, [canImport, params, setParams]);

  useEffect(() => {
    if (!lastImport || !["failed", "published"].includes(lastImport.status)) return;
    const missingIssues = lastImport.resultDetails.issueTotal > lastImport.resultDetails.issues.length;
    const missingWarnings = lastImport.warnings > lastImport.warningMessages.length;
    if ((!missingIssues && !missingWarnings) || loadedWarningJobId === lastImport.id) return;
    setLoadedWarningJobId(lastImport.id);
    void getImport(lastImport.id)
      .then(setLastImport)
      .catch(() => setLoadedWarningJobId(undefined));
  }, [lastImport, loadedWarningJobId]);
  useEffect(() => {
    if (importOpen) void loadImportBatches();
  }, [importOpen, loadImportBatches]);

  const setImportDialogOpen = (open: boolean) => {
    if (open && !canImport) return;
    setImportOpen(open);
    if (!open) {
      setImportError("");
      setImportPollingError("");
      setRollbackError("");
      setImportSubmitStage("idle");
      setUploadProgress(0);
    }
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (open) next.set("import", "1");
      else next.delete("import");
      return next;
    }, { replace: true });
  };

  const inspectImportItem = async (item: ImportQueueItem) => {
    if (item.file.size > PRODUCT_UPLOAD_MAX_BYTES) {
      setImportFiles((current) => current.map((currentItem) => (
        currentItem.id === item.id
          ? { ...currentItem, status: "failed", error: t("文件超过 250 MB 上限，请拆分后再上传。") }
          : currentItem
      )));
      return;
    }
    try {
      const detection = await detectFile(item.file);
      const valid = detection.detected_type === "OOXML / XLSX" && detection.extension_matches;
      setImportFiles((current) => current.map((currentItem) => (
        currentItem.id === item.id
          ? {
              ...currentItem,
              detection,
              status: valid ? "ready" : "failed",
              error: valid ? undefined : t("文件签名与 XLSX 格式不一致。"),
            }
          : currentItem
      )));
    } catch (reason) {
      setImportFiles((current) => current.map((currentItem) => (
        currentItem.id === item.id
          ? { ...currentItem, status: "failed", error: reason instanceof Error ? reason.message : t("文件检测失败") }
          : currentItem
      )));
    }
  };

  const inspectTemplates = async (selectedFiles?: FileList | File[]) => {
    if (!canImport || !selectedFiles) return;
    const files = Array.from(selectedFiles);
    if (!files.length) return;
    setImportError("");
    setLoadedWarningJobId(undefined);
    const {
      acceptedFiles,
      capacityRemaining,
      overflowCount,
    } = selectUniqueImportFiles(importFiles.map((item) => item.file), files);
    if (!acceptedFiles.length) {
      setImportError(t(capacityRemaining === 0 ? "每个批次最多选择 100 个文件。" : "这些文件已经在当前列表中。"));
      if (importInputRef.current) importInputRef.current.value = "";
      return;
    }
    if (overflowCount > 0) setImportError(t("每个批次最多选择 100 个文件，超出的文件未加入。"));
    const queued: ImportQueueItem[] = acceptedFiles.map((file) => ({
      id: crypto.randomUUID(),
      file,
      status: file.name.toLowerCase().endsWith(".xlsx") ? "checking" : "failed",
      progress: 0,
      error: file.name.toLowerCase().endsWith(".xlsx") ? undefined : t("只接受 .xlsx 商品文件。"),
    }));
    setImportFiles((current) => [...current, ...queued]);
    setImportBusy(true);
    setImportSubmitStage("checking");
    try {
      await Promise.all(queued.map(async (item) => {
        if (item.status === "failed") return;
        await inspectImportItem(item);
      }));
    } finally {
      setImportBusy(false);
      setImportSubmitStage("idle");
      if (importInputRef.current) importInputRef.current.value = "";
    }
  };

  const retryImportFile = async (item: ImportQueueItem) => {
    if (importBusy || item.status !== "failed") return;
    const retryItem: ImportQueueItem = resetFailedImportItem(item);
    setImportError("");
    setImportPollingError("");
    setLoadedWarningJobId(undefined);
    setLastImport((current) => current?.id === item.job?.id ? undefined : current);
    setImportFiles((current) => current.map((currentItem) => (
      currentItem.id === item.id ? retryItem : currentItem
    )));
    setImportBusy(true);
    setImportSubmitStage("checking");
    try {
      await inspectImportItem(retryItem);
    } finally {
      setImportBusy(false);
      setImportSubmitStage("idle");
    }
  };

  const removeImportFile = (item: ImportQueueItem) => {
    setImportFiles((current) => removeImportItem(current, item.id));
    setLastImport((current) => current?.id === item.job?.id ? undefined : current);
  };

  const recoverUploadedImport = async (
    batchId: string,
    filename: string,
    knownJobIds: ReadonlySet<string>,
  ) => {
    for (let check = 0; check < 3; check += 1) {
      if (check > 0) await waitForProductUploadRetry(1_000);
      try {
        const latestBatch = (
          await listCatalogImportBatches(10, AbortSignal.timeout(3_000))
        ).find((batch) => batch.id === batchId);
        const candidates = latestBatch?.jobs.filter((job) => (
          job.filename === filename && !knownJobIds.has(job.id)
        ));
        const recovered = candidates?.[candidates.length - 1];
        if (recovered) return recovered;
      } catch {
        // A status check is best effort. Keep polling briefly because the API
        // may still be committing a request whose response was lost.
      }
    }
    return undefined;
  };

  const uploadImportFileWithRetry = async (
    item: ImportQueueItem,
    batchId: string,
    knownJobIds: ReadonlySet<string>,
    index: number,
    total: number,
  ) => {
    let lastReason: unknown;
    for (let attempt = 0; attempt <= PRODUCT_UPLOAD_RETRY_DELAYS_MS.length; attempt += 1) {
      try {
        return await createProductTemplateImport(item.file, (progress) => {
          setUploadProgress(Math.round(((index + progress / 100) / total) * 100));
          setImportFiles((current) => current.map((currentItem) => (
            currentItem.id === item.id ? { ...currentItem, progress, error: undefined } : currentItem
          )));
        }, batchId);
      } catch (reason) {
        lastReason = reason;
        if (!isRetryableProductUploadError(reason)) throw reason;

        // The browser may lose the response after the API has committed the
        // import job. Recover that job before resending the same workbook so a
        // flaky connection cannot duplicate an import.
        const recovered = await recoverUploadedImport(batchId, item.file.name, knownJobIds);
        if (recovered) return recovered;
        if (attempt >= PRODUCT_UPLOAD_RETRY_DELAYS_MS.length) throw reason;

        const retryNumber = attempt + 1;
        setImportFiles((current) => current.map((currentItem) => (
          currentItem.id === item.id
            ? { ...currentItem, error: t("网络波动，正在自动重试第 {attempt} 次…", { attempt: retryNumber }) }
            : currentItem
        )));
        await waitForProductUploadRetry(PRODUCT_UPLOAD_RETRY_DELAYS_MS[attempt]);
      }
    }
    throw lastReason instanceof Error ? lastReason : new Error(t("商品导入失败"));
  };

  const importTemplates = async () => {
    if (!canImport) {
      setImportError(t("当前账号没有导入商品的权限。"));
      return;
    }
    const readyItems = importFiles.filter((item) => item.status === "ready" && item.detection);
    if (!readyItems.length) return;
    setImportBusy(true);
    setImportSubmitStage("uploading");
    setUploadProgress(0);
    setImportError("");
    try {
      const batch = await createCatalogImportBatch(readyItems.length);
      const knownJobIds = new Set(batch.jobs.map((job) => job.id));
      for (let index = 0; index < readyItems.length; index += 1) {
        const item = readyItems[index];
        setImportFiles((current) => current.map((currentItem) => (
          currentItem.id === item.id ? { ...currentItem, status: "uploading", progress: 0, error: undefined } : currentItem
        )));
        try {
          const job = await uploadImportFileWithRetry(
            item,
            batch.id,
            knownJobIds,
            index,
            readyItems.length,
          );
          knownJobIds.add(job.id);
          setImportFiles((current) => current.map((currentItem) => (
            currentItem.id === item.id
              ? {
                  ...currentItem,
                  job,
                  progress: job.progress,
                  status: job.status === "published" ? "published" : job.status === "failed" ? "failed" : "processing",
                  error: job.errorMessage,
                }
              : currentItem
          )));
          setLastImport(job);
          setLoadedWarningJobId(undefined);
          if (job.status === "published") {
            await Promise.all([load(), loadCategories().catch(() => undefined)]);
          }
        } catch (reason) {
          setImportFiles((current) => current.map((currentItem) => (
            currentItem.id === item.id
              ? { ...currentItem, status: "failed", error: reason instanceof Error ? reason.message : t("商品导入失败") }
              : currentItem
          )));
        }
      }
      setImportSubmitStage("processing");
      setUploadProgress(100);
      await loadImportBatches();
    } catch (reason) {
      setImportError(reason instanceof Error ? reason.message : t("商品导入失败"));
    } finally {
      setImportBusy(false);
      setImportSubmitStage("idle");
    }
  };

  const selectedRollbackBatch = importBatches.find((batch) => batch.id === rollbackBatchId);
  const requestRollback = () => {
    if (!selectedRollbackBatch) return;
    setRollbackError("");
    setRollbackResult(undefined);
    setRollbackTarget(selectedRollbackBatch);
  };
  const executeRollback = async () => {
    if (!rollbackTarget) return;
    setRollbackBusy(true);
    setRollbackError("");
    try {
      const result = await rollbackCatalogImportBatch(
        rollbackTarget.id,
        rollbackCategoryId || undefined,
      );
      setRollbackResult(result);
      setRollbackTarget(undefined);
      setRollbackCategoryId("");
      await Promise.all([load(), loadCategories(), loadImportBatches()]);
    } catch (reason) {
      setRollbackError(reason instanceof Error ? reason.message : t("撤回失败，请稍后重试。"));
    } finally {
      setRollbackBusy(false);
    }
  };

  const openProduct = useCallback(async (productId: string, skuId?: string) => {
    setSelectedSkuId(skuId);
    setDetailLoading(true);
    setError("");
    try {
      setSelected(await getProduct(productId));
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.set("product", productId);
        if (skuId) next.set("sku", skuId);
        else next.delete("sku");
        next.delete("view");
        return next;
      }, { replace: true });
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("产品详情加载失败")); }
    finally { setDetailLoading(false); }
  }, [setParams]);

  const translateProduct = async (product: CoreProduct) => {
    if (!canEdit || translatingProductId) return;
    setTranslatingProductId(product.id);
    try {
      const job = await retryCatalogTranslationProduct(product.id, translationLocale);
      notify(
        t("已提交商品“{name}”的 {language} 重译任务，共 {count} 个 SKU。", {
          name: product.name,
          language: storefrontLanguage(translationLocale).label,
          count: job.totalSkus,
        }),
        { kind: "success" },
      );
    } catch (reason) {
      notify(reason instanceof Error ? reason.message : t("商品翻译任务启动失败"), { kind: "error" });
    } finally {
      setTranslatingProductId(undefined);
    }
  };

  useEffect(() => {
    const productId = params.get("product");
    if (productId && selected?.id !== productId) {
      void openProduct(productId, params.get("sku") ?? undefined);
    }
    // Product selection is restored from the URL once on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    setSelected(undefined);
    setSelectedSkuId(undefined);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("product");
      next.delete("view");
      next.delete("sku");
      return next;
    }, { replace: true });
  };
  const refreshSelected = async () => { if (selected) setSelected(await getProduct(selected.id)); };
  const resetFilters = () => {
    setQuery("");
    setDebouncedQuery("");
    setCategoryId("");
    setStatus("");
    setMissingImagesOnly(false);
    setPage(1);
  };
  const handleManualCreated = (product: ProductDetail) => {
    setCreateOpen(false);
    resetFilters();
    setSelected(product);
    setSelectedSkuId(product.skus[0]?.id);
    setBulkNotice(t("商品“{name}”已创建。", { name: product.name }));
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("product", product.id);
      next.delete("view");
      if (product.skus[0]?.id) next.set("sku", product.skus[0].id);
      return next;
    }, { replace: true });
    void load();
  };
  const currentPageProductIds = result.items.map((product) => product.id);
  const currentPageSelected = currentPageProductIds.filter((id) => selectedProductIds.has(id));
  const allCurrentPageSelected = currentPageProductIds.length > 0
    && currentPageSelected.length === currentPageProductIds.length;
  const toggleProductSelection = (productId: string) => {
    setBulkNotice("");
    setBulkError("");
    setSelectedProductIds((current) => {
      const next = new Set(current);
      if (next.has(productId)) next.delete(productId);
      else if (next.size < 500) next.add(productId);
      return next;
    });
  };
  const toggleCurrentPageSelection = () => {
    setBulkNotice("");
    setBulkError("");
    setSelectedProductIds((current) => {
      const next = new Set(current);
      if (allCurrentPageSelected) {
        currentPageProductIds.forEach((id) => next.delete(id));
        return next;
      }
      currentPageProductIds.forEach((id) => {
        if (next.size < 500) next.add(id);
      });
      return next;
    });
  };
  const clearProductSelection = () => {
    setSelectedProductIds(new Set());
    setDeleteDialogOpen(false);
    setBulkAction(undefined);
    setBulkError("");
  };
  const openImageEnhancementForProducts = () => {
    if (!canEdit || !selectedProductIds.size) return;
    setImageEnhancementTargets(
      [...selectedProductIds].map((productId) => ({ productId, skuIds: [] })),
    );
  };
  const openImageEnhancementForSkus = (productId: string, skuIds: string[]) => {
    if (!canEdit || !skuIds.length) return;
    setImageEnhancementTargets([{ productId, skuIds }]);
  };
  const openImageEnhancementForProduct = (productId: string) => {
    if (!canEdit) return;
    setImageEnhancementTargets([{ productId, skuIds: [] }]);
  };
  const openBulkAction = (action: BulkSkuAction) => {
    if (!canEdit || !selectedProductIds.size) return;
    setBulkError("");
    if (action === "category") setBulkCategoryId("");
    setBulkAction(action);
  };
  const applyBulkAction = async () => {
    if (!canEdit || !selectedProductIds.size || !bulkAction) return;
    if (bulkAction === "category" && !bulkCategoryId) {
      setBulkError(t("请选择要移动到的分类。"));
      return;
    }
    setBulkBusy(true);
    setBulkError("");
    try {
      const selectedIds = [...selectedProductIds];
      const response = bulkAction === "category"
        ? await batchUpdateSkuCategory(
            selectedIds,
            bulkCategoryId === UNCLASSIFIED_CATEGORY_VALUE ? null : bulkCategoryId,
          )
        : bulkAction === "pin" || bulkAction === "unpin"
        ? await batchUpdateSkuPinned(selectedIds, bulkAction === "pin")
        : await batchUpdateSkuStatus(
            selectedIds,
            bulkAction === "activate" ? "ACTIVE" : "INACTIVE",
          );
      const failedIds = new Set(response.failedItems.map((item) => item.skuId));
      const affectedProducts = response.affectedProductCount ?? response.successCount;
      const categoryName = bulkCategoryId === UNCLASSIFIED_CATEGORY_VALUE
        ? t("未分类")
        : categories.find((item) => item.id === bulkCategoryId)?.name ?? t("所选分类");
      const successMessage = bulkAction === "category"
        ? t("已将 {skus} 个 SKU 对应的 {products} 个商品移动到“{category}”。", {
            skus: response.successCount,
            products: affectedProducts,
            category: categoryName,
          })
        : bulkAction === "pin"
        ? t("已置顶 {products} 个商品。", { products: affectedProducts })
        : bulkAction === "unpin"
        ? t("已取消置顶 {products} 个商品。", { products: affectedProducts })
        : bulkAction === "activate"
        ? t("已上架 {count} 个 SKU。", { count: response.successCount })
        : t("已下架 {count} 个 SKU。", { count: response.successCount });
      setSelectedProductIds(failedIds);
      setBulkNotice(
        response.failedCount
          ? t("{message} {failed} 个项目未能更新。", {
              message: successMessage,
              failed: response.failedCount,
            })
          : successMessage,
      );
      setBulkAction(undefined);
      await load();
    } catch (reason) {
      setBulkError(
        reason instanceof Error ? reason.message : t("批量更新失败，请稍后重试。"),
      );
    } finally {
      setBulkBusy(false);
    }
  };
  const deleteSelectedProducts = async () => {
    if (!canDelete || !selectedProductIds.size) return;
    setDeleteBusy(true);
    setBulkError("");
    try {
      const selectedIds = [...selectedProductIds];
      const response = await batchDeleteProducts(selectedIds);
      const failedIds = new Set(response.failedItems.map((item) => item.productId));
      setSelectedProductIds(failedIds);
      setBulkNotice(
        response.failedCount
          ? t("已删除 {products} 个商品（包含 {skus} 个 SKU），{failed} 个商品未能删除。", {
              products: response.deletedProductCount,
              skus: response.deletedSkuCount,
              failed: response.failedCount,
            })
          : t("已删除 {products} 个商品（包含 {skus} 个 SKU）。", {
              products: response.deletedProductCount,
              skus: response.deletedSkuCount,
            }),
      );
      setDeleteDialogOpen(false);
      const remainingTotal = Math.max(0, result.total - response.successCount);
      const lastAvailablePage = Math.max(1, Math.ceil(remainingTotal / pageSize));
      if (page > lastAvailablePage) {
        setPage(lastAvailablePage);
      } else {
        await load();
      }
    } catch (reason) {
      setBulkError(reason instanceof Error ? reason.message : t("批量删除商品失败，请稍后重试。"));
    } finally {
      setDeleteBusy(false);
    }
  };
  const requestSingleDelete = (sku: SkuListItem) => {
    if (!canDelete) return;
    setSingleDeleteError("");
    setSingleDeleteTarget(sku);
  };
  const deleteSingleSku = async () => {
    if (!canDelete || !singleDeleteTarget) return;
    setSingleDeleteBusy(true);
    setSingleDeleteError("");
    try {
      const target = singleDeleteTarget;
      const response = await batchDeleteSkus([target.id]);
      if (response.failedCount || response.successCount !== 1) {
        throw new Error(response.failedItems[0]?.reason || t("单个 SKU 删除失败，请稍后重试。"));
      }
      setSelectedProductIds((current) => {
        const next = new Set(current);
        next.delete(target.id);
        return next;
      });
      setSingleDeleteTarget(undefined);
      setBulkNotice(t("已删除 SKU {code}。", { code: target.skuCode }));
      const remainingTotal = Math.max(0, result.total - 1);
      const lastAvailablePage = Math.max(1, Math.ceil(remainingTotal / pageSize));
      if (page > lastAvailablePage) {
        setPage(lastAvailablePage);
      } else {
        await load();
      }
    } catch (reason) {
      setSingleDeleteError(
        reason instanceof Error ? reason.message : t("单个 SKU 删除失败，请稍后重试。"),
      );
    } finally {
      setSingleDeleteBusy(false);
    }
  };
  const setDeleteAllOpen = (open: boolean) => {
    if (!canDelete || deleteAllBusy) return;
    setDeleteAllDialogOpen(open);
    setDeleteAllPassword("");
    setDeleteAllError("");
    setDeleteAllProgress(0);
    setDeleteAllStage("QUEUED");
  };
  const deleteEveryProduct = async () => {
    if (!canDelete || !deleteAllPassword) return;
    setDeleteAllBusy(true);
    setDeleteAllError("");
    try {
      let response = await deleteAllProducts(deleteAllPassword);
      setDeleteAllProgress(response.progress);
      setDeleteAllStage(response.stage);
      let consecutivePollingFailures = 0;
      while (["QUEUED", "RUNNING"].includes(response.status)) {
        await waitForDeletePoll();
        try {
          response = await getDeleteAllProductsJob(response.id);
          consecutivePollingFailures = 0;
          setDeleteAllProgress(response.progress);
          setDeleteAllStage(response.stage);
        } catch (reason) {
          consecutivePollingFailures += 1;
          if (consecutivePollingFailures < 5) continue;
          throw new Error(
            reason instanceof Error
              ? t("删除任务已提交，但暂时无法读取进度：{message}", { message: reason.message })
              : t("删除任务已提交，但暂时无法读取进度，请稍后再次打开此操作查看。"),
          );
        }
      }
      if (response.status === "FAILED") {
        throw new Error(response.errorMessage || t("全部商品删除失败，数据未被完整提交，请稍后重试。"));
      }
      setSelectedProductIds(new Set());
      setDeleteDialogOpen(false);
      setDeleteAllDialogOpen(false);
      setDeleteAllPassword("");
      setBulkNotice(
        t("已删除当前商家的全部商品，共 {products} 个商品、{skus} 个 SKU。", {
          products: response.deletedProductCount,
          skus: response.deletedSkuCount,
        }),
      );
      if (page === 1) await load();
      else setPage(1);
    } catch (reason) {
      setDeleteAllError(
        reason instanceof Error ? t(reason.message) : t("全部商品删除失败，请稍后重试。"),
      );
    } finally {
      setDeleteAllBusy(false);
    }
  };
  const downloadIssueDetails = async (job: ImportJob) => {
    setImportError("");
    try {
      const completeJob = (
        job.resultDetails.issueTotal > job.resultDetails.issues.length
          ? await getImport(job.id)
          : job
      );
      setLastImport(completeJob);
      setLoadedWarningJobId(completeJob.id);
      exportImportIssues(completeJob);
    } catch (reason) {
      setImportError(reason instanceof Error ? reason.message : t("失败明细下载失败"));
    }
  };
  const exportCatalog = async () => {
    if (!result.total || exportBusy) return;
    setExportBusy(true);
    setError("");
    try {
      await exportSkuCatalog({
        q: debouncedQuery.trim() || undefined,
        categoryId: categoryId || undefined,
        statuses: undefined,
        missingImagesOnly,
      });
      setBulkNotice(t("已导出当前筛选条件下的 SKU 数据；无 SKU 商品仍保留在商品列表中。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("SKU 商品库导出失败"));
    } finally {
      setExportBusy(false);
    }
  };
  const rangeStart = result.total ? (result.page - 1) * result.pageSize + 1 : 0;
  const rangeEnd = Math.min(result.page * result.pageSize, result.total);
  const paginationItems = useMemo(
    () => skuPaginationItems(result.page, result.pages),
    [result.page, result.pages],
  );
  const changePageSize = (value: string) => {
    const next = SKU_PAGE_SIZE_OPTIONS.find((option) => option === Number(value));
    if (!next || next === pageSize) return;
    setPageSize(next);
    setPage(1);
    window.localStorage.setItem(SKU_PAGE_SIZE_STORAGE_KEY, String(next));
  };
  const rootCategories = useMemo(
    () => categories
      .filter((item) => !item.parentId && item.status !== "ARCHIVED")
      .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, locale)),
    [categories, locale],
  );
  const bulkCategoryOptions = useMemo(
    () => rootCategories.flatMap((root) => [
      { id: root.id, label: root.name },
      ...categories
        .filter((item) => item.parentId === root.id && item.status !== "ARCHIVED")
        .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, locale))
        .map((child) => ({ id: child.id, label: `${root.name} / ${child.name}` })),
    ]),
    [categories, locale, rootCategories],
  );
  const createCategoryOptions = useMemo(
    () => rootCategories
      .filter((root) => root.status === "ACTIVE")
      .flatMap((root) => [
        { id: root.id, label: root.name },
        ...categories
          .filter((item) => item.parentId === root.id && item.status === "ACTIVE")
          .sort((left, right) => left.sortOrder - right.sortOrder || left.name.localeCompare(right.name, locale))
          .map((child) => ({ id: child.id, label: `${root.name} / ${child.name}` })),
      ]),
    [categories, locale, rootCategories],
  );
  const hasActiveFilters = Boolean(query.trim() || categoryId || status || missingImagesOnly);
  const bulkActionTitle = bulkAction === "category"
    ? t("批量修改商品分类")
    : bulkAction === "pin"
    ? t("置顶所选商品？")
    : bulkAction === "unpin"
    ? t("取消置顶所选商品？")
    : bulkAction === "activate"
    ? t("上架所选 SKU？")
    : t("下架所选 SKU？");
  const bulkActionDescription = bulkAction === "category"
    ? t("将所选商品移到目标分类。")
    : bulkAction === "pin" || bulkAction === "unpin"
    ? t("置顶状态会应用到商品。")
    : t("将更新 {count} 个商品。", { count: selectedProductIds.size });
  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("SKU 商品库")}
        actions={<>
          <Button variant="soft" disabled={!result.total || exportBusy} loading={exportBusy} onClick={() => void exportCatalog()}><DownloadSimple />{t("导出 SKU 数据")}</Button>
          {canCreate ? <Button onClick={() => setCreateOpen(true)}><Plus />{t("新建商品")}</Button> : null}
          {canImport ? <Button variant="soft" onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入与撤回")}</Button> : null}
          {canImport || canDelete ? (
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <Button variant="soft" color="gray"><DotsThree />{t("更多")}</Button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="end">
                {canImport ? <DropdownMenu.Item asChild><a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a></DropdownMenu.Item> : null}
                {canImport && canDelete ? <DropdownMenu.Separator /> : null}
                {canDelete ? <DropdownMenu.Item color="red" onSelect={() => setDeleteAllOpen(true)}><Trash />{t("删除全部商品")}</DropdownMenu.Item> : null}
              </DropdownMenu.Content>
            </DropdownMenu.Root>
          ) : null}
        </>}
      />
      <Card className="core-sku-toolbar">
        <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索商品名称、产品编码或 SKU")} aria-label={t("搜索商品库")}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        <select value={categoryId} onChange={(event) => { setCategoryId(event.target.value); setPage(1); }} aria-label={t("按分类筛选")}>
          <option value="">{t("全部分类")}</option>
          {bulkCategoryOptions.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
        </select>
        <select value={status} onChange={(event) => { setStatus(event.target.value as "" | ProductStatus); setPage(1); }} aria-label={t("按商品状态筛选")}>
          <option value="">{t("全部状态")}</option>
          <option value="ACTIVE">{t("在售")}</option>
          <option value="DRAFT">{t("草稿")}</option>
          <option value="IN_REVIEW">{t("待审核")}</option>
          <option value="ARCHIVED">{t("已归档")}</option>
        </select>
        <select value={missingImagesOnly ? "missing" : ""} onChange={(event) => { setMissingImagesOnly(event.target.value === "missing"); setPage(1); }} aria-label={t("按图片状态筛选")}>
          <option value="">{t("全部图片")}</option>
          <option value="missing">{t("未上传图片")}</option>
        </select>
        <div className="core-sku-toolbar-actions">
          {hasActiveFilters ? <Button variant="ghost" color="gray" onClick={resetFilters}>{t("清除")}</Button> : null}
          <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}><ArrowsClockwise />{t("刷新")}</Button>
        </div>
      </Card>
      {bulkNotice ? (
        <Card className="core-sku-bulk-result" role="status">
          <CheckCircle weight="fill" />
          <Text size="2">{bulkNotice}</Text>
          <Button size="1" variant="ghost" color="gray" onClick={() => setBulkNotice("")} aria-label={t("关闭")}><X /></Button>
        </Card>
      ) : null}
      {canDelete && selectedProductIds.size > 0 ? (
        <Card className="core-sku-bulk-bar">
          <div>
            <Text size="2" weight="bold">{t("已选 {count} 个商品", { count: selectedProductIds.size })}</Text>
          </div>
          <div className="core-sku-bulk-actions">
            {canEdit ? <Button size="2" variant="soft" color="blue" onClick={openImageEnhancementForProducts}><Sparkle />{t("图片变清晰")}</Button> : null}
            <Button size="2" color="red" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(true)}><Trash />{t("删除已选商品")}</Button>
            <Button size="2" variant="ghost" color="gray" onClick={clearProductSelection}><X />{t("取消选择")}</Button>
          </div>
        </Card>
      ) : null}
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result.items.length ? <CoreLoading label={t("正在读取商品库")} /> : null}
      {!loading && !result.items.length && !error ? (
        hasActiveFilters
          ? <CoreEmpty title={t("没有符合条件的商品")} description={t("请调整筛选条件。")} action={<Button variant="soft" onClick={resetFilters}>{t("清除筛选")}</Button>} />
          : <CoreEmpty
              title={t("商品库还是空的")}
              description={t("可以新建商品或从 Excel 导入。")}
              action={canCreate || canImport ? <div className="core-empty-actions">{canCreate ? <Button onClick={() => setCreateOpen(true)}><Plus />{t("新建商品")}</Button> : null}{canImport ? <Button asChild variant="soft" color="gray"><a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a></Button> : null}{canImport ? <Button variant="soft" onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入与撤回")}</Button> : null}</div> : undefined}
            />
      ) : null}
      {result.items.length ? (
        <section className="core-sku-data-panel" aria-label={t("商品列表")}>
          <header className="core-sku-table-summary" aria-live="polite">
            <Text size="2">
              {t("共 {total} 个商品 · 当前显示 {start}–{end}", {
                total: result.total.toLocaleString(locale),
                start: rangeStart,
                end: rangeEnd,
              })}
            </Text>
            <div>{loading ? <Text size="1" color="gray">{t("正在更新结果…")}</Text> : null}</div>
          </header>
          <div className={`core-sku-table-scroll${loading ? " is-loading" : ""}`}>
            <table className="core-sku-data-table">
              <thead>
                <tr>
                  {canDelete ? (
                    <th className="core-sku-select-column" scope="col">
                      <Checkbox
                        checked={allCurrentPageSelected ? true : currentPageSelected.length ? "indeterminate" : false}
                        onCheckedChange={toggleCurrentPageSelection}
                        aria-label={t(allCurrentPageSelected ? "取消选择本页全部商品" : "选择本页全部商品")}
                      />
                    </th>
                  ) : null}
                  <th className="core-sku-image-column" scope="col">{t("图片")}</th>
                  <th className="core-sku-product-column" scope="col">{t("商品")}</th>
                  <th className="core-sku-category-column" scope="col">{t("分类")}</th>
                  <th className="core-sku-tags-column" scope="col">{t("标签")}</th>
                  <th className="core-sku-order-column" scope="col">{t("SKU / 供应商")}</th>
                  <th className="core-sku-price-column" scope="col">{t("当前价格")}</th>
                  <th className="core-sku-status-column" scope="col">{t("状态")}</th>
                  <th className="core-sku-updated-column" scope="col">{t("更新时间")}</th>
                  <th className="core-sku-action-column" scope="col">{t("操作")}</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((product) => (
                  <tr
                    key={product.id}
                    data-selected={selectedProductIds.has(product.id) || undefined}
                    tabIndex={0}
                    onClick={() => void openProduct(product.id)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") void openProduct(product.id);
                    }}
                    aria-label={t("打开商品 {name} 的详情", { name: product.name })}
                  >
                    {canDelete ? (
                      <td
                        className="core-sku-select-column"
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <Checkbox
                          checked={selectedProductIds.has(product.id)}
                          onCheckedChange={() => toggleProductSelection(product.id)}
                          aria-label={t(selectedProductIds.has(product.id) ? "取消选择商品 {name}" : "选择商品 {name}", { name: product.name })}
                        />
                      </td>
                    ) : null}
                    <td className="core-sku-image-column">
                      <ProductThumbnail
                        product={product}
                        label={t(product.imageStatus === "APPROVED" ? "图片已批准" : product.imageStatus === "SOURCE" ? "仅来源图" : "暂无图片")}
                      />
                    </td>
                    <td className="core-sku-product-column">
                      <strong title={product.name}>{product.name}</strong>
                      <small title={product.productCode || undefined}>
                        {product.productCode || t("未设置产品编码")}
                        {product.skuCount ? ` · ${t("{count} 个 SKU", { count: product.skuCount })}` : ` · ${t("暂无 SKU")}`}
                        {product.capabilities.includes("edit") && product.status === "ACTIVE" ? <span className="core-sku-pinned"><PushPin weight="fill" />{t("可发布")}</span> : null}
                      </small>
                    </td>
                    <td className="core-sku-category-column" title={product.category}>
                      {product.category || t("未分类")}
                    </td>
                    <td className="core-sku-tags-column">
                      {product.tags.length ? (
                        <span className="core-sku-table-tags">
                          {product.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray" title={tag}>{tag}</Badge>)}
                          {product.tags.length > 2 ? <small>+{product.tags.length - 2}</small> : null}
                        </span>
                      ) : <span className="core-sku-table-empty">—</span>}
                    </td>
                    <td className="core-sku-order-column core-tabular">
                      <strong>{t("{count} 个 SKU", { count: product.skuCount })}</strong>
                      <small>{t("{count} 个供应商", { count: product.supplierCount })}</small>
                    </td>
                    <td className="core-sku-price-column core-tabular">
                      <strong>{product.price === undefined ? t("未设置") : `${product.currency ?? ""} ${product.price.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim()}</strong>
                      <small>{product.supplierCount ? t("已有供应来源") : t("尚无供应来源")}</small>
                    </td>
                    <td className="core-sku-status-column">
                      <Badge color={product.status === "ACTIVE" ? "jade" : product.status === "DRAFT" || product.status === "IN_REVIEW" ? "amber" : "gray"}>
                        {t(product.status === "ACTIVE" ? "在售" : product.status === "IN_REVIEW" ? "待审核" : product.status === "DRAFT" ? "草稿" : "已归档")}
                      </Badge>
                    </td>
                    <td className="core-sku-updated-column">
                      <strong>{skuUpdatedDate(product.updated)}</strong>
                    </td>
                    <td
                      className="core-sku-action-column"
                      onClick={(event) => event.stopPropagation()}
                      onKeyDown={(event) => event.stopPropagation()}
                    >
                      <Button
                        size="1"
                        variant="ghost"
                        onClick={() => void openProduct(product.id)}
                        aria-label={t("打开商品 {name} 的详情", { name: product.name })}
                      >
                        {t("商品详情")}
                      </Button>
                      {canEdit ? (
                        <Button
                          size="1"
                          variant="soft"
                          color="blue"
                          loading={translatingProductId === product.id}
                          disabled={Boolean(translatingProductId)}
                          onClick={() => void translateProduct(product)}
                          aria-label={t("重新翻译商品 {name}", { name: product.name })}
                        >
                          <Translate />{t("翻译")}
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <nav className="core-sku-pagination" aria-label={t("SKU 列表分页")}>
            <div className="core-sku-pagination-summary">
              <Text size="1" color="gray">
                {t("第 {page} / {pages} 页", { page: result.page, pages: result.pages })}
              </Text>
              <label className="core-sku-page-size-control">
                <span>{t("每页显示")}</span>
                <select value={pageSize} onChange={(event) => changePageSize(event.target.value)} disabled={loading}>
                  {SKU_PAGE_SIZE_OPTIONS.map((option) => <option key={option} value={option}>{t("{count} 条", { count: option })}</option>)}
                </select>
              </label>
            </div>
            <div className="core-sku-pagination-controls">
              <Button
                size="2"
                variant="soft"
                color="gray"
                disabled={loading || result.page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
                aria-label={t("上一页")}
              >
                <CaretLeft />
              </Button>
              {paginationItems.map((item) => typeof item === "number" ? (
                <Button
                  key={item}
                  size="2"
                  variant={item === result.page ? "solid" : "soft"}
                  color={item === result.page ? undefined : "gray"}
                  disabled={loading}
                  onClick={() => setPage(item)}
                  aria-current={item === result.page ? "page" : undefined}
                  aria-label={t("第 {page} 页", { page: item })}
                >
                  {item}
                </Button>
              ) : <span className="core-sku-pagination-ellipsis" key={item}>…</span>)}
              <Button
                size="2"
                variant="soft"
                color="gray"
                disabled={loading || result.page >= result.pages}
                onClick={() => setPage((current) => Math.min(result.pages, current + 1))}
                aria-label={t("下一页")}
              >
                <CaretRight />
              </Button>
            </div>
          </nav>
        </section>
      ) : null}

      <Dialog.Root
        open={Boolean(bulkAction)}
        onOpenChange={(open) => {
          if (!open && !bulkBusy) {
            setBulkAction(undefined);
            setBulkError("");
          }
        }}
      >
        <Dialog.Content className="core-sku-bulk-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("批量管理")}</Text>
              <Dialog.Title>{bulkActionTitle}</Dialog.Title>
              <Dialog.Description>{bulkActionDescription}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" disabled={bulkBusy} onClick={() => { setBulkAction(undefined); setBulkError(""); }} aria-label={t("关闭")}><X /></Button>
          </div>
          {bulkAction === "category" ? (
            <label className="core-bulk-category-field">
              <Text size="2" weight="medium">{t("目标分类")}</Text>
              <select value={bulkCategoryId} onChange={(event) => { setBulkCategoryId(event.target.value); setBulkError(""); }} disabled={bulkBusy} autoFocus>
                <option value="" disabled>{t("请选择分类")}</option>
                <option value={UNCLASSIFIED_CATEGORY_VALUE}>{t("未分类")}</option>
                {bulkCategoryOptions.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
              </select>
            </label>
          ) : null}
          {bulkError ? <div className="core-form-error" role="alert">{bulkError}</div> : null}
          <div className="core-dialog-actions">
            <Button variant="soft" color="gray" disabled={bulkBusy} onClick={() => { setBulkAction(undefined); setBulkError(""); }}>{t("取消")}</Button>
            <Button
              color={bulkAction === "deactivate" ? "amber" : bulkAction === "activate" ? "jade" : undefined}
              disabled={bulkBusy || !selectedProductIds.size || (bulkAction === "category" && !bulkCategoryId)}
              onClick={() => void applyBulkAction()}
            >
              {bulkAction === "category" ? <Folders /> : bulkAction === "pin" ? <PushPin /> : bulkAction === "unpin" ? <PushPinSlash /> : bulkAction === "activate" ? <ArrowUp /> : <ArrowDown />}
              {t(bulkBusy ? "正在更新…" : "确认更新")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={deleteDialogOpen} onOpenChange={(open) => { if (!deleteBusy) { setDeleteDialogOpen(open); if (!open) setBulkError(""); } }}>
        <Dialog.Content className="core-sku-delete-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("批量删除商品")}</Text>
              <Dialog.Title>{t("确认删除 {count} 个商品？", { count: selectedProductIds.size })}</Dialog.Title>
              <Dialog.Description>{t("删除后将不再展示这些商品及其 SKU。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>
          {bulkError ? <div className="core-form-error" role="alert">{bulkError}</div> : null}
          <div className="core-dialog-actions">
            <Button variant="soft" color="gray" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)}>{t("取消")}</Button>
            <Button color="red" disabled={deleteBusy || !selectedProductIds.size} onClick={() => void deleteSelectedProducts()}>
              <Trash />{t(deleteBusy ? "正在删除…" : "确认删除")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={Boolean(singleDeleteTarget)}
        onOpenChange={(open) => {
          if (!open && !singleDeleteBusy) {
            setSingleDeleteTarget(undefined);
            setSingleDeleteError("");
          }
        }}
      >
        <Dialog.Content className="core-sku-delete-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="red">{t("删除 SKU")}</Text>
              <Dialog.Title>{t("确认删除此 SKU？")}</Dialog.Title>
              <Dialog.Description>
                {singleDeleteTarget
                  ? t("删除后将不再展示 SKU {code}，商品历史业务数据会保留。", { code: singleDeleteTarget.skuCode })
                  : t("删除后将不再展示此 SKU。")}
              </Dialog.Description>
            </div>
            <Button
              variant="ghost"
              color="gray"
              disabled={singleDeleteBusy}
              onClick={() => setSingleDeleteTarget(undefined)}
              aria-label={t("关闭")}
            >
              <X />
            </Button>
          </div>
          {singleDeleteTarget ? (
            <Card className="core-sku-single-delete-summary">
              <Text size="2" weight="bold">{singleDeleteTarget.productName}</Text>
              <Text size="1" color="gray">{singleDeleteTarget.skuCode}</Text>
            </Card>
          ) : null}
          {singleDeleteError ? <div className="core-form-error" role="alert">{singleDeleteError}</div> : null}
          <div className="core-dialog-actions">
            <Button
              variant="soft"
              color="gray"
              disabled={singleDeleteBusy}
              onClick={() => setSingleDeleteTarget(undefined)}
            >
              {t("取消")}
            </Button>
            <Button color="red" disabled={singleDeleteBusy || !singleDeleteTarget} onClick={() => void deleteSingleSku()}>
              <Trash />{t(singleDeleteBusy ? "正在删除…" : "确认删除")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={deleteAllDialogOpen} onOpenChange={(open) => setDeleteAllOpen(open)}>
        <Dialog.Content className="core-sku-delete-dialog core-delete-all-dialog">
          <form onSubmit={(event) => { event.preventDefault(); void deleteEveryProduct(); }}>
            <div className="core-dialog-heading">
              <div>
                <Text size="1" color="red">{t("危险操作")}</Text>
                <Dialog.Title>{t("删除当前商家的全部商品？")}</Dialog.Title>
                <Dialog.Description>{t("这会删除当前商家的全部商品和 SKU，不受当前筛选条件影响。")}</Dialog.Description>
              </div>
              <Button type="button" variant="ghost" color="gray" disabled={deleteAllBusy} onClick={() => setDeleteAllOpen(false)} aria-label={t("关闭")}><X /></Button>
            </div>
            <Card className="core-notice core-delete-all-notice">
              <Warning size={22} />
              <div>
                <Text weight="bold" as="div">{t("商品会从所有展示与搜索入口隐藏")}</Text>
                <Text size="2" color="gray">{t("库存流水和历史报价会保留；以后重新导入相同 SKU 时仍可恢复商品。")}</Text>
              </div>
            </Card>
            <label className="core-delete-all-password" htmlFor="delete-all-products-password">
              <Text size="2" weight="medium">{t("输入当前登录密码以确认")}</Text>
              <TextField.Root
                id="delete-all-products-password"
                name="current-password"
                type="password"
                value={deleteAllPassword}
                onChange={(event) => { setDeleteAllPassword(event.target.value); setDeleteAllError(""); }}
                autoComplete="current-password"
                placeholder={t("当前登录密码")}
                disabled={deleteAllBusy}
                maxLength={1024}
                autoFocus
              />
            </label>
            {deleteAllBusy ? (
              <Card className="core-delete-all-progress" aria-live="polite">
                <div>
                  <Text size="2" weight="medium">{t(deleteAllStageLabel[deleteAllStage] ?? "正在删除全部商品")}</Text>
                  <Text size="1" color="gray" className="core-tabular">{deleteAllProgress}%</Text>
                </div>
                <Progress value={deleteAllProgress} color="red" />
                <Text size="1" color="gray">{t("任务已在后台执行，页面通过短请求刷新进度，不会再因长时间等待而超时。")}</Text>
              </Card>
            ) : null}
            {deleteAllError ? <div className="core-form-error" role="alert">{deleteAllError}</div> : null}
            <div className="core-dialog-actions">
              <Button type="button" variant="soft" color="gray" disabled={deleteAllBusy} onClick={() => setDeleteAllOpen(false)}>{t("取消")}</Button>
              <Button type="submit" color="red" disabled={deleteAllBusy || !deleteAllPassword}>
                <Trash />{t(deleteAllBusy ? "后台删除中 {progress}%" : "确认删除全部商品", { progress: deleteAllProgress })}
              </Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      {canCreate ? (
        <ManualProductDialog
          open={createOpen}
          categories={createCategoryOptions}
          managedTags={managedTags}
          defaultCurrency={profile?.context.defaultCurrency ?? "CNY"}
          onOpenChange={setCreateOpen}
          onCreated={handleManualCreated}
        />
      ) : null}

      {canImport ? <Dialog.Root open={importOpen} onOpenChange={setImportDialogOpen}>
        <Dialog.Content className="core-template-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("商品批量操作")}</Text>
              <Dialog.Title>{t("导入与撤回")}</Dialog.Title>
              <Dialog.Description>{t("一次导入多个商品文件，或撤回指定批次与分类。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => setImportDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>

          <Tabs.Root value={importTab} onValueChange={setImportTab}>
            <Tabs.List className="core-import-tabs">
              <Tabs.Trigger value="upload"><FileArrowUp />{t("批量导入")}</Tabs.Trigger>
              <Tabs.Trigger value="rollback"><ArrowsClockwise />{t("撤回导入")}</Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="upload" className="core-import-tab-content">

          <div className="core-import-template-row">
            <Text size="2" color="gray">{t("支持新版双表、历史模板和单元格内嵌图片；商品图片最多支持50张")}</Text>
            <Button asChild size="1" variant="soft" color="gray">
              <a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a>
            </Button>
          </div>

          <input
            ref={importInputRef}
            hidden
            type="file"
            multiple
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => void inspectTemplates(event.target.files ?? undefined)}
          />

          <button
            className={`core-template-dropzone ${importDragActive ? "is-dragging" : ""}`}
            type="button"
            disabled={importBusy}
            onClick={() => importInputRef.current?.click()}
            onDragEnter={(event) => { event.preventDefault(); setImportDragActive(true); }}
            onDragOver={(event) => { event.preventDefault(); setImportDragActive(true); }}
            onDragLeave={(event) => {
              event.preventDefault();
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setImportDragActive(false);
            }}
            onDrop={(event: DragEvent<HTMLButtonElement>) => {
              event.preventDefault();
              setImportDragActive(false);
              void inspectTemplates(event.dataTransfer.files);
            }}
          >
            <FileArrowUp size={30} />
            <strong>{t("拖入或选择多个商品文件")}</strong>
            <span>{t("支持 XLSX，单文件最大 250 MB，多文件会归入同一批次")}</span>
          </button>

          {importFiles.length ? (
            <div className="core-import-file-list">
              {importFiles.map((item) => {
                const statusLabel = item.status === "checking"
                  ? t("检查中")
                  : item.status === "ready"
                  ? t("待导入")
                  : item.status === "uploading"
                  ? t("上传中")
                  : item.status === "processing"
                  ? t("导入中")
                  : item.status === "published"
                  ? t("已完成")
                  : t("失败");
                return (
                  <Card key={item.id} className={`core-import-file ${item.status}`}>
                    <FileXls size={25} />
                    <div className="core-import-file-copy">
                      <Text weight="bold" size="2" as="div" title={item.file.name}>{item.file.name}</Text>
                      <Text size="1" color="gray">
                        {(item.file.size / 1024 / 1024).toFixed(2)} MB
                        {item.detection ? ` · ${item.detection.detected_type}` : ""}
                      </Text>
                      {item.error ? (
                        <Text
                          size="1"
                          color={item.status === "failed" ? "red" : item.status === "published" ? "jade" : "gray"}
                        >
                          {item.error}
                        </Text>
                      ) : null}
                      {["uploading", "processing"].includes(item.status) ? <Progress value={item.progress} /> : null}
                    </div>
                    <Badge color={item.status === "published" || item.status === "ready" ? "jade" : item.status === "failed" ? "red" : "blue"}>{statusLabel}</Badge>
                    <div className="core-import-file-actions">
                      {item.job ? (
                        <Button size="1" variant="ghost" color="gray" onClick={() => setLastImport(item.job)}>{t("详情")}</Button>
                      ) : null}
                      {item.status === "failed" && item.file.name.toLowerCase().endsWith(".xlsx") ? (
                        <Button
                          size="1"
                          variant="soft"
                          color="gray"
                          disabled={importBusy}
                          onClick={() => void retryImportFile(item)}
                          aria-label={t("重试文件")}
                        ><ArrowsClockwise />{t("重试")}</Button>
                      ) : null}
                      {!item.job || item.status === "failed" ? (
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          disabled={importBusy}
                          onClick={() => removeImportFile(item)}
                          aria-label={t("移除文件")}
                        ><X /></Button>
                      ) : null}
                    </div>
                  </Card>
                );
              })}
            </div>
          ) : null}

          {importBusy && importSubmitStage !== "idle" ? (
            <Card className="core-import-progress" aria-live="polite">
              <div className="core-import-progress-heading">
                <span>
                  <Text weight="bold" as="div">
                    {t(
                      importSubmitStage === "checking"
                        ? "正在检查文件"
                        : importSubmitStage === "uploading"
                        ? "正在上传商品文件"
                        : "文件上传完成，正在创建导入任务",
                    )}
                  </Text>
                  <Text size="1" color="gray">
                    {t(
                      importSubmitStage === "checking"
                        ? "正在确认文件类型与扩展名"
                        : importSubmitStage === "uploading"
                        ? "上传进度 {percent}%，请勿关闭页面"
                        : "服务器已收到文件，即将读取并校验商品数据",
                      { percent: uploadProgress },
                    )}
                  </Text>
                </span>
                <strong className="core-tabular">
                  {importSubmitStage === "uploading" ? `${uploadProgress}%` : importSubmitStage === "processing" ? "100%" : "…"}
                </strong>
              </div>
              <Progress value={importSubmitStage === "uploading" ? uploadProgress : importSubmitStage === "processing" ? 100 : undefined} />
            </Card>
          ) : null}

          {importError ? <CoreError message={importError} /> : importPollingError ? <CoreError message={importPollingError} onRetry={() => void refreshCurrentImport()} /> : null}
          {lastImport ? (
            <Card className={`core-template-result ${lastImport.status}`}>
              {lastImport.status === "published" ? <CheckCircle size={24} /> : lastImport.status === "failed" ? <Warning size={24} /> : <ArrowsClockwise size={24} />}
              <div>
                <Text weight="bold" as="div">{t(importStatusLabel[lastImport.status])} · {lastImport.filename}</Text>
                <Text size="2" color="gray">
                  {lastImport.status === "failed"
                    ? t("本次未写入商品 · 共发现 {count} 个问题", { count: lastImport.resultDetails.issueTotal || lastImport.warnings })
                    : (lastImport.resultDetails.skipped ?? 0) > 0
                    ? t("{products} 个 SKU 已处理 · {skipped} 行未导入 · {warnings} 条提醒", {
                        products: lastImport.products,
                        skipped: lastImport.resultDetails.skipped ?? 0,
                        warnings: lastImport.warnings,
                      })
                    : t("{products} 个 SKU 已处理 · {warnings} 条提醒", { products: lastImport.products, warnings: lastImport.warnings })}
                </Text>

                {lastImport.status === "scanning" || lastImport.status === "parsing" ? (
                  <div className="core-import-job-progress" aria-live="polite">
                    <span>
                      <Text size="1" weight="medium">
                        {t(
                          importStageLabel[lastImport.resultDetails.importStage ?? ""]
                          ?? (lastImport.status === "scanning" ? "正在读取上传文件" : "正在处理商品数据"),
                        )}
                      </Text>
                      <strong className="core-tabular">{lastImport.progress}%</strong>
                    </span>
                    <Progress value={lastImport.progress} />
                    {lastImport.resultDetails.totalRows ? (
                      <Text size="1" color="gray">
                        {t("已处理 {processed} / {total} 行", {
                          processed: lastImport.resultDetails.processedRows ?? 0,
                          total: lastImport.resultDetails.totalRows,
                        })}
                      </Text>
                    ) : null}
                  </div>
                ) : null}

                {lastImport.errorMessage ? <Text size="1" color="gray" className="core-import-result-message">{lastImport.errorMessage}</Text> : null}

                {lastImport.resultDetails.issueTotal > 0 ? (
                  <section className="core-import-issues">
                    <div className="core-import-issues-heading">
                      <span>
                        <Text weight="bold" as="div">{t("无法导入的详细信息")}</Text>
                        <Text size="1" color="gray">
                          {lastImport.status === "published"
                            ? t("本次共跳过 {count} 行；其余额度内数据已正常写入。", {
                                count: lastImport.resultDetails.skipped ?? lastImport.resultDetails.issueTotal,
                              })
                            : t("共 {count} 个问题；请修正后重新上传，当前商品库未发生变化。", { count: lastImport.resultDetails.issueTotal })}
                        </Text>
                      </span>
                      <Button size="1" variant="soft" color="gray" onClick={() => void downloadIssueDetails(lastImport)}>
                        <DownloadSimple />{t("下载失败明细")}
                      </Button>
                    </div>
                    {lastImport.resultDetails.issueTotal > lastImport.resultDetails.issues.length ? (
                      <Text size="1" color="gray">{t("正在加载全部 {count} 条明细…", { count: lastImport.resultDetails.issueTotal })}</Text>
                    ) : null}
                    <div className="core-import-issue-list">
                      {lastImport.resultDetails.issues.map((issue, index) => (
                        <article key={`${issue.rowNumber ?? "file"}:${issue.column}:${issue.code}:${index}`}>
                          <div className="core-import-issue-meta">
                            <Badge color={lastImport.status === "published" ? "amber" : "red"} variant="soft">
                              {issue.rowNumber ? t("第 {row} 行", { row: issue.rowNumber }) : t("文件级")}
                            </Badge>
                            <strong>{issue.column}</strong>
                            <code>{issue.code}</code>
                          </div>
                          <p>{issue.message}</p>
                          {issue.value ? <small><span>{t("原值")}</span><code>{issue.value}</code></small> : null}
                          {issue.suggestion ? <small><span>{t("修改建议")}</span>{issue.suggestion}</small> : null}
                        </article>
                      ))}
                    </div>
                  </section>
                ) : null}

                {lastImport.warnings > 0 && lastImport.status === "published" ? (
                  <details
                    className="core-template-warnings"
                    onToggle={(event) => {
                      if (
                        event.currentTarget.open
                        && loadedWarningJobId !== lastImport.id
                        && lastImport.warningMessages.length < lastImport.warnings
                      ) {
                        setLoadedWarningJobId(lastImport.id);
                        void getImport(lastImport.id)
                          .then(setLastImport)
                          .catch(() => setLoadedWarningJobId(undefined));
                      }
                    }}
                  >
                    <summary>
                      {loadedWarningJobId === lastImport.id
                        && lastImport.warningMessages.length < lastImport.warnings
                        ? `查看已记录的 ${lastImport.warningMessages.length} 条提醒（另 ${lastImport.warnings - lastImport.warningMessages.length} 条仅计数）`
                        : lastImport.warningMessages.length < lastImport.warnings
                        ? `加载提醒详情（共 ${lastImport.warnings} 条）`
                        : `查看全部 ${lastImport.warningMessages.length} 条提醒`}
                    </summary>
                    {lastImport.warningMessages.length
                      ? <ol>{lastImport.warningMessages.map((message, index) => <li key={`${index}:${message}`}>{message}</li>)}</ol>
                      : <Text size="1" color="gray">{t("展开后读取提醒详情。")}</Text>}
                  </details>
                ) : null}
                {lastImport.status === "published" ? (
                  <div className="core-index-reminder">
                    <Sparkle aria-hidden="true" />
                    <div>
                      <Text size="2" weight="medium" as="div">{t("商品资料已更新，智能索引尚未同步")}</Text>
                      <Text size="1" color="gray">{t("需要使用新商品参与 AI 搜索时，请前往 AI 搜索管理执行增量更新。")}</Text>
                    </div>
                    <Button asChild size="1" variant="soft">
                      <Link to="/console/ai-search/manage">{t("前往 AI 搜索管理")}</Link>
                    </Button>
                  </div>
                ) : null}
              </div>
            </Card>
          ) : null}

          <div className="core-dialog-actions">
            {importFiles.length ? <Button variant="soft" color="gray" disabled={importBusy} onClick={() => importInputRef.current?.click()}><Plus />{t("继续添加")}</Button> : null}
            <Button
              disabled={!importFiles.some((item) => item.status === "ready") || importBusy}
              onClick={() => void importTemplates()}
            >
              <FileArrowUp />{importBusy
                ? t("正在处理…")
                : t("导入 {count} 个文件", { count: importFiles.filter((item) => item.status === "ready").length })}
            </Button>
          </div>
            </Tabs.Content>

            <Tabs.Content value="rollback" className="core-import-tab-content">
              <div className="core-import-rollback-toolbar">
                <div>
                  <Text weight="bold" as="div">{t("按批次或分类撤回")}</Text>
                  <Text size="1" color="gray">{t("只撤回该批次新建且之后未被其他导入批次接管的 SKU；既有 SKU 不会被删除。")}</Text>
                </div>
                <Button size="1" variant="soft" color="gray" disabled={importBatchesLoading} onClick={() => void loadImportBatches()}>
                  <ArrowsClockwise />{t("刷新")}
                </Button>
              </div>

              {rollbackError && !rollbackTarget ? <CoreError message={rollbackError} onRetry={() => void loadImportBatches()} /> : null}
              {rollbackResult ? (
                <Card className="core-import-rollback-result" role="status">
                  <CheckCircle weight="fill" />
                  <div>
                    <Text weight="bold" as="div">{t("撤回完成")}</Text>
                    <Text size="1" color="gray">
                      {t("已撤回 {skus} 个由该批次新建的 SKU，并归档 {products} 个不再包含有效 SKU 的商品。", {
                        skus: rollbackResult.deletedSkuCount,
                        products: rollbackResult.archivedProductCount,
                      })}
                    </Text>
                  </div>
                </Card>
              ) : null}

              {importBatchesLoading && !importBatches.length ? <CoreLoading label={t("正在读取导入批次")} /> : importBatches.length ? (
                <div className="core-import-batch-layout">
                  <div className="core-import-batch-list" role="list">
                    {importBatches.map((batch) => {
                      const running = batch.jobs.some((job) => ["scanning", "parsing"].includes(job.status));
                      return (
                        <button
                          key={batch.id}
                          type="button"
                          className={rollbackBatchId === batch.id ? "is-selected" : ""}
                          onClick={() => { setRollbackBatchId(batch.id); setRollbackCategoryId(""); setRollbackResult(undefined); }}
                        >
                          <span>
                            <strong>{new Intl.DateTimeFormat(locale === "zh-CN" ? "zh-CN" : "en", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(batch.createdAt))}</strong>
                            <small>{batch.jobs.map((job) => job.filename).join("、") || t("等待上传文件")}</small>
                          </span>
                          <span>
                            <Badge color={batch.status === "REVOKED" ? "gray" : running ? "blue" : batch.status === "PARTIALLY_REVOKED" ? "amber" : "jade"}>
                              {batch.status === "REVOKED" ? t("已撤回") : running ? t("导入中") : batch.status === "PARTIALLY_REVOKED" ? t("部分撤回") : t("可撤回")}
                            </Badge>
                            <small>{t("{files} 个文件 · {skus} 个 SKU", { files: batch.fileCount, skus: batch.remainingSkuCount })}</small>
                          </span>
                        </button>
                      );
                    })}
                  </div>

                  {selectedRollbackBatch ? (
                    <Card className="core-import-rollback-panel">
                      <div>
                        <Text weight="bold" as="div">{t("撤回范围")}</Text>
                        <Text size="1" color="gray">{selectedRollbackBatch.jobs.map((job) => job.filename).join("、")}</Text>
                      </div>
                      <label>
                        <Text size="2" weight="medium">{t("选择范围")}</Text>
                        <select value={rollbackCategoryId} onChange={(event) => setRollbackCategoryId(event.target.value)}>
                          <option value="">{t("整个批次（当前可撤回 {count} 个 SKU）", { count: selectedRollbackBatch.remainingSkuCount })}</option>
                          {selectedRollbackBatch.categories.map((category) => (
                            <option key={category.id} value={category.id}>{category.name}（{category.skuCount}）</option>
                          ))}
                        </select>
                      </label>
                      <Text size="1" color="gray">
                        {t("撤回不会恢复字段历史值；只会删除可确认由该批次新建且未被后续批次接管的 SKU。")}
                      </Text>
                      <Button
                        color="red"
                        disabled={
                          selectedRollbackBatch.status === "REVOKED"
                          || (selectedRollbackBatch.remainingSkuCount === 0 && selectedRollbackBatch.status !== "PARTIALLY_REVOKED")
                          || selectedRollbackBatch.jobs.some((job) => ["scanning", "parsing"].includes(job.status))
                        }
                        onClick={requestRollback}
                      >
                        <Trash />{t(rollbackCategoryId ? "撤回这个分类" : "撤回整个批次")}
                      </Button>
                    </Card>
                  ) : null}
                </div>
              ) : (
                <CoreEmpty title={t("暂无可撤回的导入批次")} description={t("通过“批量导入”上传的文件会显示在这里。")}/>
              )}
            </Tabs.Content>
          </Tabs.Root>
        </Dialog.Content>
      </Dialog.Root> : null}

      <Dialog.Root open={Boolean(rollbackTarget)} onOpenChange={(open) => { if (!open && !rollbackBusy) setRollbackTarget(undefined); }}>
        <Dialog.Content className="core-confirm-dialog">
          <Dialog.Title>{t(rollbackCategoryId ? "确认撤回这个分类？" : "确认撤回整个批次？")}</Dialog.Title>
          <Dialog.Description>
            {rollbackCategoryId
              ? t("只会删除所选分类中由该批次新建且未被后续批次接管的 SKU；既有 SKU 与无法确认归属的图片不会被删除。")
              : t("只会删除该批次新建且未被后续批次接管的 SKU；既有 SKU 与无法确认归属的图片不会被删除。")}
          </Dialog.Description>
          {rollbackError ? <CoreError message={rollbackError} /> : null}
          <div className="core-dialog-actions">
            <Button variant="soft" color="gray" disabled={rollbackBusy} onClick={() => setRollbackTarget(undefined)}>{t("取消")}</Button>
            <Button color="red" loading={rollbackBusy} disabled={rollbackBusy} onClick={() => void executeRollback()}><Trash />{t("确认撤回")}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={Boolean(selected || detailLoading)} onOpenChange={(open) => { if (!open) close(); }}>
        <Dialog.Content className="core-detail-dialog">
          {detailLoading || !selected ? <CoreLoading label={t("正在读取商品详情")} /> : <ProductDetailPanel product={selected} selectedSkuId={selectedSkuId} managedTags={managedTags} onEnhanceProduct={openImageEnhancementForProduct} onEnhanceSkus={openImageEnhancementForSkus} onTranslateProduct={translateProduct} translatingProductId={translatingProductId} onChanged={async () => { await refreshSelected(); await load(); }} onClose={close} />}
        </Dialog.Content>
      </Dialog.Root>

      <CatalogShareDialog
        open={Boolean(shareTarget)}
        target={shareTarget}
        onOpenChange={(open) => { if (!open) setShareTarget(undefined); }}
      />
      <ImageEnhancementDialog
        open={imageEnhancementTargets.length > 0}
        targets={imageEnhancementTargets}
        onOpenChange={(open) => { if (!open) setImageEnhancementTargets([]); }}
        onApplied={async () => { await refreshSelected(); await load(); }}
      />
    </div>
  );
}

function ManualProductDialog({
  open,
  categories,
  managedTags,
  defaultCurrency,
  onOpenChange,
  onCreated,
}: {
  open: boolean;
  categories: Array<{ id: string; label: string }>;
  managedTags: ProductTag[];
  defaultCurrency: string;
  onOpenChange: (open: boolean) => void;
  onCreated: (product: ProductDetail) => void;
}) {
  const { t } = useLocale();
  const [publishToStorefront, setPublishToStorefront] = useState(true);
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setPublishToStorefront(true);
    setSelectedTags([]);
    setError("");
  }, [open]);

  const setOpen = (next: boolean) => {
    if (saving) return;
    if (!next) setError("");
    onOpenChange(next);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = (name: string) => String(data.get(name) ?? "").trim();
    const optionalNumber = (name: string) => {
      const raw = value(name);
      return raw ? Number(raw) : undefined;
    };
    const unitPrice = Number(value("unit_price") || "0");
    const defaultMoq = optionalNumber("default_moq");
    const packingQuantity = optionalNumber("packing_quantity");
    const weight = optionalNumber("weight");
    if (
      !Number.isFinite(unitPrice)
      || unitPrice < 0
      || (defaultMoq !== undefined && (!Number.isFinite(defaultMoq) || defaultMoq < 0))
      || (packingQuantity !== undefined && (!Number.isFinite(packingQuantity) || packingQuantity < 0))
      || (weight !== undefined && (!Number.isFinite(weight) || weight < 0))
    ) {
      setError(t("价格、起订数、装箱数和重量必须是大于或等于 0 的数字。"));
      return;
    }

    setSaving(true);
    setError("");
    try {
      const created = await createManualProduct({
        name: value("name"),
        productCode: value("product_code") || undefined,
        description: value("description") || undefined,
        categoryId: value("category_id") || undefined,
        defaultUnit: value("default_unit") || "piece",
        imageUrl: value("image_url") || undefined,
        skuCode: value("sku_code") || undefined,
        skuName: value("sku_name") || undefined,
        barcode: value("barcode") || undefined,
        defaultMoq,
        moqUnit: defaultMoq === undefined ? undefined : value("moq_unit") || undefined,
        packingQuantity,
        weight,
        weightUnit: weight === undefined ? undefined : value("weight_unit") || undefined,
        unitPrice,
        currency: value("currency") || defaultCurrency,
        tags: selectedTags,
        publishToStorefront,
      });
      onCreated(created);
    } catch (reason) {
      setError(reason instanceof Error ? t(reason.message) : t("商品创建失败，请稍后重试。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Content className="core-product-create-dialog">
        <div className="core-dialog-heading">
          <div>
            <Text size="1" color="gray">{t("手工录入")}</Text>
            <Dialog.Title>{t("新建商品")}</Dialog.Title>
            <Dialog.Description>{t("填写商品与首个 SKU。")}</Dialog.Description>
          </div>
          <Button type="button" variant="ghost" color="gray" disabled={saving} onClick={() => setOpen(false)} aria-label={t("关闭")}><X /></Button>
        </div>

        <form className="core-product-create-form" onSubmit={submit}>
          <div className="core-product-create-fields">
            <section className="core-product-create-section" aria-labelledby="manual-product-section-title">
              <div className="core-product-create-section-heading">
                <span><ImageSquare weight="duotone" /></span>
                <Heading id="manual-product-section-title" size="3">{t("商品资料")}</Heading>
              </div>
              <div className="core-product-create-grid">
                <label>
                  <Text size="2" weight="medium">{t("商品名称")} *</Text>
                  <TextField.Root name="name" required maxLength={500} autoFocus placeholder={t("例如 多功能宠物旅行包")} />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("商品分类")}</Text>
                  <select name="category_id" defaultValue="">
                    <option value="">{t("未分类")}</option>
                    {categories.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
                  </select>
                </label>
              </div>
            </section>

            <section className="core-product-create-section" aria-labelledby="manual-sku-section-title">
              <div className="core-product-create-section-heading">
                <span><Tag weight="duotone" /></span>
                <Heading id="manual-sku-section-title" size="3">{t("首个 SKU")}</Heading>
              </div>
              <div className="core-product-create-grid">
                <label>
                  <Text size="2" weight="medium">{t("原始 SKU 编号（可选）")}</Text>
                  <TextField.Root name="sku_code" maxLength={160} placeholder={t("留空自动生成")} />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("SKU 名称")}</Text>
                  <TextField.Root name="sku_name" maxLength={500} placeholder={t("留空则使用商品名称")} />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("公开售价")}</Text>
                  <TextField.Root name="unit_price" type="number" min="0" step="0.000001" defaultValue="0" inputMode="decimal" required />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("计价币种")}</Text>
                  <select name="currency" defaultValue={defaultCurrency}>
                    {[defaultCurrency, "CNY", "USD", "EUR", "GBP", "JPY", "KRW"].filter((item, index, values) => values.indexOf(item) === index).map((currency) => <option key={currency} value={currency}>{currency}</option>)}
                  </select>
                </label>
                <div className="is-wide core-product-create-tag-field">
                  <Text size="2" weight="medium">{t("标签")}</Text>
                  <ManagedTagPicker tags={managedTags} selected={selectedTags} onChange={setSelectedTags} />
                </div>
              </div>
            </section>

            <details className="core-product-create-more">
              <summary>{t("更多信息")}</summary>
              <div className="core-product-create-grid">
                <label>
                  <Text size="2" weight="medium">{t("商品编码")}</Text>
                  <TextField.Root name="product_code" maxLength={100} />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("计量单位")}</Text>
                  <TextField.Root name="default_unit" defaultValue="piece" maxLength={32} placeholder="piece" />
                </label>
                <label className="is-wide">
                  <Text size="2" weight="medium">{t("商品描述")}</Text>
                  <TextArea name="description" resize="vertical" maxLength={20000} />
                </label>
                <label className="is-wide">
                  <Text size="2" weight="medium">{t("主图链接")}</Text>
                  <TextField.Root name="image_url" type="url" maxLength={2048} placeholder="https://cdn.example.com/product.jpg" />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("条码")}</Text>
                  <TextField.Root name="barcode" maxLength={120} />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("起订数")}</Text>
                  <TextField.Root name="default_moq" type="number" min="0" step="0.000001" inputMode="decimal" />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("起订单位")}</Text>
                  <TextField.Root name="moq_unit" maxLength={32} placeholder="piece" />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("装箱数")}</Text>
                  <TextField.Root name="packing_quantity" type="number" min="0" step="0.000001" inputMode="decimal" />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("毛重")}</Text>
                  <TextField.Root name="weight" type="number" min="0" step="0.000001" inputMode="decimal" />
                </label>
                <label>
                  <Text size="2" weight="medium">{t("重量单位")}</Text>
                  <TextField.Root name="weight_unit" maxLength={32} placeholder="kg" />
                </label>
              </div>
            </details>

            <label className="core-product-create-publish">
              <Checkbox checked={publishToStorefront} onCheckedChange={(value) => setPublishToStorefront(value === true)} />
              <span><strong>{t("创建后立即上架")}</strong></span>
            </label>
          </div>

          {error ? <div className="core-form-error" role="alert">{error}</div> : null}
          <div className="core-dialog-actions core-product-create-actions">
            <Button type="button" variant="soft" color="gray" disabled={saving} onClick={() => setOpen(false)}>{t("取消")}</Button>
            <Button type="submit" loading={saving}><Plus />{t(saving ? "正在创建…" : "创建商品")}</Button>
          </div>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  );
}

function ManagedTagPicker({ tags, selected, onChange, disabled = false }: {
  tags: ProductTag[];
  selected: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
}) {
  const { t } = useLocale();
  const names = useMemo(() => {
    const values = new Map<string, string>();
    tags.forEach((tag) => values.set(tag.name.toLocaleLowerCase(), tag.name));
    selected.forEach((tag) => {
      const normalized = tag.toLocaleLowerCase();
      if (!values.has(normalized)) values.set(normalized, tag);
    });
    return [...values.values()];
  }, [selected, tags]);

  if (!names.length) {
    return (
      <div className="core-managed-tag-empty">
        <Text size="2" color="gray">{t("暂无标签")}</Text>
        <Button asChild size="1" variant="ghost"><Link to="/console/products/tags">{t("前往标签管理")}</Link></Button>
      </div>
    );
  }

  return (
    <div className="core-managed-tag-picker">
      {names.map((name) => {
        const checked = selected.some((tag) => tag.toLocaleLowerCase() === name.toLocaleLowerCase());
        return (
          <label className="core-managed-tag-option" data-selected={checked || undefined} key={name}>
            <Checkbox
              checked={checked}
              disabled={disabled}
              onCheckedChange={(value) => {
                if (value === true) onChange([...selected, name]);
                else onChange(selected.filter((tag) => tag.toLocaleLowerCase() !== name.toLocaleLowerCase()));
              }}
            />
            <span>{name}</span>
          </label>
        );
      })}
    </div>
  );
}

function ProductDetailPanel({ product, selectedSkuId, managedTags, onEnhanceProduct, onEnhanceSkus, onTranslateProduct, translatingProductId, onChanged, onClose }: {
  product: ProductDetail;
  selectedSkuId?: string;
  managedTags: ProductTag[];
  onEnhanceProduct: (productId: string) => void;
  onEnhanceSkus: (productId: string, skuIds: string[]) => void;
  onTranslateProduct: (product: CoreProduct) => void;
  translatingProductId?: string;
  onChanged: () => Promise<void>;
  onClose: () => void;
}) {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const imageInputRef = useRef<HTMLInputElement>(null);
  const imageDragDepthRef = useRef(0);
  const [imageUploading, setImageUploading] = useState(false);
  const [imageDownloading, setImageDownloading] = useState(false);
  const [imageDragging, setImageDragging] = useState(false);
  const [imageError, setImageError] = useState("");
  const [imageFailed, setImageFailed] = useState(false);
  const [activeTab, setActiveTab] = useState<"product" | "skus">(selectedSkuId ? "skus" : "product");
  const canEdit = hasPermission("product.edit");
  const canEnhanceImages = canEdit;

  useEffect(() => setImageFailed(false), [product.primaryImageUrl]);
  useEffect(() => {
    setActiveTab(selectedSkuId ? "skus" : "product");
    imageDragDepthRef.current = 0;
    setImageDragging(false);
    setImageError("");
  }, [product.id, selectedSkuId]);

  const uploadImage = async (file?: File) => {
    if (!file || imageUploading || !canEdit) return;
    setImageError("");
    const supportedExtension = /\.(png|jpe?g|webp)$/i.test(file.name);
    if ((file.type && !file.type.startsWith("image/")) || (!file.type && !supportedExtension)) {
      setImageError(t("请选择 PNG、JPG 或 WebP 图片。"));
      return;
    }
    if (file.size > 20 * 1024 * 1024) {
      setImageError(t("商品图片不能超过 20 MB。"));
      return;
    }
    setImageUploading(true);
    try {
      await uploadProductMainImage(product.id, file);
      await onChanged();
    } catch (reason) {
      setImageError(reason instanceof Error ? reason.message : t("商品图片上传失败"));
    } finally {
      setImageUploading(false);
      if (imageInputRef.current) imageInputRef.current.value = "";
    }
  };

  const downloadImage = async () => {
    if (imageDownloading || product.imageStatus === "NONE") return;
    const safeName = (product.productCode || product.name || "product-image")
      .replace(/[\\/:*?"<>|]/g, "-")
      .slice(0, 100);
    setImageDownloading(true);
    setImageError("");
    try {
      await downloadProductMainImage(product.id, `${safeName || "product-image"}-主图.webp`);
    } catch (reason) {
      setImageError(reason instanceof Error ? reason.message : t("商品图片下载失败"));
    } finally {
      setImageDownloading(false);
    }
  };

  const dragContainsFiles = (event: DragEvent<HTMLElement>) => (
    Array.from(event.dataTransfer.types).includes("Files")
  );
  const beginImageDrag = (event: DragEvent<HTMLElement>) => {
    if (!canEdit || imageUploading || !dragContainsFiles(event)) return;
    event.preventDefault();
    imageDragDepthRef.current += 1;
    setImageDragging(true);
  };
  const continueImageDrag = (event: DragEvent<HTMLElement>) => {
    if (!canEdit || imageUploading || !dragContainsFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setImageDragging(true);
  };
  const endImageDrag = (event: DragEvent<HTMLElement>) => {
    if (!canEdit) return;
    event.preventDefault();
    imageDragDepthRef.current = Math.max(0, imageDragDepthRef.current - 1);
    if (imageDragDepthRef.current === 0) setImageDragging(false);
  };
  const dropImage = (event: DragEvent<HTMLElement>) => {
    if (!canEdit) return;
    event.preventDefault();
    imageDragDepthRef.current = 0;
    setImageDragging(false);
    if (imageUploading || !dragContainsFiles(event)) return;
    void uploadImage(event.dataTransfer.files[0]);
  };
  return (
    <>
      <div className="core-dialog-heading core-product-detail-heading">
        <div>
          <Dialog.Title>{product.name}</Dialog.Title>
          <Dialog.Description>{product.productCode ?? t("未设置商品编码")} · {primaryCategoryLabel(product.category) || t("未分类")}</Dialog.Description>
        </div>
        <span className="core-product-detail-heading-actions">
          {canEdit ? (
            <Button
              size="2"
              variant="soft"
              color="blue"
              loading={translatingProductId === product.id}
              disabled={Boolean(translatingProductId)}
              onClick={() => onTranslateProduct(product)}
            >
              <Translate />{t("翻译")}
            </Button>
          ) : null}
          <Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button>
        </span>
      </div>
      <div className="core-product-detail-summary">
        <Badge color={product.status === "ACTIVE" ? "jade" : product.status === "DRAFT" || product.status === "IN_REVIEW" ? "amber" : "gray"}>{t(productStatusLabel[product.status as ProductStatus] ?? product.status)}</Badge>
        <Text size="2" color="gray">{t("{count} 个 SKU", { count: product.skus.length })}</Text>
      </div>
      <Tabs.Root
        className="core-product-detail-tabs-root"
        value={activeTab}
        onValueChange={(value) => setActiveTab(value as "product" | "skus")}
      >
        <Tabs.List className="core-product-detail-tabs" aria-label={t("选择详情类型")}>
          <Tabs.Trigger value="product"><ImageSquare />{t("商品详情")}</Tabs.Trigger>
          <Tabs.Trigger value="skus"><Tag />{t("SKU 详情")}<span className="core-product-detail-tab-count">{product.skus.length}</span></Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="product" className="core-product-detail-tab-panel">
          <div className="core-product-overview">
            <section
              className="core-product-image-editor"
              data-dragging={imageDragging || undefined}
              data-uploading={imageUploading || undefined}
              onDragEnter={beginImageDrag}
              onDragOver={continueImageDrag}
              onDragLeave={endImageDrag}
              onDrop={dropImage}
            >
              <div className="core-product-image-preview">
                {product.primaryImageUrl && !imageFailed ? (
                  <img src={product.primaryImageUrl} alt={product.name} onError={() => setImageFailed(true)} />
                ) : <ImageSquare aria-hidden="true" />}
                {imageDragging ? (
                  <span className="core-product-image-drop-state" aria-hidden="true">
                    <FileArrowUp weight="duotone" />
                    <strong>{t("松开即可替换商品主图")}</strong>
                  </span>
                ) : imageUploading ? (
                  <span className="core-product-image-drop-state is-uploading" aria-live="polite">
                    <FileArrowUp weight="duotone" />
                    <strong>{t("正在上传新图片…")}</strong>
                  </span>
                ) : null}
              </div>
              <div className="core-product-image-controls">
                <span className="core-product-image-copy">
                  <Text size="2" weight="bold">{t("商品主图")}</Text>
                  <Text size="1" color="gray">
                    {t(canEdit ? "拖入新图片即可替换" : "PNG、JPG 或 WebP，最大 20 MB")}
                  </Text>
                </span>
                <span className="core-product-image-actions">
                  {product.imageStatus !== "NONE" ? (
                    <Button size="2" variant="ghost" color="gray" disabled={imageDownloading || imageUploading} loading={imageDownloading} onClick={() => void downloadImage()}>
                      <DownloadSimple />{t("下载图片")}
                    </Button>
                  ) : null}
                  {canEnhanceImages ? (
                    <Button
                      size="2"
                      variant="soft"
                      color="purple"
                      disabled={product.imageStatus === "NONE" || imageUploading || imageDownloading}
                      onClick={() => onEnhanceProduct(product.id)}
                    >
                      <Sparkle />{t("图片变清晰")}
                    </Button>
                  ) : null}
                  {canEdit ? (
                    <Button size="2" variant="soft" disabled={imageUploading} loading={imageUploading} onClick={() => imageInputRef.current?.click()}>
                      <FileArrowUp />{t(product.imageStatus !== "NONE" ? "替换图片" : "上传图片")}
                    </Button>
                  ) : null}
                </span>
                <input
                  ref={imageInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  hidden
                  onChange={(event) => void uploadImage(event.target.files?.[0])}
                />
              </div>
              {imageError ? <div className="core-form-error" role="alert">{imageError}</div> : null}
            </section>
            <div className="core-product-overview-content">
              <dl className="core-product-facts">
                <div><dt>{t("商品编码")}</dt><dd className="core-tabular">{product.productCode || t("未设置")}</dd></div>
                <div><dt>{t("分类")}</dt><dd>{primaryCategoryLabel(product.category) || t("未分类")}</dd></div>
                <div><dt>{t("计量单位")}</dt><dd>{product.defaultUnit || t("未设置")}</dd></div>
                <div><dt>{t("供应商")}</dt><dd>{product.supplier || t("未设置")}</dd></div>
              </dl>
              <section className="core-product-description">
                <Text size="1" color="gray">{t("商品描述")}</Text>
                <p>{product.description || t("暂无描述")}</p>
              </section>
            </div>
          </div>
        </Tabs.Content>
        <Tabs.Content value="skus" className="core-product-detail-tab-panel">
          <SkuPanel product={product} initialSkuId={selectedSkuId} managedTags={managedTags} onEnhanceSkus={onEnhanceSkus} onChanged={onChanged} />
        </Tabs.Content>
      </Tabs.Root>
    </>
  );
}

function SkuPanel({ product, initialSkuId, managedTags, onEnhanceSkus, onChanged }: {
  product: ProductDetail;
  initialSkuId?: string;
  managedTags: ProductTag[];
  onEnhanceSkus: (productId: string, skuIds: string[]) => void;
  onChanged: () => Promise<void>;
}) {
  const { hasAnyPermission, hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEdit = hasPermission("product.edit");
  const canEnhanceImages = canEdit;
  const canViewCatalog = hasAnyPermission("catalog.view", "catalog.publish");
  const canPublish = hasAnyPermission("catalog.publish");
  const canManageSku = canEdit || canPublish;
  const [offers, setOffers] = useState<PublicCatalogOffer[]>([]);
  const [skuCode, setSkuCode] = useState("");
  const [skuName, setSkuName] = useState(product.name);
  const [skuMoq, setSkuMoq] = useState("");
  const [skuMoqUnit, setSkuMoqUnit] = useState(product.defaultUnit || "piece");
  const [skuPackingQuantity, setSkuPackingQuantity] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSkuId, setEditingSkuId] = useState<string>();
  const [expandedSkuIds, setExpandedSkuIds] = useState<Set<string>>(() => new Set(initialSkuId ? [initialSkuId] : []));
  const [busySkuId, setBusySkuId] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const [selectedSkuIds, setSelectedSkuIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    setEditingSkuId(undefined);
    setExpandedSkuIds(new Set(initialSkuId ? [initialSkuId] : []));
    setSelectedSkuIds(new Set());
  }, [initialSkuId, product.id]);
  const loadOffers = useCallback(async () => {
    if (!canViewCatalog) { setOffers([]); return; }
    try { setOffers(await listPublicCatalogOffers(product.id)); }
    catch { setOffers([]); }
  }, [canViewCatalog, product.id]);
  useEffect(() => { void loadOffers(); }, [loadOffers]);

  const createSingle = async () => {
    const defaultMoq = skuMoq.trim() ? Number(skuMoq) : undefined;
    const packingQuantity = skuPackingQuantity.trim() ? Number(skuPackingQuantity) : undefined;
    if (
      (defaultMoq !== undefined && (!Number.isFinite(defaultMoq) || defaultMoq < 0))
      || (packingQuantity !== undefined && (!Number.isFinite(packingQuantity) || packingQuantity < 0))
    ) {
      setError(t("起订数和装箱数必须是大于或等于 0 的数字。"));
      return;
    }
    setCreating(true);
    setError("");
    try {
      await createSkus(product.id, [{
        skuCode: skuCode.trim() || undefined,
        name: skuName.trim() || undefined,
        optionValues: {},
        defaultMoq,
        moqUnit: defaultMoq === undefined ? undefined : skuMoqUnit.trim() || undefined,
        packingQuantity,
        status: "DRAFT",
      }]);
      await onChanged();
      setSkuCode("");
      setSkuName(product.name);
      setSkuMoq("");
      setSkuMoqUnit(product.defaultUnit || "piece");
      setSkuPackingQuantity("");
      setCreateOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("SKU 创建失败"));
    } finally {
      setCreating(false);
    }
  };

  const changeStatus = async (sku: ProductSku, nextStatus: ProductSku["status"]) => {
    setBusySkuId(sku.id);
    setError("");
    try {
      await updateSku(sku.id, { expectedVersion: sku.version, status: nextStatus });
      await onChanged();
      await loadOffers();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("SKU 状态更新失败"));
    } finally {
      setBusySkuId(undefined);
    }
  };

  const toggleSkuDetails = (skuId: string) => {
    setExpandedSkuIds((current) => {
      const next = new Set(current);
      if (next.has(skuId)) next.delete(skuId);
      else next.add(skuId);
      return next;
    });
  };

  const editSku = (skuId: string) => {
    setExpandedSkuIds((current) => new Set(current).add(skuId));
    setEditingSkuId((current) => current === skuId ? undefined : skuId);
  };

  return (
    <section className="core-sku-detail-section">
      <div className="core-sku-detail-heading">
        <div>
          <Heading size="4">{t("SKU 详情")}</Heading>
          <Text size="1" color="gray">{t("共 {count} 个 SKU，可逐条展开查看", { count: product.skus.length })}</Text>
        </div>
        <div className="core-sku-detail-heading-actions">
          {canEnhanceImages ? <Button size="2" variant="soft" color="blue" disabled={!selectedSkuIds.size} onClick={() => { onEnhanceSkus(product.id, [...selectedSkuIds]); setSelectedSkuIds(new Set()); }}><Sparkle />{t("图片变清晰")}</Button> : null}
          {canEdit ? <Button size="2" variant={createOpen ? "soft" : "solid"} color={createOpen ? "gray" : undefined} onClick={() => setCreateOpen((open) => !open)}><Plus />{t(createOpen ? "取消" : "添加 SKU")}</Button> : null}
        </div>
      </div>
      {createOpen ? (
        <Card className="core-sku-create-compact">
          <label><Text size="1" color="gray">{t("原始 SKU 编号（可选）")}</Text><TextField.Root value={skuCode} onChange={(event) => setSkuCode(event.target.value)} placeholder={t("留空自动生成")} autoFocus /></label>
          <label><Text size="1" color="gray">{t("SKU 名称")}</Text><TextField.Root value={skuName} onChange={(event) => setSkuName(event.target.value)} /></label>
          <label><Text size="1" color="gray">{t("起订数")}</Text><TextField.Root type="number" min="0" step="0.000001" inputMode="decimal" value={skuMoq} onChange={(event) => setSkuMoq(event.target.value)} /></label>
          <label><Text size="1" color="gray">{t("起订单位")}</Text><TextField.Root maxLength={32} value={skuMoqUnit} onChange={(event) => setSkuMoqUnit(event.target.value)} placeholder="piece" /></label>
          <label><Text size="1" color="gray">{t("装箱数")}</Text><TextField.Root type="number" min="0" step="0.000001" inputMode="decimal" value={skuPackingQuantity} onChange={(event) => setSkuPackingQuantity(event.target.value)} /></label>
          <Button disabled={creating} onClick={() => void createSingle()}>{t(creating ? "正在添加…" : "添加")}</Button>
        </Card>
      ) : null}
      {error ? <div className="core-form-error" role="alert">{error}</div> : null}
      <div className="core-sku-detail-list">
        {product.skus.map((sku) => {
          const offer = offers.find((item) => item.skuId === sku.id);
          const editing = editingSkuId === sku.id;
          const expanded = expandedSkuIds.has(sku.id);
          const options = visibleSkuOptions(sku.optionValues);
          const skuLabel = sku.name || options.map(([, value]) => String(value)).join(" · ") || t("基础款");
          const packingQuantity = getSkuPackingQuantity(sku.optionValues);
          return (
            <Card className="core-sku-detail-card" data-expanded={expanded || undefined} data-editing={editing || undefined} key={sku.id}>
              <div className="core-sku-detail-row">
                {canEnhanceImages ? (
                  <span className="core-sku-select" onClick={(event) => event.stopPropagation()}>
                    <Checkbox
                      checked={selectedSkuIds.has(sku.id)}
                      onCheckedChange={(checked) => setSelectedSkuIds((current) => {
                        const next = new Set(current);
                        if (checked === true) next.add(sku.id); else next.delete(sku.id);
                        return next;
                      })}
                      aria-label={t(selectedSkuIds.has(sku.id) ? "取消选择 SKU {code}" : "选择 SKU {code}", { code: sku.skuCode })}
                    />
                  </span>
                ) : null}
                <button
                  type="button"
                  className="core-sku-detail-main"
                  aria-expanded={expanded}
                  aria-controls={`sku-details-${sku.id}`}
                  onClick={() => toggleSkuDetails(sku.id)}
                >
                  <Tag />
                  <span>
                    <strong>{sku.skuCode}</strong>
                    <small>{sku.sourceSkuCode ? `${t("来源 SKU")} ${sku.sourceSkuCode} · ` : ""}{skuLabel}</small>
                  </span>
                  <CaretDown className="core-sku-detail-caret" aria-hidden="true" />
                </button>
                <div className="core-sku-detail-tags">
                  {offer?.tags.slice(0, 3).map((tag) => <Badge color="gray" key={tag}>{tag}</Badge>)}
                  {offer && offer.tags.length > 3 ? <small>+{offer.tags.length - 3}</small> : null}
                  {!offer?.tags.length ? <small>—</small> : null}
                </div>
                <strong className="core-sku-detail-price core-tabular">{offer ? `${offer.currency} ${offer.unitPrice.toFixed(2)}` : "—"}</strong>
                <Badge color={offer?.publicationStatus === "PUBLISHED" ? "jade" : offer?.publicationStatus === "SUSPENDED" ? "amber" : "gray"}>
                  {t(offer ? offerStatusLabel[offer.publicationStatus] : "未发布")}
                </Badge>
                <Badge color={skuStatusColor(sku.status)}>{t(skuStatusLabel[sku.status])}</Badge>
                <div className="core-sku-detail-actions">
                  <Button size="1" variant="ghost" color="gray" onClick={() => toggleSkuDetails(sku.id)}>
                    <CaretDown className="core-sku-detail-action-caret" data-expanded={expanded || undefined} />{t(expanded ? "收起" : "展开")}
                  </Button>
                  {canManageSku ? <Button size="1" variant="soft" color="gray" onClick={() => editSku(sku.id)}><PencilSimple />{t(editing ? "取消编辑" : "编辑")}</Button> : null}
                  {canEdit ? (
                    <Button
                      size="1"
                      variant="ghost"
                      color={sku.status === "ACTIVE" ? "gray" : "jade"}
                      disabled={busySkuId === sku.id}
                      onClick={() => void changeStatus(sku, sku.status === "ACTIVE" ? "INACTIVE" : "ACTIVE")}
                    >
                      {t(sku.status === "ACTIVE" ? "下架" : "上架")}
                    </Button>
                  ) : null}
                </div>
              </div>
              {expanded ? (
                <div className="core-sku-expanded-details" id={`sku-details-${sku.id}`}>
                  <div className="core-sku-expanded-field is-wide">
                    <span>{t("规格")}</span>
                    {options.length ? (
                      <div className="core-sku-option-list">
                        {options.map(([name, value]) => <Badge key={name} color="gray">{name} · {String(value)}</Badge>)}
                      </div>
                    ) : <strong>{t("暂无规格")}</strong>}
                  </div>
                  <div className="core-sku-expanded-field"><span>{t("SKU 名称")}</span><strong>{sku.name || product.name}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("条码")}</span><strong className="core-tabular">{sku.barcode || t("未设置")}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("起订数")}</span><strong className="core-tabular">{sku.defaultMoq === undefined ? t("未设置") : `${sku.defaultMoq} ${sku.moqUnit ?? ""}`.trim()}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("装箱数")}</span><strong className="core-tabular">{packingQuantity || t("未设置")}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("毛重")}</span><strong className="core-tabular">{sku.weight === undefined ? t("未设置") : `${sku.weight} ${sku.weightUnit ?? ""}`.trim()}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("公开价")}</span><strong className="core-tabular">{offer ? `${offer.currency} ${offer.unitPrice.toFixed(2)}` : t("未设置")}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("最后更新")}</span><strong>{skuUpdatedDate(sku.updatedAt)}</strong></div>
                </div>
              ) : null}
              {editing && canManageSku ? (
                <SkuQuickEditor
                  sku={sku}
                  offer={offer}
                  managedTags={managedTags}
                  onCancel={() => setEditingSkuId(undefined)}
                  onRefresh={async () => { await loadOffers(); await onChanged(); }}
                  onChanged={async () => { await loadOffers(); await onChanged(); setEditingSkuId(undefined); }}
                />
              ) : null}
            </Card>
          );
        })}
        {!product.skus.length ? <CoreEmpty title={t("还没有 SKU")} description={t("点击“添加 SKU”开始创建。")} /> : null}
      </div>
    </section>
  );
}

function SkuQuickEditor({ sku, offer, managedTags, onChanged, onRefresh, onCancel }: {
  sku: ProductSku;
  offer?: PublicCatalogOffer;
  managedTags: ProductTag[];
  onChanged: () => Promise<void>;
  onRefresh: () => Promise<void>;
  onCancel: () => void;
}) {
  const { hasPermission, profile } = useCoreAuth();
  const { t } = useLocale();
  const canEditSku = hasPermission("product.edit");
  const canPublishOffer = hasPermission("catalog.publish");
  const defaultCurrency = profile?.context.defaultCurrency ?? "CNY";
  const [defaultMoq, setDefaultMoq] = useState(sku.defaultMoq === undefined ? "" : String(sku.defaultMoq));
  const [moqUnit, setMoqUnit] = useState(sku.moqUnit ?? "piece");
  const [packingQuantity, setPackingQuantity] = useState(getSkuPackingQuantity(sku.optionValues));
  const [price, setPrice] = useState(offer ? String(offer.unitPrice) : "0");
  const [currency, setCurrency] = useState(offer?.currency ?? defaultCurrency);
  const [publicationStatus, setPublicationStatus] = useState<PublicCatalogOffer["publicationStatus"]>(offer?.publicationStatus ?? "DRAFT");
  const [selectedTags, setSelectedTags] = useState<string[]>(offer?.tags ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setDefaultMoq(sku.defaultMoq === undefined ? "" : String(sku.defaultMoq));
    setMoqUnit(sku.moqUnit ?? "piece");
    setPackingQuantity(getSkuPackingQuantity(sku.optionValues));
    setPrice(offer ? String(offer.unitPrice) : "0");
    setCurrency(offer?.currency ?? defaultCurrency);
    setPublicationStatus(offer?.publicationStatus ?? "DRAFT");
    setSelectedTags(offer?.tags ?? []);
  }, [defaultCurrency, offer, sku.defaultMoq, sku.moqUnit, sku.optionValues]);

  const save = async () => {
    const numericMoq = defaultMoq.trim() ? Number(defaultMoq) : null;
    const numericPackingQuantity = packingQuantity.trim() ? Number(packingQuantity) : null;
    const numericPrice = Number(price || "0");
    if (
      (numericMoq !== null && (!Number.isFinite(numericMoq) || numericMoq < 0))
      || (numericPackingQuantity !== null && (!Number.isFinite(numericPackingQuantity) || numericPackingQuantity < 0))
      || (canPublishOffer && (!Number.isFinite(numericPrice) || numericPrice < 0))
    ) {
      setError(t("起订数、装箱数和价格必须是大于或等于 0 的数字。"));
      return;
    }
    setBusy(true);
    setError("");
    let skuSaved = false;
    try {
      const displayTag = selectedTags[0];
      if (canEditSku) {
        await updateSku(sku.id, {
          expectedVersion: sku.version,
          defaultMoq: numericMoq,
          moqUnit: numericMoq === null ? null : moqUnit.trim() || null,
          packingQuantity: numericPackingQuantity,
        });
        skuSaved = true;
      }
      if (canPublishOffer) {
        await upsertPublicCatalogOffer(sku.id, {
          unitPrice: numericPrice,
          currency,
          tags: selectedTags,
          displayTag,
          tagColor: offer?.displayTag === displayTag ? offer.tagColor : undefined,
          publicationStatus,
          validFrom: offer?.validFrom,
          validTo: offer?.validTo,
        });
      }
      try {
        await onChanged();
      } catch (reason) {
        await onRefresh().catch(() => undefined);
        const message = reason instanceof Error ? reason.message : t("刷新失败");
        setError(t("数据已保存，但页面刷新失败：{message}", { message }));
      }
    } catch (reason) {
      await onRefresh().catch(() => undefined);
      const message = reason instanceof Error ? reason.message : t("保存失败");
      setError(skuSaved && canPublishOffer
        ? t("SKU 已保存，但公开报价保存失败：{message}", { message })
        : message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="core-sku-quick-editor">
      <div className="core-sku-quick-fields">
        {canEditSku ? <>
          <label><Text size="1" color="gray">{t("起订数")}</Text><TextField.Root type="number" min="0" step="0.000001" inputMode="decimal" value={defaultMoq} onChange={(event) => setDefaultMoq(event.target.value)} /></label>
          <label><Text size="1" color="gray">{t("起订单位")}</Text><TextField.Root maxLength={32} value={moqUnit} onChange={(event) => setMoqUnit(event.target.value)} placeholder="piece" /></label>
          <label><Text size="1" color="gray">{t("装箱数")}</Text><TextField.Root type="number" min="0" step="0.000001" inputMode="decimal" value={packingQuantity} onChange={(event) => setPackingQuantity(event.target.value)} /></label>
        </> : null}
        {canPublishOffer ? <>
          <label><Text size="1" color="gray">{t("公开价")}</Text><TextField.Root type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} /></label>
          <label><Text size="1" color="gray">{t("币种")}</Text><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option><option>GBP</option><option>JPY</option></select></label>
          <label><Text size="1" color="gray">{t("是否发布")}</Text><select value={publicationStatus} onChange={(event) => setPublicationStatus(event.target.value as PublicCatalogOffer["publicationStatus"])} disabled={busy}>
            <option value="DRAFT">{t("未发布")}</option>
            <option value="PUBLISHED">{t("已发布")}</option>
            <option value="SUSPENDED">{t("暂停公开")}</option>
          </select></label>
        </> : null}
      </div>
      {canPublishOffer ? <div className="core-sku-quick-tags">
        <Text size="1" color="gray">{t("选择标签")}</Text>
        <ManagedTagPicker tags={managedTags} selected={selectedTags} onChange={setSelectedTags} disabled={busy} />
      </div> : <Text size="1" color="gray">{t("当前角色没有目录发布权限。")}</Text>}
      {error ? <div className="core-form-error" role="alert">{error}</div> : null}
      <div className="core-sku-quick-actions">
        <Button variant="ghost" color="gray" disabled={busy} onClick={onCancel}>{t("取消")}</Button>
        <Button disabled={busy} onClick={() => void save()}>{t(busy ? "保存中…" : "保存")}</Button>
      </div>
    </div>
  );
}
