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
  MagnifyingGlass,
  Pause,
  Play,
  Plus,
  FloppyDisk,
  Sparkle,
  Trash,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Link } from "react-router-dom";
import {
  getKnowledgeIndexJob,
  getKnowledgeIndexStatus,
  getLatestKnowledgeIndexJob,
  getAISearchPopularTerms,
  pauseKnowledgeIndexJob,
  resumeKnowledgeIndexJob,
  startKnowledgeIndexJob,
  updateAISearchPopularTerms,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type {
  KnowledgeIndexJob,
  KnowledgeIndexStatus,
  PopularSearchTerm,
} from "../types";
import "./AiSearchManagementPage.css";

const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING"]);

function checkpointTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function AiSearchManagementPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const { notify } = useToast();
  const canManageIndex = hasPermission("product.edit");
  const [status, setStatus] = useState<KnowledgeIndexStatus>();
  const [job, setJob] = useState<KnowledgeIndexJob>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"" | "incremental" | "full">("");
  const [controlling, setControlling] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [popularTerms, setPopularTerms] = useState<PopularSearchTerm[]>([]);
  const [configuredTerms, setConfiguredTerms] = useState<string[]>([""]);
  const [savedConfiguredTerms, setSavedConfiguredTerms] = useState<string[]>([]);
  const [savingTerms, setSavingTerms] = useState(false);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, latestJob, popular] = await Promise.all([
        getKnowledgeIndexStatus(),
        getLatestKnowledgeIndexJob(),
        getAISearchPopularTerms(30, 10).catch(() => undefined),
      ]);
      setStatus(nextStatus);
      setJob(latestJob);
      setPopularTerms(popular?.items ?? []);
      const nextConfiguredTerms = popular?.configuredTerms ?? [];
      setConfiguredTerms(nextConfiguredTerms.length ? nextConfiguredTerms : [""]);
      setSavedConfiguredTerms(nextConfiguredTerms);
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

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const jobIsActive = Boolean(job && ACTIVE_JOB_STATUSES.has(job.status));
  const jobBlocksStart = Boolean(
    job && (ACTIVE_JOB_STATUSES.has(job.status) || job.status === "PAUSED"),
  );

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
        } else if (next.status === "PAUSED") {
          setMessage(t("向量化已暂停，已完成的向量和断点会保留。"));
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
    if (!canManageIndex || jobBlocksStart || starting) return;
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

  const controlIndexJob = async (action: "pause" | "resume") => {
    if (!canManageIndex || !job || controlling) return;
    setControlling(true);
    setError("");
    setMessage("");
    try {
      const next = action === "pause"
        ? await pauseKnowledgeIndexJob(job.id)
        : await resumeKnowledgeIndexJob(job.id);
      setJob(next);
      if (action === "pause") {
        setMessage(next.status === "PAUSED"
          ? t("向量化已暂停，已完成的向量和断点会保留。")
          : t("正在完成当前向量批次，随后会安全暂停。"));
      } else {
        setMessage(t("向量化已从断点继续，只处理剩余商品。"));
      }
    } catch (reason) {
      setError(reason instanceof Error
        ? reason.message
        : t(action === "pause" ? "暂停向量化失败。" : "继续向量化失败。"));
    } finally {
      setControlling(false);
    }
  };

  const indexedPercent = useMemo(() => {
    if (!status?.totalProducts) return 0;
    return Math.round(
      (status.indexedProducts / status.totalProducts) * 100,
    );
  }, [status]);

  const activeBusy = jobBlocksStart || Boolean(starting);
  const normalizedConfiguredTerms = useMemo(
    () => configuredTerms.map((term) => term.trim()).filter(Boolean),
    [configuredTerms],
  );
  const configuredTermKeys = normalizedConfiguredTerms.map((term) => term.toLocaleLowerCase());
  const configuredTermsHaveDuplicates = new Set(configuredTermKeys).size !== configuredTermKeys.length;
  const configuredTermsChanged = JSON.stringify(normalizedConfiguredTerms) !== JSON.stringify(savedConfiguredTerms);

  const updateConfiguredTerm = (index: number, value: string) => {
    setConfiguredTerms((current) => {
      const next = current.length ? [...current] : [""];
      next[index] = value;
      return next;
    });
  };

  const removeConfiguredTerm = (index: number) => {
    setConfiguredTerms((current) => {
      const next = current.filter((_, itemIndex) => itemIndex !== index);
      return next.length ? next : [""];
    });
  };

  const addConfiguredTerm = (term = "") => {
    setConfiguredTerms((current) => {
      const next = current.length ? [...current] : [""];
      const normalized = term.trim();
      if (normalized && next.some((item) => item.trim().toLocaleLowerCase() === normalized.toLocaleLowerCase())) {
        return next;
      }
      const emptyIndex = next.findIndex((item) => !item.trim());
      if (normalized && emptyIndex >= 0) {
        next[emptyIndex] = normalized;
        return next;
      }
      if (next.length >= 5) return next;
      next.push(normalized);
      return next;
    });
  };

  const saveConfiguredTerms = async () => {
    if (!canManageIndex || savingTerms || !configuredTermsChanged) return;
    if (configuredTermsHaveDuplicates) {
      notify(t("热门搜索词不能重复。"), { kind: "error" });
      return;
    }
    setSavingTerms(true);
    try {
      const updated = await updateAISearchPopularTerms(normalizedConfiguredTerms);
      setPopularTerms(updated.items);
      setConfiguredTerms(updated.configuredTerms.length ? updated.configuredTerms : [""]);
      setSavedConfiguredTerms(updated.configuredTerms);
      notify(t("热门搜索词已保存，并会显示在商品前台。"), { kind: "success" });
    } catch (reason) {
      notify(
        reason instanceof Error ? reason.message : t("热门搜索词保存失败，请稍后重试。"),
        { kind: "error" },
      );
    } finally {
      setSavingTerms(false);
    }
  };
  const jobBadgeColor =
    job?.status === "FAILED"
      ? "red"
      : job?.status === "PAUSED"
        ? "amber"
        : job?.status === "SUCCEEDED"
          ? "jade"
          : "amber";

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("AI 搜索")}
        title={t("AI 搜索管理")}
        description={t(
          "管理当前工作区的商品搜索数据。商品导入或编辑后，可在这里更新。",
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
                  {job?.status === "PAUSED"
                    ? t("向量化已暂停：{done} / {total} 个商品", {
                        done: job.processedProducts.toLocaleString(locale),
                        total: job.totalProducts.toLocaleString(locale),
                      })
                    : jobIsActive
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
              <Badge color={job?.status === "PAUSED" || jobIsActive ? "amber" : status.pendingProducts ? "amber" : "jade"}>
                {t(job?.status === "PAUSED" ? "任务已暂停" : jobIsActive ? "任务执行中" : status.pendingProducts ? "需要同步" : "可正常搜索")}
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
                <Progress value={job.progressPercent} color={job.status === "FAILED" ? "red" : job.status === "PAUSED" ? "amber" : "jade"} />
                <div className="core-ai-job-meta">
                  <Text size="1" color="gray">
                    {t("完成 {percent}%", {
                      percent: job.progressPercent.toLocaleString(locale),
                    })}
                  </Text>
                  <Text size="1" color="gray">
                    {t("已更新 {count} 条搜索数据", {
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
                  {job.checkpointAt && job.remainingProducts ? (
                    <Text size="1" color="gray">
                      {t("剩余 {count} 个商品 · 断点 {time}", {
                        count: job.remainingProducts.toLocaleString(locale),
                        time: checkpointTime(job.checkpointAt, locale),
                      })}
                    </Text>
                  ) : null}
                </div>
                {jobIsActive ? (
                  <Text size="1" color="gray">
                    {t(job.pauseRequested
                      ? "系统会先保存当前批次，再进入暂停状态，不会丢失已完成的向量。"
                      : "任务在后台继续执行，离开本页不会中断。")}
                  </Text>
                ) : null}
                {job.errorMessage ? (
                  <Text size="2" color={job.status === "FAILED" ? "red" : "gray"}>
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
                  {job && (
                    job.resumable
                    || (ACTIVE_JOB_STATUSES.has(job.status) && !job.pauseRequested)
                    || (job.status === "RUNNING" && job.pauseRequested)
                  ) ? (
                    <Button
                      size="3"
                      variant="soft"
                      color={job.resumable || job.pauseRequested ? "blue" : "amber"}
                      disabled={controlling}
                      onClick={() => void controlIndexJob(
                        job.resumable || job.pauseRequested ? "resume" : "pause",
                      )}
                    >
                      {job.resumable || job.pauseRequested ? <Play /> : <Pause />}
                      {t(controlling
                        ? "处理中…"
                        : job.resumable
                          ? "从断点继续"
                          : job.pauseRequested
                            ? "取消暂停"
                            : "暂停向量化")}
                    </Button>
                  ) : null}
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

          <Card className="core-ai-popular-terms">
            <div className="core-ai-recommended-heading">
              <div>
                <Text size="1" color="gray">{t("前台搜索设置")}</Text>
                <Heading size="4">{t("热门搜索词")}</Heading>
                <Text size="2" color="gray">
                  {t("最多设置 5 个热门搜索词；保存后会按当前顺序显示在商品前台搜索框下方。")}
                </Text>
              </div>
              <Badge color="jade">{t("商家自定义")}</Badge>
            </div>

            <div className="ai-popular-term-editor">
              {configuredTerms.map((term, index) => (
                <div className="ai-popular-term-row" key={index}>
                  <Badge color="gray" variant="soft">{index + 1}</Badge>
                  <TextField.Root
                    value={term}
                    maxLength={80}
                    placeholder={t("例如：大型犬玩具")}
                    aria-label={t("第 {index} 个热门搜索词", { index: index + 1 })}
                    onChange={(event) => updateConfiguredTerm(index, event.target.value)}
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    color="gray"
                    aria-label={t("删除热门搜索词")}
                    onClick={() => removeConfiguredTerm(index)}
                  >
                    <Trash />
                  </Button>
                </div>
              ))}
              {configuredTermsHaveDuplicates ? (
                <Text size="1" color="red">{t("热门搜索词不能重复。")}</Text>
              ) : null}
              <div className="ai-popular-term-actions">
                <Button
                  type="button"
                  variant="soft"
                  color="gray"
                  disabled={configuredTerms.length >= 5 || configuredTerms.some((term) => !term.trim())}
                  onClick={() => addConfiguredTerm()}
                >
                  <Plus />
                  {t("添加搜索词")}
                </Button>
                <Button
                  type="button"
                  loading={savingTerms}
                  disabled={savingTerms || configuredTermsHaveDuplicates || !configuredTermsChanged}
                  onClick={() => void saveConfiguredTerms()}
                >
                  <FloppyDisk />
                  {t("保存并显示")}
                </Button>
              </div>
            </div>

            {popularTerms.length ? (
              <div className="ai-popular-trend-section">
                <div>
                  <Text size="2" weight="medium" as="div">{t("近 30 天搜索趋势")}</Text>
                  <Text size="1" color="gray">{t("点击真实搜索词可快速添加到前台展示。")}</Text>
                </div>
              <div className="core-ai-popular-term-list">
                {popularTerms.map((item, index) => (
                  <button
                    type="button"
                    className="core-ai-popular-term"
                    key={`${item.term}-${index}`}
                    disabled={normalizedConfiguredTerms.length >= 5 || configuredTermKeys.includes(item.term.trim().toLocaleLowerCase())}
                    onClick={() => addConfiguredTerm(item.term)}
                  >
                    <div className="core-ai-popular-term-copy">
                      <Badge color={index < 3 ? "amber" : "gray"}>{index + 1}</Badge>
                      <Text size="2" weight="medium">{item.term}</Text>
                      <Text size="1" color="gray">
                        {t("{count} 次", { count: item.count.toLocaleString(locale) })}
                      </Text>
                    </div>
                    <Plus />
                  </button>
                ))}
              </div>
              </div>
            ) : (
              <Text size="2" color="gray">
                {t("暂未记录到搜索趋势，你仍然可以直接填写热门搜索词。")}
              </Text>
            )}
          </Card>

          <div className="core-ai-index-details is-single">
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
          </div>
        </>
      ) : null}

      <AlertDialog.Root open={rebuildOpen} onOpenChange={setRebuildOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>
            {t("全量重建智能索引？")}
          </AlertDialog.Title>
          <AlertDialog.Description size="2">
            {t(
              "系统会重新处理当前工作区的全部 {count} 个商品。适合搜索结果异常或需要完整同步时使用。",
              {
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
