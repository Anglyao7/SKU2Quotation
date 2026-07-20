import { Badge, Button, Card, Heading, Progress, Text, TextField } from "@radix-ui/themes";
import { ArrowRight, Check, Image, MagnifyingGlass, ShieldCheck, Sparkle, UploadSimple, Warning } from "@phosphor-icons/react";
import { useMemo, useState } from "react";
import { createCustomer, createInquiry, createQuotation, decideQuotation, getInquiry, getProduct, matchInquiry, searchImage, selectInquiryCandidate } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreError, CorePageHeading, percent } from "../CoreUi";
import type { InquiryMatch, InquiryRecord, ProductDetail, QuotationRecord } from "../types";

const statusLabel: Record<string, string> = { NEW: "新建", MATCHING: "匹配中", NEEDS_SELECTION: "待人工选择", READY_FOR_QUOTE: "可生成报价", SELECTED: "已选择", DRAFT: "草稿", CALCULATED: "待人工批准", NEEDS_APPROVAL: "规则审批", PENDING: "待批准", APPROVED: "已批准", SOURCE: "仅来源图", NONE: "暂无图片" };
const label = (value?: string) => statusLabel[value ?? ""] ?? value ?? "—";

export function InquiryPage() {
  const { hasPermission } = useCoreAuth();
  const canManageInquiry = hasPermission("inquiry.manage");
  const canCreateInquiry = hasPermission("customer.manage") && canManageInquiry;
  const canSearchImage = hasPermission("product.view") && canCreateInquiry;
  const canCreateQuote = hasPermission("quotation.create");
  const canApprove = hasPermission("quotation.approve");
  const [customer, setCustomer] = useState("Northstar Trading");
  const [requirement, setRequirement] = useState("SKU-18211");
  const [quantity, setQuantity] = useState(100);
  const [currency, setCurrency] = useState("CNY");
  const [margin, setMargin] = useState(20);
  const [inquiry, setInquiry] = useState<InquiryRecord>();
  const [matches, setMatches] = useState<Record<string, InquiryMatch[]>>({});
  const [products, setProducts] = useState<Record<string, ProductDetail>>({});
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [activeItem, setActiveItem] = useState("");
  const [imageSearchId, setImageSearchId] = useState<string>();
  const [imageStatus, setImageStatus] = useState("");
  const [quote, setQuote] = useState<QuotationRecord>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const candidates = matches[activeItem] ?? [];
  const selectedMatch = candidates.find((row) => row.id === selected[activeItem]);
  const selectedProduct = selectedMatch ? products[selectedMatch.productId] : undefined;
  const activeRequirement = inquiry?.items.find((row) => row.id === activeItem);
  const previewUnit = useMemo(() => selectedProduct?.price === undefined ? undefined : selectedProduct.price / (1 - margin / 100), [margin, selectedProduct]);

  const start = async () => {
    setBusy(true); setError(""); setQuote(undefined);
    try {
      const customerId = await createCustomer(customer.trim(), currency);
      const nextInquiry = await createInquiry({ customerId, currency, items: [{ requirement: requirement.trim(), quantity, unitCode: "PCS", imageSearchId }] });
      setInquiry(nextInquiry); setActiveItem(nextInquiry.items[0]?.id ?? ""); setSelected({});
      const nextMatches = await matchInquiry(nextInquiry.id); setMatches(nextMatches);
      const ids = [...new Set(Object.values(nextMatches).flat().map((row) => row.productId))];
      const details = await Promise.all(ids.map((id) => getProduct(id).catch(() => undefined)));
      setProducts(Object.fromEntries(details.filter((row): row is ProductDetail => Boolean(row)).map((row) => [row.id, row])));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "询盘创建失败"); }
    finally { setBusy(false); }
  };

  const uploadImage = async (file?: File) => {
    if (!file) return;
    setBusy(true); setError("");
    try { const result = await searchImage(file); setImageSearchId(result.id); setImageStatus(`${result.status} · ${result.results.length} 个视觉候选`); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "图片检索失败"); }
    finally { setBusy(false); }
  };

  const choose = async (row: InquiryMatch) => {
    setBusy(true); setError("");
    try { await selectInquiryCandidate(row.inquiryItemId, row.id); setSelected((current) => ({ ...current, [row.inquiryItemId]: row.id })); if (inquiry) setInquiry(await getInquiry(inquiry.id)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "候选选择失败"); }
    finally { setBusy(false); }
  };

  const buildQuote = async () => {
    if (!inquiry) return;
    setBusy(true); setError("");
    try { setQuote(await createQuotation(inquiry.id, margin / 100)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "报价创建失败"); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    if (!quote) return;
    setBusy(true); setError("");
    try { setQuote(await decideQuotation(quote.id, "APPROVED", "负责人已复核客户、产品来源、价格与毛利")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "报价审批失败"); }
    finally { setBusy(false); }
  };

  if (!inquiry) return <div className="core-workspace">
    <CorePageHeading eyebrow="询盘 → 匹配 → 报价" title="创建真实询盘闭环" description="AI 负责召回与解释；候选选择、定价和对客承诺始终由授权成员确认。" />
    {error ? <CoreError message={error} /> : null}
    <div className="core-inquiry-launch">
      <Card className="core-launch-copy"><Sparkle size={32} /><Heading size="6">从自然语言需求开始</Heading><Text size="3" color="gray">系统把需求保存为可审计询盘，关联版本化产品候选，再交给人工选中后生成确定性报价。</Text><div className="core-flow-steps"><span>01 保存原始需求</span><span>02 召回可信产品</span><span>03 人工选择</span><span>04 规则定价与审批</span></div></Card>
      <Card className="core-inquiry-form"><label>客户公司<TextField.Root value={customer} onChange={(event) => setCustomer(event.target.value)} /></label><label>产品需求<TextField.Root value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="输入型号、用途或关键参数" /></label><div className="core-form-split"><label>数量<TextField.Root type="number" min="1" value={String(quantity)} onChange={(event) => setQuantity(Number(event.target.value))} /></label><label>币种<select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option></select></label></div><label className="core-upload-field"><UploadSimple /><span>{imageStatus || "可选：上传产品图片辅助检索"}</span><input type="file" accept="image/*" disabled={!canSearchImage} onChange={(event) => void uploadImage(event.target.files?.[0])} /></label><Button size="3" disabled={!canCreateInquiry || busy || !customer.trim() || !requirement.trim() || quantity <= 0} onClick={() => void start()}>保存询盘并开始匹配<ArrowRight /></Button>{!canCreateInquiry ? <Text size="1" color="gray">创建询盘需要 customer.manage 与 inquiry.manage；报价权限不会替代询盘权限。</Text> : null}</Card>
    </div>
  </div>;

  return <div className="core-workspace">
    <CorePageHeading eyebrow={`${inquiry.inquiryNumber} · ${label(inquiry.status)}`} title="AI 询盘工作台" description="每个匹配结果绑定产品版本、评分理由与来源证据。" actions={<Button variant="soft" color="gray" disabled={!canCreateInquiry} onClick={() => { setInquiry(undefined); setMatches({}); setQuote(undefined); }}>新建询盘</Button>} />
    {error ? <CoreError message={error} /> : null}
    <div className="core-inquiry-workbench">
      <Card className="core-requirement-pane"><Text size="1" color="gray">客户需求</Text><Heading size="4">{customer}</Heading><div className="core-review-rows">{inquiry.items.map((row) => <button type="button" className={row.id === activeItem ? "active" : ""} key={row.id} onClick={() => setActiveItem(row.id)}><span className="core-line-number">{String(row.lineNumber).padStart(2, "0")}</span><span><strong>{row.rawRequirement}</strong><small>{row.quantity} {row.unitCode} · {label(row.status)}</small></span>{row.status === "SELECTED" ? <Check /> : <Warning />}</button>)}</div></Card>

      <Card className="core-candidate-pane"><div className="core-panel-heading"><div><Text size="1" color="gray">版本化候选</Text><Heading size="4">候选产品</Heading></div><Badge color="gray">{candidates.length} 个结果</Badge></div><div className="core-readonly-search"><MagnifyingGlass />{activeRequirement?.rawRequirement}</div>
        <div className="core-candidate-list">{candidates.map((row) => { const product = products[row.productId]; const isSelected = selected[activeItem] === row.id; return <Card className={isSelected ? "core-candidate-card selected" : "core-candidate-card"} key={row.id}><div className="core-candidate-image"><Image size={30} /><Badge color={product?.imageStatus === "APPROVED" ? "jade" : "gray"}>{label(product?.imageStatus)}</Badge></div><div className="core-candidate-copy"><div className="core-panel-heading"><div><Heading size="3">{product?.name ?? row.productId}</Heading><Text size="1" color="gray">{product?.productCode ?? "产品"} · v{row.productVersion}</Text></div><strong className="core-score">{percent(row.totalScore)}</strong></div><div className="core-chip-row">{row.reasons.map((reason) => <Badge color="jade" key={reason}><Check />{reason}</Badge>)}</div>{row.gaps.length ? <Text size="1" color="orange"><Warning />{row.gaps.join("；")}</Text> : null}<div className="core-candidate-foot"><Text size="2">{product?.price === undefined ? "成本权限受限" : `${product.currency ?? ""} ${product.price.toFixed(2)} · MOQ ${product.moq ?? "—"}`}</Text><Button size="1" disabled={busy || !canManageInquiry || isSelected} onClick={() => void choose(row)}>{isSelected ? "已人工选择" : "选择此候选"}</Button></div></div></Card>; })}{!candidates.length ? <Card className="core-state"><Sparkle size={26} /><Text weight="bold">暂无可靠候选</Text><Text size="2" color="gray">系统不会伪造高分结果，请补充产品主数据或转人工寻源。</Text></Card> : null}</div>
      </Card>

      <Card className="core-quote-pane"><div className="core-panel-heading"><div><Text size="1" color="gray">人工门禁报价</Text><Heading size="4">报价版本</Heading></div><Badge color={quote?.approvalStatus === "APPROVED" ? "jade" : "amber"}>{quote ? label(quote.approvalStatus) : "未创建"}</Badge></div>
        {quote ? <QuoteResult quote={quote} busy={busy} canApprove={canApprove} onApprove={approve} /> : selectedProduct ? <><div className="core-selected-product"><Image /><div><Text weight="bold" as="div">{selectedProduct.name}</Text><Text size="1" color="gray">{selectedProduct.productCode}</Text></div></div><div className="core-quote-form"><label>报价数量<TextField.Root value={String(activeRequirement?.quantity ?? 0)} readOnly /></label><label>采购单价<TextField.Root value={selectedProduct.price?.toFixed(2) ?? "权限受限"} readOnly /></label><label>目标毛利率<TextField.Root type="number" min="1" max="80" value={String(margin)} onChange={(event) => setMargin(Number(event.target.value))} /></label><label>预估销售单价<TextField.Root value={previewUnit?.toFixed(2) ?? "—"} readOnly /></label></div><Card className="core-notice"><Sparkle /><div><Text weight="bold" as="div">确定性规则 {margin < 15 ? "将触发审批红线" : "输入完整"}</Text><Text size="1" color="gray">最终金额仅由后端 Decimal 规则引擎生成。</Text></div></Card><Button disabled={busy || !canCreateQuote || inquiry.status !== "READY_FOR_QUOTE"} onClick={() => void buildQuote()}>创建不可变报价 V1<ArrowRight /></Button></> : <div className="core-state"><Image size={28} /><Text weight="bold">等待人工选择</Text><Text size="2" color="gray">AI 候选不会自动进入报价。</Text></div>}
      </Card>
    </div>
  </div>;
}

function QuoteResult({ quote, busy, canApprove, onApprove }: { quote: QuotationRecord; busy: boolean; canApprove: boolean; onApprove: () => Promise<void> }) {
  const line = quote.items[0];
  return <div className="core-quote-result"><div className="core-selected-product"><Check /><div><Text weight="bold" as="div">{String(line?.productSnapshot.name ?? "报价行")}</Text><Text size="1" color="gray">{quote.quotationNumber} · v{quote.currentVersion}</Text></div></div><Card className="core-calculation"><div><span>客户单价</span><b>{quote.currency} {line?.unitPrice.toFixed(2)}</b></div><div><span>数量</span><b>{line?.quantity} {line?.unitCode}</b></div><hr /><div><span>报价总额</span><strong>{quote.currency} {quote.totalAmount.toFixed(2)}</strong></div><small>版本快照 {quote.versionHash.slice(0, 14)}…</small></Card><Card className="core-notice"><ShieldCheck /><div><Text weight="bold" as="div">审批状态：{label(quote.approvalStatus)}</Text><Text size="1" color="gray">未批准版本不能形成外部承诺或发送。</Text></div></Card>{canApprove ? <Button disabled={busy || quote.approvalStatus !== "PENDING"} onClick={() => void onApprove()}>{quote.approvalStatus === "APPROVED" ? "已人工批准" : "人工批准此版本"}<ArrowRight /></Button> : null}</div>;
}
