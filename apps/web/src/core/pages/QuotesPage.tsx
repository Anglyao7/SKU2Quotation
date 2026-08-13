import { Badge, Button, Card, Dialog, Heading, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { CheckCircle, FilePdf, FileText, FileXls, PencilSimple, ShieldCheck, ShoppingCartSimple, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreApiError, decideQuotation, downloadPublicQuoteDraftDocument, getPublicQuoteDraft, getQuotation, getStorefrontOrderStatistics, listPublicQuoteDrafts, listQuotations, reviseQuotation, updatePublicQuoteDraftStatus } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { PublicQuoteDraft, PublicQuoteDraftSummary, QuotationRecord, QuotationSummary, StorefrontOrderCurrencyStatistics, StorefrontOrderStatistics } from "../types";

const statusLabel: Record<string, string> = { DRAFT: "草稿", SUBMITTED: "客户已提交", PENDING_REVIEW: "待人工确认", PENDING_CONFIRMATION: "客户提交，待确认", CONFIRMED: "已确认并下发", COMPLETED: "已成交", CANCELLED: "已取消", CALCULATED: "待人工批准", NEEDS_APPROVAL: "规则审批", PENDING: "待批准", APPROVED: "已批准", SENT: "已发送", ACCEPTED: "已接受", REJECTED: "已拒绝", EXPIRED: "已过期", NOT_REQUIRED: "无需审批" };
const label = (value: string) => statusLabel[value] ?? value;
type LineDraft = { quantity: number; targetMarginRate: number };

function orderAmounts(amounts: StorefrontOrderCurrencyStatistics[]) {
  if (!amounts.length) return "—";
  return amounts.map((amount) => `${amount.currency} ${amount.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join(" · ");
}

export function QuotesPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canRevise = hasPermission("quotation.create");
  const canApprove = hasPermission("quotation.approve");
  const [quotes, setQuotes] = useState<QuotationSummary[]>([]);
  const [publicDrafts, setPublicDrafts] = useState<PublicQuoteDraftSummary[]>([]);
  const [orderStatistics, setOrderStatistics] = useState<StorefrontOrderStatistics>();
  const [detail, setDetail] = useState<QuotationRecord>();
  const [publicDetail, setPublicDetail] = useState<PublicQuoteDraft>();
  const [drafts, setDrafts] = useState<Record<string, LineDraft>>({});
  const [changeReason, setChangeReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [draftNotice, setDraftNotice] = useState("");
  const [statisticsNotice, setStatisticsNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError(""); setDraftNotice(""); setStatisticsNotice("");
    const [quotationResult, draftResult, statisticsResult] = await Promise.allSettled([listQuotations(), listPublicQuoteDrafts(), getStorefrontOrderStatistics()]);
    if (quotationResult.status === "fulfilled") setQuotes(quotationResult.value);
    else setError(quotationResult.reason instanceof Error ? quotationResult.reason.message : t("正式报价加载失败"));
    if (draftResult.status === "fulfilled") setPublicDrafts(draftResult.value);
    else if (draftResult.reason instanceof CoreApiError && draftResult.reason.status === 404) { setPublicDrafts([]); setDraftNotice(t("客户前台草稿接口尚未启用；正式报价不受影响。")); }
    else setDraftNotice(draftResult.reason instanceof Error ? t("客户前台草稿暂不可用：{message}", { message: draftResult.reason.message }) : t("客户前台草稿暂不可用"));
    if (statisticsResult.status === "fulfilled") setOrderStatistics(statisticsResult.value);
    else setStatisticsNotice(t("订单统计暂时无法读取，订单记录不受影响。"));
    setLoading(false);
  }, [t]);
  useEffect(() => { void load(); }, [load]);

  const pending = quotes.filter((row) => ["CALCULATED", "NEEDS_APPROVAL"].includes(row.status)).length;
  const approved = quotes.filter((row) => row.status === "APPROVED").length;
  const currencies = useMemo(() => new Set(quotes.map((row) => row.currency)).size, [quotes]);

  const openQuote = async (quoteId: string) => {
    setLoading(true); setError("");
    try { const row = await getQuotation(quoteId); setDetail(row); setDrafts(Object.fromEntries(row.items.map((item) => [item.id, { quantity: item.quantity, targetMarginRate: item.targetMarginRate ?? .2 }]))); setChangeReason(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("报价详情加载失败")); }
    finally { setLoading(false); }
  };
  const openPublicDraft = async (draftId: string) => {
    setLoading(true); setError("");
    try { setPublicDetail(await getPublicQuoteDraft(draftId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("客户草稿详情加载失败")); }
    finally { setLoading(false); }
  };

  const saveRevision = async () => {
    if (!detail || changeReason.trim().length < 3) { setError(t("请填写至少 3 个字符的修改原因。")); return; }
    setSaving(true); setError("");
    try {
      const revised = await reviseQuotation(detail, detail.items.map((item) => ({ itemId: item.id, quantity: drafts[item.id]?.quantity ?? item.quantity, targetMarginRate: drafts[item.id]?.targetMarginRate ?? item.targetMarginRate ?? .2 })), changeReason.trim());
      setDetail(revised); setDrafts(Object.fromEntries(revised.items.map((item) => [item.id, { quantity: item.quantity, targetMarginRate: item.targetMarginRate ?? .2 }]))); setChangeReason(""); await load();
    } catch (reason) { setError(reason instanceof Error ? reason.message : t("报价版本保存失败")); }
    finally { setSaving(false); }
  };

  const approve = async () => {
    if (!detail) return;
    setSaving(true); setError("");
    try { setDetail(await decideQuotation(detail.id, "APPROVED", "负责人已在报价工作台复核当前版本")); await load(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : t("报价审批失败")); }
    finally { setSaving(false); }
  };

  const updatePublicStatus = async (status: "CONFIRMED" | "COMPLETED" | "CANCELLED") => {
    if (!publicDetail) return;
    setSaving(true); setError("");
    try {
      setPublicDetail(await updatePublicQuoteDraftStatus(publicDetail.id, status));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("询价单状态更新失败"));
    } finally {
      setSaving(false);
    }
  };

  return <div className="core-workspace">
    <CorePageHeading eyebrow={t("版本化报价")} title={t("报价工作台")} description={t("客户前台提交的是待确认草稿；正式 Quotation 由内部规则计算并绑定人工审批。")} actions={<Button variant="soft" color="gray" onClick={() => void load()}>{t("刷新")}</Button>} />
    <section className="core-metric-grid">
      <Card className="core-summary-card"><Text size="2" color="gray">{t("本月确认订单")}</Text><strong className="core-order-total">{orderAmounts(orderStatistics?.currentMonth.amounts ?? [])}</strong><Text size="1">{t("{count} 笔有效订单", { count: orderStatistics?.currentMonth.orderCount ?? 0 })}</Text></Card>
      <Card className="core-summary-card"><Text size="2" color="gray">{t("今年确认订单")}</Text><strong className="core-order-total">{orderAmounts(orderStatistics?.currentYear.amounts ?? [])}</strong><Text size="1">{t("{count} 笔有效订单", { count: orderStatistics?.currentYear.orderCount ?? 0 })}</Text></Card>
      <Card className="core-summary-card"><Text size="2" color="gray">{t("正式报价")}</Text><strong>{quotes.length}</strong><Text size="1">{t("当前租户权威报价表")}</Text></Card>
      <Card className="core-summary-card"><Text size="2" color="gray">{t("客户待确认草稿")}</Text><strong>{publicDrafts.length}</strong><Text size="1">{t("尚未形成内部正式承诺")}</Text></Card>
      <Card className="core-summary-card"><Text size="2" color="gray">{t("等待人工批准")}</Text><strong>{pending}</strong><Text size="1">{t("发送前必须完成审批")}</Text></Card>
      <Card className="core-summary-card"><Text size="2" color="gray">{t("已批准 / 币种")}</Text><strong>{approved} / {currencies}</strong><Text size="1">{t("不做隐式汇率换算")}</Text></Card>
    </section>
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
    {draftNotice ? <Card className="core-notice"><FileText /><Text size="2">{draftNotice}</Text></Card> : null}
    {statisticsNotice ? <Card className="core-notice"><FileText /><Text size="2">{statisticsNotice}</Text></Card> : null}

    <Tabs.Root defaultValue="official">
      <Tabs.List><Tabs.Trigger value="official">{t("正式报价")} ({quotes.length})</Tabs.Trigger><Tabs.Trigger value="public">{t("客户前台草稿")} ({publicDrafts.length})</Tabs.Trigger></Tabs.List>
      <Tabs.Content value="official"><Card className="core-table-card"><div className="core-table core-quotes-table"><div className="core-table-head"><span>{t("报价编号 / 客户")}</span><span>{t("版本")}</span><span>{t("金额")}</span><span>{t("审批门禁")}</span><span>{t("状态")}</span><span>{t("更新时间")}</span></div>{quotes.map((quote) => <button type="button" className="core-table-row" key={quote.id} onClick={() => void openQuote(quote.id)}><span className="core-name-cell"><span className="core-row-icon"><FileText /></span><span><strong>{quote.customerName}</strong><small>{quote.quotationNumber}</small></span></span><strong>v{quote.currentVersion}</strong><strong>{quote.currency} {quote.totalAmount.toFixed(2)}</strong><span><ShieldCheck />{t("人工")}</span><Badge color={quote.status === "APPROVED" ? "jade" : quote.status === "REJECTED" ? "red" : "amber"}>{t(label(quote.status))}</Badge><span>{coreDate(quote.updatedAt)}</span></button>)}{loading && !quotes.length ? <CoreLoading label={t("正在读取报价版本")} /> : null}{!loading && !quotes.length ? <CoreEmpty title={t("尚无正式报价")} description={t("从询盘工作台人工选择候选并创建报价。")} /> : null}</div></Card></Tabs.Content>
      <Tabs.Content value="public"><Card className="core-notice"><ShoppingCartSimple /><div><Text weight="bold" as="div">{t("客户前台询价")}</Text><Text size="2" color="gray">{t("确认后，访客会在前台个人中心收到更新提醒。")}</Text></div></Card><div className="core-draft-grid">{publicDrafts.map((draft) => <Card className="core-draft-card" key={draft.id} onClick={() => void openPublicDraft(draft.id)}><div className="core-panel-heading"><div><Text size="1" color="gray">{draft.quoteNumber}</Text><Heading size="4">{draft.customerCompany || draft.customerName}</Heading></div><Badge color={draft.status === "COMPLETED" ? "jade" : draft.status === "CONFIRMED" ? "blue" : draft.status === "CANCELLED" ? "gray" : "amber"}>{t(label(draft.status))}</Badge></div><Text size="2" color="gray">{t("联系人")}：{draft.customerName}</Text><strong>{draft.currency} {draft.total.toFixed(2)}</strong><Text size="1" color="gray">{t("提交于 {created} · 有效至 {valid}", { created: coreDate(draft.createdAt), valid: coreDate(draft.validUntil) })}</Text><Button variant="soft">{t("查看详情")}</Button></Card>)}{!loading && !publicDrafts.length ? <CoreEmpty title={t("暂无客户前台草稿")} description={t("客户在店铺提交报价请求后，会进入这里等待人工确认。")} /> : null}</div></Tabs.Content>
    </Tabs.Root>

    <Dialog.Root open={Boolean(detail)} onOpenChange={(open) => { if (!open) setDetail(undefined); }}><Dialog.Content className="core-detail-dialog">{detail ? <OfficialQuoteDetail quote={detail} drafts={drafts} setDrafts={setDrafts} changeReason={changeReason} setChangeReason={setChangeReason} canRevise={canRevise} canApprove={canApprove} saving={saving} onSave={saveRevision} onApprove={approve} onClose={() => setDetail(undefined)} /> : <CoreLoading />}</Dialog.Content></Dialog.Root>
    <Dialog.Root open={Boolean(publicDetail)} onOpenChange={(open) => { if (!open) setPublicDetail(undefined); }}><Dialog.Content className="core-detail-dialog">{publicDetail ? <PublicDraftDetail draft={publicDetail} canManage={canRevise} saving={saving} onStatus={updatePublicStatus} onClose={() => setPublicDetail(undefined)} /> : <CoreLoading />}</Dialog.Content></Dialog.Root>
  </div>;
}

function OfficialQuoteDetail({ quote, drafts, setDrafts, changeReason, setChangeReason, canRevise, canApprove, saving, onSave, onApprove, onClose }: { quote: QuotationRecord; drafts: Record<string, LineDraft>; setDrafts: React.Dispatch<React.SetStateAction<Record<string, LineDraft>>>; changeReason: string; setChangeReason: (value: string) => void; canRevise: boolean; canApprove: boolean; saving: boolean; onSave: () => Promise<void>; onApprove: () => Promise<void>; onClose: () => void }) {
  const { t } = useLocale();
  return <><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("正式报价")} · v{quote.currentVersion}</Text><Dialog.Title>{quote.quotationNumber}</Dialog.Title><Dialog.Description>{quote.currency} {quote.totalAmount.toFixed(2)} · {t(label(quote.status))} · {quote.versionHash.slice(0, 12)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div><Card className="core-notice"><PencilSimple /><Text size="2">{t("编辑会创建新版本，不会覆盖当前版本。")}</Text></Card>
    <div className="core-quote-lines">{quote.items.map((item) => { const draft = drafts[item.id] ?? { quantity: item.quantity, targetMarginRate: item.targetMarginRate ?? .2 }; return <Card key={item.id}><div><Text weight="bold" as="div">{String(item.productSnapshot.name ?? item.productSnapshot.code ?? item.productId)}</Text><Text size="1" color="gray">{String(item.productSnapshot.code ?? item.productId)}</Text></div><label>{t("数量")}<TextField.Root type="number" disabled={!canRevise} value={String(draft.quantity)} onChange={(event) => setDrafts((rows) => ({ ...rows, [item.id]: { ...draft, quantity: Number(event.target.value) } }))} /></label><label>{t("目标毛利 %")}<TextField.Root type="number" disabled={!canRevise} value={String(Math.round(draft.targetMarginRate * 100))} onChange={(event) => setDrafts((rows) => ({ ...rows, [item.id]: { ...draft, targetMarginRate: Number(event.target.value) / 100 } }))} /></label><div><Text weight="bold" as="div">{quote.currency} {item.unitPrice.toFixed(2)}</Text><Text size="1" color="gray">{t("小计")} {item.lineTotal.toFixed(2)}</Text></div></Card>; })}</div>
    {canRevise ? <div className="core-revision-controls"><label>{t("修改原因（写入审计快照）")}<TextArea value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder={t("例如：客户调整首批数量")} /></label><Button disabled={saving} onClick={() => void onSave()}><PencilSimple />{t("保存为 v{version}", { version: quote.currentVersion + 1 })}</Button></div> : <Text size="2" color="gray">{t("当前角色只能查看报价。")}</Text>}
    {quote.approvalStatus === "PENDING" && canApprove ? <Button color="green" disabled={saving} onClick={() => void onApprove()}><CheckCircle />{t("人工确认并批准当前 v{version}", { version: quote.currentVersion })}</Button> : null}
    <Heading size="4">{t("不可变版本历史")}</Heading><div className="core-list">{quote.versions.map((version) => <div className="core-list-row" key={version.versionNumber}><ShieldCheck /><div><Text weight="bold" as="div">v{version.versionNumber} · {version.currency} {version.totalAmount.toFixed(2)}</Text><Text size="1" color="gray">{coreDate(version.createdAt)} · {version.ruleVersion} · {version.contentHash.slice(0, 16)}</Text></div><Badge color={version.approvalStatus === "APPROVED" ? "jade" : "gray"}>{t(label(version.approvalStatus))}</Badge></div>)}</div></>;
}

function PublicDraftDetail({ draft, canManage, saving, onStatus, onClose }: { draft: PublicQuoteDraft; canManage: boolean; saving: boolean; onStatus: (status: "CONFIRMED" | "COMPLETED" | "CANCELLED") => Promise<void>; onClose: () => void }) {
  const { t } = useLocale();
  const [downloading, setDownloading] = useState<"pdf" | "xlsx" | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const download = async (type: "pdf" | "xlsx") => {
    setDownloading(type);
    setDownloadError("");
    try {
      await downloadPublicQuoteDraftDocument(draft.id, draft.quoteNumber, type);
    } catch (reason) {
      setDownloadError(reason instanceof Error ? reason.message : t("报价文件下载失败"));
    } finally {
      setDownloading(null);
    }
  };
  return <><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("客户前台询价")}</Text><Dialog.Title>{draft.quoteNumber}</Dialog.Title><Dialog.Description>{draft.customerCompany || draft.customerName} · {coreDate(draft.createdAt)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div><div className="core-dialog-actions"><Badge color={draft.status === "COMPLETED" ? "jade" : draft.status === "CONFIRMED" ? "blue" : "amber"}>{t(label(draft.status))}</Badge><Button variant="soft" color="gray" loading={downloading === "pdf"} onClick={() => void download("pdf")}><FilePdf />{t("下载 PDF")}</Button><Button loading={downloading === "xlsx"} onClick={() => void download("xlsx")}><FileXls />{t("下载 Excel")}</Button></div>{canManage && draft.status === "PENDING_CONFIRMATION" ? <div className="core-dialog-actions"><Button color="green" loading={saving} onClick={() => void onStatus("CONFIRMED")}><CheckCircle />{t("确认并下发给访客")}</Button><Button variant="soft" color="red" disabled={saving} onClick={() => void onStatus("CANCELLED")}>{t("取消询价")}</Button></div> : null}{canManage && draft.status === "CONFIRMED" ? <div className="core-dialog-actions"><Button color="green" loading={saving} onClick={() => void onStatus("COMPLETED")}><CheckCircle />{t("标记为已成交")}</Button><Button variant="soft" color="red" disabled={saving} onClick={() => void onStatus("CANCELLED")}>{t("取消询价")}</Button></div> : null}{downloadError ? <Text size="2" color="red">{downloadError}</Text> : null}<div className="core-master-grid"><Card><Text size="1" color="gray">{t("联系人")}</Text><Heading size="3">{draft.customerName}</Heading><Text size="1">{draft.customerEmail ?? draft.customerPhone ?? "—"}</Text></Card><Card><Text size="1" color="gray">{t("询价合计")}</Text><Heading size="3">{draft.currency} {draft.total.toFixed(2)}</Heading></Card><Card><Text size="1" color="gray">{t("有效至")}</Text><Heading size="3">{coreDate(draft.validUntil)}</Heading></Card><Card><Text size="1" color="gray">{t("更新时间")}</Text><Heading size="3">{coreDate(draft.updatedAt)}</Heading></Card></div><Heading size="4">{t("客户选择的商品")}</Heading><div className="core-list">{draft.items.map((item) => <div className="core-list-row" key={item.id}><ShoppingCartSimple /><div><Text weight="bold" as="div">{item.name}</Text><Text size="1" color="gray">{item.skuCode}</Text></div><Text size="2">{item.quantity} {item.unitCode}</Text><Text weight="bold">{item.currency} {item.lineTotal.toFixed(2)}</Text></div>)}</div>{draft.notes ? <Card><Text size="1" color="gray">{t("客户备注")}</Text><Text as="div">{draft.notes}</Text></Card> : null}</>;
}
