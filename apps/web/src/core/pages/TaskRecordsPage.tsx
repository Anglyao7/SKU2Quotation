import { Badge, Button, Text, TextField } from "@radix-ui/themes";
import { ArrowSquareOut, ArrowsClockwise, MagnifyingGlass } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { getLatestCatalogTranslationJob, getLatestImageIndexJob, getLatestKnowledgeIndexJob, listCatalogImportBatches, listImageEnhancementTasks } from "../api";
import { STOREFRONT_LANGUAGE_OPTIONS } from "../../lib/storefrontLocale";
import { ImageEnhancementDialog } from "../components/ImageEnhancementDialog";
import { activeTaskStates as activeStates, failedTaskStates as failedStates, normalizeTaskStatus } from "../taskStatus";

type TaskRow = { id: string; kind: string; name: string; status: string; progress: number; createdAt: string; href: string; reviewId?: string };
type TaskSource = { key: string; label: string; load: () => Promise<TaskRow[]> };
const statusNames: Record<string, string> = { QUEUED: "排队中", PENDING: "排队中", RUNNING: "处理中", PROCESSING: "处理中", PARSING: "处理中", UPLOADING: "处理中", IMPORTING: "处理中", COMPLETED: "已完成", SUCCEEDED: "已完成", PUBLISHED: "已发布", SUCCESS: "已完成", FAILED: "失败", PARTIAL: "部分完成", CANCELLED: "已取消", PAUSED: "已暂停", REVIEW: "待审核", REVOKED: "已撤回" };

export function TaskRecordsPage() {
  const { profile, hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const tenantId = profile?.context.tenantId ?? "";
  const canImport = hasPermission("product.import");
  const canEdit = hasPermission("product.edit");
  const isAdmin = Boolean(profile?.user.isPlatformAdmin);
  const isChild = profile?.context.accountScope === "CUSTOMER_SUBACCOUNT";
  const [rows, setRows] = useState<Record<string, TaskRow[]>>({});
  const [errors, setErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("ALL");
  const [refresh, setRefresh] = useState(0);
  const [reviewId, setReviewId] = useState<string>();
  const generation = useRef(0);
  useEffect(() => {
    const version = ++generation.current;
    setRows({}); setErrors([]); setLoading(true);
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const sources: TaskSource[] = [];
    if (!isChild && canImport) sources.push({ key: "imports", label: "导入商品", load: async () => (await listCatalogImportBatches(30)).flatMap((batch) => batch.jobs.map((job) => ({ id: `import:${job.id}`, kind: "导入商品", name: job.filename, status: batch.status === "REVOKED" ? "REVOKED" : job.status, progress: job.progress, createdAt: job.createdAt, href: `/console/products?import=1&job=${encodeURIComponent(job.id)}` }))) });
    if (!isChild && canEdit) {
      sources.push({ key: "text-index", label: "AI 搜索管理", load: async () => { const job = await getLatestKnowledgeIndexJob(); return job ? [{ id: `index:${job.id}`, kind: "AI 搜索管理", name: "商品索引", status: job.status, progress: job.progressPercent, createdAt: job.createdAt, href: "/console/ai-search/manage" }] : []; } });
      sources.push({ key: "image-index", label: "图片搜索管理", load: async () => { const job = await getLatestImageIndexJob(); return job ? [{ id: `image-index:${job.id}`, kind: "图片搜索管理", name: "图片索引", status: job.status, progress: job.progressPercent, createdAt: job.createdAt, href: "/console/image-search/manage" }] : []; } });
    }
    if (!isChild && isAdmin && canEdit) {
      sources.push({ key: "enhancements", label: "图片变清晰", load: async () => (await listImageEnhancementTasks(20)).map((job) => ({ id: `enhance:${job.id}`, kind: "图片变清晰", name: job.items[0]?.productName || t("图片变清晰"), status: job.items.some((item) => item.status === "COMPLETED" && item.reviewStatus === "PENDING") ? "REVIEW" : job.status, progress: job.progressPercent, createdAt: job.createdAt, href: "/console/products", reviewId: job.id })) });
      for (const language of STOREFRONT_LANGUAGE_OPTIONS.filter((option) => option.code !== "zh-CN")) sources.push({ key: `translation:${language.code}`, label: `${t("翻译")} · ${language.label}`, load: async () => { const job = await getLatestCatalogTranslationJob(language.code, tenantId); return job ? [{ id: `translation:${job.id}`, kind: "翻译", name: language.label, status: job.status, progress: job.progressPercent, createdAt: job.createdAt, href: `/console/platform/translations?tenant=${encodeURIComponent(tenantId)}&language=${encodeURIComponent(language.code)}` }] : []; } });
    }
    const poll = async () => {
      if (!alive) return;
      if (document.hidden) { timer = setTimeout(() => void poll(), 30_000); return; }
      const results = await Promise.allSettled(sources.map(async (source) => ({ key: source.key, rows: await source.load() })));
      if (!alive || generation.current !== version) return;
      setRows((current) => {
        const next = { ...current };
        results.forEach((result) => { if (result.status === "fulfilled") next[result.value.key] = result.value.rows; });
        return next;
      });
      setErrors(results.flatMap((result, index) => result.status === "rejected" ? [t(sources[index].label)] : []));
      setLoading(false);
      timer = setTimeout(() => void poll(), 30_000);
    };
    void poll();
    return () => { alive = false; clearTimeout(timer); };
  }, [tenantId, canImport, canEdit, isAdmin, isChild, refresh, t]);
  const tasks = useMemo(() => Object.values(rows).flat().map((row) => ({ ...row, status: normalizeTaskStatus(row.status), progress: Number.isFinite(row.progress) ? Math.max(0, Math.min(100, row.progress)) : 0 })).sort((a, b) => b.createdAt.localeCompare(a.createdAt)), [rows]);
  const visible = tasks.filter((row) => [row.name, t(row.kind)].join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
    && (filter === "ALL" || (filter === "RUNNING" && activeStates.has(row.status)) || (filter === "FAILED" && failedStates.has(row.status)) || row.status === filter));
  return <div className="core-workspace admin-tasks-page">
    <CorePageHeading eyebrow={t("工作")} title={t("任务记录")} actions={<Button variant="soft" color="gray" loading={loading} onClick={() => setRefresh((value) => value + 1)}><ArrowsClockwise />{t("刷新")}</Button>} />
    <Text size="2" color="gray">{t("当前商家的最近任务；索引与每种语言展示最近一次任务。")}</Text>
    <div className="admin-list-filters"><TextField.Root value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("搜索任务")} aria-label={t("搜索任务")}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
      <select value={filter} aria-label={t("任务状态")} onChange={(event) => setFilter(event.target.value)}>{["ALL", "RUNNING", "REVIEW", "FAILED", "PAUSED", "COMPLETED"].map((value) => <option key={value} value={value}>{t(value === "ALL" ? "全部状态" : statusNames[value])}</option>)}</select>
    </div>
    {errors.length ? <div className="admin-task-source-error" role="status">{t("部分任务暂时无法读取")}: {errors.join("、")}<Button size="1" variant="ghost" onClick={() => setRefresh((value) => value + 1)}>{t("重试")}</Button></div> : null}
    {loading && !tasks.length ? <CoreLoading /> : <div className="admin-table-wrap"><table className="admin-data-table"><thead><tr><th>{t("任务")}</th><th>{t("类型")}</th><th>{t("状态")}</th><th>{t("进度")}</th><th>{t("创建时间")}</th><th>{t("操作")}</th></tr></thead><tbody>{visible.map((row) => <tr key={row.id}>
      <td><strong>{t(row.name)}</strong></td><td>{t(row.kind)}</td><td><Badge color={failedStates.has(row.status) ? "red" : row.status === "REVIEW" ? "amber" : activeStates.has(row.status) ? "blue" : "gray"}>{t(statusNames[row.status] || row.status)}</Badge></td>
      <td><div className="admin-task-progress"><Text size="1">{Math.round(row.progress)}%</Text><progress aria-label={t("进度")} value={row.progress} max={100} /></div></td><td>{coreDate(row.createdAt)}</td>
      <td>{row.reviewId ? <Button variant="soft" onClick={() => setReviewId(row.reviewId)}>{t("查看详情")}</Button> : <Button asChild variant="soft"><Link to={row.href}>{t("查看详情")}<ArrowSquareOut /></Link></Button>}</td>
    </tr>)}</tbody></table>{!visible.length ? <CoreEmpty title={t("暂无任务")} description={t("请调整筛选条件。")} /> : null}</div>}
    {isAdmin && canEdit && reviewId ? <ImageEnhancementDialog open targets={[]} initialTaskId={reviewId} onOpenChange={(open) => { if (!open) { setReviewId(undefined); setRefresh((value) => value + 1); } }} /> : null}
  </div>;
}
