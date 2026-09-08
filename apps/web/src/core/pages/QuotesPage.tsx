import { Badge, Button, Card, Dialog, Heading, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { CaretLeft, CaretRight, MagnifyingGlass, Plus, CheckCircle, FileText, PencilSimple, ShieldCheck, ShoppingCartSimple, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { CoreApiError, decideQuotation, getPublicQuoteDraft, getQuotation, getStorefrontOrderStatistics, listPublicQuoteDrafts, listQuotations, reviseQuotation, updatePublicQuoteDraftStatus } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { PublicQuoteDraft, PublicQuoteDraftSummary, QuotationRecord, QuotationSummary, StorefrontOrderCurrencyStatistics, StorefrontOrderStatistics } from "../types";
import { Link, useSearchParams } from "react-router-dom";
import { ToastNotice } from "../ToastContext";
import { quoteDocumentHref } from "../quoteDocumentNavigation";
import { filterInquiries, paginateInquiries } from "../inquiryFilters";

const statusLabel: Record<string, string> = { DRAFT: "草稿", SUBMITTED: "客户已提交", PENDING_REVIEW: "待人工确认", PENDING_CONFIRMATION: "客户提交，待确认", CONFIRMED: "已确认并下发", COMPLETED: "已成交", CANCELLED: "已取消", CALCULATED: "待人工批准", NEEDS_APPROVAL: "规则审批", PENDING: "待批准", APPROVED: "已批准", SENT: "已发送", ACCEPTED: "已接受", REJECTED: "已拒绝", EXPIRED: "已过期", NOT_REQUIRED: "无需审批" };
const label = (value: string) => statusLabel[value] ?? value;
type LineDraft = { quantity: number; targetMarginRate: number };

function orderAmounts(amounts: StorefrontOrderCurrencyStatistics[]) {
  if (!amounts.length) return "—";
  return amounts.map((amount) => `${amount.currency} ${amount.totalAmount.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join(" · ");
}

function countryFlag(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(normalized)) return "🌐";
  return String.fromCodePoint(
    ...[...normalized].map((character) => 127397 + character.charCodeAt(0)),
  );
}

function countryLabel(countryCode?: string) {
  const normalized = String(countryCode || "").trim().toUpperCase();
  return normalized ? `${countryFlag(normalized)} ${normalized}` : "—";
}

export function QuotesPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canRevise = hasPermission("quotation.create");
  const canApprove = hasPermission("quotation.approve");
  const canViewHistory = hasPermission("quotation.view");
  const canCreateInquiry = hasPermission("inquiry.manage") && hasPermission("customer.manage");
  const [params, setParams] = useSearchParams();
  const tab = canViewHistory && params.get("tab") === "history" ? "history" : "public";
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState(params.get("status") || "");
  const [fromDate, setFromDate] = useState("");
  const [toDate, setToDate] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
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
    const [quotationResult, draftResult, statisticsResult] = await Promise.allSettled([canViewHistory ? listQuotations() : Promise.resolve([]), listPublicQuoteDrafts(), canViewHistory ? getStorefrontOrderStatistics() : Promise.resolve(undefined)]);
    if (quotationResult.status === "fulfilled") setQuotes(quotationResult.value);
    else setError(quotationResult.reason instanceof Error ? quotationResult.reason.message : t("正式报价加载失败"));
    if (draftResult.status === "fulfilled") setPublicDrafts(draftResult.value);
    else if (draftResult.reason instanceof CoreApiError && draftResult.reason.status === 404) { setPublicDrafts([]); setDraftNotice(t("客户询价暂时无法读取，请重试。")); }
    else setDraftNotice(draftResult.reason instanceof Error ? t("客户前台草稿暂不可用：{message}", { message: draftResult.reason.message }) : t("客户前台草稿暂不可用"));
    if (statisticsResult.status === "fulfilled") setOrderStatistics(statisticsResult.value);
    else setStatisticsNotice(t("订单统计暂时无法读取，订单记录不受影响。"));
    setLoading(false);
  }, [t, canViewHistory]);
  useEffect(() => { void load(); }, [load]);

  const pending = publicDrafts.filter((row) => row.status === "PENDING_CONFIRMATION").length;
  const filteredDrafts = useMemo(() => filterInquiries(publicDrafts, { query, status: statusFilter, from: fromDate, to: toDate }), [publicDrafts, query, statusFilter, fromDate, toDate]);
  const { pages, currentPage, pageRows } = paginateInquiries(filteredDrafts, page, pageSize);
  const filterStatus = (value: string) => {
    setStatusFilter(value); setPage(1);
    const next = new URLSearchParams(params);
    if (value) next.set("status", value); else next.delete("status");
    next.delete("tab");
    setParams(next, { replace: true });
  };
  useEffect(() => { setStatusFilter(params.get("status") || ""); setPage(1); }, [params]);


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
      const updated = await updatePublicQuoteDraftStatus(publicDetail.id, status);
      setPublicDetail(updated);
      window.dispatchEvent(new Event("atc:public-quote-changed"));
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("询价单状态更新失败"));
    } finally {
      setSaving(false);
    }
  };

  return <div className="core-workspace admin-quotes-page">
    <CorePageHeading eyebrow={t("销售")} title={t("客户询价")} actions={<>
      {canCreateInquiry ? <Button asChild><Link to="/console/inquiries"><Plus />{t("手动新建询价")}</Link></Button> : null}
      <Button variant="soft" color="gray" loading={loading} onClick={() => void load()}>{t("刷新")}</Button>
    </>} />
    <section className="admin-metric-strip">
      <button type="button" onClick={() => filterStatus("PENDING_CONFIRMATION")}><span>{t("待处理")}</span><strong>{pending}</strong></button>
      <button type="button" onClick={() => filterStatus("CONFIRMED")}><span>{t("已确认并下发")}</span><strong>{publicDrafts.filter((row) => row.status === "CONFIRMED").length}</strong></button>
      <div><span>{t("本月确认订单")}</span><strong>{orderAmounts(orderStatistics?.currentMonth.amounts ?? [])}</strong></div>
      <div><span>{t("今年确认订单")}</span><strong>{orderAmounts(orderStatistics?.currentYear.amounts ?? [])}</strong></div>
    </section>
    {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
    {draftNotice ? <ToastNotice kind="error" message={draftNotice} /> : null}
    {statisticsNotice ? <ToastNotice kind="error" message={statisticsNotice} /> : null}
    <Tabs.Root value={tab} onValueChange={(value) => { const next = new URLSearchParams(params); if (value === "history") next.set("tab", value); else next.delete("tab"); setParams(next, { replace: true }); }}>
      <Tabs.List><Tabs.Trigger value="public">{t("客户询价")} ({publicDrafts.length})</Tabs.Trigger>{canViewHistory ? <Tabs.Trigger value="history">{t("历史报价")} ({quotes.length})</Tabs.Trigger> : null}</Tabs.List>
      <Tabs.Content value="public">
        <div className="admin-list-filters">
          <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder={t("搜索单号、客户或国家")} aria-label={t("搜索单号、客户或国家")}><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
          <select aria-label={t("状态")} value={statusFilter} onChange={(event) => filterStatus(event.target.value)}>
            <option value="">{t("全部状态")}</option>
            {["PENDING_CONFIRMATION", "CONFIRMED", "COMPLETED", "CANCELLED", "EXPIRED"].map((status) => <option key={status} value={status}>{t(status === "PENDING_CONFIRMATION" ? "待处理" : label(status))}</option>)}
          </select>
          <label>{t("开始日期")}<input type="date" value={fromDate} onChange={(event) => { setFromDate(event.target.value); setPage(1); }} /></label>
          <label>{t("结束日期")}<input type="date" value={toDate} min={fromDate || undefined} onChange={(event) => { setToDate(event.target.value); setPage(1); }} /></label>
          <Button variant="ghost" color="gray" onClick={() => { setQuery(""); setFromDate(""); setToDate(""); filterStatus(""); }}>{t("清除筛选")}</Button>
        </div>
        {publicDrafts.length >= 500 ? <Text size="1" color="gray">{t("当前展示最近 500 条询价")}</Text> : null}
        <div className="admin-table-wrap">
          <table className="admin-data-table admin-inquiry-table">
            <thead><tr><th>{t("报价编号 / 客户")}</th><th>{t("客户国家")}</th><th>{t("金额")}</th><th>{t("状态")}</th><th>{t("提交时间")}</th><th>{t("操作")}</th></tr></thead>
            <tbody>{pageRows.map((row) => <tr key={row.id}>
              <td><strong>{row.customerCompany || row.customerName}</strong><small>{row.quoteNumber}</small></td>
              <td>{countryLabel(row.visitorCountryCode)}</td>
              <td className="core-tabular">{row.currency} {row.total.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
              <td><Badge color={row.status === "COMPLETED" ? "jade" : row.status === "CONFIRMED" ? "blue" : row.status === "PENDING_CONFIRMATION" ? "amber" : "gray"}>{t(row.status === "PENDING_CONFIRMATION" ? "待处理" : label(row.status))}</Badge>{row.readOnly ? <small>{t("只读")}</small> : null}</td>
              <td>{coreDate(row.createdAt)}</td>
              <td><div className="admin-row-actions">
                {canRevise && !row.readOnly && ["PENDING_CONFIRMATION", "CONFIRMED"].includes(row.status) ? <Button asChild size="2"><Link to={quoteDocumentHref(row.id, "quotation")}>{t("前往多证工作台")}</Link></Button> : null}
                <Button size="2" variant="ghost" onClick={() => void openPublicDraft(row.id)}>{t("查看详情")}</Button>
              </div></td>
            </tr>)}</tbody>
          </table>
          {loading && !publicDrafts.length ? <CoreLoading /> : !pageRows.length ? <CoreEmpty title={t("暂无询价")} description={t("请调整筛选条件。")} /> : null}
        </div>
        <div className="admin-pagination">
          <Text size="2">{t("共 {count} 条", { count: filteredDrafts.length })}</Text>
          <label>{t("每页显示")}<select value={pageSize} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1); }}>{[20, 50, 100].map((size) => <option key={size} value={size}>{size}</option>)}</select></label>
          <Button variant="soft" color="gray" disabled={currentPage <= 1} onClick={() => setPage(currentPage - 1)}><CaretLeft />{t("上一页")}</Button>
          <Text size="2">{currentPage} / {pages}</Text>
          <Button variant="soft" color="gray" disabled={currentPage >= pages} onClick={() => setPage(currentPage + 1)}>{t("下一页")}<CaretRight /></Button>
        </div>
      </Tabs.Content>
      <Tabs.Content value="history">
        <div className="admin-table-wrap"><table className="admin-data-table"><thead><tr><th>{t("报价编号 / 客户")}</th><th>{t("金额")}</th><th>{t("状态")}</th><th>{t("更新时间")}</th><th>{t("操作")}</th></tr></thead>
          <tbody>{quotes.map((quote) => <tr key={quote.id}><td><strong>{quote.customerName}</strong><small>{quote.quotationNumber}</small></td><td>{quote.currency} {quote.totalAmount.toFixed(2)}</td><td><Badge>{t(label(quote.status))}</Badge></td><td>{coreDate(quote.updatedAt)}</td><td><Button variant="ghost" onClick={() => void openQuote(quote.id)}>{t("查看详情")}</Button></td></tr>)}</tbody>
        </table>{!loading && !quotes.length ? <CoreEmpty title={t("尚无正式报价")} description={t("暂无记录")} /> : null}</div>
      </Tabs.Content>
    </Tabs.Root>

    <Dialog.Root open={Boolean(detail)} onOpenChange={(open) => { if (!open) setDetail(undefined); }}><Dialog.Content className="core-detail-dialog">{detail ? <OfficialQuoteDetail quote={detail} drafts={drafts} setDrafts={setDrafts} changeReason={changeReason} setChangeReason={setChangeReason} canRevise={canRevise && !detail.readOnly} canApprove={canApprove && !detail.readOnly} saving={saving} onSave={saveRevision} onApprove={approve} onClose={() => setDetail(undefined)} /> : <CoreLoading />}</Dialog.Content></Dialog.Root>
    <Dialog.Root open={Boolean(publicDetail)} onOpenChange={(open) => { if (!open) setPublicDetail(undefined); }}><Dialog.Content className="core-detail-dialog">{publicDetail ? <PublicDraftDetail draft={publicDetail} canManage={canRevise && !publicDetail.readOnly} saving={saving} onStatus={updatePublicStatus} onClose={() => setPublicDetail(undefined)} /> : <CoreLoading />}</Dialog.Content></Dialog.Root>
  </div>;
}

function OfficialQuoteDetail({ quote, drafts, setDrafts, changeReason, setChangeReason, canRevise, canApprove, saving, onSave, onApprove, onClose }: { quote: QuotationRecord; drafts: Record<string, LineDraft>; setDrafts: React.Dispatch<React.SetStateAction<Record<string, LineDraft>>>; changeReason: string; setChangeReason: (value: string) => void; canRevise: boolean; canApprove: boolean; saving: boolean; onSave: () => Promise<void>; onApprove: () => Promise<void>; onClose: () => void }) {
  const { t } = useLocale();
  return <><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("正式报价")} · v{quote.currentVersion}</Text><Dialog.Title>{quote.quotationNumber}</Dialog.Title><Dialog.Description>{quote.currency} {quote.totalAmount.toFixed(2)} · {t(label(quote.status))}</Dialog.Description></div><div className="core-dialog-actions">{quote.readOnly ? <Badge color="gray">{t("主账号只读")}</Badge> : null}<Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div></div><Card className="core-notice"><PencilSimple /><Text size="2">{t(quote.readOnly ? "该报价由子账号负责，主账号仅可查看。" : "编辑会创建新版本，不会覆盖当前版本。")}</Text></Card>
    <div className="core-quote-lines">{quote.items.map((item) => { const draft = drafts[item.id] ?? { quantity: item.quantity, targetMarginRate: item.targetMarginRate ?? .2 }; return <Card key={item.id}><div><Text weight="bold" as="div">{String(item.productSnapshot.name ?? item.productSnapshot.code ?? item.productId)}</Text><Text size="1" color="gray">{String(item.productSnapshot.code ?? item.productId)}</Text></div><label>{t("数量")}<TextField.Root type="number" disabled={!canRevise} value={String(draft.quantity)} onChange={(event) => setDrafts((rows) => ({ ...rows, [item.id]: { ...draft, quantity: Number(event.target.value) } }))} /></label><label>{t("目标毛利 %")}<TextField.Root type="number" disabled={!canRevise} value={String(Math.round(draft.targetMarginRate * 100))} onChange={(event) => setDrafts((rows) => ({ ...rows, [item.id]: { ...draft, targetMarginRate: Number(event.target.value) / 100 } }))} /></label><div><Text weight="bold" as="div">{quote.currency} {item.unitPrice.toFixed(2)}</Text><Text size="1" color="gray">{t("小计")} {item.lineTotal.toFixed(2)}</Text></div></Card>; })}</div>
    {canRevise ? <div className="core-revision-controls"><label>{t("修改原因")}<TextArea value={changeReason} onChange={(event) => setChangeReason(event.target.value)} placeholder={t("例如：客户调整首批数量")} /></label><Button disabled={saving} onClick={() => void onSave()}><PencilSimple />{t("保存为 v{version}", { version: quote.currentVersion + 1 })}</Button></div> : <Text size="2" color="gray">{t("当前角色只能查看报价。")}</Text>}
    {quote.approvalStatus === "PENDING" && canApprove ? <Button color="green" disabled={saving} onClick={() => void onApprove()}><CheckCircle />{t("人工确认并批准当前 v{version}", { version: quote.currentVersion })}</Button> : null}
    <Heading size="4">{t("修改记录")}</Heading><div className="core-list">{quote.versions.map((version) => <div className="core-list-row" key={version.versionNumber}><ShieldCheck /><div><Text weight="bold" as="div">v{version.versionNumber} · {version.currency} {version.totalAmount.toFixed(2)}</Text><Text size="1" color="gray">{coreDate(version.createdAt)} · </Text></div><Badge color={version.approvalStatus === "APPROVED" ? "jade" : "gray"}>{t(label(version.approvalStatus))}</Badge></div>)}</div></>;
}

function PublicDraftDetail({ draft, canManage, saving, onStatus, onClose }: { draft: PublicQuoteDraft; canManage: boolean; saving: boolean; onStatus: (status: "CONFIRMED" | "COMPLETED" | "CANCELLED") => Promise<void>; onClose: () => void }) {
  const { t } = useLocale();
  return <><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("客户前台询价")}</Text><Dialog.Title>{draft.quoteNumber}</Dialog.Title><Dialog.Description>{draft.customerCompany || draft.customerName} · {coreDate(draft.createdAt)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label={t("关闭")}><X /></Button></div><div className="core-dialog-actions"><Badge color={draft.status === "COMPLETED" ? "jade" : draft.status === "CONFIRMED" ? "blue" : "amber"}>{t(label(draft.status))}</Badge>{draft.readOnly ? <Text size="1" color="gray">{t("子账号询价只读")}</Text> : null}{canManage ? <><Button asChild><Link to={quoteDocumentHref(draft.id, "quotation")}><FileText />{t("前往多证工作台")}</Link></Button><Button asChild variant="soft"><Link to={quoteDocumentHref(draft.id, "proforma")}><FileText />{t("形式发票")}（PI）</Link></Button></> : null}</div>{canManage && draft.status === "PENDING_CONFIRMATION" ? <div className="core-dialog-actions"><Text size="1" color="gray">{t("请先在报价工作台完成报价单，再确认下发。")}</Text><Button variant="soft" color="red" disabled={saving} onClick={() => void onStatus("CANCELLED")}>{t("取消询价")}</Button></div> : null}{canManage && draft.status === "CONFIRMED" ? <div className="core-dialog-actions"><Button color="green" loading={saving} onClick={() => void onStatus("COMPLETED")}><CheckCircle />{t("标记为已成交")}</Button><Button variant="soft" color="red" disabled={saving} onClick={() => void onStatus("CANCELLED")}>{t("取消询价")}</Button></div> : null}<div className="core-master-grid"><Card><Text size="1" color="gray">{t("联系人")}</Text><Heading size="3">{draft.customerName}</Heading><Text size="1">{draft.customerCompany || "—"}</Text><Text size="1">{draft.customerEmail || "—"}</Text><Text size="1">{draft.customerPhone || "—"}</Text></Card><Card><Text size="1" color="gray">{t("客户国家")}</Text><Heading size="3">{countryLabel(draft.visitorCountryCode)}</Heading></Card><Card><Text size="1" color="gray">{t("询价合计")}</Text><Heading size="3">{draft.currency} {draft.total.toFixed(2)}</Heading></Card><Card><Text size="1" color="gray">{t("有效至")}</Text><Heading size="3">{coreDate(draft.validUntil)}</Heading></Card><Card><Text size="1" color="gray">{t("更新时间")}</Text><Heading size="3">{coreDate(draft.updatedAt)}</Heading></Card></div>{draft.notes ? <Card><Text size="1" color="gray">{t("整单备注")}</Text><Text as="div">{draft.notes}</Text></Card> : null}<Heading size="4">{t("客户选择的商品")}</Heading><div className="core-list">{draft.items.map((item) => <div className="core-list-row" key={item.id}><ShoppingCartSimple /><div><Text weight="bold" as="div">{item.name}</Text><Text size="1" color="gray">{item.skuCode}</Text>{item.customerNote ? <Text size="1" color="amber" as="div">{t("客户商品备注")}：{item.customerNote}</Text> : null}</div><Text size="2">{item.quantity} {item.unitCode}</Text><Text size="1" color="gray">{t("单价")} {item.currency} {item.unitPrice.toFixed(2)}</Text><Text weight="bold">{item.currency} {item.lineTotal.toFixed(2)}</Text></div>)}</div></>;
}
