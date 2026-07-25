import { Badge, Button, Card, Dialog, Heading, Progress, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { ArrowsClockwise, CaretRight, CheckCircle, ClockCounterClockwise, DownloadSimple, FileArrowUp, FileXls, ImageSquare, MagnifyingGlass, Plus, Tag, Warning, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createAttributeDefinition,
  createProductTemplateImport,
  createSkus,
  detectFile,
  getImport,
  getProduct,
  listAttributeDefinitions,
  listCategories,
  listImports,
  listPublicCatalogOffers,
  listSkus,
  PRODUCT_TEMPLATE_DOWNLOAD_URL,
  updateSku,
  upsertPublicCatalogOffer,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import type { AttributeDefinition, FileDetection, ImportJob, ProductCategory, ProductDetail, ProductSku, PublicCatalogOffer, SkuListItem, SkuListPage } from "../types";

const splitValues = (value: string) => value.split(/[,，;；、|\n]/).map((item) => item.trim()).filter(Boolean);
const emptySkuPage: SkuListPage = { items: [], page: 1, pageSize: 50, total: 0, pages: 0 };

const skuStatusLabel: Record<ProductSku["status"], string> = {
  ACTIVE: "在售",
  DRAFT: "草稿",
  INACTIVE: "已下架",
  ARCHIVED: "已归档",
};

const offerStatusLabel: Record<NonNullable<SkuListItem["publicOfferStatus"]>, string> = {
  PUBLISHED: "公开价已发布",
  DRAFT: "公开价草稿",
  SUSPENDED: "公开价已暂停",
};

const importStatusLabel: Record<ImportJob["status"], string> = {
  scanning: "安全扫描",
  parsing: "导入中",
  needs_review: "待复核",
  published: "已完成",
  failed: "导入失败",
};

function imageStatusLabel(status: SkuListItem["imageStatus"]) {
  if (status === "APPROVED") return "图片已就绪";
  if (status === "SOURCE") return "图片待确认";
  return "暂无图片";
}

function skuStatusColor(status: ProductSku["status"]): "jade" | "amber" | "gray" {
  if (status === "ACTIVE") return "jade";
  if (status === "DRAFT") return "amber";
  return "gray";
}

function skuPrice(row: SkuListItem) {
  if (row.publicPrice === undefined) return "未设置";
  return `${row.publicCurrency ?? ""} ${row.publicPrice.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim();
}

function skuUpdatedDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function ProductsPage() {
  const { hasPermission } = useCoreAuth();
  const canImport = hasPermission("product.import")
    && hasPermission("product.edit")
    && hasPermission("catalog.publish");
  const [params, setParams] = useSearchParams();
  const importInputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [primaryCategoryId, setPrimaryCategoryId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [status, setStatus] = useState<"" | ProductSku["status"]>("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<SkuListPage>(emptySkuPage);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [selected, setSelected] = useState<ProductDetail>();
  const [detailInitialTab, setDetailInitialTab] = useState<"overview" | "skus">(
    params.get("view") === "skus" ? "skus" : "overview",
  );
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [importOpen, setImportOpen] = useState(canImport && params.get("import") === "1");
  const [importJobs, setImportJobs] = useState<ImportJob[]>([]);
  const [pendingFile, setPendingFile] = useState<File>();
  const [detection, setDetection] = useState<FileDetection>();
  const [lastImport, setLastImport] = useState<ImportJob>();
  const [loadedWarningJobId, setLoadedWarningJobId] = useState<string>();
  const [importBusy, setImportBusy] = useState(false);
  const [importError, setImportError] = useState("");
  const [importPollingError, setImportPollingError] = useState("");
  const loadSequence = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError("");
    try {
      const next = await listSkus({
        q: query.trim() || undefined,
        categoryId: categoryId || primaryCategoryId || undefined,
        statuses: status ? [status] : undefined,
        page,
        pageSize: 50,
      });
      if (sequence === loadSequence.current) setResult(next);
    } catch (reason) {
      if (sequence === loadSequence.current) {
        setError(reason instanceof Error ? reason.message : "SKU 商品库加载失败");
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [categoryId, page, primaryCategoryId, query, status]);

  const loadCategories = useCallback(async () => {
    setCategories(await listCategories());
  }, []);
  useEffect(() => { void loadCategories().catch(() => setCategories([])); }, [loadCategories]);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 240); return () => window.clearTimeout(timer); }, [load]);

  const loadTemplateImports = useCallback(async () => {
    if (!canImport) return;
    const rows = await listImports();
    setImportJobs(rows.filter((row) => row.sourceType === "PRODUCT_TEMPLATE"));
    setImportPollingError("");
  }, [canImport]);

  useEffect(() => {
    if (!canImport) {
      setImportJobs([]);
      return;
    }
    void loadTemplateImports().catch((reason) => {
      setImportJobs([]);
      setImportPollingError(reason instanceof Error ? `导入记录刷新失败：${reason.message}` : "导入记录暂时无法刷新。");
    });
  }, [loadTemplateImports]);

  useEffect(() => {
    if (!importJobs.some((job) => job.status === "scanning" || job.status === "parsing")) return;
    let cancelled = false;
    let timer = 0;
    const poll = () => {
      timer = window.setTimeout(() => {
        void loadTemplateImports()
          .catch((reason) => {
            setImportPollingError(reason instanceof Error ? `状态刷新失败，系统将继续重试：${reason.message}` : "状态刷新失败，系统将继续重试。");
          })
          .finally(() => {
            if (!cancelled) poll();
          });
      }, 1800);
    };
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [importJobs, loadTemplateImports]);

  useEffect(() => {
    const requested = params.get("import") === "1";
    if (requested && canImport) {
      setImportOpen(true);
      return;
    }
    if (requested && !canImport) {
      setImportOpen(false);
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.delete("import");
        return next;
      }, { replace: true });
    }
  }, [canImport, params, setParams]);

  useEffect(() => {
    if (!lastImport) return;
    const latest = importJobs.find((job) => job.id === lastImport.id);
    if (latest) setLastImport(latest);
  }, [importJobs, lastImport?.id]);

  useEffect(() => {
    if (importJobs[0]?.status === "published") {
      void load();
      void loadCategories().catch(() => undefined);
    }
  }, [importJobs, load, loadCategories]);

  const setImportDialogOpen = (open: boolean) => {
    if (open && !canImport) return;
    setImportOpen(open);
    if (!open) {
      setPendingFile(undefined);
      setDetection(undefined);
      setImportError("");
      setImportPollingError("");
    }
    setParams((current) => {
      const next = new URLSearchParams(current);
      if (open) next.set("import", "1");
      else next.delete("import");
      return next;
    }, { replace: true });
  };

  const inspectTemplate = async (file?: File) => {
    if (!canImport || !file) return;
    setImportError("");
    setLastImport(undefined);
    setLoadedWarningJobId(undefined);
    setPendingFile(file);
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      setDetection(undefined);
      setImportError("这里只接受固定格式的 .xlsx 商品模版。");
      if (importInputRef.current) importInputRef.current.value = "";
      return;
    }
    setImportBusy(true);
    try {
      const nextDetection = await detectFile(file);
      setDetection(nextDetection);
      if (
        nextDetection.detected_type !== "OOXML / XLSX"
        || !nextDetection.extension_matches
      ) {
        setImportError("文件签名与 XLSX 商品模版不一致，请重新选择。");
      }
    } catch (reason) {
      setDetection(undefined);
      setImportError(reason instanceof Error ? reason.message : "文件检测失败");
    } finally {
      setImportBusy(false);
      if (importInputRef.current) importInputRef.current.value = "";
    }
  };

  const importTemplate = async () => {
    if (!canImport) {
      setImportError("当前账号没有导入商品的权限。");
      return;
    }
    if (!pendingFile || !detection || importError) return;
    setImportBusy(true);
    setImportError("");
    try {
      const job = await createProductTemplateImport(pendingFile);
      setLastImport(job);
      setLoadedWarningJobId(undefined);
      setPendingFile(undefined);
      setDetection(undefined);
      await loadTemplateImports();
      if (job.status === "published") {
        await load();
        setCategories(await listCategories());
      }
    } catch (reason) {
      setImportError(reason instanceof Error ? reason.message : "商品模版导入失败");
    } finally {
      setImportBusy(false);
    }
  };

  const openProduct = useCallback(async (productId: string, initialTab: "overview" | "skus" = "overview") => {
    setDetailInitialTab(initialTab);
    setDetailLoading(true);
    setError("");
    try {
      setSelected(await getProduct(productId));
      setParams((current) => {
        const next = new URLSearchParams(current);
        next.set("product", productId);
        if (initialTab === "skus") next.set("view", "skus");
        else next.delete("view");
        return next;
      }, { replace: true });
    }
    catch (reason) { setError(reason instanceof Error ? reason.message : "产品详情加载失败"); }
    finally { setDetailLoading(false); }
  }, [setParams]);

  useEffect(() => {
    const productId = params.get("product");
    if (productId && selected?.id !== productId) {
      void openProduct(productId, params.get("view") === "skus" ? "skus" : "overview");
    }
    // Product selection is restored from the URL once on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    setSelected(undefined);
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("product");
      next.delete("view");
      return next;
    }, { replace: true });
  };
  const refreshSelected = async () => { if (selected) setSelected(await getProduct(selected.id)); };
  const resetFilters = () => {
    setQuery("");
    setPrimaryCategoryId("");
    setCategoryId("");
    setStatus("");
    setPage(1);
  };
  const rangeStart = result.total ? (result.page - 1) * result.pageSize + 1 : 0;
  const rangeEnd = Math.min(result.page * result.pageSize, result.total);
  const rootCategories = useMemo(
    () => categories.filter((item) => !item.parentId && item.status !== "ARCHIVED"),
    [categories],
  );
  const secondaryCategories = useMemo(
    () => categories.filter((item) => item.parentId === primaryCategoryId && item.status !== "ARCHIVED"),
    [categories, primaryCategoryId],
  );
  const hasActiveFilters = Boolean(query.trim() || primaryCategoryId || categoryId || status);

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow="商品资料"
        title="SKU 商品库"
        description="所有商品从固定 Excel 模版进入这里，并直接按 SKU 管理名称、分类、价格、图片与上下架状态。"
        actions={<>
          {canImport ? <Button onClick={() => setImportDialogOpen(true)}><FileArrowUp />导入商品模版</Button> : null}
        </>}
      />
      <Card className="core-sku-toolbar">
        <TextField.Root value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }} placeholder="搜索 SKU、商品名称或产品编码" aria-label="搜索 SKU 商品库"><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        <select value={primaryCategoryId} onChange={(event) => { setPrimaryCategoryId(event.target.value); setCategoryId(""); setPage(1); }} aria-label="按一级分类筛选"><option value="">全部一级分类</option>{rootCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
        <select value={categoryId} disabled={!primaryCategoryId || !secondaryCategories.length} onChange={(event) => { setCategoryId(event.target.value); setPage(1); }} aria-label="按二级分类筛选"><option value="">{primaryCategoryId ? "全部二级分类" : "请先选择一级分类"}</option>{secondaryCategories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
        <select value={status} onChange={(event) => { setStatus(event.target.value as "" | ProductSku["status"]); setPage(1); }} aria-label="按 SKU 状态筛选">
          <option value="">全部状态</option>
          <option value="ACTIVE">在售</option>
          <option value="DRAFT">草稿</option>
          <option value="INACTIVE">已下架</option>
          <option value="ARCHIVED">已归档</option>
        </select>
        <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}><ArrowsClockwise />刷新</Button>
      </Card>
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result.items.length ? <CoreLoading label="正在读取 SKU 商品库" /> : null}
      {!loading && !result.items.length && !error ? (
        hasActiveFilters
          ? <CoreEmpty title="没有符合条件的 SKU" description="尝试更换关键词、分类或状态。" action={<Button variant="soft" onClick={resetFilters}>清除筛选</Button>} />
          : <CoreEmpty
              title="商品库还是空的"
              description="下载固定模版并填写商品资料，导入后即可按 SKU 管理和发布。"
              action={canImport ? <Button onClick={() => setImportDialogOpen(true)}><FileArrowUp />导入商品模版</Button> : undefined}
            />
      ) : null}
      {result.items.length ? (
        <>
          <div className="core-sku-list-meta" aria-live="polite">
            <Text size="2" color="gray">共 <strong>{result.total.toLocaleString("zh-CN")}</strong> 个 SKU · 当前显示 {rangeStart}–{rangeEnd}</Text>
            {loading ? <Text size="1" color="gray">正在更新结果…</Text> : <Text size="1" color="gray">每页 {result.pageSize} 条</Text>}
          </div>
          <Card className="core-sku-table-card">
            <div className="core-sku-table" role="table" aria-label="SKU 商品列表">
              <div className="core-sku-table-head" role="row">
                <span>SKU / 商品</span><span>分类与标签</span><span>公开价</span><span>状态</span><span>更新时间</span><span aria-hidden="true" />
              </div>
              {result.items.map((sku) => (
                <button type="button" className="core-sku-table-row" role="row" key={sku.id} onClick={() => void openProduct(sku.productId, "skus")} aria-label={`打开 SKU ${sku.skuCode} 的编辑详情`}>
                  <span className="core-sku-name-cell">
                    <span className={`core-sku-image-state ${sku.imageStatus.toLowerCase()}`} title={sku.imageStatus === "APPROVED" ? "图片已批准" : sku.imageStatus === "SOURCE" ? "仅来源图" : "暂无图片"}><ImageSquare /></span>
                    <span><strong className="core-tabular">{sku.skuCode}</strong><small>{sku.name || sku.productName}</small></span>
                  </span>
                  <span className="core-sku-category-cell"><strong>{sku.category?.name ?? "未分类"}</strong><span className="core-chip-row">{sku.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</span></span>
                  <span className="core-tabular"><strong>{skuPrice(sku)}</strong><small>{sku.publicOfferStatus ? offerStatusLabel[sku.publicOfferStatus] : "尚无公开报价"}</small></span>
                  <Badge color={skuStatusColor(sku.status)}>{skuStatusLabel[sku.status]}</Badge>
                  <span><strong>{skuUpdatedDate(sku.updatedAt)}</strong><small>v{sku.version}</small></span>
                  <CaretRight aria-hidden="true" />
                </button>
              ))}
            </div>
          </Card>
          <div className="core-sku-mobile-list">
            {result.items.map((sku) => (
              <button type="button" className="core-sku-mobile-card" key={sku.id} onClick={() => void openProduct(sku.productId, "skus")} aria-label={`打开 SKU ${sku.skuCode} 的编辑详情`}>
                <span className="core-sku-mobile-heading"><span><small className="core-tabular">{sku.skuCode}</small><strong>{sku.name || sku.productName}</strong></span><Badge color={skuStatusColor(sku.status)}>{skuStatusLabel[sku.status]}</Badge></span>
                <span className="core-sku-mobile-facts"><span><small>公开价</small><strong className="core-tabular">{skuPrice(sku)}</strong></span><span><small>图片</small><strong>{imageStatusLabel(sku.imageStatus)}</strong></span></span>
                <span className="core-chip-row"><Badge color="gray">{sku.category?.name ?? "未分类"}</Badge>{sku.tags.slice(0, 2).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</span>
                <span className="core-sku-mobile-footer"><small>更新于 {skuUpdatedDate(sku.updatedAt)}</small><span>SKU 详情<CaretRight /></span></span>
              </button>
            ))}
          </div>
          {result.pages > 1 ? (
            <nav className="core-sku-pagination" aria-label="SKU 列表分页">
              <Button variant="soft" color="gray" disabled={loading || result.page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>上一页</Button>
              <Text size="2" color="gray">第 <strong>{result.page}</strong> / {result.pages} 页</Text>
              <Button variant="soft" color="gray" disabled={loading || result.page >= result.pages} onClick={() => setPage((current) => Math.min(result.pages, current + 1))}>下一页</Button>
            </nav>
          ) : null}
        </>
      ) : null}

      {canImport ? <Dialog.Root open={importOpen} onOpenChange={setImportDialogOpen}>
        <Dialog.Content className="core-template-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">固定商品资料入口</Text>
              <Dialog.Title>导入商品模版</Dialog.Title>
              <Dialog.Description>选择按约定填写的 XLSX；不需要选择供应商，也不会按供应商拆分商品。</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => setImportDialogOpen(false)} aria-label="关闭"><X /></Button>
          </div>

          <Card className="core-template-contract">
            <span className="core-row-icon"><FileXls /></span>
            <div>
              <Text weight="bold" as="div">当前固定模版：商品模版.xlsx</Text>
              <Text size="2" color="gray">“商品型号”作为唯一 SKU；分类填写“A”或“A/B”，最多两级；标签支持中英文逗号分隔；图片列读取图床链接。</Text>
              <div className="core-chip-row" aria-label="固定模版字段">
                {["商品名称", "商品分类", "商品型号", "商品价格", "商品描述", "备注", "标签", "商品图片1–10"].map((field) => <Badge color="gray" key={field}>{field}</Badge>)}
              </div>
              <div>
                <Button asChild size="1" variant="soft" color="gray">
                  <a href={PRODUCT_TEMPLATE_DOWNLOAD_URL} download="商品模版.xlsx"><DownloadSimple />下载空白模版</a>
                </Button>
              </div>
            </div>
          </Card>

          <Card className="core-notice">
            <Warning size={22} />
            <div>
              <Text weight="bold" as="div">这份模版代表当前完整商品库</Text>
              <Text size="2" color="gray">重复型号保留第一条；缺价商品只进入后台；标签会同步到客户前台；从下一份文件移除的 SKU 会自动下架。</Text>
            </div>
          </Card>

          <input
            ref={importInputRef}
            hidden
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            onChange={(event) => void inspectTemplate(event.target.files?.[0])}
          />

          {detection && pendingFile ? (
            <Card className="core-detection">
              <FileXls size={30} />
              <div>
                <Text weight="bold" as="div">{pendingFile.name}</Text>
                <Text size="2" color="gray">{(pendingFile.size / 1024).toFixed(1)} KB · {detection.detected_type} · {detection.parser}</Text>
              </div>
              <Badge color={detection.extension_matches ? "jade" : "amber"}>{detection.extension_matches ? "格式已确认" : "格式不一致"}</Badge>
            </Card>
          ) : (
            <button className="core-template-dropzone" type="button" disabled={importBusy} onClick={() => importInputRef.current?.click()}>
              <FileArrowUp size={30} />
              <strong>选择商品模版</strong>
              <span>仅支持固定列名和列顺序的 XLSX 文件</span>
            </button>
          )}

          {importError ? <CoreError message={importError} /> : importPollingError ? <CoreError message={importPollingError} onRetry={() => void loadTemplateImports()} /> : null}
          {lastImport ? (
            <Card className={`core-template-result ${lastImport.status}`}>
              {lastImport.status === "published" ? <CheckCircle size={24} /> : lastImport.status === "failed" ? <Warning size={24} /> : <ArrowsClockwise size={24} />}
              <div>
                <Text weight="bold" as="div">{importStatusLabel[lastImport.status]} · {lastImport.filename}</Text>
                <Text size="2" color="gray">{lastImport.products} 个 SKU 已处理 · {lastImport.warnings} 条提醒</Text>
                {lastImport.errorMessage ? <Text size="1" color="gray">{lastImport.errorMessage.split("；", 1)[0]}</Text> : null}
                {lastImport.warnings > 0 ? (
                  <details
                    className="core-template-warnings"
                    onToggle={(event) => {
                      if (
                        event.currentTarget.open
                        && loadedWarningJobId !== lastImport.id
                        && lastImport.warningMessages.length < lastImport.warnings
                      ) {
                        setLoadedWarningJobId(lastImport.id);
                        void getImport(lastImport.id)
                          .then(setLastImport)
                          .catch(() => setLoadedWarningJobId(undefined));
                      }
                    }}
                  >
                    <summary>
                      {loadedWarningJobId === lastImport.id
                        && lastImport.warningMessages.length < lastImport.warnings
                        ? `查看已记录的 ${lastImport.warningMessages.length} 条提醒（另 ${lastImport.warnings - lastImport.warningMessages.length} 条仅计数）`
                        : lastImport.warningMessages.length < lastImport.warnings
                        ? `加载提醒详情（共 ${lastImport.warnings} 条）`
                        : `查看全部 ${lastImport.warningMessages.length} 条提醒`}
                    </summary>
                    {lastImport.warningMessages.length
                      ? <ol>{lastImport.warningMessages.map((message, index) => <li key={`${index}:${message}`}>{message}</li>)}</ol>
                      : <Text size="1" color="gray">展开后读取提醒详情。</Text>}
                  </details>
                ) : null}
              </div>
            </Card>
          ) : null}

          <div className="core-dialog-actions">
            {detection ? <Button variant="soft" color="gray" disabled={importBusy} onClick={() => importInputRef.current?.click()}>重新选择</Button> : null}
            <Button
              disabled={!pendingFile || !detection || Boolean(importError) || importBusy}
              onClick={() => void importTemplate()}
            >
              <FileArrowUp />{importBusy ? "正在处理…" : "确认导入商品库"}
            </Button>
          </div>

          {importJobs.length ? (
            <div className="core-template-history">
              <Text size="1" color="gray">最近模版导入</Text>
              {importJobs.slice(0, 4).map((job) => (
                <div className="core-template-history-row" key={job.id}>
                  <FileXls />
                  <span><strong>{job.filename}</strong><small>{job.products} 个 SKU · {job.warnings} 条提醒</small></span>
                  {job.status === "scanning" || job.status === "parsing" ? <Progress value={job.progress} /> : null}
                  <Badge color={job.status === "failed" ? "red" : job.status === "published" ? "jade" : "amber"}>{importStatusLabel[job.status]}</Badge>
                </div>
              ))}
            </div>
          ) : null}
        </Dialog.Content>
      </Dialog.Root> : null}

      <Dialog.Root open={Boolean(selected || detailLoading)} onOpenChange={(open) => { if (!open) close(); }}>
        <Dialog.Content className="core-detail-dialog">
          {detailLoading || !selected ? <CoreLoading label="正在读取产品聚合视图" /> : <ProductDetailPanel product={selected} initialTab={detailInitialTab} onChanged={async () => { await refreshSelected(); await load(); }} onClose={close} />}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}

function ProductDetailPanel({ product, initialTab, onChanged, onClose }: { product: ProductDetail; initialTab: "overview" | "skus"; onChanged: () => Promise<void>; onClose: () => void }) {
  return (
    <>
      <div className="core-dialog-heading"><div><Text size="1" color="gray">权威产品记录 · v{product.currentVersion}</Text><Dialog.Title>{product.name}</Dialog.Title><Dialog.Description>{product.productCode ?? "产品"} · {product.category}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label="关闭"><X /></Button></div>
      <Tabs.Root key={`${product.id}:${initialTab}`} defaultValue={initialTab}>
        <Tabs.List><Tabs.Trigger value="overview">主数据</Tabs.Trigger><Tabs.Trigger value="skus">SKU ({product.skus.length})</Tabs.Trigger><Tabs.Trigger value="attributes">分类属性</Tabs.Trigger><Tabs.Trigger value="activity">活动</Tabs.Trigger></Tabs.List>
        <Tabs.Content value="overview"><div className="core-master-grid"><Fact label="状态" value={product.status} /><Fact label="产品版本" value={`v${product.currentVersion}`} /><Fact label="图片状态" value={product.imageStatus} /><Fact label="SKU" value={String(product.skuCount)} /><section><Text size="1" color="gray">标准描述</Text><p>{product.description || "尚未维护标准描述。"}</p></section><section><Text size="1" color="gray">商品模版映射</Text><p>型号作为 SKU 编码；价格进入对客公开价；标签用于前台展示与筛选；图床链接作为商品图片。</p></section></div></Tabs.Content>
        <Tabs.Content value="skus"><SkuPanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="attributes"><AttributePanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="activity"><div className="core-list">{product.activity.map((row) => <div className="core-list-row" key={row.id}><ClockCounterClockwise /><div><Text weight="medium" as="div">{row.action}</Text><Text size="1" color="gray">{row.entityType} · {coreDate(row.occurredAt)}</Text></div></div>)}{!product.activity.length ? <CoreEmpty title="暂无活动记录" description="重要修改将在此处形成审计时间线。" /> : null}</div></Tabs.Content>
      </Tabs.Root>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) { return <Card><Text size="1" color="gray">{label}</Text><Heading size="4">{value}</Heading></Card>; }

function SkuPanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasAnyPermission, hasPermission } = useCoreAuth();
  const canEdit = hasPermission("product.edit");
  const canViewCatalog = hasAnyPermission("catalog.view", "catalog.publish");
  const canPublish = hasAnyPermission("catalog.publish");
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([]);
  const [offers, setOffers] = useState<PublicCatalogOffer[]>([]);
  const [skuCode, setSkuCode] = useState(`${product.productCode ?? "SKU"}-${product.skus.length + 1}`);
  const [skuName, setSkuName] = useState(product.name);
  const [firstValues, setFirstValues] = useState("");
  const [secondValues, setSecondValues] = useState("");
  const [prefix, setPrefix] = useState(product.productCode ?? "SKU");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { void listAttributeDefinitions(product.categoryId).then((rows) => setDefinitions(rows.filter((row) => row.isVariant))).catch(() => setDefinitions([])); }, [product.categoryId]);
  const loadOffers = useCallback(async () => {
    if (!canViewCatalog) { setOffers([]); return; }
    try { setOffers(await listPublicCatalogOffers(product.id)); }
    catch { setOffers([]); }
  }, [canViewCatalog, product.id]);
  useEffect(() => { void loadOffers(); }, [loadOffers]);
  const matrix = useMemo(() => {
    const first = splitValues(firstValues); const second = splitValues(secondValues);
    if (!definitions[0] || !first.length) return [];
    const right = definitions[1] && second.length ? second : [""];
    return first.flatMap((a) => right.map((b) => ({ skuCode: `${prefix}-${a}-${b}`.replace(/[^a-zA-Z0-9-]+/g, "-").replace(/-+$/g, "").toUpperCase(), name: [a, b].filter(Boolean).join(" / "), optionValues: { [definitions[0].attributeKey]: a, ...(definitions[1] && b ? { [definitions[1].attributeKey]: b } : {}) } })));
  }, [definitions, firstValues, prefix, secondValues]);
  const createSingle = async () => {
    if (!skuCode.trim()) return;
    setBusy(true); setError("");
    try {
      await createSkus(product.id, [{
        skuCode: skuCode.trim(),
        name: skuName.trim() || undefined,
        optionValues: {},
        status: "DRAFT",
      }]);
      await onChanged();
      setSkuCode(`${product.productCode ?? "SKU"}-${product.skus.length + 2}`);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "SKU 创建失败"); }
    finally { setBusy(false); }
  };
  const createVariants = async () => {
    setBusy(true); setError("");
    try { await createSkus(product.id, matrix); await onChanged(); setFirstValues(""); setSecondValues(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "SKU 创建失败"); }
    finally { setBusy(false); }
  };
  const changeStatus = async (sku: ProductSku, status: ProductSku["status"]) => {
    setBusy(true); setError("");
    try { await updateSku(sku.id, { expectedVersion: sku.version, status }); await onChanged(); await loadOffers(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "SKU 状态更新失败"); }
    finally { setBusy(false); }
  };
  return <div className="core-tab-panel">
    {canEdit ? <Card className="core-form-grid">
      <div><Text weight="bold" as="div">新增基础 SKU</Text><Text size="1" color="gray">不需要先配置变体属性；新建后先保存为草稿。</Text></div>
      <label>SKU 编码<TextField.Root value={skuCode} onChange={(event) => setSkuCode(event.target.value)} /></label>
      <label>前台名称<TextField.Root value={skuName} onChange={(event) => setSkuName(event.target.value)} /></label>
      <Button disabled={!skuCode.trim() || busy} onClick={() => void createSingle()}><Plus />创建草稿 SKU</Button>
    </Card> : <Text size="2" color="gray">当前角色只有查看权限。</Text>}
    {canEdit && definitions.length ? <Card className="core-form-grid">
      <div><Text weight="bold" as="div">按变体批量创建</Text><Text size="1" color="gray">已读取当前类目的变体定义。</Text></div>
      <label>SKU 前缀<TextField.Root value={prefix} onChange={(event) => setPrefix(event.target.value)} /></label>
      {definitions.slice(0, 2).map((definition, index) => <label key={definition.id}>{definition.displayName}<TextArea value={index ? secondValues : firstValues} onChange={(event) => index ? setSecondValues(event.target.value) : setFirstValues(event.target.value)} placeholder="逗号分隔" /></label>)}
      <Button disabled={!matrix.length || busy} onClick={() => void createVariants()}><Plus />创建 {matrix.length} 个草稿 SKU</Button>
    </Card> : null}
    {error ? <CoreError message={error} /> : null}
    <div className="core-list">{product.skus.map((sku) => {
      const offer = offers.find((item) => item.skuId === sku.id);
      return <Card key={sku.id}>
        <div className="core-list-row"><Tag /><div><Text weight="medium" as="div">{sku.skuCode}</Text><Text size="1" color="gray">{sku.name || Object.values(sku.optionValues).join(" · ") || "基础款"}</Text></div><Badge color={sku.status === "ACTIVE" ? "jade" : "gray"}>{sku.status}</Badge><Text size="1">v{sku.version}</Text>{canEdit && sku.status !== "ACTIVE" ? <Button size="1" disabled={busy} onClick={() => void changeStatus(sku, "ACTIVE")}>激活 SKU</Button> : null}{canEdit && sku.status === "ACTIVE" ? <Button size="1" variant="soft" color="gray" disabled={busy} onClick={() => void changeStatus(sku, "INACTIVE")}>下架 SKU</Button> : null}</div>
        {canViewCatalog ? <PublicOfferEditor sku={sku} offer={offer} canPublish={canPublish} onChanged={async () => { await loadOffers(); await onChanged(); }} /> : null}
      </Card>;
    })}{!product.skus.length ? <CoreEmpty title="还没有 SKU" description="先创建一个基础 SKU；不必预先建立类目变体定义。" /> : null}</div>
  </div>;
}

function PublicOfferEditor({ sku, offer, canPublish, onChanged }: { sku: ProductSku; offer?: PublicCatalogOffer; canPublish: boolean; onChanged: () => Promise<void> }) {
  const [price, setPrice] = useState(offer ? String(offer.unitPrice) : "");
  const [currency, setCurrency] = useState(offer?.currency ?? "CNY");
  const [tags, setTags] = useState(offer?.tags.join("，") ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { setPrice(offer ? String(offer.unitPrice) : ""); setCurrency(offer?.currency ?? "CNY"); setTags(offer?.tags.join("，") ?? ""); }, [offer]);
  const save = async (publicationStatus: PublicCatalogOffer["publicationStatus"]) => {
    const numericPrice = Number(price);
    if (!Number.isFinite(numericPrice) || numericPrice < 0) { setError("请填写有效的公开售价。"); return; }
    setBusy(true); setError("");
    try {
      await upsertPublicCatalogOffer(sku.id, {
        unitPrice: numericPrice,
        currency,
        tags: splitValues(tags),
        publicationStatus,
        validFrom: offer?.validFrom,
        validTo: offer?.validTo,
      });
      await onChanged();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "公开目录保存失败"); }
    finally { setBusy(false); }
  };
  return <div className="core-tab-panel">
    <div><Text weight="bold">客户公开目录</Text> <Badge color={offer?.publicationStatus === "PUBLISHED" ? "jade" : offer?.publicationStatus === "SUSPENDED" ? "amber" : "gray"}>{offer?.publicationStatus ?? "未配置"}</Badge></div>
    <Text size="1" color="gray">模版中的商品价格和标签会同步到前台；也可以在这里单独修改，下一次导入时以模版内容为准。</Text>
    {canPublish ? <div className="core-inline-form">
      <TextField.Root type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="公开售价" />
      <select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option></select>
      <label><Text size="1" color="gray">商品标签</Text><TextField.Root value={tags} onChange={(event) => setTags(event.target.value)} placeholder="新品，热卖，现货" /></label>
      <Button variant="soft" color="gray" disabled={busy || !price} onClick={() => void save("DRAFT")}>保存草稿</Button>
      <Button disabled={busy || !price || sku.status !== "ACTIVE"} onClick={() => void save("PUBLISHED")}>{sku.status === "ACTIVE" ? "发布到前台" : "请先激活 SKU"}</Button>
      {offer?.publicationStatus === "PUBLISHED" ? <Button variant="soft" color="amber" disabled={busy} onClick={() => void save("SUSPENDED")}>暂停公开</Button> : null}
    </div> : <Text size="1" color="gray">当前角色没有目录发布权限。</Text>}
    {error ? <CoreError message={error} /> : null}
  </div>;
}

function AttributePanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasPermission } = useCoreAuth();
  const canEdit = hasPermission("product.edit");
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([]);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [variant, setVariant] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => listAttributeDefinitions(product.categoryId).then(setDefinitions), [product.categoryId]);
  useEffect(() => { void load().catch(() => setDefinitions([])); }, [load]);
  const add = async () => { setError(""); try { await createAttributeDefinition({ categoryId: product.categoryId, attributeKey: key, displayName: name, dataType: "TEXT", isRequired: false, isVariant: variant, isFilterable: true, isMatchable: true }); await load(); await onChanged(); setKey(""); setName(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "属性创建失败"); } };
  return <div className="core-tab-panel">{canEdit ? <Card className="core-inline-form"><TextField.Root value={key} onChange={(event) => setKey(event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, ""))} placeholder="属性键" /><TextField.Root value={name} onChange={(event) => setName(event.target.value)} placeholder="显示名称" /><label className="core-check"><input type="checkbox" checked={variant} onChange={(event) => setVariant(event.target.checked)} />SKU 变体</label><Button disabled={!key || !name} onClick={() => void add()}><Plus />新增定义</Button></Card> : null}{error ? <CoreError message={error} /> : null}<div className="core-definition-grid">{definitions.map((definition) => <Card key={definition.id}><Tag /><Text weight="bold" as="div">{definition.displayName}</Text><code>{definition.attributeKey}</code><Badge color="gray">{definition.isVariant ? "变体" : definition.dataType}</Badge></Card>)}</div><Heading size="3">当前产品值</Heading><div className="core-chip-row">{product.attributes.map((attribute) => <Badge color="gray" key={attribute.id}>{attribute.key}: {String(attribute.value ?? "—")}</Badge>)}</div></div>;
}
