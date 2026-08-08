import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Card,
  Heading,
  Progress,
  Select,
  Text,
} from "@radix-ui/themes";
import {
  ArrowsClockwise,
  Check,
  CheckCircle,
  CloudArrowUp,
  Database,
  GlobeHemisphereWest,
  Info,
  LockSimple,
  Package,
  Pause,
  Play,
  Translate,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useCoreAuth } from "../AuthContext";
import {
  CoreApiError,
  getCatalogTranslationJob,
  getCatalogTranslationStatus,
  getMerchantSettings,
  pauseCatalogTranslationJob,
  resumeCatalogTranslationJob,
  startCatalogTranslationJob,
  updateMerchantSettings,
} from "../api";
import type {
  CatalogTranslationJob,
  CatalogTranslationJobStage,
  CatalogTranslationStatus,
} from "../types";
import { useLocale } from "../LocaleContext";
import {
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
} from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";

const TARGET_LANGUAGES = STOREFRONT_LANGUAGE_OPTIONS.filter(
  (language) => language.code !== "zh-CN",
);

const stageCopy: Record<CatalogTranslationJobStage, string> = {
  QUEUED: "等待开始",
  PREPARING: "核对变更",
  TRANSLATING: "调用翻译 API",
  PACKAGING: "整理语言包",
  UPLOADING: "上传 Cloudflare",
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

export function LanguagePackagesPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canEditProducts = hasPermission("product.edit");
  const canManageSettings = hasPermission("system.settings_manage");
  const [enabledLocales, setEnabledLocales] = useState<StorefrontLocale[]>([
    "zh-CN",
    "en-US",
  ]);
  const [savedLocales, setSavedLocales] = useState<StorefrontLocale[]>([
    "zh-CN",
    "en-US",
  ]);
  const [selectedLocale, setSelectedLocale] = useState<StorefrontLocale>("en-US");
  const [status, setStatus] = useState<CatalogTranslationStatus>();
  const [job, setJob] = useState<CatalogTranslationJob>();
  const [loading, setLoading] = useState(true);
  const [savingLanguages, setSavingLanguages] = useState(false);
  const [startingJob, setStartingJob] = useState(false);
  const [controllingJob, setControllingJob] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const languagesChanged = enabledLocales.join(",") !== savedLocales.join(",");
  const activeJob = job && ["QUEUED", "RUNNING", "PAUSED"].includes(job.status)
    ? job
    : undefined;
  const controllableJob = activeJob ?? (
    job?.status === "FAILED" && job.resumable ? job : undefined
  );
  const pollableJob = job && (
    ["QUEUED", "RUNNING"].includes(job.status) || job.pauseRequested
  ) ? job : undefined;
  const selectedLanguage = storefrontLanguage(selectedLocale);

  const refreshStatus = async (locale = selectedLocale) => {
    const next = await getCatalogTranslationStatus(locale);
    setStatus(next);
    setJob(next.latestJob);
    return next;
  };

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([getMerchantSettings(), getCatalogTranslationStatus(selectedLocale)])
      .then(([settings, translationStatus]) => {
        if (!active) return;
        setEnabledLocales(settings.storefrontLocales);
        setSavedLocales(settings.storefrontLocales);
        setStatus(translationStatus);
        setJob(translationStatus.latestJob);
      })
      .catch((caught) => {
        if (active) {
          setError(caught instanceof Error ? caught.message : t("语言包状态读取失败。"));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (loading) return;
    let active = true;
    setError("");
    void refreshStatus(selectedLocale).catch((caught) => {
      if (active) setError(caught instanceof Error ? caught.message : t("语言包状态读取失败。"));
    });
    return () => {
      active = false;
    };
  }, [selectedLocale]);

  useEffect(() => {
    if (!pollableJob) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getCatalogTranslationJob(pollableJob.id)
        .then((next) => {
          if (cancelled) return;
          setJob(next);
          if (!["QUEUED", "RUNNING"].includes(next.status)) {
            window.clearInterval(timer);
            if (next.status === "PAUSED") {
              setSuccess(t("翻译已暂停，已完成的内容会保留。"));
              return;
            }
            void refreshStatus(next.targetLocale).then((latest) => {
              if (cancelled) return;
              if (next.status === "SUCCEEDED" && latest.package) {
                setSuccess(t("语言包已发布，前台将在下一次版本检查后自动使用。"));
              }
            });
          }
        })
        .catch(() => undefined);
    }, 1200);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [pollableJob?.id, pollableJob?.pauseRequested]);

  const toggleLanguage = (locale: StorefrontLocale, checked: boolean) => {
    setEnabledLocales((current) => {
      const values = new Set(current);
      if (checked) values.add(locale);
      else values.delete(locale);
      values.add("zh-CN");
      return STOREFRONT_LANGUAGE_OPTIONS
        .map((language) => language.code)
        .filter((code) => values.has(code));
    });
    setError("");
    setSuccess("");
  };

  const saveLanguages = async () => {
    if (!canManageSettings || !languagesChanged || savingLanguages) return;
    setSavingLanguages(true);
    setError("");
    setSuccess("");
    try {
      const updated = await updateMerchantSettings({ storefrontLocales: enabledLocales });
      setEnabledLocales(updated.storefrontLocales);
      setSavedLocales(updated.storefrontLocales);
      setSuccess(t("前台语言已更新。尚未发布语言包的语言会暂时回退到原文。"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("前台语言保存失败。"));
    } finally {
      setSavingLanguages(false);
    }
  };

  const startJob = async (fullRebuild: boolean) => {
    if (!canEditProducts || startingJob || activeJob) return;
    setStartingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = await startCatalogTranslationJob(selectedLocale, fullRebuild);
      setJob(next);
      if (next.status === "SUCCEEDED") {
        await refreshStatus(selectedLocale);
        setSuccess(t("当前语言包已经是最新版本。"));
      }
    } catch (caught) {
      const message = caught instanceof CoreApiError || caught instanceof Error
        ? caught.message
        : t("翻译任务启动失败。" );
      setError(message);
    } finally {
      setStartingJob(false);
    }
  };

  const controlTranslationJob = async (action: "pause" | "resume") => {
    if (!canEditProducts || !controllableJob || controllingJob) return;
    setControllingJob(true);
    setError("");
    setSuccess("");
    try {
      const next = action === "pause"
        ? await pauseCatalogTranslationJob(controllableJob.id)
        : await resumeCatalogTranslationJob(controllableJob.id);
      setJob(next);
      if (action === "pause") {
        setSuccess(next.status === "PAUSED"
          ? t("翻译已暂停，已完成的内容会保留。")
          : t("正在完成当前翻译批次，随后会安全暂停。"));
      } else {
        setSuccess(t("翻译任务已从断点继续，只会处理剩余商品。"));
      }
    } catch (caught) {
      setError(caught instanceof Error
        ? caught.message
        : t(action === "pause" ? "暂停翻译失败。" : "继续翻译失败。"));
    } finally {
      setControllingJob(false);
    }
  };

  const coverage = useMemo(() => {
    if (!status?.totalSkus) return 0;
    return Math.round(status.translatedSkus / status.totalSkus * 100);
  }, [status?.totalSkus, status?.translatedSkus]);

  return (
    <div className="core-workspace language-pack-page">
      <div className="core-page-heading language-pack-heading">
        <div>
          <Text size="2" color="gray">{t("商品资料")}</Text>
          <Heading size="8">{t("多语言与语言包")}</Heading>
          <Text size="2" color="gray">
            {t("集中管理前台语言、翻译任务与 Cloudflare 语言包。访客下载一次后会保存在当前浏览器。")}
          </Text>
        </div>
      </div>

      {error ? (
        <Callout.Root color="red" role="alert">
          <Callout.Icon><WarningCircle /></Callout.Icon>
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      ) : null}
      {success ? (
        <Callout.Root color="green" role="status">
          <Callout.Icon><CheckCircle /></Callout.Icon>
          <Callout.Text>{success}</Callout.Text>
        </Callout.Root>
      ) : null}

      <Card className="language-selection-card">
        <div className="language-card-heading language-selection-heading">
          <span><GlobeHemisphereWest weight="duotone" /></span>
          <div className="language-heading-copy">
            <Heading size="5">{t("前台语言")}</Heading>
            <Text size="2" color="gray">
              {t("选择访客可以使用的语言；简体中文固定保留。翻译任务在下方单独管理。")}
            </Text>
          </div>
          <div className="language-selection-toolbar">
            <Text size="1" color="gray">
              {t("已启用 {count} 种", { count: enabledLocales.length })}
            </Text>
            <Button
              variant={languagesChanged ? "solid" : "soft"}
              onClick={() => void saveLanguages()}
              loading={savingLanguages}
              disabled={!canManageSettings || !languagesChanged || savingLanguages}
            >
              {t(languagesChanged ? "保存更改" : "已保存")}
            </Button>
          </div>
        </div>
        <div className="language-package-options">
          {STOREFRONT_LANGUAGE_OPTIONS.map((language) => {
            const enabled = enabledLocales.includes(language.code);
            const source = language.code === "zh-CN";
            const localeCode = source
              ? t("源语言")
              : language.code.split("-")[0].toUpperCase();
            return (
              <button
                type="button"
                key={language.code}
                className={`language-package-option${enabled ? " is-enabled" : ""}${source ? " is-source" : ""}`}
                onClick={() => toggleLanguage(language.code, !enabled)}
                disabled={source || !canManageSettings}
                aria-pressed={enabled}
                aria-label={source
                  ? t("{language} 始终启用", { language: language.label })
                  : t("展示 {language}", { language: language.label })}
              >
                <span className="language-option-flag" aria-hidden="true">{language.flag}</span>
                <span className="language-option-copy">
                  <strong lang={language.code} dir={language.direction}>{language.label}</strong>
                  <small>{localeCode}</small>
                </span>
                <span className="language-option-indicator" aria-hidden="true">
                  {source ? <LockSimple weight="bold" /> : enabled ? <Check weight="bold" /> : null}
                </span>
              </button>
            );
          })}
        </div>
      </Card>

      <div className="language-pack-grid">
        <Card className="language-pack-status-card">
          <div className="language-card-heading compact">
            <span><Translate weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{selectedLanguage.flag} {selectedLanguage.label}</Text>
              <Heading size="5">{t("翻译覆盖")}</Heading>
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
              <Badge color={status?.packageOutdated ? "amber" : status?.package ? "green" : "gray"}>
                {t(status?.packageOutdated ? "有变更待发布" : status?.package ? "语言包最新" : "尚未生成")}
              </Badge>
            </div>
          </div>
          <div className="language-pack-metrics">
            <div><strong>{status?.totalSkus ?? 0}</strong><span>{t("公开 SKU")}</span></div>
            <div><strong>{status?.translatedSkus ?? 0}</strong><span>{t("已翻译")}</span></div>
            <div><strong>{status?.pendingSkus ?? 0}</strong><span>{t("新增或变更")}</span></div>
            <div><strong>{coverage}%</strong><span>{t("数据库覆盖")}</span></div>
          </div>
          <Progress value={coverage} size="3" color={coverage === 100 ? "green" : "blue"} />
          <div className="language-pack-actions">
            <Button
              size="3"
              onClick={() => void startJob(false)}
              loading={startingJob && !activeJob}
              disabled={!canEditProducts || Boolean(activeJob) || !status?.providerConfigured || !status?.packageStorageConfigured}
            >
              <ArrowsClockwise />
              {t("翻译新增与变更")}
            </Button>
            <AlertDialog.Root>
              <AlertDialog.Trigger>
                <Button
                  size="3"
                  variant="soft"
                  color="gray"
                  disabled={!canEditProducts || Boolean(activeJob) || !status?.providerConfigured || !status?.packageStorageConfigured}
                >
                  {t("全量翻译")}
                </Button>
              </AlertDialog.Trigger>
              <AlertDialog.Content maxWidth="480px">
                <AlertDialog.Title>{t("全量重新翻译 {language}？", { language: selectedLanguage.label })}</AlertDialog.Title>
                <AlertDialog.Description>
                  {t("系统会重新核对全部商品，并用当前翻译模型生成一个新的不可变语言包。旧包会继续可用，直到新包完整上传后才切换。")}
                </AlertDialog.Description>
                <div className="language-pack-dialog-actions">
                  <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
                  <AlertDialog.Action><Button color="red" onClick={() => void startJob(true)}>{t("确认全量翻译")}</Button></AlertDialog.Action>
                </div>
              </AlertDialog.Content>
            </AlertDialog.Root>
            {controllableJob ? (
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
          {activeJob?.pauseRequested && activeJob.status !== "PAUSED" ? (
            <Text size="1" color="gray" className="language-pause-note">
              {t("系统会先保存当前批次，再进入暂停状态，不会丢失已完成的翻译。")}
            </Text>
          ) : null}
          {!status?.providerConfigured ? (
            <Callout.Root color="amber">
              <Callout.Icon><Info /></Callout.Icon>
              <Callout.Text>{t("平台尚未配置可用的翻译 API。")}</Callout.Text>
            </Callout.Root>
          ) : null}
          {status && !status.packageStorageConfigured ? (
            <Callout.Root color="red">
              <Callout.Icon><CloudArrowUp /></Callout.Icon>
              <Callout.Text>
                {t("语言包存储尚未配置，请先在服务器配置 Cloudflare R2。")}
              </Callout.Text>
            </Callout.Root>
          ) : null}
        </Card>

        <Card className="language-package-release-card">
          <div className="language-card-heading compact">
            <span><Package weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{t("当前发布版本")}</Text>
              <Heading size="5">{status?.package ? `v${status.package.version}` : "—"}</Heading>
            </div>
          </div>
          <dl className="language-package-details">
            <div><dt>{t("发布时间")}</dt><dd>{formatDate(status?.package?.publishedAt)}</dd></div>
            <div><dt>{t("源数据截止")}</dt><dd>{formatDate(status?.package?.sourceCutoffAt)}</dd></div>
            <div><dt>{t("压缩后大小")}</dt><dd>{formatBytes(status?.package?.byteSize)}</dd></div>
            <div><dt>{t("包含内容")}</dt><dd>{status?.package ? `${status.package.productCount} Products · ${status.package.skuCount} SKUs` : "—"}</dd></div>
            <div><dt>{t("翻译模型")}</dt><dd>{status?.provider || "—"}</dd></div>
            <div><dt>{t("浏览器策略")}</dt><dd>{t("IndexedDB 按版本长期保存")}</dd></div>
          </dl>
          <Callout.Root color="blue">
            <Callout.Icon><Database /></Callout.Icon>
            <Callout.Text>
              {t("前台只会请求一个很小的版本清单；版本未变化时直接读取浏览器本地语言包，不会重复下载。")}
            </Callout.Text>
          </Callout.Root>
        </Card>
      </div>

      {job ? (
        <Card className={`language-job-card is-${job.status.toLocaleLowerCase()}`}>
          <div className="language-job-header">
            <div>
              <Text size="1" color="gray">{t("最近任务")}</Text>
              <Heading size="4">
                {t(job.status === "FAILED" && job.resumable
                  ? "任务中断，断点已保存"
                  : stageCopy[job.stage])}
              </Heading>
            </div>
            <Badge color={job.status === "FAILED"
              ? "red"
              : job.status === "SUCCEEDED"
                ? "green"
                : job.status === "PAUSED" || job.pauseRequested
                  ? "amber"
                  : "blue"}>
              {job.progressPercent.toFixed(1)}%
            </Badge>
          </div>
          <Progress
            value={job.progressPercent}
            size="3"
            color={job.status === "FAILED"
              ? "red"
              : job.status === "PAUSED" || job.pauseRequested
                ? "amber"
                : "blue"}
          />
          <div className="language-job-copy">
            <span>{t("已处理 {done} / {total} 个 SKU", { done: job.processedSkus, total: job.totalSkus })}</span>
            {job.resumable ? (
              <span>
                {t("剩余 {remaining} 个 SKU · 断点 {time}", {
                  remaining: job.remainingSkus,
                  time: formatDate(job.checkpointAt),
                })}
              </span>
            ) : null}
            {job.currentSkuName ? <span>{job.currentSkuName}</span> : null}
            {job.status === "PAUSED" ? <span>{t("继续后将从剩余商品开始")}</span> : null}
            {job.packagePublished ? <span>{t("已发布语言包 v{version}", { version: job.packageVersion ?? "—" })}</span> : null}
          </div>
          {job.errorMessage ? <Text color="red" size="2">{job.errorMessage}</Text> : null}
        </Card>
      ) : null}
    </div>
  );
}
