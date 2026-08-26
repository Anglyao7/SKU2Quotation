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
  Pause,
  Play,
  Sparkle,
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
  getAISearchRecommendedQuestions,
  pauseKnowledgeIndexJob,
  resumeKnowledgeIndexJob,
  startKnowledgeIndexJob,
  updateAISearchRecommendedQuestions,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  KnowledgeIndexJob,
  KnowledgeIndexStatus,
  PopularSearchTerm,
} from "../types";

const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING"]);
const RECOMMENDED_QUESTION_SLOTS = 5;

function padRecommendedQuestions(questions: string[]): string[] {
  return [
    ...questions.slice(0, RECOMMENDED_QUESTION_SLOTS),
    ...Array(Math.max(0, RECOMMENDED_QUESTION_SLOTS - questions.length)).fill(""),
  ];
}

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
  const canManageIndex = hasPermission("product.edit");
  const [status, setStatus] = useState<KnowledgeIndexStatus>();
  const [job, setJob] = useState<KnowledgeIndexJob>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"" | "incremental" | "full">("");
  const [controlling, setControlling] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);
  const [recommendedQuestions, setRecommendedQuestions] = useState(
    () => Array(RECOMMENDED_QUESTION_SLOTS).fill(""),
  );
  const [savingQuestions, setSavingQuestions] = useState(false);
  const [popularTerms, setPopularTerms] = useState<PopularSearchTerm[]>([]);

  const loadStatus = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, latestJob, questions, popular] = await Promise.all([
        getKnowledgeIndexStatus(),
        getLatestKnowledgeIndexJob(),
        getAISearchRecommendedQuestions().catch(() => undefined),
        getAISearchPopularTerms(30, 10).catch(() => undefined),
      ]);
      setStatus(nextStatus);
      setJob(latestJob);
      if (questions?.questions) {
        setRecommendedQuestions(padRecommendedQuestions(questions.questions));
      }
      setPopularTerms(popular?.items ?? []);
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

  const saveRecommendedQuestions = async () => {
    if (!canManageIndex || savingQuestions) return;
    const questions = recommendedQuestions
      .map((question) => question.trim())
      .filter(Boolean);
    if (new Set(questions.map((question) => question.toLocaleLowerCase())).size !== questions.length) {
      setError(t("推荐问题不能重复。"));
      return;
    }
    setSavingQuestions(true);
    setError("");
    setMessage("");
    try {
      const saved = await updateAISearchRecommendedQuestions(questions);
      setRecommendedQuestions(padRecommendedQuestions(saved.questions));
      setMessage(t("前台推荐问题已保存。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("推荐问题保存失败。"));
    } finally {
      setSavingQuestions(false);
    }
  };

  const addPopularTermToRecommendations = (term: string) => {
    if (!canManageIndex) return;
    const existingIndex = recommendedQuestions.findIndex(
      (question) => question.trim().toLocaleLowerCase() === term.toLocaleLowerCase(),
    );
    if (existingIndex >= 0) {
      setMessage(t("该热门搜索词已在推荐列表中。"));
      return;
    }
    const emptyIndex = recommendedQuestions.findIndex((question) => !question.trim());
    if (emptyIndex < 0) {
      setError(t("推荐问题最多设置五条。"));
      return;
    }
    setRecommendedQuestions((current) => current.map((question, index) => (
      index === emptyIndex ? term : question
    )));
    setMessage(t("已填入推荐列表，保存后将在前台显示。"));
  };

  const useTopPopularTerms = () => {
    if (!canManageIndex || !popularTerms.length) return;
    setRecommendedQuestions(
      padRecommendedQuestions(popularTerms.slice(0, RECOMMENDED_QUESTION_SLOTS).map((item) => item.term)),
    );
    setMessage(t("已用热门搜索词前五条填入推荐列表，保存后将在前台显示。"));
  };

  const indexedPercent = useMemo(() => {
    if (!status?.totalProducts) return 0;
    return Math.round(
      (status.indexedProducts / status.totalProducts) * 100,
    );
  }, [status]);

  const activeBusy = jobBlocksStart || Boolean(starting);
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
                <Text size="1" color="gray">{t("搜索趋势")}</Text>
                <Heading size="4">{t("热门搜索词")}</Heading>
                <Text size="2" color="gray">
                  {t("自动记录近30天前台搜索次数最多的前十个词，可一键填入下方推荐。")}
                </Text>
              </div>
              <Badge color="amber">{t("自动记录")}</Badge>
            </div>
            {popularTerms.length ? (
              <div className="core-ai-popular-term-list">
                {popularTerms.map((item, index) => {
                  const alreadyRecommended = recommendedQuestions.some(
                    (question) => question.trim().toLocaleLowerCase() === item.term.toLocaleLowerCase(),
                  );
                  return (
                    <div className="core-ai-popular-term" key={`${item.term}-${index}`}>
                      <div className="core-ai-popular-term-copy">
                        <Badge color={index < 3 ? "amber" : "gray"}>{index + 1}</Badge>
                        <Text size="2" weight="medium">{item.term}</Text>
                        <Text size="1" color="gray">
                          {t("{count} 次", { count: item.count.toLocaleString(locale) })}
                        </Text>
                      </div>
                      <Button
                        size="1"
                        variant="soft"
                        color={alreadyRecommended ? "gray" : "jade"}
                        disabled={!canManageIndex || alreadyRecommended || savingQuestions}
                        onClick={() => addPopularTermToRecommendations(item.term)}
                      >
                        {alreadyRecommended ? t("已在推荐中") : t("填入推荐")}
                      </Button>
                    </div>
                  );
                })}
              </div>
            ) : (
              <Text size="2" color="gray">
                {t("暂未记录到搜索词，访客开始搜索后会自动汇总。")}
              </Text>
            )}
            {canManageIndex && popularTerms.length ? (
              <Button
                variant="soft"
                color="amber"
                onClick={useTopPopularTerms}
                disabled={savingQuestions}
              >
                {t("用热门前五条填充推荐")}
              </Button>
            ) : null}
          </Card>

          <Card className="core-ai-recommended-questions">
            <div className="core-ai-recommended-heading">
              <div>
                <Text size="1" color="gray">{t("前台商品查找")}</Text>
                <Heading size="4">{t("推荐问题")}</Heading>
                <Text size="2" color="gray">
                  {t("设置最多五条常用搜索词，它们会显示在公开商品目录的“查找商品”下面。")}
                </Text>
              </div>
              <Badge color="gray">{t("商家自定义 · 最多5条")}</Badge>
            </div>
            <div className="core-ai-recommended-list">
              {recommendedQuestions.map((question, index) => (
                <label key={index}>
                  <Text size="1" color="gray">{t("推荐问题 {index}", { index: index + 1 })}</Text>
                  <TextField.Root
                    value={question}
                    maxLength={200}
                    disabled={!canManageIndex || savingQuestions}
                    placeholder={t("例如：适合户外使用的轻便商品有哪些？")}
                    onChange={(event) => setRecommendedQuestions((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))}
                  />
                </label>
              ))}
            </div>
            {canManageIndex ? (
              <Button
                variant="soft"
                disabled={savingQuestions}
                onClick={() => void saveRecommendedQuestions()}
              >
                <FloppyDisk />
                {t(savingQuestions ? "保存中…" : "保存推荐问题")}
              </Button>
            ) : (
              <Text size="1" color="gray">{t("当前账号没有商品编辑权限，无法修改推荐问题。")}</Text>
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
