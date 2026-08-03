import { Badge, Button, Card, Checkbox, Dialog, Heading, Progress, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { ArrowDown, ArrowUp, ArrowsClockwise, CaretRight, CheckCircle, ClockCounterClockwise, DownloadSimple, FileArrowUp, FileXls, Folders, ImageSquare, MagnifyingGlass, Plus, PushPin, PushPinSlash, Sparkle, Tag, Trash, Warning, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  batchDeleteSkus,
  batchUpdateSkuCategory,
  batchUpdateSkuPinned,
  batchUpdateSkuStatus,
  createAttributeDefinition,
  createProductTemplateImport,
  createSkus,
  deleteAllProducts,
  detectFile,
  getDeleteAllProductsJob,
  getImport,
  getProduct,
  listAttributeDefinitions,
  listCategories,
  listPublicCatalogOffers,
  listSkus,
  PRODUCT_TEMPLATE_DOWNLOAD_URL,
  updateSku,
  upsertPublicCatalogOffer,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { primaryCategoryLabel } from "../../lib/format";
import { automaticTagColor, TAG_COLOR_PALETTE, tagGlassStyle } from "../../lib/tagColors";
import type { AttributeDefinition, FileDetection, ImportJob, ProductCategory, ProductDetail, ProductSku, PublicCatalogOffer, SkuListItem, SkuListPage } from "../types";

const splitValues = (value: string) => value.split(/[,，;；、|\n]/).map((item) => item.trim()).filter(Boolean);
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

function imageStatusLabel(status: SkuListItem["imageStatus"]) {
  if (status === "APPROVED") return "图片已就绪";
  if (status === "SOURCE") return "图片待确认";
  return "暂无图片";
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

function skuImportDateTime(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(document.documentElement.lang || "zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function skuSourceLabel(row: SkuListItem) {
  if (row.sourceFilename) return row.sourceFilename;
  if (row.sourceType === "LEGACY_IMPORT") return "历史导入";
  return "手工录入";
}

export function ProductsPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canEdit = hasPermission("product.edit");
  const canDelete = canEdit;
  const canImport = hasPermission("product.import")
    && hasPermission("product.edit")
    && hasPermission("catalog.publish");
  const [params, setParams] = useSearchParams();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [primaryCategoryId, setPrimaryCategoryId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState<"" | ProductSku["status"]>("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(initialSkuPageSize);
  const [result, setResult] = useState<SkuListPage>(emptySkuPage);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [selected, setSelected] = useState<ProductDetail>();
  const [detailInitialTab, setDetailInitialTab] = useState<"overview" | "skus">(
    params.get("view") === "skus" ? "skus" : "overview",
  );
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(canImport && params.get("import") === "1");
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
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await listSkus({
        q: debouncedQuery.trim() || undefined,
        categoryId: categoryId || primaryCategoryId || undefined,
        statuses: status ? [status] : undefined,
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
  }, [categoryId, debouncedQuery, page, pageSize, primaryCategoryId, status, t]);

  const loadCategories = useCallback(async () => {
    setCategories(await listCategories());
  }, []);
  useEffect(() => { void loadCategories().catch(() => setCategories([])); }, [loadCategories]);
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
  }, [categoryId, debouncedQuery, primaryCategoryId, status]);

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

  const openProduct = useCallback(async (productId: string, initialTab: "overview" | "skus" = "overview") => {
    setDetailInitialTab(initialTab);
    setDetailLoading(true);
    setError("");
    try {
      setSelected(await getProduct(productId));
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.set("product", productId);
        if (initialTab === "skus") next.set("view", "skus");
        else next.delete("view");
        return next;
      }, { replace: true });
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("产品详情加载失败")); }
    finally { setDetailLoading(false); }
  }, [setParams]);

  useEffect(() => {
    const productId = params.get("product");
    if (productId && selected?.id !== productId) {
      void openProduct(productId, params.get("view") === "skus" ? "skus" : "overview");
    }
    // Product selection is restored from the URL once on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    setSelected(undefined);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("product");
      next.delete("view");
      return next;
    }, { replace: true });
  };
  const refreshSelected = async () => { if (selected) setSelected(await getProduct(selected.id)); };
  const resetFilters = () => {
    setQuery("");
    setDebouncedQuery("");
    setPrimaryCategoryId("");
    setCategoryId("");
    setStatus("");
    setPage(1);
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
  const rangeStart = result.total ? (result.page - 1) * result.pageSize + 1 : 0;
  const rangeEnd = Math.min(result.page * result.pageSize, result.total);
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
  const secondaryCategories = useMemo(
    () => categories.filter((item) => item.parentId === primaryCategoryId && item.status !== "ARCHIVED"),
    [categories, primaryCategoryId],
  );
  const hasActiveFilters = Boolean(query.trim() || primaryCategoryId || categoryId || status);
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
    ? t("所选 SKU 对应的商品会统一移动到目标分类；同一商品的其他 SKU 也会随商品归入该分类。")
    : bulkAction === "pin" || bulkAction === "unpin"
    ? t("置顶状态按商品生效，并在全部商品和所属分类中优先展示。")
    : t("状态会应用到所选的 {count} 个 SKU，并立即影响商家前台是否展示。", { count: selectedSkuIds.size });
  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("商品资料")}
        title={t("SKU 商品库")}
        description={t("使用 Product 与 SKU 双表模板批量维护商品主数据，并在每个商品下管理不同 SKU、规格、价格与供应商。")}
        actions={<>
          {canImport ? <Button asChild variant="soft" color="gray"><a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a></Button> : null}
          {canImport ? <Button onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入商品")}</Button> : null}
          {canDelete ? <Button variant="soft" color="red" onClick={() => setDeleteAllOpen(true)}><Trash />{t("删除全部商品")}</Button> : null}
        </>}
      />
      <Card className="core-sku-toolbar">
        <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索 SKU、商品名称或产品编码")} aria-label={t("搜索 SKU 商品库")}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        <select value={primaryCategoryId} onChange={(event) => { setPrimaryCategoryId(event.target.value); setCategoryId(""); setPage(1); }} aria-label={t("按一级分类筛选")}><option value="">{t("全部一级分类")}</option>{rootCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
        <select value={categoryId} disabled={!primaryCategoryId || !secondaryCategories.length} onChange={(event) => { setCategoryId(event.target.value); setPage(1); }} aria-label={t("按二级分类筛选")}><option value="">{t(primaryCategoryId ? "全部二级分类" : "请先选择一级分类")}</option>{secondaryCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
        <select value={status} onChange={(event) => { setStatus(event.target.value as "" | ProductSku["status"]); setPage(1); }} aria-label={t("按 SKU 状态筛选")}>
          <option value="">{t("全部状态")}</option>
          <option value="ACTIVE">{t("在售")}</option>
          <option value="DRAFT">{t("草稿")}</option>
          <option value="INACTIVE">{t("已下架")}</option>
          <option value="ARCHIVED">{t("已归档")}</option>
        </select>
        <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}><ArrowsClockwise />{t("刷新")}</Button>
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
            <Text size="1" color="gray">{t("批量管理")}</Text>
            <Text size="2" weight="bold">{t("已选择 {count} 个，最多 500 个", { count: selectedSkuIds.size })}</Text>
            <Text size="1" color="gray">{t("分类和置顶会应用到所选 SKU 对应的商品。")}</Text>
          </div>
          <div className="core-sku-bulk-actions">
            <Button size="2" variant="soft" onClick={() => openBulkAction("pin")}><PushPin />{t("置顶")}</Button>
            <Button size="2" variant="soft" color="gray" onClick={() => openBulkAction("unpin")}><PushPinSlash />{t("取消置顶")}</Button>
            <Button size="2" variant="soft" color="gray" onClick={() => openBulkAction("category")}><Folders />{t("修改分类")}</Button>
            <Button size="2" variant="soft" color="jade" onClick={() => openBulkAction("activate")}><ArrowUp />{t("上架")}</Button>
            <Button size="2" variant="soft" color="amber" onClick={() => openBulkAction("deactivate")}><ArrowDown />{t("下架")}</Button>
            <Button size="2" color="red" disabled={!selectedSkuIds.size || deleteBusy} onClick={() => setDeleteDialogOpen(true)}>
              <Trash />{t("删除已选 {count} 项", { count: selectedSkuIds.size })}
            </Button>
            <Button size="2" variant="ghost" color="gray" onClick={clearSkuSelection}>{t("清除选择")}</Button>
          </div>
        </Card>
      ) : null}
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result.items.length ? <CoreLoading label={t("正在读取 SKU 商品库")} /> : null}
      {!loading && !result.items.length && !error ? (
        hasActiveFilters
          ? <CoreEmpty title={t("没有符合条件的 SKU")} description={t("尝试更换关键词、分类或状态。")} action={<Button variant="soft" onClick={resetFilters}>{t("清除筛选")}</Button>} />
          : <CoreEmpty
              title={t("商品库还是空的")}
              description={t("先在 Product 表填写商品，再在 SKU 表用商品编码关联不同规格；导入后即可统一管理和发布。")}
              action={canImport ? <div className="core-empty-actions"><Button asChild variant="soft" color="gray"><a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a></Button><Button onClick={() => setImportDialogOpen(true)}><FileArrowUp />{t("导入商品")}</Button></div> : undefined}
            />
      ) : null}
      {result.items.length ? (
        <>
          <div className="core-sku-list-meta" aria-live="polite">
            <Text size="2" color="gray">{t("共 {total} 个 SKU · 当前显示 {start}–{end}", { total: result.total.toLocaleString(locale), start: rangeStart, end: rangeEnd })}</Text>
            <div className="core-sku-list-meta-actions">
              {loading ? <Text size="1" color="gray">{t("正在更新结果…")}</Text> : <Text size="1" color="gray">{t("每页 {count} 条", { count: result.pageSize })}</Text>}
              {canDelete ? <Text size="1" color={selectedSkuIds.size ? undefined : "gray"}>{t("已选择 {count} 个 SKU", { count: selectedSkuIds.size })}</Text> : null}
            </div>
          </div>
          <Card className="core-sku-table-card">
            <div className={canDelete ? "core-sku-table selection-enabled" : "core-sku-table"} role="table" aria-label={t("SKU 商品列表")}>
              <div className="core-sku-table-head" role="row">
                {canDelete ? (
                  <span className="core-sku-checkbox-cell">
                    <Checkbox
                      checked={allCurrentPageSelected ? true : currentPageSelected.length ? "indeterminate" : false}
                      onCheckedChange={toggleCurrentPageSelection}
                      aria-label={t(allCurrentPageSelected ? "取消选择本页全部 SKU" : "选择本页全部 SKU")}
                    />
                  </span>
                ) : null}
                <span>{t("SKU / 商品")}</span><span>{t("分类与标签")}</span><span>{t("公开价")}</span><span>{t("状态")}</span><span>{t("源文件 / 导入时间")}</span><span>{t("更新时间")}</span><span aria-hidden="true" />
              </div>
              {result.items.map((sku) => {
                const isSelected = selectedSkuIds.has(sku.id);
                return (
                <div
                  className="core-sku-table-row"
                  role="row"
                  tabIndex={0}
                  key={sku.id}
                  data-selected={isSelected || undefined}
                  onClick={() => void openProduct(sku.productId, "skus")}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void openProduct(sku.productId, "skus");
                  }}
                  aria-label={t("打开 SKU {code} 的编辑详情", { code: sku.skuCode })}
                >
                  {canDelete ? (
                    <span className="core-sku-checkbox-cell" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()}>
                      <Checkbox
                        checked={isSelected}
                        onCheckedChange={() => toggleSkuSelection(sku.id)}
                        aria-label={t(isSelected ? "取消选择 SKU {code}" : "选择 SKU {code}", { code: sku.skuCode })}
                      />
                    </span>
                  ) : null}
                  <span className="core-sku-name-cell">
                    <span className={`core-sku-image-state ${sku.imageStatus.toLowerCase()}`} title={t(sku.imageStatus === "APPROVED" ? "图片已批准" : sku.imageStatus === "SOURCE" ? "仅来源图" : "暂无图片")}><ImageSquare /></span>
                    <span><strong className="core-tabular">{sku.skuCode}</strong><small>{sku.name || sku.productName}</small></span>
                  </span>
                  <span className="core-sku-category-cell">
                    <span className="core-sku-category-heading">
                      <strong>{primaryCategoryLabel(sku.category?.name) || t("未分类")}</strong>
                      {sku.isPinned ? <Badge color="amber" variant="soft"><PushPin weight="fill" />{t("已置顶")}</Badge> : null}
                    </span>
                    {sku.supplierSummary.primarySupplierName ? <small>{t("供应商")}：{sku.supplierSummary.primarySupplierName}</small> : null}
                    <span className="core-chip-row">{sku.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</span>
                  </span>
                  <span className="core-tabular"><strong>{t(skuPrice(sku))}</strong><small>{t(sku.publicOfferStatus ? offerStatusLabel[sku.publicOfferStatus] : "尚无公开报价")}</small></span>
                  <Badge color={skuStatusColor(sku.status)}>{t(skuStatusLabel[sku.status])}</Badge>
                  <span className="core-sku-source-cell" title={sku.sourceFilename}><strong>{t(skuSourceLabel(sku))}</strong><small>{sku.sourceImportedAt ? skuImportDateTime(sku.sourceImportedAt) : t(sku.sourceType === "LEGACY_IMPORT" ? "历史数据暂无文件记录" : "非文件导入")}</small></span>
                  <span><strong>{skuUpdatedDate(sku.updatedAt)}</strong><small>v{sku.version}</small></span>
                  <CaretRight aria-hidden="true" />
                </div>
                );
              })}
            </div>
          </Card>
          <div className="core-sku-mobile-list">
            {result.items.map((sku) => {
              const isSelected = selectedSkuIds.has(sku.id);
              return (
              <article className="core-sku-mobile-card" key={sku.id} data-selected={isSelected || undefined}>
                {canDelete ? (
                  <label className="core-sku-mobile-selection">
                    <Checkbox
                      checked={isSelected}
                      onCheckedChange={() => toggleSkuSelection(sku.id)}
                      aria-label={t(isSelected ? "取消选择 SKU {code}" : "选择 SKU {code}", { code: sku.skuCode })}
                    />
                    <span>{t(isSelected ? "已选择" : "选择此 SKU")}</span>
                  </label>
                ) : null}
                <button type="button" className="core-sku-mobile-open" onClick={() => void openProduct(sku.productId, "skus")} aria-label={t("打开 SKU {code} 的编辑详情", { code: sku.skuCode })}>
                  <span className="core-sku-mobile-heading"><span><small className="core-tabular">{sku.skuCode}</small><strong>{sku.name || sku.productName}</strong></span><span className="core-sku-mobile-badges">{sku.isPinned ? <Badge color="amber" variant="soft"><PushPin weight="fill" />{t("已置顶")}</Badge> : null}<Badge color={skuStatusColor(sku.status)}>{t(skuStatusLabel[sku.status])}</Badge></span></span>
                  <span className="core-sku-mobile-facts">
                    <span><small>{t("公开价")}</small><strong className="core-tabular">{t(skuPrice(sku))}</strong></span>
                    <span><small>{t("图片")}</small><strong>{t(imageStatusLabel(sku.imageStatus))}</strong></span>
                    <span><small>{t("供应商")}</small><strong>{sku.supplierSummary.primarySupplierName || t("未关联")}</strong></span>
                  </span>
                  <span className="core-chip-row"><Badge color="gray">{primaryCategoryLabel(sku.category?.name) || t("未分类")}</Badge>{sku.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</span>
                  <span className="core-sku-mobile-source">
                    <span><small>{t("源文件")}</small><strong title={sku.sourceFilename}>{t(skuSourceLabel(sku))}</strong></span>
                    <span><small>{t("导入时间")}</small><strong>{skuImportDateTime(sku.sourceImportedAt)}</strong></span>
                  </span>
                  <span className="core-sku-mobile-footer"><small>{t("更新于 {date}", { date: skuUpdatedDate(sku.updatedAt) })}</small><span>{t("SKU 详情")}<CaretRight /></span></span>
                </button>
              </article>
              );
            })}
          </div>
          <nav className="core-sku-pagination" aria-label={t("SKU 列表分页")}>
            <label className="core-sku-page-size-control">
              <span>{t("每页显示")}</span>
              <select value={pageSize} onChange={(event) => changePageSize(event.target.value)} disabled={loading}>
                {SKU_PAGE_SIZE_OPTIONS.map((option) => <option key={option} value={option}>{t("{count} 条", { count: option })}</option>)}
              </select>
            </label>
            <div className="core-sku-pagination-controls">
              <Button variant="soft" color="gray" disabled={loading || result.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>{t("上一页")}</Button>
              <Text size="2" color="gray">{t("第 {page} / {pages} 页", { page: result.page, pages: result.pages })}</Text>
              <Button variant="soft" color="gray" disabled={loading || result.page >= result.pages} onClick={() => setPage((current) => Math.min(result.pages, current + 1))}>{t("下一页")}</Button>
            </div>
          </nav>
        </>
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
          <Card className="core-notice">
            {bulkAction === "category" ? <Folders size={22} /> : bulkAction === "pin" || bulkAction === "unpin" ? <PushPin size={22} /> : bulkAction === "activate" ? <ArrowUp size={22} /> : <ArrowDown size={22} />}
            <div>
              <Text weight="bold" as="div">{t("当前选择 {count} 个 SKU", { count: selectedSkuIds.size })}</Text>
              <Text size="2" color="gray">{t("操作完成后，失败项目会继续保持选中，便于再次处理。")}</Text>
            </div>
          </Card>
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
              <Dialog.Description>{t("删除后这些 SKU 将从商品库、商家前台和搜索结果中隐藏。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" disabled={deleteBusy} onClick={() => setDeleteDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>
          <Card className="core-notice">
            <Warning size={22} />
            <div>
              <Text weight="bold" as="div">{t("历史业务数据会保留")}</Text>
              <Text size="2" color="gray">{t("库存流水和历史报价不会被物理删除；以后重新导入相同 SKU 时可以恢复商品。")}</Text>
            </div>
          </Card>
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

      {canImport ? <Dialog.Root open={importOpen} onOpenChange={setImportDialogOpen}>
        <Dialog.Content className="core-template-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("商品批量导入")}</Text>
              <Dialog.Title>{t("导入商品")}</Dialog.Title>
              <Dialog.Description>{t("上传 Product + SKU 双表 XLSX；也继续兼容历史单表模板。系统会先完整校验，再按 SKU 增量合并到当前商品库。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => setImportDialogOpen(false)} aria-label={t("关闭")}><X /></Button>
          </div>

          <Card className="core-template-contract">
            <span className="core-row-icon"><FileXls /></span>
            <div>
              <Text weight="bold" as="div">{t("先下载标准模板")}</Text>
              <Text size="2" color="gray">{t("Product 表填写商品主数据；SKU 表每行最多定义三个规格，每个规格最多五个候选值，系统会自动组合成具体 SKU。SKU 编号作为组合编号的稳定前缀。")}</Text>
              <div className="core-chip-row" aria-label={t("固定模版字段")}>
                {["Product 商品主表", "SKU 明细表", "商品与 SKU 编码关联", "每个规格 5 个候选值", "候选值自动组合 SKU", "供应商、价格与包装", "标签与图片1–10"].map((field) => <Badge color="gray" key={field}>{t(field)}</Badge>)}
              </div>
              <div>
                <Button asChild size="1" variant="soft" color="gray">
                  <a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品导入模板.xlsx"><DownloadSimple />{t("下载模板")}</a>
                </Button>
              </div>
            </div>
          </Card>

          <Card className="core-notice">
            <Warning size={22} />
            <div>
              <Text weight="bold" as="div">{t("每次导入都会增量合并")}</Text>
              <Text size="2" color="gray">{t("相同 SKU 更新，新 SKU 新增；本次文件未包含的旧商品继续保留。文件会先完整校验，存在错误时不会写入部分商品。")}</Text>
            </div>
          </Card>

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
              <span>{t("上传最新版 Product + SKU 双表或受支持的历史 XLSX，单文件最大 250 MB")}</span>
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
                          {t("共 {count} 个问题；请修正后重新上传，当前商品库未发生变化。", { count: lastImport.resultDetails.issueTotal })}
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
                            <Badge color="red" variant="soft">
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
          {detailLoading || !selected ? <CoreLoading label={t("正在读取产品聚合视图")} /> : <ProductDetailPanel product={selected} initialTab={detailInitialTab} onChanged={async () => { await refreshSelected(); await load(); }} onClose={close} />}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}

function ProductDetailPanel({ product, initialTab, onChanged, onClose }: { product: ProductDetail; initialTab: "overview" | "skus"; onChanged: () => Promise<void>; onClose: () => void }) {
  const { t } = useLocale();
  return (
    <>
      <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("权威产品记录")} · v{product.currentVersion}</Text><Dialog.Title>{product.name}</Dialog.Title><Dialog.Description>{product.productCode ?? t("产品")} · {primaryCategoryLabel(product.category) || t("未分类")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div>
      <Tabs.Root key={`${product.id}:${initialTab}`} defaultValue={initialTab}>
        <Tabs.List><Tabs.Trigger value="overview">{t("主数据")}</Tabs.Trigger><Tabs.Trigger value="skus">SKU ({product.skus.length})</Tabs.Trigger><Tabs.Trigger value="attributes">{t("分类属性")}</Tabs.Trigger><Tabs.Trigger value="activity">{t("活动")}</Tabs.Trigger></Tabs.List>
        <Tabs.Content value="overview"><div className="core-master-grid"><Fact label={t("状态")} value={t(product.status)} /><Fact label={t("产品版本")} value={`v${product.currentVersion}`} /><Fact label={t("图片状态")} value={t(product.imageStatus)} /><Fact label="SKU" value={String(product.skuCount)} /><section><Text size="1" color="gray">{t("标准描述")}</Text><p>{product.description || t("尚未维护标准描述。")}</p></section><section><Text size="1" color="gray">{t("商品模版映射")}</Text><p>{t("Product 表维护商品主数据与图片；SKU 表通过商品编码关联规格、供应商和价格。标签用于商品展示与 AI 搜索召回。")}</p></section></div></Tabs.Content>
        <Tabs.Content value="skus"><SkuPanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="attributes"><AttributePanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="activity"><div className="core-list">{product.activity.map((row) => <div className="core-list-row" key={row.id}><ClockCounterClockwise /><div><Text weight="medium" as="div">{t(row.action)}</Text><Text size="1" color="gray">{t(row.entityType)} · {coreDate(row.occurredAt)}</Text></div></div>)}{!product.activity.length ? <CoreEmpty title={t("暂无活动记录")} description={t("重要修改将在此处形成审计时间线。")} /> : null}</div></Tabs.Content>
      </Tabs.Root>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) { return <Card><Text size="1" color="gray">{label}</Text><Heading size="4">{value}</Heading></Card>; }

function SkuPanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasAnyPermission, hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEdit = hasPermission("product.edit");
  const canViewCatalog = hasAnyPermission("catalog.view", "catalog.publish");
  const canPublish = hasAnyPermission("catalog.publish");
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([]);
  const [offers, setOffers] = useState<PublicCatalogOffer[]>([]);
  const [skuCode, setSkuCode] = useState(`${product.productCode ?? "SKU"}-${product.skus.length + 1}`);
  const [skuName, setSkuName] = useState(product.name);
  const [firstValues, setFirstValues] = useState("");
  const [secondValues, setSecondValues] = useState("");
  const [prefix, setPrefix] = useState(product.productCode ?? "SKU");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { void listAttributeDefinitions(product.categoryId).then((rows) => setDefinitions(rows.filter((row) => row.isVariant))).catch(() => setDefinitions([])); }, [product.categoryId]);
  const loadOffers = useCallback(async () => {
    if (!canViewCatalog) { setOffers([]); return; }
    try { setOffers(await listPublicCatalogOffers(product.id)); }
    catch { setOffers([]); }
  }, [canViewCatalog, product.id]);
  useEffect(() => { void loadOffers(); }, [loadOffers]);
  const matrix = useMemo(() => {
    const first = splitValues(firstValues); const second = splitValues(secondValues);
    if (!definitions[0] || !first.length) return [];
    const right = definitions[1] && second.length ? second : [""];
    return first.flatMap((a) => right.map((b) => ({ skuCode: `${prefix}-${a}-${b}`.replace(/[^a-zA-Z0-9-]+/g, "-").replace(/-+$/g, "").toUpperCase(), name: [a, b].filter(Boolean).join(" / "), optionValues: { [definitions[0].attributeKey]: a, ...(definitions[1] && b ? { [definitions[1].attributeKey]: b } : {}) } })));
  }, [definitions, firstValues, prefix, secondValues]);
  const createSingle = async () => {
    if (!skuCode.trim()) return;
    setBusy(true); setError("");
    try {
      await createSkus(product.id, [{
        skuCode: skuCode.trim(),
        name: skuName.trim() || undefined,
        optionValues: {},
        status: "DRAFT",
      }]);
      await onChanged();
      setSkuCode(`${product.productCode ?? "SKU"}-${product.skus.length + 2}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("SKU 创建失败")); }
    finally { setBusy(false); }
  };
  const createVariants = async () => {
    setBusy(true); setError("");
    try { await createSkus(product.id, matrix); await onChanged(); setFirstValues(""); setSecondValues(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("SKU 创建失败")); }
    finally { setBusy(false); }
  };
  const changeStatus = async (sku: ProductSku, status: ProductSku["status"]) => {
    setBusy(true); setError("");
    try { await updateSku(sku.id, { expectedVersion: sku.version, status }); await onChanged(); await loadOffers(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("SKU 状态更新失败")); }
    finally { setBusy(false); }
  };
  return <div className="core-tab-panel">
    {canEdit ? <Card className="core-form-grid">
      <div><Text weight="bold" as="div">{t("新增基础 SKU")}</Text><Text size="1" color="gray">{t("不需要先配置变体属性；新建后先保存为草稿。")}</Text></div>
      <label>{t("SKU 编码")}<TextField.Root value={skuCode} onChange={(event) => setSkuCode(event.target.value)} /></label>
      <label>{t("前台名称")}<TextField.Root value={skuName} onChange={(event) => setSkuName(event.target.value)} /></label>
      <Button disabled={!skuCode.trim() || busy} onClick={() => void createSingle()}><Plus />{t("创建草稿 SKU")}</Button>
    </Card> : <Text size="2" color="gray">{t("当前角色只有查看权限。")}</Text>}
    {canEdit && definitions.length ? <Card className="core-form-grid">
      <div><Text weight="bold" as="div">{t("按变体批量创建")}</Text><Text size="1" color="gray">{t("已读取当前类目的变体定义。")}</Text></div>
      <label>{t("SKU 前缀")}<TextField.Root value={prefix} onChange={(event) => setPrefix(event.target.value)} /></label>
      {definitions.slice(0, 2).map((definition, index) => <label key={definition.id}>{definition.displayName}<TextArea value={index ? secondValues : firstValues} onChange={(event) => index ? setSecondValues(event.target.value) : setFirstValues(event.target.value)} placeholder={t("逗号分隔")} /></label>)}
      <Button disabled={!matrix.length || busy} onClick={() => void createVariants()}><Plus />{t("创建 {count} 个草稿 SKU", { count: matrix.length })}</Button>
    </Card> : null}
    {error ? <CoreError message={error} /> : null}
    <div className="core-list">{product.skus.map((sku) => {
      const offer = offers.find((item) => item.skuId === sku.id);
      return <Card key={sku.id}>
        <div className="core-list-row"><Tag /><div><Text weight="medium" as="div">{sku.skuCode}</Text><Text size="1" color="gray">{sku.name || Object.values(sku.optionValues).join(" · ") || t("基础款")}</Text></div><Badge color={sku.status === "ACTIVE" ? "jade" : "gray"}>{t(skuStatusLabel[sku.status])}</Badge><Text size="1">v{sku.version}</Text>{canEdit && sku.status !== "ACTIVE" ? <Button size="1" disabled={busy} onClick={() => void changeStatus(sku, "ACTIVE")}>{t("激活 SKU")}</Button> : null}{canEdit && sku.status === "ACTIVE" ? <Button size="1" variant="soft" color="gray" disabled={busy} onClick={() => void changeStatus(sku, "INACTIVE")}>{t("下架 SKU")}</Button> : null}</div>
        {canViewCatalog ? <PublicOfferEditor sku={sku} offer={offer} canPublish={canPublish} onChanged={async () => { await loadOffers(); await onChanged(); }} /> : null}
      </Card>;
    })}{!product.skus.length ? <CoreEmpty title={t("还没有 SKU")} description={t("先创建一个基础 SKU；不必预先建立类目变体定义。")} /> : null}</div>
  </div>;
}

function PublicOfferEditor({ sku, offer, canPublish, onChanged }: { sku: ProductSku; offer?: PublicCatalogOffer; canPublish: boolean; onChanged: () => Promise<void> }) {
  const { profile } = useCoreAuth();
  const { t } = useLocale();
  const defaultCurrency = profile?.context.defaultCurrency ?? "CNY";
  const [price, setPrice] = useState(offer ? String(offer.unitPrice) : "");
  const [currency, setCurrency] = useState(offer?.currency ?? defaultCurrency);
  const [tags, setTags] = useState(offer?.tags.join("，") ?? "");
  const [displayTag, setDisplayTag] = useState(offer?.displayTag ?? offer?.tags[0] ?? "");
  const [tagColor, setTagColor] = useState(offer?.tagColor ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setPrice(offer ? String(offer.unitPrice) : "");
    setCurrency(offer?.currency ?? defaultCurrency);
    setTags(offer?.tags.join("，") ?? "");
    setDisplayTag(offer?.displayTag ?? offer?.tags[0] ?? "");
    setTagColor(offer?.tagColor ?? "");
  }, [defaultCurrency, offer]);
  const availableTags = useMemo(() => {
    const unique = new Map<string, string>();
    splitValues(tags).forEach((tag) => {
      const normalized = tag.toLocaleLowerCase();
      if (!unique.has(normalized)) unique.set(normalized, tag);
    });
    return Array.from(unique.values());
  }, [tags]);
  const selectedDisplayTag = availableTags.find(
    (tag) => tag.toLocaleLowerCase() === displayTag.toLocaleLowerCase(),
  ) ?? availableTags[0] ?? "";
  const previewTag = selectedDisplayTag || t("标签预览");
  const activeTagColor = tagColor || automaticTagColor(previewTag);
  const save = async (publicationStatus: PublicCatalogOffer["publicationStatus"]) => {
    const numericPrice = Number(price);
    if (!Number.isFinite(numericPrice) || numericPrice < 0) { setError(t("请填写有效的公开售价。")); return; }
    setBusy(true); setError("");
    try {
      await upsertPublicCatalogOffer(sku.id, {
        unitPrice: numericPrice,
        currency,
        tags: availableTags,
        displayTag: selectedDisplayTag || undefined,
        tagColor: tagColor || undefined,
        publicationStatus,
        validFrom: offer?.validFrom,
        validTo: offer?.validTo,
      });
      await onChanged();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("公开目录保存失败")); }
    finally { setBusy(false); }
  };
  return <div className="core-tab-panel">
    <div><Text weight="bold">{t("客户公开目录")}</Text> <Badge color={offer?.publicationStatus === "PUBLISHED" ? "jade" : offer?.publicationStatus === "SUSPENDED" ? "amber" : "gray"}>{offer ? t(offerStatusLabel[offer.publicationStatus]) : t("未配置")}</Badge></div>
    <Text size="1" color="gray">{t("模版中的价格和标签会同步到前台；每个商品只展示一个选定标签，后续导入会尽量保留该选择与颜色。")}</Text>
    {canPublish ? <div className="core-inline-form core-public-offer-form">
      <label><Text size="1" color="gray">{t("公开售价")}</Text><TextField.Root type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} placeholder={t("公开售价")} /></label>
      <label><Text size="1" color="gray">{t("计价币种")}</Text><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option></select></label>
      <div className="core-offer-tag-field">
        <Text size="1" color="gray">{t("商品标签")}</Text>
        <TextField.Root value={tags} onChange={(event) => setTags(event.target.value)} placeholder={t("新品，热卖，现货")} />
        <div className="core-tag-display-row">
          <label>
            <Text size="1" color="gray">{t("前台展示标签")}</Text>
            <select
              value={selectedDisplayTag}
              disabled={!availableTags.length}
              onChange={(event) => setDisplayTag(event.target.value)}
            >
              {!availableTags.length ? <option value="">{t("暂无可选标签")}</option> : null}
              {availableTags.map((tag) => <option value={tag} key={tag}>{tag}</option>)}
            </select>
          </label>
          <span className="core-tag-glass-preview" style={tagGlassStyle(previewTag, tagColor)}>
            <Tag weight="fill" />{previewTag}
          </span>
        </div>
        <div className="core-tag-color-control">
          <div className="core-tag-color-presets" role="group" aria-label={t("标签颜色")}>
            {TAG_COLOR_PALETTE.map((color) => (
              <button
                type="button"
                className={tagColor === color ? "is-active" : ""}
                style={{ background: color }}
                aria-label={`${t("标签颜色")} ${color}`}
                aria-pressed={tagColor === color}
                onClick={() => setTagColor(color)}
                key={color}
              />
            ))}
            <label className="core-tag-custom-color" title={t("自定义颜色")}>
              <input
                type="color"
                value={activeTagColor}
                aria-label={t("自定义颜色")}
                onChange={(event) => setTagColor(event.target.value.toUpperCase())}
              />
              <span>{t("自定义")}</span>
            </label>
          </div>
          <Button size="1" variant="ghost" color="gray" disabled={!tagColor} onClick={() => setTagColor("")}>{t("自动配色")}</Button>
        </div>
        <Text size="1" color="gray">{t(tagColor ? "当前使用自定义颜色。" : "系统会根据展示标签自动生成稳定颜色。")}</Text>
      </div>
      <div className="core-offer-actions">
        <Button variant="soft" color="gray" disabled={busy || !price} onClick={() => void save("DRAFT")}>{t("保存草稿")}</Button>
        <Button disabled={busy || !price || sku.status !== "ACTIVE"} onClick={() => void save("PUBLISHED")}>{t(sku.status === "ACTIVE" ? "发布到前台" : "请先激活 SKU")}</Button>
        {offer?.publicationStatus === "PUBLISHED" ? <Button variant="soft" color="amber" disabled={busy} onClick={() => void save("SUSPENDED")}>{t("暂停公开")}</Button> : null}
      </div>
    </div> : <Text size="1" color="gray">{t("当前角色没有目录发布权限。")}</Text>}
    {error ? <CoreError message={error} /> : null}
  </div>;
}

function AttributePanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEdit = hasPermission("product.edit");
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([]);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [variant, setVariant] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => listAttributeDefinitions(product.categoryId).then(setDefinitions), [product.categoryId]);
  useEffect(() => { void load().catch(() => setDefinitions([])); }, [load]);
  const add = async () => { setError(""); try { await createAttributeDefinition({ categoryId: product.categoryId, attributeKey: key, displayName: name, dataType: "TEXT", isRequired: false, isVariant: variant, isFilterable: true, isMatchable: true }); await load(); await onChanged(); setKey(""); setName(""); } catch (reason) { setError(reason instanceof Error ? reason.message : t("属性创建失败")); } };
  return <div className="core-tab-panel">{canEdit ? <Card className="core-inline-form"><TextField.Root value={key} onChange={(event) => setKey(event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))} placeholder={t("属性键")} /><TextField.Root value={name} onChange={(event) => setName(event.target.value)} placeholder={t("显示名称")} /><label className="core-check"><input type="checkbox" checked={variant} onChange={(event) => setVariant(event.target.checked)} />{t("SKU 变体")}</label><Button disabled={!key || !name} onClick={() => void add()}><Plus />{t("新增定义")}</Button></Card> : null}{error ? <CoreError message={error} /> : null}<div className="core-definition-grid">{definitions.map((definition) => <Card key={definition.id}><Tag /><Text weight="bold" as="div">{definition.displayName}</Text><code>{definition.attributeKey}</code><Badge color="gray">{definition.isVariant ? t("变体") : definition.dataType}</Badge></Card>)}</div><Heading size="3">{t("当前产品值")}</Heading><div className="core-chip-row">{product.attributes.map((attribute) => <Badge color="gray" key={attribute.id}>{attribute.key}: {String(attribute.value ?? "—")}</Badge>)}</div></div>;
}
