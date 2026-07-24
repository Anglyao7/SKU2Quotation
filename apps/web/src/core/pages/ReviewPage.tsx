import { Badge, Button, Card, Heading, Text, TextField } from "@radix-ui/themes";
import { Check, FileXls, Image, ShieldCheck, Sparkle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { approveProductCandidate, approveReviewItem, listReviewItems, updateReviewItem } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, percent } from "../CoreUi";
import type { ReviewItem } from "../types";

export function ReviewPage() {
  const { hasPermission } = useCoreAuth();
  const canApprove = hasPermission("product.review");
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const rows = await listReviewItems();
      setItems(rows);
      setSelectedId((current) => rows.some((row) => row.id === current) ? current : rows[0]?.id ?? "");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "审核队列加载失败"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const item = useMemo(() => items.find((row) => row.id === selectedId) ?? items[0], [items, selectedId]);
  const values = useMemo(() => item ? Object.fromEntries(item.fields.map((field) => [field.key, edits[field.key] ?? field.normalized])) : {}, [edits, item]);

  const save = async () => {
    if (!item) return;
    setBusy(true); setError("");
    try { await updateReviewItem(item.id, values); setEdits({}); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "审核修改保存失败"); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    if (!item) return;
    setBusy(true); setError("");
    try {
      if (item.taskId && item.candidateGroupKey) await approveProductCandidate(item, values);
      else { if (Object.keys(edits).length) await updateReviewItem(item.id, values); await approveReviewItem(item.id); }
      setEdits({}); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "产品发布失败"); }
    finally { setBusy(false); }
  };

  return <div className="core-workspace">
    <CorePageHeading eyebrow="人工确认边界" title="产品审核队列" description="逐字段比对来源证据。产品发布与图片批准是两套独立门禁。" actions={<Button variant="soft" color="gray" onClick={() => void load()}>刷新队列</Button>} />
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
    {loading && !items.length ? <CoreLoading label="正在读取待审核候选" /> : !item ? <CoreEmpty title="审核队列已清空" description="需要人工确认的非标准资料产生候选后，会出现在这里。" /> : <div className="core-review-layout">
      <Card className="core-review-queue">
        <div className="core-panel-heading"><div><Text size="1" color="gray">实时队列</Text><Heading size="4">标准化候选</Heading></div><Badge color="amber">{items.filter((row) => row.status !== "approved").length} 待处理</Badge></div>
        <div className="core-review-rows">{items.map((row) => <button type="button" className={row.id === item.id ? "active" : ""} key={row.id} onClick={() => { setSelectedId(row.id); setEdits({}); }}><span className="core-row-icon"><Image /></span><span><strong>{row.name || "产品名待确认"}</strong><small>{row.model || "型号待确认"} · {row.location}</small></span>{row.status === "approved" ? <Check /> : <span>›</span>}</button>)}</div>
      </Card>

      <Card className="core-review-source">
        <div className="core-panel-heading"><div><Text size="1" color="gray">来源证据</Text><Heading size="4">{item.source}</Heading></div><FileXls /></div>
        <div className="core-sheet-preview"><div className="core-sheet-head"><span>A</span><span>B</span><span>C</span></div><div className="core-sheet-row"><strong>字段</strong><strong>来源值</strong><strong>位置</strong></div>{item.fields.slice(0, 5).map((field) => <div className="core-sheet-row" key={field.key}><span>{field.label}</span><span>{field.source || "—"}</span><span>{item.location}</span></div>)}</div>
        <Card className="core-image-policy"><div className="core-product-art"><Image size={36} /></div><div><Text size="1" color="gray">图片策略</Text><Heading size="3">{item.imageStatus === "SOURCE" ? "仅来源图" : "图片已批准"}</Heading><Text size="2" color="gray">确认字段不会自动批准图片。只有通过独立图片审核的素材才能进入对客报价。</Text></div></Card>
      </Card>

      <Card className="core-review-editor">
        <div className="core-panel-heading"><div><Text size="1" color="gray">标准化记录</Text><Heading size="4">可信产品字段</Heading></div><Sparkle /></div>
        <div className="core-review-meta"><Badge color="gray">{item.supplier}</Badge><Text weight="bold">{item.model || "型号待确认"}</Text></div>
        <div className="core-field-list">{item.fields.map((field) => <label key={`${item.id}-${field.key}`}><span><Text weight="medium">{field.label}</Text><Badge color={field.confidence >= .8 ? "jade" : field.confidence >= .6 ? "amber" : "red"}>{percent(field.confidence)}</Badge></span><small>来源：{field.source || "空"}</small><TextField.Root disabled={!canApprove} value={edits[field.key] ?? field.normalized} onChange={(event) => setEdits((current) => ({ ...current, [field.key]: event.target.value }))} /></label>)}</div>
        <Card className="core-notice"><ShieldCheck /><div><Text weight="bold" as="div">内部发布门禁</Text><Text size="1" color="gray">确认后产品进入当前租户的内部搜索和询盘匹配；来源图片继续保持 SOURCE。</Text></div></Card>
        {canApprove ? <div className="core-dialog-actions">{!item.taskId ? <Button variant="soft" color="gray" disabled={busy || !Object.keys(edits).length} onClick={() => void save()}>暂存修改</Button> : <Text size="1" color="gray">候选不可变，修改将随发布决定一起提交。</Text>}<Button disabled={busy || item.status === "approved"} onClick={() => void approve()}><Check />{item.status === "approved" ? "已发布" : "确认并发布"}</Button></div> : <Text size="2" color="gray">当前角色只有查看审核证据的权限。</Text>}
      </Card>
    </div>}
  </div>;
}
