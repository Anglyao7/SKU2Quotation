import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Select,
  Spinner,
  Text,
} from "@radix-ui/themes";
import {
  ArrowsClockwise,
  CaretLeft,
  CaretRight,
  Package,
  Pause,
  Play,
  Translate,
  UploadSimple,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../lib/api";
import { useCoreAuth } from "../AuthContext";
import { ToastNotice } from "../ToastContext";
import {
  CoreApiError,
  getCatalogTranslationJob,
  getCatalogTranslationBatchPage,
  getCatalogTranslationStatus,
  getLatestCatalogTranslationJob,
  pauseCatalogTranslationJob,
  publishCatalogLanguagePack,
  resumeCatalogTranslationJob,
  retryCatalogTranslationBatch,
  startCatalogTranslationJob,
} from "../api";
import type {
  CatalogTranslationJob,
  CatalogTranslationJobStage,
  CatalogTranslationBatch,
  CatalogTranslationBatchFilter,
  CatalogTranslationBatchPage,
  CatalogTranslationStatus,
} from "../types";
import { useLocale } from "../LocaleContext";
import {
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
} from "../../lib/storefrontLocale";
import type { StorefrontLocale, Tenant } from "../../types";
import { CatalogTranslationEditor } from "./CatalogTranslationEditor";

const TARGET_LANGUAGES = STOREFRONT_LANGUAGE_OPTIONS.filter(
  (language) => language.code !== "zh-CN",
);
const TRANSLATION_TENANT_STORAGE_KEY = "atc.admin.catalog-translation-tenant";
const BATCH_PAGE_SIZE_OPTIONS = [20, 50, 100] as const;

type PaginationItem = number | "leading-ellipsis" | "trailing-ellipsis";

function paginationItems(page: number, pages: number): PaginationItem[] {
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

const stageCopy: Record<CatalogTranslationJobStage, string> = {
  QUEUED: "等待开始",
  PREPARING: "核对变更",
  TRANSLATING: "正在翻译",
  PACKAGING: "正在生成语言包",
  UPLOADING: "正在上传语言包",
  PAUSED: "翻译已暂停",
  PUBLISHED: "发布完成",
  FAILED: "任务失败",
};

function formatBytes(value?: number) {
  if (value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(2)} MB`;
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString();
}

function completedSkuCount(job?: CatalogTranslationJob) {
  if (!job) return 0;
  return job.executionMode === "QWEN_BATCH"
    ? job.translationProcessedSkus
    : job.processedSkus;
}

export function LanguagePackagesPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEditProducts = hasPermission("product.edit");
  const [merchants, setMerchants] = useState<Tenant[]>([]);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [merchantsLoading, setMerchantsLoading] = useState(true);
  const [merchantsError, setMerchantsError] = useState("");
  const [selectedLocale, setSelectedLocale] = useState<StorefrontLocale>("en-US");
  const [status, setStatus] = useState<CatalogTranslationStatus>();
  const [job, setJob] = useState<CatalogTranslationJob>();
  const [batchHistory, setBatchHistory] = useState<CatalogTranslationBatchPage>();
  const [batchesJobId, setBatchesJobId] = useState<string>();
  const [batchPage, setBatchPage] = useState(1);
  const [batchPageSize, setBatchPageSize] = useState(50);
  const [batchStatusFilter, setBatchStatusFilter] = useState<CatalogTranslationBatchFilter>("ALL");
  const [retryingBatchId, setRetryingBatchId] = useState<string>();
  const [coverageLoading, setCoverageLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [batchHistoryLoading, setBatchHistoryLoading] = useState(false);
  const [startingJob, setStartingJob] = useState(false);
  const [publishingPack, setPublishingPack] = useState(false);
  const [controllingJob, setControllingJob] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const selectedTenantIdRef = useRef(selectedTenantId);
  const selectedLocaleRef = useRef<StorefrontLocale>(selectedLocale);
  const localeRequestIdRef = useRef(0);
  const batchRequestIdRef = useRef(0);
  const batchPageRef = useRef(batchPage);
  const batchPageSizeRef = useRef(batchPageSize);
  const batchStatusFilterRef = useRef(batchStatusFilter);

  const selectedMerchant = merchants.find(
    (merchant) => merchant.id === selectedTenantId,
  );

  useEffect(() => {
    let active = true;
    void api.getTenants()
      .then((rows) => {
        if (!active) return;
        const available = rows.filter((tenant) => (
          tenant.identity_code !== "ADMIN" && tenant.status !== "archived"
        ));
        setMerchants(available);
        const remembered = window.localStorage.getItem(
          TRANSLATION_TENANT_STORAGE_KEY,
        );
        const initial = available.find((tenant) => tenant.id === remembered)
          ?? available.find((tenant) => tenant.status === "active")
          ?? available[0];
        setSelectedTenantId(initial?.id ?? "");
      })
      .catch((reason) => {
        if (active) {
          setMerchantsError(
            reason instanceof Error ? reason.message : t("商家列表加载失败。"),
          );
        }
      })
      .finally(() => {
        if (active) setMerchantsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [t]);

  const selectedStatus = status?.targetLocale === selectedLocale
    ? status
    : undefined;
  const selectedJob = job?.targetLocale === selectedLocale
    ? job
    : undefined;
  const selectedBatchHistory = selectedJob && batchesJobId === selectedJob.id
    ? batchHistory
    : undefined;
  const selectedBatches = selectedBatchHistory?.items ?? [];
  const activeJob = selectedJob && ["QUEUED", "RUNNING", "PAUSED"].includes(selectedJob.status)
    ? selectedJob
    : undefined;
  const controllableJob = activeJob ?? (
    selectedJob?.status === "FAILED" && selectedJob.resumable ? selectedJob : undefined
  );
  const pollableJob = selectedJob && (
    ["QUEUED", "RUNNING"].includes(selectedJob.status) || selectedJob.pauseRequested
  ) ? selectedJob : undefined;
  const selectedLanguage = storefrontLanguage(selectedLocale);
  const jobIsPublishing = Boolean(
    activeJob && ["PACKAGING", "UPLOADING"].includes(activeJob.stage),
  );
  const displayedTotalSkus = selectedStatus
    ? selectedStatus.totalSkus
    : selectedJob
      ? selectedJob.totalSkus
      : 0;
  const checkpointTranslatedSkus = completedSkuCount(selectedJob);
  const displayedTranslatedSkus = Math.min(
    displayedTotalSkus,
    Math.max(
      selectedStatus?.translatedSkus ?? 0,
      checkpointTranslatedSkus,
    ),
  );
  const displayedPendingSkus = Math.max(
    0,
    displayedTotalSkus - displayedTranslatedSkus,
  );
  const displayedRemainingJobSkus = selectedJob
    ? selectedJob.executionMode === "QWEN_BATCH"
      ? Math.max(0, selectedJob.totalSkus - completedSkuCount(selectedJob))
      : selectedStatus?.pendingSkus ?? selectedJob.remainingSkus
    : 0;
  const resumableRealtimeJob = selectedJob?.resumable
    && selectedJob.executionMode === "REALTIME"
    ? selectedJob
    : undefined;
  const resumableBatchJob = selectedJob?.resumable
    && selectedJob.executionMode === "QWEN_BATCH"
    ? selectedJob
    : undefined;
  const jobOnlyNeedsPackageFields = Boolean(
    selectedJob?.status === "FAILED"
    && selectedJob.translationTotalValues === 0
    && selectedStatus
    && selectedStatus.pendingSkus === 0
    && selectedStatus.packageOutdated,
  );
  const displayedJobError = (() => {
    const message = selectedJob?.errorMessage;
    if (!message) return "";
    const incomplete = message.match(
      /^language package translation left (\d+) fields incomplete/i,
    );
    if (incomplete) {
      return t("语言包仍有 {count} 个字段未完成翻译，SKU 译文不会丢失。", {
        count: incomplete[1],
      });
    }
    return message;
  })();

  const localeRequestIsCurrent = (
    locale: StorefrontLocale,
    tenantId: string,
    requestId?: number,
  ) => selectedLocaleRef.current === locale
    && selectedTenantIdRef.current === tenantId
    && (requestId === undefined || localeRequestIdRef.current === requestId);

  const refreshStatus = async (
    locale = selectedLocaleRef.current,
    tenantId = selectedTenantIdRef.current,
    requestId?: number,
  ) => {
    const next = await getCatalogTranslationStatus(locale, {
      includeLatestJob: false,
      tenantId,
    });
    if (localeRequestIsCurrent(locale, tenantId, requestId)) setStatus(next);
    return next;
  };

  const refreshBatches = async (
    jobId: string | undefined,
    locale = selectedLocaleRef.current,
    tenantId = selectedTenantIdRef.current,
    requestId?: number,
  ) => {
    const batchRequestId = ++batchRequestIdRef.current;
    if (!jobId) {
      if (localeRequestIsCurrent(locale, tenantId, requestId)) {
        setBatchHistory(undefined);
        setBatchesJobId(undefined);
        setBatchHistoryLoading(false);
      }
      return;
    }
    if (localeRequestIsCurrent(locale, tenantId, requestId)) {
      setBatchHistoryLoading(true);
    }
    try {
      const requestedPage = batchPageRef.current;
      const next = await getCatalogTranslationBatchPage(jobId, {
        includeSkus: false,
        page: requestedPage,
        pageSize: batchPageSizeRef.current,
        status: batchStatusFilterRef.current,
        tenantId,
      });
      if (
        batchRequestIdRef.current === batchRequestId
        && localeRequestIsCurrent(locale, tenantId, requestId)
      ) {
        setBatchHistory(next);
        setBatchesJobId(jobId);
        if (next.page !== requestedPage) {
          batchPageRef.current = next.page;
          setBatchPage(next.page);
        }
      }
    } finally {
      if (
        batchRequestIdRef.current === batchRequestId
        && localeRequestIsCurrent(locale, tenantId, requestId)
      ) {
        setBatchHistoryLoading(false);
      }
    }
  };

  const refreshHistory = async (
    locale = selectedLocaleRef.current,
    tenantId = selectedTenantIdRef.current,
    requestId?: number,
  ) => {
    const next = await getLatestCatalogTranslationJob(locale, tenantId);
    if (!localeRequestIsCurrent(locale, tenantId, requestId)) return next;
    setJob(next);
    setHistoryLoading(false);
    await refreshBatches(next?.id, locale, tenantId, requestId).catch(
      () => undefined,
    );
    return next;
  };

  useEffect(() => {
    selectedTenantIdRef.current = selectedTenantId;
    selectedLocaleRef.current = selectedLocale;
    const requestId = ++localeRequestIdRef.current;
    batchRequestIdRef.current += 1;
    setError("");
    setSuccess("");
    setStatus(undefined);
    setJob(undefined);
    setBatchHistory(undefined);
    setBatchesJobId(undefined);
    batchPageRef.current = 1;
    batchPageSizeRef.current = 50;
    batchStatusFilterRef.current = "ALL";
    setBatchPage(1);
    setBatchPageSize(50);
    setBatchStatusFilter("ALL");
    setCoverageLoading(true);
    setHistoryLoading(true);
    setBatchHistoryLoading(false);
    if (!selectedTenantId) {
      setCoverageLoading(false);
      setHistoryLoading(false);
      return;
    }
    window.localStorage.setItem(
      TRANSLATION_TENANT_STORAGE_KEY,
      selectedTenantId,
    );

    void refreshStatus(selectedLocale, selectedTenantId, requestId)
      .catch((caught) => {
        if (localeRequestIsCurrent(selectedLocale, selectedTenantId, requestId)) {
          setError(caught instanceof Error ? caught.message : t("翻译状态读取失败。"));
        }
      })
      .finally(() => {
        if (localeRequestIsCurrent(selectedLocale, selectedTenantId, requestId)) {
          setCoverageLoading(false);
        }
      });
    void refreshHistory(selectedLocale, selectedTenantId, requestId)
      .catch((caught) => {
        if (localeRequestIsCurrent(selectedLocale, selectedTenantId, requestId)) {
          setHistoryLoading(false);
          setError(caught instanceof Error ? caught.message : t("翻译历史记录读取失败。"));
        }
      });
  }, [selectedLocale, selectedTenantId]);

  useEffect(() => {
    if (!pollableJob || !selectedTenantId) return;
    const pollTenantId = selectedTenantId;
    let cancelled = false;
    let requestInFlight = false;
    let lastObservedStage = pollableJob.stage;
    let lastObservedProcessed = completedSkuCount(pollableJob);
    let lastCoverageRefreshAt = Date.now();
    let lastBatchRefreshAt = 0;
    let coverageRefreshInFlight = false;
    const poll = () => {
      if (requestInFlight) return;
      requestInFlight = true;
      void getCatalogTranslationJob(pollableJob.id, pollTenantId)
        .then((next) => {
          if (cancelled) return;
          const now = Date.now();
          const stageChanged = next.stage !== lastObservedStage;
          const nextProcessed = completedSkuCount(next);
          const processedChanged = nextProcessed !== lastObservedProcessed;
          if (
            next.targetLocale !== selectedLocaleRef.current
            || pollTenantId !== selectedTenantIdRef.current
          ) return;
          setJob(next);
          if (
            now - lastBatchRefreshAt >= 5_000
            || !["QUEUED", "RUNNING"].includes(next.status)
          ) {
            lastBatchRefreshAt = now;
            void refreshBatches(
              next.id,
              next.targetLocale,
              pollTenantId,
            ).catch(() => undefined);
          }
          if (
            next.targetLocale === selectedLocaleRef.current
            && !coverageRefreshInFlight
            && (
              stageChanged
              || (processedChanged && now - lastCoverageRefreshAt >= 8_000)
            )
          ) {
            lastCoverageRefreshAt = now;
            coverageRefreshInFlight = true;
            void getCatalogTranslationStatus(next.targetLocale, {
              includeLatestJob: false,
              tenantId: pollTenantId,
            })
              .then((latest) => {
                if (
                  !cancelled
                  && latest.targetLocale === selectedLocaleRef.current
                  && pollTenantId === selectedTenantIdRef.current
                ) setStatus(latest);
              })
              .catch(() => undefined)
              .finally(() => {
                coverageRefreshInFlight = false;
              });
          }
          lastObservedStage = next.stage;
          lastObservedProcessed = nextProcessed;
          if (!["QUEUED", "RUNNING"].includes(next.status)) {
            window.clearInterval(timer);
            if (next.status === "PAUSED") {
              setSuccess(t("翻译已暂停，已完成的内容会保留。"));
              void Promise.all([
                refreshStatus(next.targetLocale, pollTenantId),
                refreshHistory(next.targetLocale, pollTenantId),
              ]).catch(() => undefined);
              return;
            }
            void Promise.all([
              refreshStatus(next.targetLocale, pollTenantId),
              refreshHistory(next.targetLocale, pollTenantId),
            ]).then(([latest]) => {
              if (cancelled) return;
              if (next.status === "SUCCEEDED" && latest.package) {
                setSuccess(t("翻译内容已更新，前台将自动使用最新版本。"));
              }
            });
          }
        })
        .catch(() => undefined)
        .finally(() => {
          requestInFlight = false;
        });
    };
    const timer = window.setInterval(poll, 1200);
    poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [
    pollableJob?.id,
    pollableJob?.pauseRequested,
    selectedLocale,
    selectedTenantId,
  ]);

  useEffect(() => {
    if (
      !selectedTenantId
      || !selectedJob?.id
      || pollableJob
      || batchesJobId === selectedJob.id
    ) return;
    void refreshBatches(
      selectedJob.id,
      selectedJob.targetLocale,
      selectedTenantId,
    ).catch(() => undefined);
  }, [selectedJob?.id, pollableJob, batchesJobId, selectedTenantId]);

  useEffect(() => {
    if (
      !selectedTenantId
      || !selectedJob?.id
      || batchesJobId !== selectedJob.id
    ) return;
    void refreshBatches(
      selectedJob.id,
      selectedJob.targetLocale,
      selectedTenantId,
    ).catch(() => undefined);
  }, [batchPage, batchPageSize, batchStatusFilter]);

  const startJob = async (fullRebuild: boolean) => {
    if (
      !canEditProducts
      || !selectedTenantId
      || startingJob
      || (activeJob && activeJob.status !== "PAUSED")
    ) return;
    const executionMode = fullRebuild ? "QWEN_BATCH" : "REALTIME";
    const resumeCandidate = fullRebuild
      ? resumableBatchJob
      : resumableRealtimeJob;
    const actionLocale = selectedLocale;
    const actionTenantId = selectedTenantId;
    setStartingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = resumeCandidate
        ? await resumeCatalogTranslationJob(resumeCandidate.id, actionTenantId)
        : await startCatalogTranslationJob(
            actionLocale,
            fullRebuild,
            executionMode,
            actionTenantId,
          );
      if (!localeRequestIsCurrent(actionLocale, actionTenantId)) return;
      setJob(next);
      setBatchHistory(undefined);
      setBatchesJobId(undefined);
      batchPageRef.current = 1;
      batchPageSizeRef.current = 50;
      batchStatusFilterRef.current = "ALL";
      setBatchPage(1);
      setBatchPageSize(50);
      setBatchStatusFilter("ALL");
      void refreshBatches(
        next.id,
        next.targetLocale,
        actionTenantId,
      ).catch(() => undefined);
      if (next.status === "SUCCEEDED") {
        await Promise.all([
          refreshStatus(actionLocale, actionTenantId),
          refreshHistory(actionLocale, actionTenantId),
        ]);
        setSuccess(t("当前翻译内容已经是最新版本。"));
      } else if (resumeCandidate) {
        setSuccess(t(fullRebuild
          ? "Batch 全量翻译已从原断点继续。"
          : displayedRemainingJobSkus === 0
            ? "正在核对断点并补齐未完成的语言包字段。"
            : "并发翻译已从原断点继续。"));
      }
    } catch (caught) {
      const message = caught instanceof CoreApiError || caught instanceof Error
        ? caught.message
        : t("翻译任务启动失败。");
      if (localeRequestIsCurrent(actionLocale, actionTenantId)) setError(message);
    } finally {
      setStartingJob(false);
    }
  };

  const publishCurrentLanguagePack = async () => {
    if (
      !canEditProducts
      || !selectedTenantId
      || publishingPack
      || displayedTranslatedSkus === 0
    ) return;
    const actionLocale = selectedLocale;
    const actionTenantId = selectedTenantId;
    setPublishingPack(true);
    setError("");
    setSuccess("");
    try {
      const pack = await publishCatalogLanguagePack(
        actionLocale,
        actionTenantId,
      );
      if (!localeRequestIsCurrent(actionLocale, actionTenantId)) return;
      await refreshStatus(actionLocale, actionTenantId);
      setSuccess(t("已手动发布 {language} 语言包 v{version}；未完成内容继续显示中文原文。", {
        language: selectedLanguage.label,
        version: pack.version,
      }));
    } catch (caught) {
      if (localeRequestIsCurrent(actionLocale, actionTenantId)) {
        setError(caught instanceof Error
          ? caught.message
          : t("手动发布语言包失败。"));
      }
    } finally {
      setPublishingPack(false);
    }
  };

  const controlTranslationJob = async (action: "pause" | "resume") => {
    if (
      !canEditProducts
      || !selectedTenantId
      || !controllableJob
      || controllingJob
    ) return;
    const actionTenantId = selectedTenantId;
    setControllingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = action === "pause"
        ? await pauseCatalogTranslationJob(controllableJob.id, actionTenantId)
        : await resumeCatalogTranslationJob(controllableJob.id, actionTenantId);
      setJob(next);
      void refreshBatches(
        next.id,
        next.targetLocale,
        actionTenantId,
      ).catch(() => undefined);
      if (action === "pause") {
        setSuccess(next.status === "PAUSED"
          ? t("翻译已暂停，已完成的内容会保留。")
          : t("正在完成当前翻译批次，随后会安全暂停。"));
      } else {
        setSuccess(t(displayedRemainingJobSkus === 0
          ? "正在核对断点并补齐未完成的语言包字段。"
          : "翻译任务已从断点继续，只会处理剩余商品。"));
      }
    } catch (caught) {
      setError(caught instanceof Error
        ? caught.message
        : t(action === "pause" ? "暂停翻译失败。" : "继续翻译失败。"));
    } finally {
      setControllingJob(false);
    }
  };

  const retryBatch = async (batch: CatalogTranslationBatch) => {
    if (!selectedTenantId || !selectedJob || retryingBatchId) return;
    const actionTenantId = selectedTenantId;
    setRetryingBatchId(batch.id);
    setError("");
    setSuccess("");
    try {
      const next = await retryCatalogTranslationBatch(
        selectedJob.id,
        batch.id,
        actionTenantId,
      );
      setJob(next);
      await refreshBatches(next.id, next.targetLocale, actionTenantId);
      setSuccess(t("已重新提交第 {batch} 批，正在从该批次重新翻译。", { batch: batch.sequenceNo }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("批次重新请求失败。"));
    } finally {
      setRetryingBatchId(undefined);
    }
  };

  const changeBatchFilter = (next: CatalogTranslationBatchFilter) => {
    if (next === batchStatusFilter) return;
    batchStatusFilterRef.current = next;
    batchPageRef.current = 1;
    setBatchStatusFilter(next);
    setBatchPage(1);
  };

  const changeBatchPage = (next: number) => {
    const pages = selectedBatchHistory?.pages ?? 0;
    const normalized = Math.max(1, Math.min(next, Math.max(1, pages)));
    if (normalized === batchPage) return;
    batchPageRef.current = normalized;
    setBatchPage(normalized);
  };

  const changeBatchPageSize = (next: number) => {
    if (next === batchPageSize) return;
    batchPageSizeRef.current = next;
    batchPageRef.current = 1;
    setBatchPageSize(next);
    setBatchPage(1);
  };

  const coverage = useMemo(() => {
    if (!displayedTotalSkus) return 0;
    return Math.round(displayedTranslatedSkus / displayedTotalSkus * 100);
  }, [displayedTotalSkus, displayedTranslatedSkus]);
  const batchPagination = useMemo(
    () => paginationItems(
      selectedBatchHistory?.page ?? 1,
      selectedBatchHistory?.pages ?? 0,
    ),
    [selectedBatchHistory?.page, selectedBatchHistory?.pages],
  );
  const batchFilterOptions: Array<{
    value: CatalogTranslationBatchFilter;
    label: string;
    count: number;
  }> = [
    {
      value: "ALL",
      label: "全部批次",
      count: selectedBatchHistory?.allCount ?? selectedJob?.batchCount ?? 0,
    },
    {
      value: "SUCCEEDED",
      label: "已完成",
      count: selectedBatchHistory?.completedCount
        ?? selectedJob?.completedBatchCount
        ?? 0,
    },
    {
      value: "IN_PROGRESS",
      label: "请求中",
      count: selectedBatchHistory?.inProgressCount ?? 0,
    },
    {
      value: "FAILED",
      label: "失败待重试",
      count: selectedBatchHistory?.failedCount
        ?? selectedJob?.failedBatchCount
        ?? 0,
    },
  ];

  return (
    <div className="core-workspace language-pack-page">
      <div className="core-page-heading language-pack-heading">
        <div>
          <Text size="2" color="gray">{t("平台")}</Text>
          <Heading size="8">{t("商家翻译")}</Heading>
          <Text size="2" color="gray">
            {t("管理员统一执行翻译任务，并查看、微调各语言的商品译文。")}
          </Text>
        </div>
        <div className="language-merchant-selector">
          <Text size="1" color="gray">{t("当前翻译商家")}</Text>
          <Select.Root
            value={selectedTenantId}
            onValueChange={setSelectedTenantId}
            disabled={merchantsLoading || !merchants.length}
          >
            <Select.Trigger
              placeholder={t(merchantsLoading ? "正在读取商家" : "选择要翻译的商家")}
              aria-label={t("选择要翻译的商家")}
            />
            <Select.Content position="popper">
              {merchants.map((merchant) => (
                <Select.Item key={merchant.id} value={merchant.id}>
                  {merchant.name} · {merchant.sku_count ?? 0} SKU
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
          {selectedMerchant ? (
            <Text size="1" color="gray">/{selectedMerchant.slug}</Text>
          ) : null}
        </div>
      </div>

      {merchantsError ? <ToastNotice kind="error" message={merchantsError} /> : null}
      {error ? <ToastNotice kind="error" message={error} /> : null}
      {success ? <ToastNotice kind="success" message={success} /> : null}
      {!merchantsLoading && !merchants.length && !merchantsError ? (
        <ToastNotice kind="info" message={t("当前没有可翻译的商家。")} />
      ) : null}

      <div className="language-pack-grid">
        <Card className="language-pack-status-card">
          <div className="language-card-heading compact">
            <span><Translate weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{selectedLanguage.flag} {selectedLanguage.label}</Text>
              <Heading size="5">{t("SKU 翻译覆盖")}</Heading>
            </div>
            <div className="language-status-controls">
              <Select.Root
                value={selectedLocale}
                onValueChange={(value) => setSelectedLocale(value as StorefrontLocale)}
              >
                <Select.Trigger
                  className="language-target-trigger"
                  aria-label={t("选择翻译语言")}
                />
                <Select.Content position="popper">
                  {TARGET_LANGUAGES.map((language) => (
                    <Select.Item key={language.code} value={language.code}>
                      {language.flag} {language.label}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
              <Badge color={coverageLoading
                ? "gray"
                : selectedStatus?.packageOutdated
                  ? "amber"
                  : selectedStatus?.package && displayedPendingSkus > 0
                    ? "blue"
                    : selectedStatus?.package
                      ? "green"
                      : "gray"}>
                {t(coverageLoading
                  ? "正在同步"
                  : selectedStatus?.packageOutdated
                    ? "有内容待更新"
                    : selectedStatus?.package && displayedPendingSkus > 0
                      ? "已发布当前进度"
                      : selectedStatus?.package
                        ? "内容已是最新"
                      : "尚未翻译")}
              </Badge>
            </div>
          </div>
          {coverageLoading ? (
            <div className="language-history-loading">
              <Spinner size="3" />
              <div>
                <Text weight="bold">{t("正在核对翻译覆盖情况")}</Text>
                <Text size="1" color="gray">{t("正在统计已翻译、待更新和新增的 SKU，请稍候。")}</Text>
              </div>
            </div>
          ) : (
            <>
              <div className="language-pack-metrics">
                <div><strong>{displayedTotalSkus}</strong><span>{t("公开 SKU")}</span></div>
                <div><strong>{displayedTranslatedSkus}</strong><span>{t("已完成（含人工）")}</span></div>
                <div><strong>{displayedPendingSkus}</strong><span>{t("新增或变更")}</span></div>
                <div><strong>{coverage}%</strong><span>{t("SKU 翻译覆盖")}</span></div>
              </div>
              <Progress value={coverage} size="3" color={coverage === 100 ? "green" : "blue"} />
            </>
          )}
          <div className="language-pack-actions">
            <Button
              size="3"
              onClick={() => void startJob(false)}
              loading={startingJob}
              disabled={
                !canEditProducts
                || !selectedTenantId
                || coverageLoading
                || historyLoading
                || startingJob
                || Boolean(activeJob && activeJob.status !== "PAUSED")
              }
            >
              <ArrowsClockwise />
              {t("更新翻译（并发 AI）")}
            </Button>
            <AlertDialog.Root>
              <AlertDialog.Trigger>
                <Button
                  size="3"
                  variant="soft"
                  color="gray"
                  disabled={
                    !canEditProducts
                    || !selectedTenantId
                    || coverageLoading
                    || historyLoading
                    || startingJob
                    || Boolean(activeJob && activeJob.status !== "PAUSED")
                  }
                >
                  {t(resumableBatchJob ? "继续 Batch 全量翻译" : "全量翻译（Batch）")}
                </Button>
              </AlertDialog.Trigger>
              <AlertDialog.Content maxWidth="480px">
                <AlertDialog.Title>{t(resumableBatchJob
                  ? "从 Batch 断点继续翻译 {language}？"
                  : "全量重新翻译 {language}？", { language: selectedLanguage.label })}</AlertDialog.Title>
                <AlertDialog.Description>
                  {t(resumableBatchJob
                    ? "系统会继续原 Batch 任务及失败重试，不会重新提交已成功的内容。"
                    : "系统会通过 Batch 翻译全部商品。完成前，前台会继续使用现有翻译内容。")}
                </AlertDialog.Description>
                <div className="language-pack-dialog-actions">
                  <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
                  <AlertDialog.Action><Button color="red" onClick={() => void startJob(true)}>{t(resumableBatchJob ? "确认从断点继续" : "确认全量翻译")}</Button></AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Root>
            {controllableJob && !jobIsPublishing ? (
              <Button
                size="3"
                variant="soft"
                color={controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? "green" : "amber"}
                loading={controllingJob}
                disabled={
                  controllingJob
                  || (controllableJob.status !== "PAUSED" && controllableJob.pauseRequested)
                }
                onClick={() => void controlTranslationJob(
                  controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? "resume" : "pause",
                )}
              >
                {controllableJob.status === "PAUSED" || controllableJob.status === "FAILED" ? <Play weight="fill" /> : <Pause weight="fill" />}
                {t(controllableJob.status === "FAILED"
                  ? "从断点继续"
                  : controllableJob.status === "PAUSED"
                    ? "继续翻译"
                    : controllableJob.pauseRequested
                      ? "正在暂停"
                      : "暂停翻译")}
              </Button>
            ) : null}
          </div>
          <Text size="1" color="gray" className="language-action-note">
            {t("更新翻译按配置中心的模型与并发，只处理新增或变更；全量翻译使用 Batch，并优先延续已有断点。")}
          </Text>
          {activeJob?.pauseRequested && activeJob.status !== "PAUSED" ? (
            <Text size="1" color="gray" className="language-pause-note">
              {t("系统会先保存当前批次，再进入暂停状态，不会丢失已完成的翻译。")}
            </Text>
          ) : null}
          {jobIsPublishing ? (
            <Text size="1" color="gray" className="language-pause-note">
              {t("翻译结果已全部保存；当前只在生成或上传语言包，不再请求翻译模型。")}
            </Text>
          ) : null}
        </Card>

        <Card className="language-package-release-card">
          <div className="language-card-heading compact">
            <span><Package weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{t("当前发布版本")}</Text>
              <Heading size="5">{selectedStatus?.package ? `v${selectedStatus.package.version}` : "—"}</Heading>
            </div>
          </div>
          {coverageLoading ? (
            <div className="language-history-loading is-compact">
              <Spinner size="2" />
              <Text size="2" color="gray">{t("正在读取当前发布版本")}</Text>
            </div>
          ) : (
            <dl className="language-package-details">
              <div><dt>{t("发布时间")}</dt><dd>{formatDate(selectedStatus?.package?.publishedAt)}</dd></div>
              <div><dt>{t("源数据截止")}</dt><dd>{formatDate(selectedStatus?.package?.sourceCutoffAt)}</dd></div>
              <div><dt>{t("内容大小")}</dt><dd>{formatBytes(selectedStatus?.package?.byteSize)}</dd></div>
              <div><dt>{t("包含内容")}</dt><dd>{selectedStatus?.package ? `${selectedStatus.package.productCount} Products · ${selectedStatus.package.skuCount} SKUs` : "—"}</dd></div>
            </dl>
          )}
          <div className="language-package-manual-release">
            <div>
              <Text size="2" weight="bold">{t("手动发布当前进度")}</Text>
              <Text size="1" color="gray">
                {t("无需等待全部翻译完成；发布后，已完成和人工确认的译文立即生效，缺失内容继续回退中文。")}
              </Text>
            </div>
            <AlertDialog.Root>
              <AlertDialog.Trigger>
                <Button
                  variant="soft"
                  size="2"
                  loading={publishingPack}
                  disabled={
                    !canEditProducts
                    || coverageLoading
                    || publishingPack
                    || displayedTranslatedSkus === 0
                    || !selectedStatus?.packageOutdated
                  }
                >
                  <UploadSimple />
                  {t("手动发布语言包")}
                </Button>
              </AlertDialog.Trigger>
              <AlertDialog.Content maxWidth="500px">
                <AlertDialog.Title>
                  {t("发布当前 {language} 翻译进度？", {
                    language: selectedLanguage.label,
                  })}
                </AlertDialog.Title>
                <AlertDialog.Description>
                  {t("当前已完成 {done} / {total} 个 SKU。系统会创建一个新的语言包版本；未完成的 SKU 不会阻塞发布，并继续显示中文原文。", {
                    done: displayedTranslatedSkus,
                    total: displayedTotalSkus,
                  })}
                </AlertDialog.Description>
                <div className="language-pack-dialog-actions">
                  <AlertDialog.Cancel>
                    <Button variant="soft" color="gray">{t("取消")}</Button>
                  </AlertDialog.Cancel>
                  <AlertDialog.Action>
                    <Button onClick={() => void publishCurrentLanguagePack()}>
                      {t("确认发布新版本")}
                    </Button>
                  </AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Root>
          </div>
        </Card>
      </div>

      {selectedTenantId ? (
        <CatalogTranslationEditor
          key={`${selectedTenantId}:${selectedLocale}`}
          tenantId={selectedTenantId}
          locale={selectedLocale}
          packageVersion={selectedStatus?.package?.version}
          onLocaleChange={setSelectedLocale}
          onSaved={async () => {
            await refreshStatus(selectedLocale, selectedTenantId);
          }}
        />
      ) : null}

      {historyLoading ? (
        <Card className="language-job-card">
          <div className="language-history-loading">
            <Spinner size="3" />
            <div>
              <Text weight="bold">{t("正在读取翻译历史记录")}</Text>
              <Text size="1" color="gray">{t("任务进度与批次记录会在读取完成后同步显示。")}</Text>
            </div>
          </div>
        </Card>
      ) : selectedJob ? (
        <Card className={`language-job-card is-${selectedJob.status.toLocaleLowerCase()}`}>
          <div className="language-job-header">
            <div>
              <Text size="1" color="gray">{t("最近任务")}</Text>
              <Heading size="4">
                {t(jobOnlyNeedsPackageFields
                  ? "SKU 已翻译，语言包仍待补全"
                  : selectedJob.status === "FAILED" && selectedJob.resumable
                    ? "任务中断，断点已保存"
                    : stageCopy[selectedJob.stage])}
              </Heading>
            </div>
            <Badge color={selectedJob.status === "FAILED"
              ? "red"
              : selectedJob.status === "SUCCEEDED"
                ? "green"
                : selectedJob.status === "PAUSED" || selectedJob.pauseRequested
                  ? "amber"
                  : "blue"}>
              {selectedJob.progressPercent.toFixed(1)}%
            </Badge>
          </div>
          <Progress
            value={selectedJob.progressPercent}
            size="3"
            color={selectedJob.status === "FAILED"
              ? "red"
              : selectedJob.status === "PAUSED" || selectedJob.pauseRequested
                ? "amber"
                : "blue"}
          />
          <div className="language-job-copy">
            {selectedJob.translationTotalValues > 0 ? (
              <>
                <span>
                  {t("已完成 {done} / {total} 个翻译字段", {
                    done: selectedJob.translationProcessedValues,
                    total: selectedJob.translationTotalValues,
                  })}
                </span>
                <span>
                  {t("已有完整译文 {done} / {total} 个 SKU", {
                    done: displayedTranslatedSkus,
                    total: selectedJob.totalSkus,
                  })}
                </span>
                {selectedJob.executionMode === "QWEN_BATCH" ? (
                  <span>
                    {selectedJob.externalBatchStatus?.startsWith("realtime_")
                      ? t("Qwen 实时并发 · 已完成 {done} / {total} 个请求", {
                          done: selectedJob.externalCompletedRequests,
                          total: selectedJob.externalTotalRequests,
                        })
                      : t("Qwen Batch · {status} · 上游完成 {done} / {total} 个请求", {
                          status: selectedJob.externalBatchStatus ?? t("准备中"),
                          done: selectedJob.externalCompletedRequests,
                          total: selectedJob.externalTotalRequests,
                        })}
                  </span>
                ) : (
                  <span>{t("实时并发 · SKU 与语言包字段统一翻译")}</span>
                )}
              </>
            ) : (
              <span>{t("已处理 {done} / {total} 个 SKU", { done: selectedJob.processedSkus, total: selectedJob.totalSkus })}</span>
            )}
            {selectedJob.translationTotalValues === 0
              && selectedJob.finalizationTotalValues > 0 ? (
              <span>
                {t("语言包字段 {done} / {total} 项", {
                  done: selectedJob.finalizationProcessedValues,
                  total: selectedJob.finalizationTotalValues,
                })}
              </span>
            ) : null}
            {selectedJob.resumable ? (
              <span>
                {t("剩余 {remaining} 个 SKU · 断点 {time}", {
                  remaining: displayedRemainingJobSkus,
                  time: formatDate(selectedJob.checkpointAt),
                })}
              </span>
            ) : null}
            {selectedJob.currentSkuName ? <span>{selectedJob.currentSkuName}</span> : null}
            {selectedJob.status === "PAUSED" ? (
              <span>{t(
                selectedJob.translationTotalValues > selectedJob.translationProcessedValues
                  ? "继续后将从未完成文本断点继续"
                  : displayedRemainingJobSkus === 0
                    ? "继续后将核对并补齐未完成字段"
                    : "继续后将从剩余商品开始",
              )}</span>
            ) : null}
            {selectedJob.packagePublished ? <span>{t("已发布版本 v{version}", { version: selectedJob.packageVersion ?? "—" })}</span> : null}
          </div>
          {displayedJobError ? <Text color="red" size="2">{displayedJobError}</Text> : null}
        </Card>
      ) : null}

      {batchHistoryLoading && selectedJob && !selectedBatchHistory ? (
        <Card className="language-batch-history-card">
          <div className="language-history-loading is-compact">
            <Spinner size="2" />
            <Text size="2" color="gray">{t("正在读取翻译批次记录")}</Text>
          </div>
        </Card>
      ) : selectedJob ? (
        <Card className="language-batch-history-card">
          <div className="language-job-header">
            <div>
              <Text size="1" color="gray">{t("请求记录")}</Text>
              <Heading size="4">{t("翻译批次")}</Heading>
            </div>
            <div className="language-batch-heading-meta">
              {batchHistoryLoading ? <Spinner size="1" /> : null}
              <Badge color="gray">
                {t("共 {count} 批", {
                  count: selectedBatchHistory?.allCount ?? selectedJob.batchCount,
                })}
              </Badge>
            </div>
          </div>
          <div className="language-batch-filters" role="tablist" aria-label={t("筛选翻译批次")}>
            {batchFilterOptions.map((option) => (
              <button
                type="button"
                role="tab"
                aria-selected={batchStatusFilter === option.value}
                className={batchStatusFilter === option.value ? "is-active" : undefined}
                key={option.value}
                onClick={() => changeBatchFilter(option.value)}
              >
                <span>{t(option.label)}</span>
                <strong>{option.count}</strong>
              </button>
            ))}
          </div>
          {!selectedBatches.length ? (
            <div className="language-batch-empty">
              <Text size="2" color="gray">
                {t((selectedBatchHistory?.allCount ?? 0) > 0
                  ? "没有符合当前状态的翻译批次。"
                  : "该任务还没有翻译批次。")}
              </Text>
            </div>
          ) : null}
          <div className={`language-batch-list${batchHistoryLoading ? " is-loading" : ""}`}>
            {selectedBatches.map((batch) => {
              const latestAttempt = batch.attempts[batch.attempts.length - 1];
              const failedAttemptCount = batch.attempts.filter(
                (attempt) => attempt.status === "FAILED",
              ).length;
              const automaticRetrying = batch.status === "RUNNING"
                && latestAttempt?.status === "FAILED";
              const recoveredAfterRetry = batch.status === "SUCCEEDED"
                && failedAttemptCount > 0;
              const retryAvailable = batch.status === "FAILED"
                && selectedJob.status === "FAILED"
                && !activeJob;
              const batchStatusLabel = automaticRetrying
                ? "自动重试中"
                : recoveredAfterRetry
                  ? "重试后完成"
                  : batch.status === "SUCCEEDED"
                    ? "已完成"
                    : batch.status === "FAILED"
                      ? "失败待重试"
                      : batch.status === "RUNNING"
                        ? "请求中"
                        : batch.status === "CANCELLED"
                          ? "已拆分"
                        : "等待请求";
              const itemLabel = batch.itemKind === "TEXT" ? "字段" : "SKU";
              const preview = batch.skuRefs.slice(0, 3).map((ref) => (
                batch.itemKind === "TEXT" ? ref.name : ref.code || ref.name
              )).join("、");
              return (
                <div className={`language-batch-row is-${batch.status.toLowerCase()}`} key={batch.id}>
                  <div className="language-batch-main">
                    <div className="language-batch-title">
                      <strong>{t("第 {batch} 批", { batch: batch.sequenceNo })}</strong>
                      <Badge color={batch.status === "SUCCEEDED" ? "green" : batch.status === "FAILED" ? "red" : automaticRetrying ? "amber" : batch.status === "RUNNING" ? "blue" : "gray"}>
                        {t(batchStatusLabel)}
                      </Badge>
                    </div>
                    <Text size="1" color="gray">
                      {t("{count} 个{item}", { count: batch.totalItems, item: itemLabel })}
                      {batch.sourceLocale ? ` · ${batch.sourceLocale}` : ""}
                      {preview ? ` · ${preview}${batch.totalItems > batch.skuRefs.length ? " …" : ""}` : ""}
                    </Text>
                    {latestAttempt ? (
                      <Text size="1" color="gray">
                        {t("第 {attempt} 次请求 · 首响 {first}", {
                          attempt: latestAttempt.attemptNo,
                          first: formatDate(latestAttempt.firstByteAt),
                        })}
                        {latestAttempt.firstByteLatencyMs != null
                          ? ` (${latestAttempt.firstByteLatencyMs} ms)`
                          : ""}
                        {` · ${t("完成")} ${formatDate(latestAttempt.completedAt)}`}
                        {latestAttempt.responseTimeMs != null
                          ? ` (${latestAttempt.responseTimeMs} ms)`
                          : ""}
                      </Text>
                    ) : null}
                    {automaticRetrying ? (
                      <Text size="1" color="amber">
                        {t("上一次请求失败，系统正在自动缩小批次重试。")}
                      </Text>
                    ) : null}
                    {batch.status === "FAILED" && failedAttemptCount > 1 ? (
                      <Text size="1" color="red">
                        {t("已自动重试 {count} 次，仍未成功。", {
                          count: failedAttemptCount - 1,
                        })}
                      </Text>
                    ) : null}
                    {batch.status === "FAILED" && batch.errorMessage ? <Text size="1" color="red">{batch.errorMessage}</Text> : null}
                    {batch.status === "CANCELLED" && batch.errorMessage ? <Text size="1" color="gray">{batch.errorMessage}</Text> : null}
                    {batch.attempts.length ? (
                      <details className="language-batch-attempts">
                        <summary>{t("查看 {count} 次请求记录", { count: batch.attempts.length })}</summary>
                        <div>
                          {batch.attempts.map((attempt) => (
                            <div key={attempt.id}>
                              <span>
                                {t("第 {attempt} 次", { attempt: attempt.attemptNo })}
                                {` · ${t(attempt.status === "SUCCEEDED"
                                  ? "成功"
                                  : attempt.status === "RUNNING"
                                    ? "请求中"
                                    : attempt.status === "CANCELLED"
                                      ? "已取消"
                                      : "失败")}`}
                                {` · ${formatDate(attempt.completedAt)}`}
                              </span>
                              {attempt.errorMessage ? <small>{attempt.errorMessage}</small> : null}
                            </div>
                          ))}
                        </div>
                      </details>
                    ) : null}
                  </div>
                  <div className="language-batch-actions">
                    <Text size="1" color="gray">
                      {latestAttempt?.responseTimeMs != null ? `${latestAttempt.responseTimeMs} ms` : "—"}
                    </Text>
                    {batch.status === "FAILED" ? (
                      retryAvailable ? (
                        <Button
                          size="1"
                          variant="soft"
                          color="amber"
                          loading={retryingBatchId === batch.id}
                          disabled={!canEditProducts || Boolean(retryingBatchId)}
                          onClick={() => void retryBatch(batch)}
                        >
                          {t("重新请求")}
                        </Button>
                      ) : (
                        <Badge color="amber" variant="soft">
                          {t("当前任务结束后可重试")}
                        </Badge>
                      )
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
          {selectedBatchHistory && selectedBatchHistory.pages > 0 ? (
            <nav className="language-batch-pagination" aria-label={t("翻译批次分页")}>
              <div className="language-batch-pagination-summary">
                <Text size="1" color="gray">
                  {t("第 {page} / {pages} 页", {
                    page: selectedBatchHistory.page,
                    pages: selectedBatchHistory.pages,
                  })}
                </Text>
                <label>
                  <span>{t("每页显示")}</span>
                  <select
                    value={batchPageSize}
                    disabled={batchHistoryLoading}
                    onChange={(event) => changeBatchPageSize(Number(event.target.value))}
                  >
                    {BATCH_PAGE_SIZE_OPTIONS.map((option) => (
                      <option value={option} key={option}>
                        {t("{count} 条", { count: option })}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="language-batch-pagination-controls">
                <Button
                  size="2"
                  variant="soft"
                  color="gray"
                  disabled={batchHistoryLoading || selectedBatchHistory.page <= 1}
                  onClick={() => changeBatchPage(selectedBatchHistory.page - 1)}
                  aria-label={t("上一页")}
                >
                  <CaretLeft />
                </Button>
                {batchPagination.map((item) => typeof item === "number" ? (
                  <Button
                    size="2"
                    variant={item === selectedBatchHistory.page ? "solid" : "soft"}
                    color={item === selectedBatchHistory.page ? undefined : "gray"}
                    disabled={batchHistoryLoading}
                    onClick={() => changeBatchPage(item)}
                    aria-current={item === selectedBatchHistory.page ? "page" : undefined}
                    aria-label={t("第 {page} 页", { page: item })}
                    key={item}
                  >
                    {item}
                  </Button>
                ) : (
                  <span className="language-batch-pagination-ellipsis" key={item}>…</span>
                ))}
                <Button
                  size="2"
                  variant="soft"
                  color="gray"
                  disabled={
                    batchHistoryLoading
                    || selectedBatchHistory.page >= selectedBatchHistory.pages
                  }
                  onClick={() => changeBatchPage(selectedBatchHistory.page + 1)}
                  aria-label={t("下一页")}
                >
                  <CaretRight />
                </Button>
              </div>
            </nav>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
