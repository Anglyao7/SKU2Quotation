import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsClockwise,
  Database,
  FloppyDisk,
  MagnifyingGlass,
  Sparkle,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import {
  getEmbeddingSettings,
  getKnowledgeIndexJob,
  getKnowledgeIndexStatus,
  getLatestKnowledgeIndexJob,
  startKnowledgeIndexJob,
  updateEmbeddingSettings,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  EmbeddingSettings,
  KnowledgeIndexJob,
  KnowledgeIndexStatus,
} from "../types";

const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING"]);

export function AiSearchManagementPage() {
  const { hasPermission, profile } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManageIndex = hasPermission("product.edit");
  const isPlatformAdmin = Boolean(profile?.user.isPlatformAdmin);
  const [status, setStatus] = useState<KnowledgeIndexStatus>();
  const [job, setJob] = useState<KnowledgeIndexJob>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"" | "incremental" | "full">("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [settings, setSettings] = useState<EmbeddingSettings>();
  const [settingsError, setSettingsError] = useState("");
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dimensions, setDimensions] = useState("1024");
  const [timeoutSeconds, setTimeoutSeconds] = useState("20");

  const applySettings = useCallback((next: EmbeddingSettings) => {
    setSettings(next);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName);
    setDimensions(String(next.dimensions));
    setTimeoutSeconds(String(next.timeoutSeconds));
    setApiKey("");
  }, []);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, latestJob] = await Promise.all([
        getKnowledgeIndexStatus(),
        getLatestKnowledgeIndexJob(),
      ]);
      setStatus(nextStatus);
      setJob(latestJob);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("智能索引状态读取失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [t]);

  const loadSettings = useCallback(async () => {
    if (!isPlatformAdmin) return;
    setSettingsError("");
    try {
      applySettings(await getEmbeddingSettings());
    } catch (reason) {
      setSettingsError(
        reason instanceof Error
          ? reason.message
          : t("Embedding 配置读取失败"),
      );
    }
  }, [applySettings, isPlatformAdmin, t]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const jobIsActive = Boolean(job && ACTIVE_JOB_STATUSES.has(job.status));

  useEffect(() => {
    if (!job || !ACTIVE_JOB_STATUSES.has(job.status)) return;
    let stopped = false;
    let requestInFlight = false;
    const poll = async () => {
      if (requestInFlight) return;
      requestInFlight = true;
      try {
        const next = await getKnowledgeIndexJob(job.id);
        if (stopped) return;
        setJob(next);
        if (next.status === "SUCCEEDED") {
          setStatus(await getKnowledgeIndexStatus());
          setMessage(
            next.mode === "FULL_REBUILD"
              ? t("全量重建完成，共重新处理 {count} 个商品。", {
                  count: next.processedProducts.toLocaleString(locale),
                })
              : next.processedProducts
                ? t("增量更新完成，本次处理 {count} 个商品。", {
                    count: next.processedProducts.toLocaleString(locale),
                  })
                : t("当前没有需要更新的商品。"),
          );
          setStarting("");
        } else if (next.status === "FAILED") {
          setError(next.errorMessage ?? t("智能索引更新失败"));
          setStarting("");
        }
      } catch (reason) {
        if (!stopped) {
          setError(
            reason instanceof Error
              ? reason.message
              : t("智能索引状态读取失败"),
          );
        }
      } finally {
        requestInFlight = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [job?.id, job?.status, locale, t]);

  const startIndex = async (fullRebuild: boolean) => {
    if (!canManageIndex || jobIsActive || starting) return;
    setStarting(fullRebuild ? "full" : "incremental");
    setError("");
    setMessage("");
    try {
      const next = await startKnowledgeIndexJob(fullRebuild);
      setJob(next);
      if (next.status === "SUCCEEDED") {
        setMessage(t("当前没有需要更新的商品。"));
        setStarting("");
        setStatus(await getKnowledgeIndexStatus());
      }
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : t("智能索引更新失败"),
      );
      setStarting("");
      await loadStatus();
    }
  };

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!isPlatformAdmin || settingsSaving) return;
    setSettingsSaving(true);
    setSettingsError("");
    setMessage("");
    try {
      const next = await updateEmbeddingSettings({
        baseUrl: baseUrl.trim(),
        apiKey: apiKey.trim() || undefined,
        modelName: modelName.trim(),
        dimensions: Number(dimensions),
        timeoutSeconds: Number(timeoutSeconds),
      });
      applySettings(next);
      setMessage(
        t("Embedding 模型配置已保存；请执行全量重建以使用新模型。"),
      );
      setStatus(await getKnowledgeIndexStatus());
    } catch (reason) {
      setSettingsError(
        reason instanceof Error
          ? reason.message
          : t("Embedding 配置保存失败"),
      );
    } finally {
      setSettingsSaving(false);
    }
  };

  const indexedPercent = useMemo(() => {
    if (!status?.totalProducts) return 0;
    return Math.round(
      (status.indexedProducts / status.totalProducts) * 100,
    );
  }, [status]);

  const activeBusy = jobIsActive || Boolean(starting);
  const jobBadgeColor =
    job?.status === "FAILED"
      ? "red"
      : job?.status === "SUCCEEDED"
        ? "jade"
        : "amber";

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("AI 搜索")}
        title={t("AI 搜索管理")}
        description={t(
          "控制当前商家商品知识的向量索引。商品导入和编辑不会自动产生模型费用，由你决定何时更新。",
        )}
        actions={(
          <>
            <Button asChild variant="soft" color="gray">
              <Link to="/console/ai-search">
                <MagnifyingGlass />
                {t("打开 AI 搜索")}
              </Link>
            </Button>
            <Button
              variant="soft"
              color="gray"
              disabled={loading}
              onClick={() => void loadStatus()}
            >
              <ArrowClockwise />
              {t("刷新状态")}
            </Button>
          </>
        )}
      />

      {loading && !status ? (
        <CoreLoading label={t("正在核对商品与智能索引")} />
      ) : null}
      {error && !status ? (
        <CoreError message={error} onRetry={() => void loadStatus()} />
      ) : null}

      {status ? (
        <>
          <Card className="core-ai-index-overview" aria-live="polite">
            <div className="core-ai-index-heading">
              <span className="core-index-icon">
                <Database />
              </span>
              <div>
                <Text size="1" color="gray" as="div">
                  {t("当前商家索引")}
                </Text>
                <Heading size="5">
                  {jobIsActive
                    ? t("正在处理 {done} / {total} 个商品", {
                        done: job!.processedProducts.toLocaleString(locale),
                        total: job!.totalProducts.toLocaleString(locale),
                      })
                    : status.pendingProducts
                      ? t("{count} 个商品等待更新", {
                          count:
                            status.pendingProducts.toLocaleString(locale),
                        })
                      : t("商品索引已是最新")}
                </Heading>
              </div>
              <Badge color={jobIsActive ? "amber" : status.pendingProducts ? "amber" : "jade"}>
                {t(jobIsActive ? "任务执行中" : status.pendingProducts ? "需要同步" : "可正常搜索")}
              </Badge>
            </div>

            {job ? (
              <div className="core-ai-job-progress">
                <div className="core-ai-job-progress-head">
                  <span>
                    <Text size="1" color="gray" as="div">
                      {t(job.mode === "FULL_REBUILD" ? "全量重建任务" : "增量更新任务")}
                    </Text>
                    <Text size="2" weight="bold" as="div">
                      {job.processedProducts.toLocaleString(locale)} /{" "}
                      {job.totalProducts.toLocaleString(locale)}
                    </Text>
                  </span>
                  <Badge color={jobBadgeColor}>{t(job.status)}</Badge>
                </div>
                <Progress value={job.progressPercent} color={job.status === "FAILED" ? "red" : "jade"} />
                <div className="core-ai-job-meta">
                  <Text size="1" color="gray">
                    {t("完成 {percent}%", {
                      percent: job.progressPercent.toLocaleString(locale),
                    })}
                  </Text>
                  <Text size="1" color="gray">
                    {t("已生成 {count} 条向量", {
                      count: job.embeddings.toLocaleString(locale),
                    })}
                  </Text>
                  {job.currentProductName ? (
                    <Text size="1" color="gray">
                      {t("当前批次：{name}", {
                        name: job.currentProductName,
                      })}
                    </Text>
                  ) : null}
                </div>
                {jobIsActive ? (
                  <Text size="1" color="gray">
                    {t("任务在后台继续执行，离开本页不会中断。")}
                  </Text>
                ) : null}
                {job.errorMessage ? (
                  <Text size="2" color="red">
                    {job.errorMessage}
                  </Text>
                ) : null}
              </div>
            ) : null}

            <div className="core-ai-index-progress">
              <span>
                <Text size="2" color="gray">
                  {t("索引覆盖")}
                </Text>
                <Text size="2" weight="bold">
                  {status.indexedProducts.toLocaleString(locale)} /{" "}
                  {status.totalProducts.toLocaleString(locale)}
                </Text>
              </span>
              <Progress value={indexedPercent} />
            </div>

            <div className="core-ai-index-actions">
              {canManageIndex ? (
                <>
                  <Button
                    size="3"
                    disabled={
                      status.pendingProducts === 0 || activeBusy
                    }
                    onClick={() => void startIndex(false)}
                  >
                    <Sparkle />
                    {t(
                      starting === "incremental" || jobIsActive
                        ? "正在更新…"
                        : "更新智能索引",
                    )}
                  </Button>
                  <Button
                    size="3"
                    variant="soft"
                    color="gray"
                    disabled={!status.totalProducts || activeBusy}
                    onClick={() => setRebuildOpen(true)}
                  >
                    <ArrowsClockwise />
                    {t(
                      starting === "full"
                        ? "正在重建…"
                        : "全量重建索引",
                    )}
                  </Button>
                </>
              ) : (
                <Text size="2" color="gray">
                  {t(
                    "当前账号可查看索引状态，但没有商品编辑权限，无法执行更新。",
                  )}
                </Text>
              )}
            </div>

            {message ? (
              <Text size="2" color="green">
                {message}
              </Text>
            ) : null}
            {error ? (
              <Text size="2" color="red">
                {error}
              </Text>
            ) : null}
          </Card>

          <div className="core-ai-index-details">
            <section>
              <Text size="1" color="gray">
                {t("建议操作")}
              </Text>
              <Heading size="4">{t("通常只需增量更新")}</Heading>
              <p>
                {t(
                  "导入新商品，或修改商品名称、描述、分类与标签后，使用“更新智能索引”即可。系统只处理发生变化的商品。",
                )}
              </p>
            </section>
            <section>
              <Text size="1" color="gray">
                {t("当前生效模型")}
              </Text>
              <dl>
                <div>
                  <dt>{t("模型")}</dt>
                  <dd>{status.modelName}</dd>
                </div>
                <div>
                  <dt>{t("向量维度")}</dt>
                  <dd>{status.dimensions.toLocaleString(locale)}</dd>
                </div>
                <div>
                  <dt>{t("提供方")}</dt>
                  <dd>{status.modelProvider}</dd>
                </div>
                <div>
                  <dt>{t("模型版本")}</dt>
                  <dd>{status.modelVersion}</dd>
                </div>
              </dl>
            </section>
          </div>

          {isPlatformAdmin ? (
            <Card className="core-embedding-settings">
              <div className="core-embedding-settings-heading">
                <div>
                  <Text size="1" color="gray" as="div">
                    {t("平台级配置")}
                  </Text>
                  <Heading size="4">{t("Embedding 模型")}</Heading>
                  <Text size="2" color="gray">
                    {t("仅平台管理员可以修改；配置对所有商家生效。")}
                  </Text>
                </div>
                {settings ? (
                  <Badge color={settings.source === "database" ? "jade" : "gray"}>
                    {t(
                      settings.source === "database"
                        ? "后台配置"
                        : settings.source === "environment"
                          ? "环境变量"
                          : "本地测试模型",
                    )}
                  </Badge>
                ) : null}
              </div>

              <form className="core-embedding-settings-form" onSubmit={(event) => void saveSettings(event)}>
                <label className="core-embedding-field-wide">
                  <Text size="1" color="gray">{t("Base URL")}</Text>
                  <TextField.Root
                    type="url"
                    value={baseUrl}
                    onChange={(event) => setBaseUrl(event.target.value)}
                    placeholder="https://api.example.com/v1"
                    required
                  />
                </label>
                <label>
                  <Text size="1" color="gray">{t("模型")}</Text>
                  <TextField.Root
                    value={modelName}
                    onChange={(event) => setModelName(event.target.value)}
                    placeholder="text-embedding-3-large"
                    required
                  />
                </label>
                <label>
                  <Text size="1" color="gray">{t("API Key")}</Text>
                  <TextField.Root
                    type="password"
                    autoComplete="new-password"
                    value={apiKey}
                    onChange={(event) => setApiKey(event.target.value)}
                    placeholder={
                      settings?.apiKeyConfigured
                        ? t("已配置 {hint}，留空则保持不变", {
                            hint: settings.apiKeyHint ?? "",
                          })
                        : t("请输入 API Key")
                    }
                    required={!settings?.apiKeyConfigured}
                  />
                </label>
                <label>
                  <Text size="1" color="gray">{t("向量维度")}</Text>
                  <TextField.Root
                    type="number"
                    min="1"
                    max="2000"
                    value={dimensions}
                    onChange={(event) => setDimensions(event.target.value)}
                    required
                  />
                </label>
                <label>
                  <Text size="1" color="gray">{t("超时（秒）")}</Text>
                  <TextField.Root
                    type="number"
                    min="1"
                    max="120"
                    value={timeoutSeconds}
                    onChange={(event) => setTimeoutSeconds(event.target.value)}
                    required
                  />
                </label>
                <div className="core-embedding-settings-actions">
                  <Button
                    type="submit"
                    size="3"
                    disabled={
                      settingsSaving ||
                      !baseUrl.trim() ||
                      !modelName.trim() ||
                      Number(dimensions) < 1 ||
                      Number(dimensions) > 2000
                    }
                  >
                    <FloppyDisk />
                    {t(settingsSaving ? "保存中…" : "保存模型配置")}
                  </Button>
                  <Text size="1" color="gray">
                    {t("密钥加密保存，保存后不会显示明文。")}
                  </Text>
                </div>
              </form>
              {settingsError ? (
                <Text size="2" color="red">{settingsError}</Text>
              ) : null}
            </Card>
          ) : null}
        </>
      ) : null}

      <AlertDialog.Root open={rebuildOpen} onOpenChange={setRebuildOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>
            {t("全量重建智能索引？")}
          </AlertDialog.Title>
          <AlertDialog.Description size="2">
            {t(
              "系统会使用当前的 {model}，重新向量化当前商家的全部 {count} 个商品。通常仅在更换模型或索引异常时使用。",
              {
                model: status?.modelName ?? "Embedding",
                count: status
                  ? status.totalProducts.toLocaleString(locale)
                  : "0",
              },
            )}
          </AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={activeBusy}>
                {t("取消")}
              </Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button
                disabled={activeBusy}
                onClick={() => void startIndex(true)}
              >
                <ArrowsClockwise />
                {t("确认全量重建")}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
