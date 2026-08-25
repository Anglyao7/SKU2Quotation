import {
  AlertDialog,
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Text,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsClockwise,
  CloudArrowDown,
  ImageSquare,
  Pause,
  Play,
  Sparkle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  getImageIndexJob,
  getImageIndexStatus,
  getLatestImageIndexJob,
  pauseImageIndexJob,
  resumeImageIndexJob,
  startImageIndexJob,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { ImageIndexJob, ImageIndexStatus } from "../types";

const ACTIVE_STATUSES = new Set(["QUEUED", "RUNNING"]);

function checkpointTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function ImageSearchManagementPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManage = hasPermission("product.edit");
  const [status, setStatus] = useState<ImageIndexStatus>();
  const [job, setJob] = useState<ImageIndexJob>();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState<"" | "incremental" | "full">("");
  const [controlling, setControlling] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [rebuildOpen, setRebuildOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStatus, nextJob] = await Promise.all([
        getImageIndexStatus(),
        getLatestImageIndexJob(),
      ]);
      setStatus(nextStatus);
      setJob(nextJob);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("图片索引状态读取失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => { void load(); }, [load]);

  const jobIsActive = Boolean(job && ACTIVE_STATUSES.has(job.status));
  const jobBlocksStart = Boolean(job && (jobIsActive || job.status === "PAUSED"));

  useEffect(() => {
    if (!job || !ACTIVE_STATUSES.has(job.status)) return;
    let stopped = false;
    let pending = false;
    const poll = async () => {
      if (pending) return;
      pending = true;
      try {
        const next = await getImageIndexJob(job.id);
        if (stopped) return;
        setJob(next);
        if (next.status === "SUCCEEDED") {
          setStatus(await getImageIndexStatus());
          setStarting("");
          setMessage(next.processedImages
            ? t("图片向量化完成，本次处理 {count} 张图片。", { count: next.processedImages.toLocaleString(locale) })
            : t("当前没有需要更新的商品图片。"));
        } else if (next.status === "FAILED") {
          setStarting("");
          setError(next.errorMessage ?? t("图片向量化失败"));
        } else if (next.status === "PAUSED") {
          setStarting("");
          setMessage(t("图片向量化已暂停，已完成向量和断点均已保留。"));
        }
      } catch (reason) {
        if (!stopped) setError(reason instanceof Error ? reason.message : t("图片索引状态读取失败"));
      } finally {
        pending = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1500);
    return () => { stopped = true; window.clearInterval(timer); };
  }, [job?.id, job?.status, locale, t]);

  const start = async (full: boolean) => {
    if (!canManage || jobBlocksStart || starting) return;
    setStarting(full ? "full" : "incremental");
    setError("");
    setMessage("");
    try {
      const next = await startImageIndexJob(full);
      setJob(next);
      if (next.status === "SUCCEEDED") {
        setStarting("");
        setMessage(t("当前没有需要更新的商品图片。"));
        setStatus(await getImageIndexStatus());
      }
    } catch (reason) {
      setStarting("");
      setError(reason instanceof Error ? reason.message : t("图片向量化任务启动失败"));
      await load();
    }
  };

  const control = async (action: "pause" | "resume") => {
    if (!canManage || !job || controlling) return;
    setControlling(true);
    setError("");
    setMessage("");
    try {
      const next = action === "pause"
        ? await pauseImageIndexJob(job.id)
        : await resumeImageIndexJob(job.id);
      setJob(next);
      setMessage(action === "pause"
        ? next.status === "PAUSED"
          ? t("图片向量化已暂停。")
          : t("系统会在当前图片完成后保存断点并暂停。")
        : t("图片向量化已从断点继续，只处理剩余图片。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("任务操作失败"));
    } finally {
      setControlling(false);
    }
  };

  const coverage = useMemo(() => {
    if (!status?.totalImages) return 0;
    return Math.round(status.indexedImages / status.totalImages * 100);
  }, [status]);
  const badgeColor = job?.status === "FAILED"
    ? "red"
    : job?.status === "SUCCEEDED"
      ? "jade"
      : "amber";

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow={t("客户图搜")}
        title={t("图片搜索管理")}
        description={t("把当前店铺已审批的 R2 或 CDN 商品图片建立为视觉向量，供客户上传图片查找商品。")}
        actions={(
          <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}>
            <ArrowClockwise />{t("刷新状态")}
          </Button>
        )}
      />

      {loading && !status ? <CoreLoading label={t("正在核对商品图片与视觉索引")} /> : null}
      {error && !status ? <CoreError message={error} onRetry={() => void load()} /> : null}

      {status ? (
        <>
          <Card className="core-ai-index-overview" aria-live="polite">
            <div className="core-ai-index-heading">
              <span className="core-index-icon"><ImageSquare /></span>
              <div>
                <Text size="1" color="gray" as="div">{t("当前店铺图片索引")}</Text>
                <Heading size="5">
                  {job?.status === "PAUSED"
                    ? t("已暂停：{done} / {total} 张图片", { done: job.processedImages, total: job.totalImages })
                    : jobIsActive
                      ? t("正在处理 {done} / {total} 张图片", { done: job!.processedImages, total: job!.totalImages })
                      : status.pendingImages
                        ? t("{count} 张图片等待向量化", { count: status.pendingImages })
                        : t("图片索引已是最新")}
                </Heading>
              </div>
              <Badge color={job?.status === "PAUSED" || jobIsActive || status.pendingImages ? "amber" : "jade"}>
                {t(job?.status === "PAUSED" ? "任务已暂停" : jobIsActive ? "任务执行中" : status.pendingImages ? "需要同步" : "客户可使用")}
              </Badge>
            </div>

            {job ? (
              <div className="core-ai-job-progress">
                <div className="core-ai-job-progress-head">
                  <span>
                    <Text size="1" color="gray" as="div">{t(job.mode === "FULL_REBUILD" ? "全量重建" : "增量更新")}</Text>
                    <Text size="2" weight="bold" as="div">{job.processedImages} / {job.totalImages}</Text>
                  </span>
                  <Badge color={badgeColor}>{t(job.status)}</Badge>
                </div>
                <Progress value={job.progressPercent} color={job.status === "FAILED" ? "red" : job.status === "PAUSED" ? "amber" : "jade"} />
                <div className="core-ai-job-meta">
                  <Text size="1" color="gray">{t("已写入 {count} 条图片向量", { count: job.embeddings })}</Text>
                  {job.currentProductName ? <Text size="1" color="gray">{t("正在读取：{name}", { name: job.currentProductName })}</Text> : null}
                  {job.checkpointAt && job.remainingImages ? (
                    <Text size="1" color="gray">{t("剩余 {count} 张 · 断点 {time}", { count: job.remainingImages, time: checkpointTime(job.checkpointAt, locale) })}</Text>
                  ) : null}
                </div>
                {job.errorMessage ? <Text size="2" color={job.status === "FAILED" ? "red" : "gray"}>{job.errorMessage}</Text> : null}
              </div>
            ) : null}

            <div className="core-ai-index-progress">
              <span>
                <Text size="2" color="gray">{t("图片覆盖")}</Text>
                <Text size="2" weight="bold">{status.indexedImages} / {status.totalImages}</Text>
              </span>
              <Progress value={coverage} />
            </div>

            <div className="core-ai-index-actions">
              {canManage ? (
                <>
                  {job && (job.resumable || jobIsActive || job.pauseRequested) ? (
                    <Button
                      size="3"
                      variant="soft"
                      color={job.resumable || job.pauseRequested ? "blue" : "amber"}
                      disabled={controlling}
                      onClick={() => void control(job.resumable || job.pauseRequested ? "resume" : "pause")}
                    >
                      {job.resumable || job.pauseRequested ? <Play /> : <Pause />}
                      {t(controlling ? "处理中…" : job.resumable ? "从断点继续" : job.pauseRequested ? "取消暂停" : "暂停向量化")}
                    </Button>
                  ) : null}
                  <Button size="3" disabled={!status.pendingImages || jobBlocksStart || Boolean(starting)} onClick={() => void start(false)}>
                    <Sparkle />{t(starting === "incremental" || jobIsActive ? "正在更新…" : "更新图片索引")}
                  </Button>
                  <Button size="3" variant="soft" color="gray" disabled={!status.totalImages || jobBlocksStart || Boolean(starting)} onClick={() => setRebuildOpen(true)}>
                    <ArrowsClockwise />{t("全量重建")}
                  </Button>
                </>
              ) : <Text size="2" color="gray">{t("当前账号只能查看状态，没有商品编辑权限。")}</Text>}
            </div>
            {message ? <Text size="2" color="green">{message}</Text> : null}
            {error ? <Text size="2" color="red">{error}</Text> : null}
          </Card>

          <div className="core-ai-index-details is-single">
            <section>
              <Text size="1" color="gray"><CloudArrowDown /> R2 / CDN</Text>
              <Heading size="4">{t("兼容 R2 对象键和现有 CDN 图片")}</Heading>
              <p>{t("服务端临时读取已批准的 R2 或 CDN 商品图片，校验并预处理后以 Base64 调用模型；客户上传的搜索图片只用于本次检索，不写入长期知识库。")}</p>
            </section>
          </div>
        </>
      ) : null}

      <AlertDialog.Root open={rebuildOpen} onOpenChange={setRebuildOpen}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>{t("全量重建图片索引？")}</AlertDialog.Title>
          <AlertDialog.Description size="2">{t("系统会重新下载并向量化当前店铺全部 {count} 张已审批图片，会消耗相应模型额度。", { count: status?.totalImages ?? 0 })}</AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
            <AlertDialog.Action><Button onClick={() => void start(true)}><ArrowsClockwise />{t("确认全量重建")}</Button></AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
