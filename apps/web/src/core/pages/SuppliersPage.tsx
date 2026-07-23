import { Badge, Button, Card, Dialog, Heading, Progress, Tabs, Text, TextField } from "@radix-ui/themes";
import { ArrowRight, Buildings, FileArrowUp, FileText, ShieldCheck, Warning, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { createImport, createSupplierProfile, detectFile, getSupplierProfile, listImports, listSupplierProfiles } from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import type { FileDetection, ImportJob, SupplierProfile, SupplierProfileDetail } from "../types";

const stateLabel: Record<string, string> = {
  ACTIVE: "已启用", INACTIVE: "已停用", HEALTHY: "健康", ATTENTION: "需关注", RISK: "风险",
  VALID: "有效", EXPIRING: "即将过期", EXPIRED: "已过期", UNKNOWN: "未知",
  scanning: "安全扫描", parsing: "解析中", needs_review: "待复核", published: "已发布", failed: "失败",
};

function label(value?: string) { return stateLabel[value ?? ""] ?? stateLabel[value?.toUpperCase() ?? ""] ?? value ?? "—"; }

export function SuppliersPage() {
  const { hasAnyPermission } = useCoreAuth();
  const canViewSuppliers = hasAnyPermission("supplier.view", "supplier.manage");
  const canManageSuppliers = hasAnyPermission("supplier.manage");
  const canImport = hasAnyPermission("product.import");
  const inputRef = useRef<HTMLInputElement>(null);
  const [suppliers, setSuppliers] = useState<SupplierProfile[]>([]);
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [detail, setDetail] = useState<SupplierProfileDetail>();
  const [detection, setDetection] = useState<FileDetection>();
  const [pendingFile, setPendingFile] = useState<File>();
  const [selectedSupplierId, setSelectedSupplierId] = useState("");
  const [creatingSupplier, setCreatingSupplier] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [nextSuppliers, nextJobs] = await Promise.all([
        canViewSuppliers || canImport ? listSupplierProfiles() : Promise.resolve([]),
        canImport ? listImports() : Promise.resolve([]),
      ]);
      setSuppliers(nextSuppliers); setJobs(nextJobs);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "供应网络加载失败"); }
    finally { setLoading(false); }
  }, [canImport, canViewSuppliers]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (!suppliers.some((supplier) => supplier.id === selectedSupplierId)) {
      setSelectedSupplierId(suppliers[0]?.id ?? "");
    }
  }, [selectedSupplierId, suppliers]);

  const inspectFile = async (file?: File) => {
    if (!file) return;
    setBusy(true); setError(""); setPendingFile(file);
    try { setDetection(await detectFile(file)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "文件检测失败"); }
    finally { setBusy(false); if (inputRef.current) inputRef.current.value = ""; }
  };

  const importFile = async () => {
    if (!pendingFile) return;
    setBusy(true); setError("");
    try {
      if (!selectedSupplierId) throw new Error("请先选择这份资料所属的供应商。");
      await createImport(pendingFile, selectedSupplierId);
      setDetection(undefined); setPendingFile(undefined); await load();
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "导入任务创建失败"); }
    finally { setBusy(false); }
  };

  const openSupplier = async (supplierId: string) => {
    setBusy(true); setError("");
    try { setDetail(await getSupplierProfile(supplierId)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "供应商详情加载失败"); }
    finally { setBusy(false); }
  };

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow="供应网络"
        title="供应商"
        description="集中查看供应商档案、关联 SKU、价格有效性与待处理资料。"
        actions={<><Button variant="soft" color="gray" onClick={() => void load()}>刷新</Button>{canManageSuppliers ? <Button onClick={() => setCreatingSupplier(true)}><Buildings />新增供应商</Button> : null}</>}
      />
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      <section className="core-metric-grid core-metric-grid-three">
        <Card className="core-summary-card"><Text size="2" color="gray">供应商总数</Text><strong>{suppliers.length}</strong><Text size="1">当前租户可见档案</Text></Card>
        <Card className="core-summary-card"><Text size="2" color="gray">有效供应产品</Text><strong>{suppliers.reduce((sum, row) => sum + row.activeProducts, 0)}</strong><Text size="1">已关联权威产品</Text></Card>
        <Card className="core-summary-card"><Text size="2" color="gray">需要关注</Text><strong>{suppliers.filter((row) => row.expiredPrices > 0 || row.pendingReviews > 0).length}</strong><Text size="1">存在过期价格或待审记录</Text></Card>
      </section>

      {canImport ? <Card className="core-import-bar">
        <div className="core-import-bar-copy"><span className="core-row-icon"><FileArrowUp /></span><div><Text weight="medium" as="div">导入供应商商品资料</Text><Text size="1" color="gray">选择资料归属后上传，文件会先经过隔离扫描和格式识别。</Text></div></div>
        <select value={selectedSupplierId} onChange={(event) => setSelectedSupplierId(event.target.value)} aria-label="选择资料所属供应商"><option value="">选择资料所属供应商</option>{suppliers.map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.name}</option>)}</select>
        <Button disabled={!selectedSupplierId || busy} onClick={() => inputRef.current?.click()}><FileArrowUp />选择文件</Button>
        <input ref={inputRef} hidden type="file" accept=".xlsx,.xls,.csv,.docx,.doc,.pdf,.pptx" onChange={(event) => void inspectFile(event.target.files?.[0])} />
      </Card> : null}

      <Tabs.Root defaultValue={canViewSuppliers ? "suppliers" : "imports"}>
        <Tabs.List><Tabs.Trigger value="suppliers" disabled={!canViewSuppliers}>供应商网络</Tabs.Trigger><Tabs.Trigger value="imports" disabled={!canImport}>导入动态</Tabs.Trigger></Tabs.List>
        <Tabs.Content value="suppliers">
          {loading && !suppliers.length ? <CoreLoading label="正在读取供应商档案" /> : suppliers.length ? <Card className="core-table-card core-supplier-table-card">
            <div className="core-table-scroll"><div className="core-supplier-table">
              <div className="core-supplier-table-head"><span>供应商</span><span>主营类目</span><span>有效 SKU</span><span>价格状态</span><span>综合评分</span><span>状态</span><span /></div>
              {suppliers.map((supplier) => (
                <button className="core-supplier-table-row" type="button" key={supplier.id} onClick={() => void openSupplier(supplier.id)}>
                  <span className="core-name-cell"><span className="core-supplier-icon"><Buildings /></span><span><strong>{supplier.name}</strong><small>{supplier.supplierCode} · {supplier.countryCode ?? "地区未维护"}</small></span></span>
                  <span>{supplier.categorySummary ?? supplier.category}</span>
                  <strong className="core-tabular">{supplier.activeSkus}</strong>
                  <span className="core-price-health"><Text size="1">{supplier.validPrices} 条有效</Text>{supplier.expiredPrices ? <Text size="1" color="orange">{supplier.expiredPrices} 条过期</Text> : null}</span>
                  <strong className="core-tabular">{supplier.latestScore?.overallScore ?? "—"}</strong>
                  <Badge color={supplier.health.toUpperCase() === "HEALTHY" ? "jade" : "amber"}>{label(supplier.health)}</Badge>
                  <ArrowRight />
                </button>
              ))}
            </div></div>
          </Card> : <CoreEmpty title="暂无供应商档案" description="先新增供应商，再选择它并上传产品资料。" action={canManageSuppliers ? <Button onClick={() => setCreatingSupplier(true)}><Buildings />新增供应商</Button> : undefined} />}
          {!loading && suppliers.length ? <div className="core-supplier-mobile-list">
            {suppliers.map((supplier) => (
              <button className="core-supplier-mobile-card" type="button" key={supplier.id} onClick={() => void openSupplier(supplier.id)} aria-label={`打开供应商 ${supplier.name}`}>
                <span className="core-supplier-mobile-heading">
                  <span className="core-supplier-icon"><Buildings /></span>
                  <span><small>{supplier.supplierCode}</small><strong>{supplier.name}</strong><small>{supplier.countryCode ?? "地区未维护"} · {supplier.categorySummary ?? supplier.category}</small></span>
                  <Badge color={supplier.health.toUpperCase() === "HEALTHY" ? "jade" : "amber"}>{label(supplier.health)}</Badge>
                </span>
                <span className="core-supplier-mobile-facts">
                  <span><small>有效 SKU</small><strong>{supplier.activeSkus}</strong></span>
                  <span><small>有效价格</small><strong>{supplier.validPrices}</strong></span>
                  <span><small>综合评分</small><strong>{supplier.latestScore?.overallScore ?? "—"}</strong></span>
                </span>
                <span className="core-supplier-mobile-footer">{supplier.expiredPrices || supplier.pendingReviews ? <Text size="1" color="orange">{supplier.expiredPrices} 条过期价格 · {supplier.pendingReviews} 条待审</Text> : <Text size="1" color="gray">资料状态正常</Text>}<span>查看档案<ArrowRight /></span></span>
              </button>
            ))}
          </div> : null}
        </Tabs.Content>
        <Tabs.Content value="imports">
          <Card className="core-notice"><ShieldCheck size={24} /><div><Text weight="bold" as="div">文件先隔离扫描，再生成候选草稿</Text><Text size="2" color="gray">解析结果不会自动成为产品主数据，所有低置信度字段必须人工复核。</Text></div></Card>
          <div className="core-list core-job-list">
            {jobs.map((job) => <Card className="core-list-row" key={job.id}><FileText size={22} /><div><Text weight="medium" as="div">{job.filename}</Text><Text size="1" color="gray">{job.supplier || "供应商待识别"} · {job.detectedType} · {job.parser ?? "检测中"}</Text>{job.status === "parsing" || job.status === "scanning" ? <Progress value={job.progress} /> : null}</div><div><Text weight="bold" as="div">{job.products} 条产品</Text><Text size="1" color="gray">{job.warnings} 条提醒</Text></div><Badge color={job.status === "failed" ? "red" : job.status === "needs_review" ? "amber" : "jade"}>{label(job.status)}</Badge><Text size="1" color="gray">{coreDate(job.createdAt)}</Text></Card>)}
            {!loading && !jobs.length ? <CoreEmpty title="暂无导入任务" description="上传 XLSX、旧版 XLS、DOCX 或 PDF 文件开始产品导入。" /> : null}
          </div>
        </Tabs.Content>
      </Tabs.Root>

      <Dialog.Root open={Boolean(detection)} onOpenChange={(open) => { if (!open) { setDetection(undefined); setPendingFile(undefined); } }}>
        <Dialog.Content>
          <Dialog.Title>确认导入文件</Dialog.Title><Dialog.Description>已读取文件签名，以下结果不只依赖扩展名。</Dialog.Description>
          {detection ? <div className="core-detection"><FileText size={30} /><div><Text weight="bold" as="div">{detection.filename}</Text><Text size="2" color="gray">所属供应商：{suppliers.find((supplier) => supplier.id === selectedSupplierId)?.name ?? "尚未选择"}</Text><Text size="2" color="gray">真实格式：{detection.detected_type} · 解析器：{detection.parser}</Text></div><Badge color={detection.extension_matches ? "jade" : "amber"}>{detection.extension_matches ? "签名一致" : "扩展名不一致"}</Badge></div> : null}
          {detection?.warning ? <Card className="core-warning"><Warning />{detection.warning}</Card> : null}
          <div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={() => { setDetection(undefined); setPendingFile(undefined); }}>取消</Button><Button disabled={busy || !selectedSupplierId} onClick={() => void importFile()}><FileArrowUp />创建隔离导入任务</Button></div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={Boolean(detail)} onOpenChange={(open) => { if (!open) setDetail(undefined); }}>
        <Dialog.Content className="core-detail-dialog">
          {detail ? <SupplierDetail detail={detail} onClose={() => setDetail(undefined)} /> : <CoreLoading />}
        </Dialog.Content>
      </Dialog.Root>

      <SupplierCreateDialog
        open={creatingSupplier}
        onOpenChange={setCreatingSupplier}
        onCreated={async (supplier) => {
          await load();
          setSelectedSupplierId(supplier.id);
          setCreatingSupplier(false);
        }}
      />
    </div>
  );
}

function SupplierCreateDialog({ open, onOpenChange, onCreated }: { open: boolean; onOpenChange: (open: boolean) => void; onCreated: (supplier: SupplierProfile) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      const supplier = await createSupplierProfile({
        supplierCode: String(data.get("supplier_code") || ""),
        name: String(data.get("name") || ""),
        category: String(data.get("category") || "待分类"),
        countryCode: String(data.get("country_code") || "") || undefined,
        website: String(data.get("website") || "") || undefined,
      });
      await onCreated(supplier);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "供应商创建失败"); }
    finally { setBusy(false); }
  };
  return <Dialog.Root open={open} onOpenChange={onOpenChange}>
    <Dialog.Content>
      <Dialog.Title>新增供应商</Dialog.Title>
      <Dialog.Description>先建立当前商家的供应商档案，再上传属于它的产品资料。</Dialog.Description>
      <form className="core-form-grid" onSubmit={(event) => void submit(event)}>
        <label>供应商编码 *<TextField.Root name="supplier_code" required placeholder="例如 SUP-ACME" /></label>
        <label>供应商名称 *<TextField.Root name="name" required placeholder="例如 海岸家居制造" /></label>
        <label>主营类目 *<TextField.Root name="category" required defaultValue="待分类" /></label>
        <label>国家 / 地区代码<TextField.Root name="country_code" maxLength={2} placeholder="例如 CN" /></label>
        <label>网站<TextField.Root name="website" type="url" placeholder="https://example.com" /></label>
        {error ? <CoreError message={error} /> : null}
        <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={() => onOpenChange(false)}>取消</Button><Button type="submit" disabled={busy}>{busy ? "创建中…" : "创建并选择"}</Button></div>
      </form>
    </Dialog.Content>
  </Dialog.Root>;
}

function SupplierDetail({ detail, onClose }: { detail: SupplierProfileDetail; onClose: () => void }) {
  return <><div className="core-dialog-heading"><div><Text size="1" color="gray">供应商档案 · v{detail.version}</Text><Dialog.Title>{detail.name}</Dialog.Title><Dialog.Description>{detail.supplierCode} · {detail.countryCode ?? "国家未维护"} · {label(detail.status)}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose}><X /></Button></div>
    <div className="core-master-grid"><Card><Text size="1" color="gray">有效产品</Text><Heading>{detail.activeProducts}</Heading></Card><Card><Text size="1" color="gray">有效价格</Text><Heading>{detail.validPrices}</Heading></Card><Card><Text size="1" color="gray">过期价格</Text><Heading>{detail.expiredPrices}</Heading></Card><Card><Text size="1" color="gray">综合评分</Text><Heading>{detail.latestScore?.overallScore ?? "—"}</Heading></Card></div>
    <Heading size="4">供应产品与采购事实</Heading><div className="core-list">{detail.sources.map((source) => <div className="core-list-row" key={source.supplierProductId}><Buildings /><div><Text weight="medium" as="div">{source.productName}</Text><Text size="1" color="gray">{source.productCode} · 供应商 SKU {source.supplierSku ?? "—"}</Text></div><Text size="2">MOQ {source.moq ?? "—"} {source.moqUnit ?? ""} · {source.leadTimeDays ?? "—"} 天</Text><Text weight="bold">{source.currency ?? ""} {source.unitPrice?.toFixed(2) ?? "—"}</Text><Badge color={source.priceValidity === "VALID" ? "jade" : "amber"}>{label(source.priceValidity)}</Badge></div>)}{!detail.sources.length ? <CoreEmpty title="暂无关联来源" description="完成导入和产品审核后会建立供应来源。" /> : null}</div>
    <Heading size="4">最近导入</Heading><div className="core-list">{detail.recentImports.map((item) => <div className="core-list-row" key={item.id}><FileText /><div><Text weight="medium" as="div">{item.filename}</Text><Text size="1" color="gray">{item.productsCount} 条产品 · {item.warningsCount} 条提醒</Text></div><Badge color="gray">{label(item.status)}</Badge><Text size="1" color="gray">{coreDate(item.createdAt)}</Text></div>)}</div>
  </>;
}
