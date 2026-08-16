import { Badge, Button, Dialog, Progress, Text } from "@radix-ui/themes";
import { Check, CheckCircle, ImageSquare, Sparkle, X, XCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  cancelImageEnhancementTask,
  confirmImageEnhancementTask,
  getImageEnhancementTask,
  reviewImageEnhancementTask,
  startImageEnhancement,
} from "../api";
import { useLocale } from "../LocaleContext";
import type { ImageEnhancementTask } from "../types";
import "./ImageEnhancementDialog.css";

export interface ImageEnhancementTarget {
  productId: string;
  skuIds: string[];
}

function statusLabel(status: ImageEnhancementTask["items"][number]["status"], t: (key: string) => string) {
  if (status === "QUEUED") return t("排队中");
  if (status === "RUNNING") return t("处理中");
  if (status === "COMPLETED") return t("已完成");
  if (status === "CANCELLED") return t("已取消");
  return t("失败");
}

function reviewLabel(status: ImageEnhancementTask["items"][number]["reviewStatus"], t: (key: string) => string) {
  if (status === "APPROVED") return t("已通过");
  if (status === "REJECTED") return t("已驳回");
  if (status === "APPLIED") return t("已应用");
  return t("待审核");
}

export function ImageEnhancementDialog({
  open,
  targets,
  onOpenChange,
  onApplied,
}: {
  open: boolean;
  targets: ImageEnhancementTarget[];
  onOpenChange: (open: boolean) => void;
  onApplied?: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [task, setTask] = useState<ImageEnhancementTask>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [previewUrl, setPreviewUrl] = useState<string>();
  const startedKey = useRef("");
  const targetKey = useMemo(
    () => targets.map((target) => `${target.productId}:${[...target.skuIds].sort().join(",")}`).sort().join("|")
    , [targets],
  );

  useEffect(() => {
    if (!open || !targetKey) {
      // Closing the dialog ends this run. Allow the same selection to start a
      // fresh task when the operator opens it again (including after a failure).
      startedKey.current = "";
      return;
    }
    if (startedKey.current === targetKey) return;
    startedKey.current = targetKey;
    setTask(undefined);
    setError("");
    setBusy(true);
    void startImageEnhancement(targets)
      .then(setTask)
      .catch((reason) => {
        startedKey.current = "";
        setError(reason instanceof Error ? reason.message : t("图片清晰化任务创建失败"));
      })
      .finally(() => setBusy(false));
  }, [open, t, targetKey, targets]);

  useEffect(() => {
    if (!open || !task || !["QUEUED", "RUNNING"].includes(task.status)) return;
    let cancelled = false;
    let timer = 0;
    const poll = () => {
      timer = window.setTimeout(() => {
        void getImageEnhancementTask(task.id)
          .then((next) => {
            if (cancelled) return;
            setTask(next);
            if (["QUEUED", "RUNNING"].includes(next.status)) poll();
          })
          .catch((reason) => {
            if (!cancelled) {
              setError(reason instanceof Error ? reason.message : t("任务状态刷新失败"));
              poll();
            }
          });
      }, 1500);
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, t, task]);

  const reviewableIds = task?.items
    .filter((item) => item.status === "COMPLETED" && item.reviewStatus === "PENDING")
    .map((item) => item.id) ?? [];
  const approvedIds = task?.items
    .filter((item) => item.status === "COMPLETED" && item.reviewStatus === "APPROVED")
    .map((item) => item.id) ?? [];
  const reviewItem = async (itemId: string, decision: "APPROVE" | "REJECT") => {
    if (!task || busy) return;
    setBusy(true);
    setError("");
    try {
      const reviewed = await reviewImageEnhancementTask(task.id, [itemId], decision);
      if (decision === "APPROVE") {
        const applied = await confirmImageEnhancementTask(reviewed.id, [itemId]);
        setTask(applied);
        await onApplied?.();
      } else {
        setTask(reviewed);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("审核失败"));
    } finally {
      setBusy(false);
    }
  };
  const reviewAll = async (decision: "APPROVE" | "REJECT") => {
    if (!task || busy || !reviewableIds.length) return;
    setBusy(true);
    setError("");
    try {
      const reviewed = await reviewImageEnhancementTask(task.id, reviewableIds, decision);
      if (decision === "APPROVE") {
        const applied = await confirmImageEnhancementTask(reviewed.id, reviewableIds);
        setTask(applied);
        await onApplied?.();
      } else {
        setTask(reviewed);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("审核失败"));
    } finally {
      setBusy(false);
    }
  };
  const cancelItem = async (itemId?: string) => {
    if (!task || busy) return;
    setBusy(true);
    setError("");
    try {
      setTask(await cancelImageEnhancementTask(task.id, itemId ? [itemId] : []));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("取消失败"));
    } finally {
      setBusy(false);
    }
  };
  const confirm = async () => {
    if (!task || busy || !approvedIds.length) return;
    setBusy(true);
    setError("");
    try {
      setTask(await confirmImageEnhancementTask(task.id, approvedIds));
      await onApplied?.();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("应用图片失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Content className="core-image-enhancement-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("商品图片")}</Text>
              <Dialog.Title><Sparkle />{t("图片变清晰")}</Dialog.Title>
              <Dialog.Description>{t("生成结果会先进入审核，确认后才会替换商品主图。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => onOpenChange(false)} aria-label={t("关闭")}><X /></Button>
          </div>
          {busy && !task ? <div className="core-image-enhancement-starting"><Sparkle className="is-spinning" /><Text>{t("正在创建清晰化任务…")}</Text></div> : null}
          {error ? <div className="core-form-error" role="alert">{error}</div> : null}
          {task ? (
            <div className="core-image-enhancement-body">
              <div className="core-image-enhancement-progress">
                <div>
                  <Text weight="bold">{task.status === "COMPLETED" || task.status === "PARTIAL" ? t("任务已完成") : t("正在生成清晰图片")}</Text>
                  <Text size="1" color="gray">{t("已完成 {done} / {total}", { done: task.completedItems, total: task.totalItems })}</Text>
                </div>
                <strong>{Math.round(task.progressPercent)}%</strong>
                <Progress value={task.progressPercent} />
              </div>
              <div className="core-image-enhancement-toolbar">
                <Text size="1" color="gray">{t("完成后请逐张审核，审核通过后会自动替换商品主图。")}</Text>
                <span>
                  {reviewableIds.length ? <Button size="1" variant="soft" disabled={busy} onClick={() => void reviewAll("APPROVE")}><Check />{t("全部审核通过")}</Button> : null}
                  {approvedIds.length ? <Button size="1" color="jade" disabled={busy} onClick={() => void confirm()}><CheckCircle />{t("应用已审核 {count} 张", { count: approvedIds.length })}</Button> : null}
                  {["QUEUED", "RUNNING"].includes(task.status) ? <Button size="1" variant="soft" color="gray" disabled={busy} onClick={() => void cancelItem()}><XCircle />{t("取消剩余任务")}</Button> : null}
                </span>
              </div>
              <div className="core-image-enhancement-items">
                {task.items.map((item) => (
                  <article className="core-image-enhancement-item" key={item.id}>
                    <div className="core-image-enhancement-preview" data-ready={Boolean(item.resultUrl) || undefined}>
                      {item.resultUrl ? (
                        <div className="core-image-enhancement-comparison" aria-label={t("原图与清晰化结果对比")}>
                          <div className="core-image-enhancement-comparison-side">
                            {item.sourceImageUrl ? (
                              <button type="button" onClick={() => setPreviewUrl(item.sourceImageUrl)} aria-label={t("查看原图大图")}>
                                <img src={item.sourceImageUrl} alt={`${item.productName} · ${t("原图")}`} />
                              </button>
                            ) : <ImageSquare aria-hidden="true" />}
                            <span>{t("原图")}</span>
                          </div>
                          <div className="core-image-enhancement-comparison-side">
                            <button type="button" onClick={() => setPreviewUrl(item.resultUrl)} aria-label={t("查看清晰化结果大图")}>
                              <img src={item.resultUrl} alt={`${item.productName} · ${t("清晰化结果")}`} />
                            </button>
                            <span>{t("清晰化结果")}</span>
                          </div>
                        </div>
                      ) : item.sourceImageUrl ? (
                        <button type="button" onClick={() => setPreviewUrl(item.sourceImageUrl)} aria-label={t("查看原图大图")}>
                          <img src={item.sourceImageUrl} alt={item.productName} />
                        </button>
                      ) : <ImageSquare />}
                    </div>
                    <div className="core-image-enhancement-item-main">
                      <div className="core-image-enhancement-item-title"><strong>{item.productName}</strong><Badge color={item.status === "COMPLETED" ? "jade" : item.status === "FAILED" ? "red" : item.status === "CANCELLED" ? "gray" : "blue"}>{statusLabel(item.status, t)}</Badge><Badge color={item.reviewStatus === "APPROVED" ? "jade" : item.reviewStatus === "REJECTED" ? "red" : item.reviewStatus === "APPLIED" ? "purple" : "amber"}>{reviewLabel(item.reviewStatus, t)}</Badge></div>
                      <Text size="1" color="gray">{item.skuSnapshot.length ? item.skuSnapshot.map((sku) => sku.skuCode || sku.name).filter(Boolean).join("、") : t("全部 SKU")}</Text>
                      {item.errorMessage ? <Text size="1" color="red">{item.errorMessage}</Text> : null}
                    </div>
                    <div className="core-image-enhancement-item-actions">
                      {item.status === "COMPLETED" && item.reviewStatus === "PENDING" ? <><Button size="1" variant="soft" color="red" disabled={busy} onClick={() => void reviewItem(item.id, "REJECT")}>{t("驳回")}</Button><Button size="1" color="jade" disabled={busy} onClick={() => void reviewItem(item.id, "APPROVE")}><Check />{t("审核通过")}</Button></> : null}
                      {item.status === "QUEUED" || item.status === "RUNNING" ? <Button size="1" variant="ghost" color="gray" disabled={busy} onClick={() => void cancelItem(item.id)}>{t("取消")}</Button> : null}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Root>
      <Dialog.Root open={Boolean(previewUrl)} onOpenChange={(next) => { if (!next) setPreviewUrl(undefined); }}>
        <Dialog.Content className="core-image-enhancement-preview-dialog">
          <Button className="core-image-enhancement-preview-close" variant="ghost" color="gray" onClick={() => setPreviewUrl(undefined)} aria-label={t("关闭")}><X /></Button>
          {previewUrl ? <img src={previewUrl} alt={t("清晰化结果")} /> : null}
        </Dialog.Content>
      </Dialog.Root>
    </>
  );
}
