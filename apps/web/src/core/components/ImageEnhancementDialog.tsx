import { Badge, Button, Dialog, Progress, Text, TextArea } from "@radix-ui/themes";
import { Check, ImageSquare, Sparkle, X, XCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import {
  cancelImageEnhancementTask,
  getImageEnhancementTask,
  reviewImageEnhancementTask,
  startImageEnhancement,
} from "../api";
import { useLocale } from "../LocaleContext";
import type { ImageEnhancementRatio, ImageEnhancementSize, ImageEnhancementTask } from "../types";
import "./ImageEnhancementDialog.css";

export interface ImageEnhancementTarget {
  productId: string;
  skuIds: string[];
}

const DEFAULT_IMAGE_ENHANCEMENT_PROMPT =
  "Enhance only the provided product image: make it sharper, clearer, and less noisy. " +
  "The input image is the source of truth. Preserve the exact product, colors, materials, " +
  "shape, proportions, existing text, markings, existing logos, background, lighting, and composition. " +
  "Do not add, remove, redraw, or invent any logo, text, label, accessory, decoration, prop, or other object. " +
  "Do not change the background or create a new design.";

const IMAGE_ENHANCEMENT_RATIOS: ImageEnhancementRatio[] = ["1:1", "4:3", "3:4", "16:9", "9:16"];
const IMAGE_ENHANCEMENT_SIZES: ImageEnhancementSize[] = ["1K", "2K", "4K"];

type ImageEnhancementRetryDraft = {
  prompt: string;
  ratio: ImageEnhancementRatio;
  size: ImageEnhancementSize;
};

function defaultRetryDraft(): ImageEnhancementRetryDraft {
  return { prompt: DEFAULT_IMAGE_ENHANCEMENT_PROMPT, ratio: "1:1", size: "1K" };
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
  const [prompt, setPrompt] = useState(DEFAULT_IMAGE_ENHANCEMENT_PROMPT);
  const [ratio, setRatio] = useState<ImageEnhancementRatio>("1:1");
  const [size, setSize] = useState<ImageEnhancementSize>("1K");
  const [retryDrafts, setRetryDrafts] = useState<Record<string, ImageEnhancementRetryDraft>>({});
  const targetKey = useMemo(
    () => targets.map((target) => `${target.productId}:${[...target.skuIds].sort().join(",")}`).sort().join("|")
    , [targets],
  );

  useEffect(() => {
    if (!open || !targetKey) {
      setTask(undefined);
      setError("");
      setBusy(false);
      return;
    }
    // A new selection starts with a fresh editable configuration. The task is
    // intentionally not created until the operator confirms the prompt.
    setTask(undefined);
    setError("");
    setBusy(false);
    setPrompt(DEFAULT_IMAGE_ENHANCEMENT_PROMPT);
    setRatio("1:1");
    setSize("1K");
    setRetryDrafts({});
  }, [open, targetKey]);

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
  const start = async () => {
    if (!targetKey || busy || task) return;
    if (!prompt.trim()) {
      setError(t("请输入清晰化提示词"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      setTask(await startImageEnhancement(targets, prompt, ratio, size));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("图片清晰化任务创建失败"));
    } finally {
      setBusy(false);
    }
  };
  const updateRetryDraft = (itemId: string, patch: Partial<ImageEnhancementRetryDraft>) => {
    setRetryDrafts((current) => ({
      ...current,
      [itemId]: { ...defaultRetryDraft(), ...current[itemId], ...patch },
    }));
  };
  const retryItem = async (item: ImageEnhancementTask["items"][number]) => {
    if (busy) return;
    const draft = { ...defaultRetryDraft(), ...retryDrafts[item.id] };
    if (!draft.prompt.trim()) {
      setError(t("请输入清晰化提示词"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      setTask(await startImageEnhancement(
        [{ productId: item.productId, skuIds: item.skuIds }],
        draft.prompt,
        draft.ratio,
        draft.size,
      ));
      setRetryDrafts({});
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("图片清晰化任务创建失败"));
    } finally {
      setBusy(false);
    }
  };
  const reviewItem = async (itemId: string, decision: "APPROVE" | "REJECT") => {
    if (!task || busy) return;
    setBusy(true);
    setError("");
    try {
      const reviewed = await reviewImageEnhancementTask(task.id, [itemId], decision);
      setTask(reviewed);
      if (decision === "APPROVE" && reviewed.items.some((item) => item.id === itemId && item.reviewStatus === "APPLIED")) {
        await onApplied?.();
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
      setTask(reviewed);
      if (decision === "APPROVE" && reviewed.items.some((item) => item.reviewStatus === "APPLIED")) {
        await onApplied?.();
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
  return (
    <>
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Content className="core-image-enhancement-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("商品图片")}</Text>
              <Dialog.Title><Sparkle />{t("图片变清晰")}</Dialog.Title>
              <Dialog.Description>{t("生成结果会先进入审核，审核通过后立即替换商品主图。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => onOpenChange(false)} aria-label={t("关闭")}><X /></Button>
          </div>
          {error ? <div className="core-form-error" role="alert">{error}</div> : null}
          {!task ? (
            <div className="core-image-enhancement-settings">
              <label>
                <Text size="2" weight="medium">{t("清晰化提示词")}</Text>
                <TextArea
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  maxLength={2000}
                  rows={6}
                  disabled={busy}
                  placeholder={t("描述希望如何改善图片，同时说明需要保持不变的内容")}
                />
              </label>
              <div className="core-image-enhancement-settings-grid">
                <label>
                  <Text size="2" weight="medium">{t("图片比例")}</Text>
                  <select value={ratio} onChange={(event) => setRatio(event.target.value as ImageEnhancementRatio)} disabled={busy}>
                    {IMAGE_ENHANCEMENT_RATIOS.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
                <label>
                  <Text size="2" weight="medium">{t("输出尺寸")}</Text>
                  <select value={size} onChange={(event) => setSize(event.target.value as ImageEnhancementSize)} disabled={busy}>
                    {IMAGE_ENHANCEMENT_SIZES.map((option) => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
              </div>
              <div className="core-image-enhancement-settings-actions">
                {busy ? <Text size="1" color="gray"><Sparkle className="is-spinning" />{t("正在创建清晰化任务…")}</Text> : null}
                <Button disabled={busy || !targets.length} onClick={() => void start()}><Sparkle />{t("开始生成")}</Button>
              </div>
            </div>
          ) : (
            <div className="core-image-enhancement-body">
              <div className="core-image-enhancement-summary">
                <Text size="1" color="gray">{t("本次设置")}</Text>
                <span>{task.ratio} · {task.size}</span>
              </div>
              <div className="core-image-enhancement-progress">
                <div>
                  <Text weight="bold">{task.status === "COMPLETED" || task.status === "PARTIAL" ? t("任务已完成") : t("正在生成清晰图片")}</Text>
                  <Text size="1" color="gray">{t("已完成 {done} / {total}", { done: task.completedItems, total: task.totalItems })}</Text>
                </div>
                <strong>{Math.round(task.progressPercent)}%</strong>
                <Progress value={task.progressPercent} />
              </div>
              <div className="core-image-enhancement-toolbar">
                <Text size="1" color="gray">{t("审核通过后会立即替换商品主图。")}</Text>
                <span>
                  {reviewableIds.length ? <Button size="2" variant="soft" disabled={busy} onClick={() => void reviewAll("APPROVE")}><Check />{t("全部审核通过")}</Button> : null}
                  {["QUEUED", "RUNNING"].includes(task.status) ? <Button size="2" variant="soft" color="gray" disabled={busy} onClick={() => void cancelItem()}><XCircle />{t("取消剩余任务")}</Button> : null}
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
                      {item.status === "COMPLETED" && item.reviewStatus === "REJECTED" ? (() => {
                        const draft = { ...defaultRetryDraft(), ...retryDrafts[item.id] };
                        return (
                          <div className="core-image-enhancement-retry">
                            <div className="core-image-enhancement-retry-heading">
                              <Text weight="bold">{t("重新处理这张图片")}</Text>
                              <Text size="1" color="gray">{t("已载入系统默认提示词，可按需修改后再次提交。")}</Text>
                            </div>
                            <TextArea
                              value={draft.prompt}
                              onChange={(event) => updateRetryDraft(item.id, { prompt: event.target.value })}
                              maxLength={2000}
                              rows={4}
                              disabled={busy}
                              aria-label={t("重新处理提示词")}
                            />
                            <div className="core-image-enhancement-retry-options">
                              <select value={draft.ratio} onChange={(event) => updateRetryDraft(item.id, { ratio: event.target.value as ImageEnhancementRatio })} disabled={busy} aria-label={t("图片比例")}>
                                {IMAGE_ENHANCEMENT_RATIOS.map((option) => <option key={option} value={option}>{t("比例")}: {option}</option>)}
                              </select>
                              <select value={draft.size} onChange={(event) => updateRetryDraft(item.id, { size: event.target.value as ImageEnhancementSize })} disabled={busy} aria-label={t("输出尺寸")}>
                                {IMAGE_ENHANCEMENT_SIZES.map((option) => <option key={option} value={option}>{t("尺寸")}: {option}</option>)}
                              </select>
                              <Button size="2" color="blue" disabled={busy} onClick={() => void retryItem(item)}><Sparkle />{t("修改提示词并重新生成")}</Button>
                            </div>
                          </div>
                        );
                      })() : null}
                    </div>
                    <div className="core-image-enhancement-item-actions">
                      {item.status === "COMPLETED" && item.reviewStatus === "PENDING" ? <><Button size="2" variant="soft" color="red" disabled={busy} onClick={() => void reviewItem(item.id, "REJECT")}>{t("驳回")}</Button><Button size="2" color="jade" disabled={busy} onClick={() => void reviewItem(item.id, "APPROVE")}><Check />{t("审核通过")}</Button></> : null}
                      {item.status === "QUEUED" || item.status === "RUNNING" ? <Button size="2" variant="ghost" color="gray" disabled={busy} onClick={() => void cancelItem(item.id)}>{t("取消")}</Button> : null}
                    </div>
                  </article>
                ))}
              </div>
            </div>
          )}
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
