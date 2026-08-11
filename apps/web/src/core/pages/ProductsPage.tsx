import { Badge, Button, Card, Checkbox, Dialog, DropdownMenu, Heading, Progress, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { ArrowDown, ArrowUp, ArrowsClockwise, CaretDown, CaretLeft, CaretRight, CheckCircle, DotsThree, DownloadSimple, FileArrowUp, FileXls, Folders, ImageSquare, MagnifyingGlass, PencilSimple, Plus, PushPin, PushPinSlash, ShareNetwork, Sparkle, Tag, Trash, Warning, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  batchDeleteSkus,
  batchUpdateSkuCategory,
  batchUpdateSkuPinned,
  batchUpdateSkuStatus,
  createManualProduct,
  createProductTemplateImport,
  createSkus,
  deleteAllProducts,
  detectFile,
  downloadProductMainImage,
  exportSkuCatalog,
  getDeleteAllProductsJob,
  getImport,
  getProduct,
  listCategories,
  listPublicCatalogOffers,
  listSkus,
  PRODUCT_TEMPLATE_DOWNLOAD_URL,
  updateSku,
  uploadProductMainImage,
  upsertPublicCatalogOffer,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { CatalogShareDialog, type CatalogShareTarget } from "../components/CatalogShareDialog";
import { primaryCategoryLabel } from "../../lib/format";
import { api } from "../../lib/api";
import type { ProductTag } from "../../types";
import type { FileDetection, ImportJob, ProductCategory, ProductDetail, ProductSku, PublicCatalogOffer, SkuListItem, SkuListPage } from "../types";

const emptySkuPage: SkuListPage = { items: [], page: 1, pageSize: 50, total: 0, pages: 0 };
const SKU_PAGE_SIZE_OPTIONS = [20, 50, 100] as const;
const SKU_PAGE_SIZE_STORAGE_KEY = "ai-trade-cloud:sku-page-size";
const UNCLASSIFIED_CATEGORY_VALUE = "__unclassified__";
type BulkSkuAction = "pin" | "unpin" | "activate" | "deactivate" | "category";

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

const offerStatusLabel: Record<NonNullable<SkuListItem["publicOfferStatus"]>, string> = {
  PUBLISHED: "公开价已发布",
  DRAFT: "公开价草稿",
  SUSPENDED: "公开价已暂停",
};

const importStatusLabel: Record<ImportJob["status"], string> = {
  scanning: "安全扫描",
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

const waitForDeletePoll = () => new Promise<void>((resolve) => {
  window.setTimeout(resolve, 900);
});

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

function skuStatusColor(status: ProductSku["status"]): "jade" | "amber" | "gray" {
  if (status === "ACTIVE") return "jade";
  if (status === "DRAFT") return "amber";
  return "gray";
}

function skuPrice(row: SkuListItem) {
  if (row.publicPrice === undefined) return "未设置";
  return `${row.publicCurrency ?? ""} ${row.publicPrice.toLocaleString(document.documentElement.lang || "zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
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
  const canEdit = hasPermission("product.edit");
  const canDelete = canEdit;
  const canImport = hasPermission("product.import")
    && hasPermission("product.edit")
    && hasPermission("catalog.publish");
  const canCreate = canEdit && hasPermission("catalog.publish");
  const canShare = canEdit && hasPermission("catalog.publish");
  const [params, setParams] = useSearchParams();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState<"" | ProductSku["status"]>("");
  const [missingImagesOnly, setMissingImagesOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSkuPageSize);
  const [result, setResult] = useState<SkuListPage>(emptySkuPage);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [managedTags, setManagedTags] = useState<ProductTag[]>([]);
  const [selected, setSelected] = useState<ProductDetail>();
  const [selectedSkuId, setSelectedSkuId] = useState<string | undefined>(params.get("sku") ?? undefined);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(canImport && params.get("import") === "1");
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingFile, setPendingFile] = useState<File>();
  const [detection, setDetection] = useState<FileDetection>();
  const [lastImport, setLastImport] = useState<ImportJob>();
  const [loadedWarningJobId, setLoadedWarningJobId] = useState<string>();
  const [importBusy, setImportBusy] = useState(false);
  const [importSubmitStage, setImportSubmitStage] = useState<"idle" | "checking" | "uploading" | "processing">("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [importError, setImportError] = useState("");
  const [importPollingError, setImportPollingError] = useState("");
  const [selectedSkuIds, setSelectedSkuIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
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
  const [shareTarget, setShareTarget] = useState<CatalogShareTarget>();
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await listSkus({
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
  useEffect(() => { void loadCategories().catch(() => setCategories([])); }, [loadCategories]);
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
    setSelectedSkuIds(new Set());
    setDeleteDialogOpen(false);
    setBulkAction(undefined);
    setBulkError("");
  }, [categoryId, debouncedQuery, missingImagesOnly, status]);

  const refreshCurrentImport = useCallback(async () => {
    if (!lastImport?.id) return undefined;
    const next = await getImport(lastImport.id);
    setLastImport(next);
    setImportPollingError("");
    if (next.status === "published") {
      await load();
      await loadCategories().catch(() => undefined);
    }
    return next;
  }, [lastImport?.id, load, loadCategories]);

  useEffect(() => {
    if (!importOpen || !lastImport || !["scanning", "parsing"].includes(lastImport.status)) return;
    let cancelled = false;
    let timer = 0;
    const poll = () => {
      timer = window.setTimeout(() => {
        void refreshCurrentImport()
          .then((next) => {
            if (!cancelled && next && ["scanning", "parsing"].includes(next.status)) poll();
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
  }, [importOpen, lastImport?.id, lastImport?.status, refreshCurrentImport, t]);

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

  const setImportDialogOpen = (open: boolean) => {
    if (open && !canImport) return;
    setImportOpen(open);
    if (!open) {
      setPendingFile(undefined);
      setDetection(undefined);
      setImportError("");
      setImportPollingError("");
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

  const inspectTemplate = async (file?: File) => {
    if (!canImport || !file) return;
    setImportError("");
    setLastImport(undefined);
    setLoadedWarningJobId(undefined);
    setPendingFile(file);
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setDetection(undefined);
      setImportError(t("这里只接受 .xlsx 商品文件。"));
      if (importInputRef.current) importInputRef.current.value = "";
      return;
    }
    setImportBusy(true);
    setImportSubmitStage("checking");
    try {
      const nextDetection = await detectFile(file);
      setDetection(nextDetection);
      if (
        nextDetection.detected_type !== "OOXML / XLSX"
        || !nextDetection.extension_matches
      ) {
        setImportError(t("文件签名与 XLSX 格式不一致，请重新选择。"));
      }
    } catch (reason) {
      setDetection(undefined);
      setImportError(reason instanceof Error ? reason.message : t("文件检测失败"));
    } finally {
      setImportBusy(false);
      setImportSubmitStage("idle");
      if (importInputRef.current) importInputRef.current.value = "";
    }
  };

  const importTemplate = async () => {
    if (!canImport) {
      setImportError(t("当前账号没有导入商品的权限。"));
      return;
    }
    if (!pendingFile || !detection || importError) return;
    setImportBusy(true);
    setImportSubmitStage("uploading");
    setUploadProgress(0);
    setImportError("");
    try {
      const job = await createProductTemplateImport(pendingFile, (progress) => {
        setUploadProgress(progress);
        if (progress >= 100) setImportSubmitStage("processing");
      });
      setLastImport(job);
      setLoadedWarningJobId(undefined);
      setPendingFile(undefined);
      setDetection(undefined);
      if (job.status === "published") {
        await load();
        setCategories(await listCategories());
      }
    } catch (reason) {
      setImportError(reason instanceof Error ? reason.message : t("商品导入失败"));
    } finally {
      setImportBusy(false);
      setImportSubmitStage("idle");
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
  const currentPageSkuIds = result.items.map((sku) => sku.id);
  const currentPageSelected = currentPageSkuIds.filter((id) => selectedSkuIds.has(id));
  const allCurrentPageSelected = currentPageSkuIds.length > 0
    && currentPageSelected.length === currentPageSkuIds.length;
  const toggleSkuSelection = (skuId: string) => {
    setBulkNotice("");
    setBulkError("");
    setSelectedSkuIds((current) => {
      const next = new Set(current);
      if (next.has(skuId)) next.delete(skuId);
      else if (next.size < 500) next.add(skuId);
      return next;
    });
  };
  const toggleCurrentPageSelection = () => {
    setBulkNotice("");
    setBulkError("");
    setSelectedSkuIds((current) => {
      const next = new Set(current);
      if (allCurrentPageSelected) {
        currentPageSkuIds.forEach((id) => next.delete(id));
        return next;
      }
      currentPageSkuIds.forEach((id) => {
        if (next.size < 500) next.add(id);
      });
      return next;
    });
  };
  const clearSkuSelection = () => {
    setSelectedSkuIds(new Set());
    setDeleteDialogOpen(false);
    setBulkAction(undefined);
    setBulkError("");
  };
  const openBulkAction = (action: BulkSkuAction) => {
    if (!canEdit || !selectedSkuIds.size) return;
    setBulkError("");
    if (action === "category") setBulkCategoryId("");
    setBulkAction(action);
  };
  const applyBulkAction = async () => {
    if (!canEdit || !selectedSkuIds.size || !bulkAction) return;
    if (bulkAction === "category" && !bulkCategoryId) {
      setBulkError(t("请选择要移动到的分类。"));
      return;
    }
    setBulkBusy(true);
    setBulkError("");
    try {
      const selectedIds = [...selectedSkuIds];
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
      setSelectedSkuIds(failedIds);
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
  const deleteSelectedSkus = async () => {
    if (!canDelete || !selectedSkuIds.size) return;
    setDeleteBusy(true);
    setBulkError("");
    try {
      const selectedIds = [...selectedSkuIds];
      const response = await batchDeleteSkus(selectedIds);
      const failedIds = new Set(response.failedItems.map((item) => item.skuId));
      setSelectedSkuIds(failedIds);
      setBulkNotice(
        response.failedCount
          ? t("已删除 {success} 个 SKU，{failed} 个未能删除。", {
              success: response.successCount,
              failed: response.failedCount,
            })
          : t("已删除 {count} 个 SKU。", { count: response.successCount }),
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
      setBulkError(
        reason instanceof Error ? reason.message : t("批量删除失败，请稍后重试。"),
      );
    } finally {
      setDeleteBusy(false);
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
      setSelectedSkuIds(new Set());
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
      const selectedIds = [...selectedSkuIds];
      await exportSkuCatalog({
        q: selectedIds.length ? undefined : debouncedQuery.trim() || undefined,
        categoryId: selectedIds.length ? undefined : categoryId || undefined,
        statuses: selectedIds.length || !status ? undefined : [status],
        missingImagesOnly: selectedIds.length ? false : missingImagesOnly,
        skuIds: selectedIds.length ? selectedIds : undefined,
      });
      setBulkNotice(
        selectedIds.length
          ? t("已导出所选 {count} 个 SKU。", { count: selectedIds.length })
          : t("已导出当前筛选下的 SKU 商品库。"),
      );
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
    : t("将更新 {count} 个 SKU。", { count: selectedSkuIds.size });
  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("SKU 商品库")}
        actions={<>
          <Button variant="soft" disabled={!result.total || exportBusy} loading={exportBusy} onClick={() => void exportCatalog()}><DownloadSimple />{t(selectedSkuIds.size ? "导出所选" : "导出")}</Button>
          {canCreate ? <Button onClick={() => setCreateOpen(true)}><Plus />{t("新建商品")}</Button> : null}
          {canImport ? <Button variant="soft" onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入商品")}</Button> : null}
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
        <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索 SKU、商品名称或产品编码")} aria-label={t("搜索 SKU 商品库")}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        <select value={categoryId} onChange={(event) => { setCategoryId(event.target.value); setPage(1); }} aria-label={t("按分类筛选")}>
          <option value="">{t("全部分类")}</option>
          {bulkCategoryOptions.map((category) => <option key={category.id} value={category.id}>{category.label}</option>)}
        </select>
        <select value={status} onChange={(event) => { setStatus(event.target.value as "" | ProductSku["status"]); setPage(1); }} aria-label={t("按 SKU 状态筛选")}>
          <option value="">{t("全部状态")}</option>
          <option value="ACTIVE">{t("在售")}</option>
          <option value="DRAFT">{t("草稿")}</option>
          <option value="INACTIVE">{t("已下架")}</option>
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
      {canEdit && selectedSkuIds.size > 0 ? (
        <Card className="core-sku-bulk-bar">
          <div>
            <Text size="2" weight="bold">{t("已选 {count} 项", { count: selectedSkuIds.size })}</Text>
          </div>
          <div className="core-sku-bulk-actions">
            {canShare ? (
              <Button
                size="2"
                onClick={() => setShareTarget({ type: "PRODUCTS", skuIds: [...selectedSkuIds] })}
              >
                <ShareNetwork />{t("分享")}
              </Button>
            ) : null}
            <Button size="2" variant="soft" color="gray" onClick={() => openBulkAction("category")}><Folders />{t("修改分类")}</Button>
            <Button size="2" variant="soft" color="jade" onClick={() => openBulkAction("activate")}><ArrowUp />{t("上架")}</Button>
            <Button size="2" variant="soft" color="amber" onClick={() => openBulkAction("deactivate")}><ArrowDown />{t("下架")}</Button>
            <DropdownMenu.Root>
              <DropdownMenu.Trigger>
                <Button size="2" variant="soft" color="gray"><DotsThree />{t("更多")}</Button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Content align="end">
                <DropdownMenu.Item onSelect={() => openBulkAction("pin")}><PushPin />{t("置顶")}</DropdownMenu.Item>
                <DropdownMenu.Item onSelect={() => openBulkAction("unpin")}><PushPinSlash />{t("取消置顶")}</DropdownMenu.Item>
                <DropdownMenu.Separator />
                <DropdownMenu.Item color="red" disabled={!selectedSkuIds.size || deleteBusy} onSelect={() => setDeleteDialogOpen(true)}><Trash />{t("删除")}</DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Root>
            <Button size="2" variant="ghost" color="gray" onClick={clearSkuSelection}><X />{t("取消选择")}</Button>
          </div>
        </Card>
      ) : null}
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result.items.length ? <CoreLoading label={t("正在读取 SKU 商品库")} /> : null}
      {!loading && !result.items.length && !error ? (
        hasActiveFilters
          ? <CoreEmpty title={t("没有符合条件的 SKU")} description={t("请调整筛选条件。")} action={<Button variant="soft" onClick={resetFilters}>{t("清除筛选")}</Button>} />
          : <CoreEmpty
              title={t("商品库还是空的")}
              description={t("可以新建商品或从 Excel 导入。")}
              action={canCreate || canImport ? <div className="core-empty-actions">{canCreate ? <Button onClick={() => setCreateOpen(true)}><Plus />{t("新建商品")}</Button> : null}{canImport ? <Button asChild variant="soft" color="gray"><a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a></Button> : null}{canImport ? <Button variant="soft" onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入商品")}</Button> : null}</div> : undefined}
            />
      ) : null}
      {result.items.length ? (
        <section className="core-sku-data-panel" aria-label={t("SKU 商品列表")}>
          <header className="core-sku-table-summary" aria-live="polite">
            <Text size="2">
              {t("共 {total} 个 SKU · 当前显示 {start}–{end}", {
                total: result.total.toLocaleString(locale),
                start: rangeStart,
                end: rangeEnd,
              })}
            </Text>
            <div>
              {loading ? <Text size="1" color="gray">{t("正在更新结果…")}</Text> : null}
              {canDelete ? (
                <Text size="1" color={selectedSkuIds.size ? undefined : "gray"}>
                  {t("已选择 {count} 个 SKU", { count: selectedSkuIds.size })}
                </Text>
              ) : null}
            </div>
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
                        aria-label={t(allCurrentPageSelected ? "取消选择本页全部 SKU" : "选择本页全部 SKU")}
                      />
                    </th>
                  ) : null}
                  <th className="core-sku-image-column" scope="col">{t("图片")}</th>
                  <th className="core-sku-product-column" scope="col">{t("SKU / 商品")}</th>
                  <th className="core-sku-category-column" scope="col">{t("分类")}</th>
                  <th className="core-sku-tags-column" scope="col">{t("标签")}</th>
                  <th className="core-sku-price-column" scope="col">{t("公开价")}</th>
                  <th className="core-sku-status-column" scope="col">{t("状态")}</th>
                  <th className="core-sku-updated-column" scope="col">{t("更新时间")}</th>
                  <th className="core-sku-action-column" scope="col">{t("操作")}</th>
                </tr>
              </thead>
              <tbody>
                {result.items.map((sku) => {
                  const isSelected = selectedSkuIds.has(sku.id);
                  const skuDisplayName = sku.name && sku.name !== sku.productName
                    ? sku.name
                    : sku.productCode;
                  return (
                    <tr
                      key={sku.id}
                      tabIndex={0}
                      data-selected={isSelected || undefined}
                      onClick={() => void openProduct(sku.productId, sku.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void openProduct(sku.productId, sku.id);
                      }}
                      aria-label={t("打开 SKU {code} 的编辑详情", { code: sku.skuCode })}
                    >
                      {canDelete ? (
                        <td
                          className="core-sku-select-column"
                          onClick={(event) => event.stopPropagation()}
                          onKeyDown={(event) => event.stopPropagation()}
                        >
                          <Checkbox
                            checked={isSelected}
                            onCheckedChange={() => toggleSkuSelection(sku.id)}
                            aria-label={t(isSelected ? "取消选择 SKU {code}" : "选择 SKU {code}", { code: sku.skuCode })}
                          />
                        </td>
                      ) : null}
                      <td className="core-sku-image-column">
                        <SkuThumbnail
                          sku={sku}
                          label={t(sku.imageStatus === "APPROVED" ? "图片已批准" : sku.imageStatus === "SOURCE" ? "仅来源图" : "暂无图片")}
                        />
                      </td>
                      <td className="core-sku-product-column">
                        <strong className="core-tabular" title={sku.skuCode}>{sku.skuCode}</strong>
                        <small title={`${sku.productName}${skuDisplayName ? ` · ${skuDisplayName}` : ""}`}>
                          {sku.productName}{skuDisplayName ? ` · ${skuDisplayName}` : ""}
                          {sku.isPinned ? <span className="core-sku-pinned"><PushPin weight="fill" />{t("置顶")}</span> : null}
                        </small>
                      </td>
                      <td className="core-sku-category-column" title={sku.category?.name}>
                        {sku.category?.name || t("未分类")}
                      </td>
                      <td className="core-sku-tags-column">
                        {sku.tags.length ? (
                          <span className="core-sku-table-tags">
                            {sku.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray" title={tag}>{tag}</Badge>)}
                            {sku.tags.length > 2 ? <small>+{sku.tags.length - 2}</small> : null}
                          </span>
                        ) : <span className="core-sku-table-empty">—</span>}
                      </td>
                      <td className="core-sku-price-column core-tabular">
                        <strong>{t(skuPrice(sku))}</strong>
                        <small>{t(sku.publicOfferStatus ? offerStatusLabel[sku.publicOfferStatus] : "尚无公开报价")}</small>
                      </td>
                      <td className="core-sku-status-column">
                        <Badge color={skuStatusColor(sku.status)}>{t(skuStatusLabel[sku.status])}</Badge>
                      </td>
                      <td className="core-sku-updated-column">
                        <strong>{skuUpdatedDate(sku.updatedAt)}</strong>
                      </td>
                      <td
                        className="core-sku-action-column"
                        onClick={(event) => event.stopPropagation()}
                        onKeyDown={(event) => event.stopPropagation()}
                      >
                        <Button
                          size="1"
                          variant="ghost"
                          onClick={() => void openProduct(sku.productId, sku.id)}
                          aria-label={t("打开 SKU {code} 的编辑详情", { code: sku.skuCode })}
                        >
                          {t("详情")}
                        </Button>
                      </td>
                    </tr>
                  );
                })}
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
              disabled={bulkBusy || !selectedSkuIds.size || (bulkAction === "category" && !bulkCategoryId)}
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
              <Text size="1" color="gray">{t("批量删除 SKU")}</Text>
              <Dialog.Title>{t("确认删除 {count} 个 SKU？", { count: selectedSkuIds.size })}</Dialog.Title>
              <Dialog.Description>{t("删除后将不再展示这些 SKU。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>
          {bulkError ? <div className="core-form-error" role="alert">{bulkError}</div> : null}
          <div className="core-dialog-actions">
            <Button variant="soft" color="gray" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)}>{t("取消")}</Button>
            <Button color="red" disabled={deleteBusy || !selectedSkuIds.size} onClick={() => void deleteSelectedSkus()}>
              <Trash />{t(deleteBusy ? "正在删除…" : "确认删除")}
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
              <Text size="1" color="gray">{t("商品批量导入")}</Text>
              <Dialog.Title>{t("导入商品")}</Dialog.Title>
              <Dialog.Description>{t("上传 XLSX，系统会合并到现有商品库。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => setImportDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>

          <div className="core-import-template-row">
            <Text size="2" color="gray">{t("支持新版双表与历史模板")}</Text>
            <Button asChild size="1" variant="soft" color="gray">
              <a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a>
            </Button>
          </div>

          <input
            ref={importInputRef}
            hidden
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => void inspectTemplate(event.target.files?.[0])}
          />

          {detection && pendingFile ? (
            <Card className="core-detection">
              <FileXls size={30} />
              <div>
                <Text weight="bold" as="div">{pendingFile.name}</Text>
                <Text size="2" color="gray">{(pendingFile.size / 1024 / 1024).toFixed(2)} MB · {detection.detected_type} · {detection.parser}</Text>
              </div>
              <Badge color={detection.extension_matches ? "jade" : "amber"}>{t(detection.extension_matches ? "格式已确认" : "格式不一致")}</Badge>
            </Card>
          ) : (
            <button className="core-template-dropzone" type="button" disabled={importBusy} onClick={() => importInputRef.current?.click()}>
              <FileArrowUp size={30} />
              <strong>{t("选择商品文件")}</strong>
              <span>{t("XLSX · 最大 250 MB")}</span>
            </button>
          )}

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
                        : "服务器已收到文件，即将进入安全检查和数据校验",
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
                          ?? (lastImport.status === "scanning" ? "正在进行文件安全检查" : "正在处理商品数据"),
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
            {detection ? <Button variant="soft" color="gray" disabled={importBusy} onClick={() => importInputRef.current?.click()}>{t("重新选择")}</Button> : null}
            <Button
              disabled={!pendingFile || !detection || Boolean(importError) || importBusy}
              onClick={() => void importTemplate()}
            >
              <FileArrowUp />{t(importBusy ? "正在处理…" : "开始导入")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root> : null}

      <Dialog.Root open={Boolean(selected || detailLoading)} onOpenChange={(open) => { if (!open) close(); }}>
        <Dialog.Content className="core-detail-dialog">
          {detailLoading || !selected ? <CoreLoading label={t("正在读取商品详情")} /> : <ProductDetailPanel product={selected} selectedSkuId={selectedSkuId} managedTags={managedTags} onChanged={async () => { await refreshSelected(); await load(); }} onClose={close} />}
        </Dialog.Content>
      </Dialog.Root>

      <CatalogShareDialog
        open={Boolean(shareTarget)}
        target={shareTarget}
        onOpenChange={(open) => { if (!open) setShareTarget(undefined); }}
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
    const weight = optionalNumber("weight");
    if (
      !Number.isFinite(unitPrice)
      || unitPrice < 0
      || (defaultMoq !== undefined && (!Number.isFinite(defaultMoq) || defaultMoq < 0))
      || (weight !== undefined && (!Number.isFinite(weight) || weight < 0))
    ) {
      setError(t("价格、起订数和重量必须是大于或等于 0 的数字。"));
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
                  <Text size="2" weight="medium">{t("SKU 编码")}</Text>
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

function ProductDetailPanel({ product, selectedSkuId, managedTags, onChanged, onClose }: {
  product: ProductDetail;
  selectedSkuId?: string;
  managedTags: ProductTag[];
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
        <Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button>
      </div>
      <div className="core-product-detail-summary">
        <Badge color={product.status === "ACTIVE" ? "jade" : "gray"}>{t(skuStatusLabel[product.status as ProductSku["status"]] ?? product.status)}</Badge>
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
          <SkuPanel product={product} initialSkuId={selectedSkuId} managedTags={managedTags} onChanged={onChanged} />
        </Tabs.Content>
      </Tabs.Root>
    </>
  );
}

function SkuPanel({ product, initialSkuId, managedTags, onChanged }: {
  product: ProductDetail;
  initialSkuId?: string;
  managedTags: ProductTag[];
  onChanged: () => Promise<void>;
}) {
  const { hasAnyPermission, hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEdit = hasPermission("product.edit");
  const canViewCatalog = hasAnyPermission("catalog.view", "catalog.publish");
  const canPublish = hasAnyPermission("catalog.publish");
  const [offers, setOffers] = useState<PublicCatalogOffer[]>([]);
  const [skuCode, setSkuCode] = useState(`${product.productCode ?? "SKU"}-${product.skus.length + 1}`);
  const [skuName, setSkuName] = useState(product.name);
  const [createOpen, setCreateOpen] = useState(false);
  const [editingSkuId, setEditingSkuId] = useState<string>();
  const [expandedSkuIds, setExpandedSkuIds] = useState<Set<string>>(() => new Set(initialSkuId ? [initialSkuId] : []));
  const [busySkuId, setBusySkuId] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setEditingSkuId(undefined);
    setExpandedSkuIds(new Set(initialSkuId ? [initialSkuId] : []));
  }, [initialSkuId, product.id]);
  const loadOffers = useCallback(async () => {
    if (!canViewCatalog) { setOffers([]); return; }
    try { setOffers(await listPublicCatalogOffers(product.id)); }
    catch { setOffers([]); }
  }, [canViewCatalog, product.id]);
  useEffect(() => { void loadOffers(); }, [loadOffers]);

  const createSingle = async () => {
    if (!skuCode.trim()) return;
    setCreating(true);
    setError("");
    try {
      await createSkus(product.id, [{ skuCode: skuCode.trim(), name: skuName.trim() || undefined, optionValues: {}, status: "DRAFT" }]);
      await onChanged();
      setSkuCode(`${product.productCode ?? "SKU"}-${product.skus.length + 2}`);
      setSkuName(product.name);
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
        {canEdit ? <Button size="2" variant={createOpen ? "soft" : "solid"} color={createOpen ? "gray" : undefined} onClick={() => setCreateOpen((open) => !open)}><Plus />{t(createOpen ? "取消" : "添加 SKU")}</Button> : null}
      </div>
      {createOpen ? (
        <Card className="core-sku-create-compact">
          <label><Text size="1" color="gray">{t("SKU 编码")}</Text><TextField.Root value={skuCode} onChange={(event) => setSkuCode(event.target.value)} autoFocus /></label>
          <label><Text size="1" color="gray">{t("SKU 名称")}</Text><TextField.Root value={skuName} onChange={(event) => setSkuName(event.target.value)} /></label>
          <Button disabled={!skuCode.trim() || creating} onClick={() => void createSingle()}>{t(creating ? "正在添加…" : "添加")}</Button>
        </Card>
      ) : null}
      {error ? <div className="core-form-error" role="alert">{error}</div> : null}
      <div className="core-sku-detail-list">
        {product.skus.map((sku) => {
          const offer = offers.find((item) => item.skuId === sku.id);
          const skuLabel = sku.name || Object.values(sku.optionValues).join(" · ") || t("基础款");
          const editing = editingSkuId === sku.id;
          const expanded = expandedSkuIds.has(sku.id);
          const options = Object.entries(sku.optionValues).filter(([, value]) => value !== "" && value !== undefined && value !== null);
          return (
            <Card className="core-sku-detail-card" data-expanded={expanded || undefined} data-editing={editing || undefined} key={sku.id}>
              <div className="core-sku-detail-row">
                <button
                  type="button"
                  className="core-sku-detail-main"
                  aria-expanded={expanded}
                  aria-controls={`sku-details-${sku.id}`}
                  onClick={() => toggleSkuDetails(sku.id)}
                >
                  <Tag />
                  <span><strong>{sku.skuCode}</strong><small>{skuLabel}</small></span>
                  <CaretDown className="core-sku-detail-caret" aria-hidden="true" />
                </button>
                <div className="core-sku-detail-tags">
                  {offer?.tags.slice(0, 3).map((tag) => <Badge color="gray" key={tag}>{tag}</Badge>)}
                  {offer && offer.tags.length > 3 ? <small>+{offer.tags.length - 3}</small> : null}
                  {!offer?.tags.length ? <small>—</small> : null}
                </div>
                <strong className="core-sku-detail-price core-tabular">{offer ? `${offer.currency} ${offer.unitPrice.toFixed(2)}` : "—"}</strong>
                <Badge color={skuStatusColor(sku.status)}>{t(skuStatusLabel[sku.status])}</Badge>
                <div className="core-sku-detail-actions">
                  <Button size="1" variant="ghost" color="gray" onClick={() => toggleSkuDetails(sku.id)}>
                    <CaretDown className="core-sku-detail-action-caret" data-expanded={expanded || undefined} />{t(expanded ? "收起" : "展开")}
                  </Button>
                  {canPublish ? <Button size="1" variant="soft" color="gray" onClick={() => editSku(sku.id)}><PencilSimple />{t(editing ? "取消编辑" : "编辑")}</Button> : null}
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
                  <div className="core-sku-expanded-field"><span>{t("毛重")}</span><strong className="core-tabular">{sku.weight === undefined ? t("未设置") : `${sku.weight} ${sku.weightUnit ?? ""}`.trim()}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("公开价")}</span><strong className="core-tabular">{offer ? `${offer.currency} ${offer.unitPrice.toFixed(2)}` : t("未设置")}</strong></div>
                  <div className="core-sku-expanded-field"><span>{t("最后更新")}</span><strong>{skuUpdatedDate(sku.updatedAt)}</strong></div>
                </div>
              ) : null}
              {editing && canPublish ? (
                <SkuQuickEditor
                  sku={sku}
                  offer={offer}
                  managedTags={managedTags}
                  onCancel={() => setEditingSkuId(undefined)}
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

function SkuQuickEditor({ sku, offer, managedTags, onChanged, onCancel }: {
  sku: ProductSku;
  offer?: PublicCatalogOffer;
  managedTags: ProductTag[];
  onChanged: () => Promise<void>;
  onCancel: () => void;
}) {
  const { profile } = useCoreAuth();
  const { t } = useLocale();
  const defaultCurrency = profile?.context.defaultCurrency ?? "CNY";
  const [price, setPrice] = useState(offer ? String(offer.unitPrice) : "0");
  const [currency, setCurrency] = useState(offer?.currency ?? defaultCurrency);
  const [selectedTags, setSelectedTags] = useState<string[]>(offer?.tags ?? []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setPrice(offer ? String(offer.unitPrice) : "0");
    setCurrency(offer?.currency ?? defaultCurrency);
    setSelectedTags(offer?.tags ?? []);
    setError("");
  }, [defaultCurrency, offer]);

  const save = async () => {
    const numericPrice = Number(price || "0");
    if (!Number.isFinite(numericPrice) || numericPrice < 0) {
      setError(t("请输入正确的价格。"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      const displayTag = selectedTags[0];
      await upsertPublicCatalogOffer(sku.id, {
        unitPrice: numericPrice,
        currency,
        tags: selectedTags,
        displayTag,
        tagColor: offer?.displayTag === displayTag ? offer.tagColor : undefined,
        publicationStatus: sku.status === "ACTIVE" ? "PUBLISHED" : "DRAFT",
        validFrom: offer?.validFrom,
        validTo: offer?.validTo,
      });
      await onChanged();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("保存失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="core-sku-quick-editor">
      <div className="core-sku-quick-fields">
        <label><Text size="1" color="gray">{t("公开价")}</Text><TextField.Root type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} /></label>
        <label><Text size="1" color="gray">{t("币种")}</Text><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option><option>GBP</option><option>JPY</option></select></label>
      </div>
      <div className="core-sku-quick-tags">
        <Text size="1" color="gray">{t("选择标签")}</Text>
        <ManagedTagPicker tags={managedTags} selected={selectedTags} onChange={setSelectedTags} disabled={busy} />
      </div>
      {error ? <div className="core-form-error" role="alert">{error}</div> : null}
      <div className="core-sku-quick-actions">
        <Button variant="ghost" color="gray" disabled={busy} onClick={onCancel}>{t("取消")}</Button>
        <Button disabled={busy} onClick={() => void save()}>{t(busy ? "保存中…" : "保存")}</Button>
      </div>
    </div>
  );
}
