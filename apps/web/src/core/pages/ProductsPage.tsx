import { Badge, Button, Card, Dialog, Heading, Tabs, Text, TextArea, TextField } from "@radix-ui/themes";
import { ArrowsClockwise, ClockCounterClockwise, Cube, CurrencyCircleDollar, MagnifyingGlass, Plus, ShieldCheck, Tag, X } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  createAttributeDefinition,
  createPrice,
  createSkus,
  getProduct,
  listAttributeDefinitions,
  listCategories,
  listPublicCatalogOffers,
  listPrices,
  listProducts,
  updateSku,
  upsertPublicCatalogOffer,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import type { AttributeDefinition, CoreProduct, ProductCategory, ProductDetail, ProductSku, PublicCatalogOffer, SupplierPrice } from "../types";

const splitValues = (value: string) => value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);

export function ProductsPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [approvedOnly, setApprovedOnly] = useState(false);
  const [products, setProducts] = useState<CoreProduct[]>([]);
  const [categories, setCategories] = useState<ProductCategory[]>([]);
  const [selected, setSelected] = useState<ProductDetail>();
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setProducts(await listProducts({ q: query, categoryId: categoryId || undefined, approvedImagesOnly: approvedOnly })); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "产品加载失败"); setProducts([]); }
    finally { setLoading(false); }
  }, [approvedOnly, categoryId, query]);

  useEffect(() => { void listCategories().then(setCategories).catch(() => setCategories([])); }, []);
  useEffect(() => { const timer = window.setTimeout(() => void load(), 220); return () => window.clearTimeout(timer); }, [load]);

  const openProduct = useCallback(async (productId: string) => {
    setDetailLoading(true);
    setError("");
    try { setSelected(await getProduct(productId)); setParams((current) => { const next = new URLSearchParams(current); next.set("product", productId); return next; }, { replace: true }); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "产品详情加载失败"); }
    finally { setDetailLoading(false); }
  }, [setParams]);

  useEffect(() => {
    const productId = params.get("product");
    if (productId && selected?.id !== productId) void openProduct(productId);
    // Product selection is restored from the URL once on entry.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    setSelected(undefined);
    setParams((current) => { const next = new URLSearchParams(current); next.delete("product"); return next; }, { replace: true });
  };
  const refreshSelected = async () => { if (selected) setSelected(await getProduct(selected.id)); };

  return (
    <div className="core-workspace">
      <CorePageHeading
        eyebrow="产品主数据"
        title="产品中心"
        description="一份可信 Product 同时支撑供应商、AI 搜索、询盘与报价。"
        actions={<Button asChild><Link to="/console/products/review"><ShieldCheck />打开审核队列</Link></Button>}
      />
      <Card className="core-toolbar">
        <TextField.Root value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索产品名称、编码或 SKU"><TextField.Slot><MagnifyingGlass /></TextField.Slot></TextField.Root>
        <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)} aria-label="产品分类"><option value="">全部分类</option>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select>
        <label className="core-check"><input type="checkbox" checked={approvedOnly} onChange={(event) => setApprovedOnly(event.target.checked)} />仅显示已批准图片</label>
        <Button variant="soft" color="gray" onClick={() => void load()}><ArrowsClockwise />刷新</Button>
      </Card>
      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !products.length ? <CoreLoading label="正在读取权威产品数据" /> : (
        <div className="core-product-grid">
          {products.map((product) => (
            <Card className="core-product-card" key={product.id} onClick={() => void openProduct(product.id)}>
              <div className="core-product-art"><Cube size={34} /><Badge color={product.imageStatus === "APPROVED" ? "jade" : "gray"}>{product.imageStatus === "APPROVED" ? "图片已批准" : "仅来源图"}</Badge></div>
              <div><Text size="1" color="gray">{product.productCode ?? product.model} · v{product.currentVersion}</Text><Heading size="4">{product.name}</Heading></div>
              <div className="core-chip-row">{product.tags.slice(0, 3).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</div>
              <div className="core-product-facts"><span>{product.category}</span><span>{product.supplierCount} 个供应来源</span><span>{product.skuCount} 个 SKU</span></div>
              <Button variant="soft">查看详情</Button>
            </Card>
          ))}
          {!loading && !products.length && !error ? <CoreEmpty title="没有符合条件的产品" description="请更换关键词或重置筛选条件。" /> : null}
        </div>
      )}

      <Dialog.Root open={Boolean(selected || detailLoading)} onOpenChange={(open) => { if (!open) close(); }}>
        <Dialog.Content className="core-detail-dialog">
          {detailLoading || !selected ? <CoreLoading label="正在读取产品聚合视图" /> : <ProductDetailPanel product={selected} onChanged={async () => { await refreshSelected(); await load(); }} onClose={close} />}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}

function ProductDetailPanel({ product, onChanged, onClose }: { product: ProductDetail; onChanged: () => Promise<void>; onClose: () => void }) {
  return (
    <>
      <div className="core-dialog-heading"><div><Text size="1" color="gray">权威产品记录 · v{product.currentVersion}</Text><Dialog.Title>{product.name}</Dialog.Title><Dialog.Description>{product.productCode ?? "产品"} · {product.category}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={onClose} aria-label="关闭"><X /></Button></div>
      <Tabs.Root defaultValue="overview">
        <Tabs.List><Tabs.Trigger value="overview">主数据</Tabs.Trigger><Tabs.Trigger value="skus">SKU ({product.skus.length})</Tabs.Trigger><Tabs.Trigger value="prices">价格历史</Tabs.Trigger><Tabs.Trigger value="attributes">分类属性</Tabs.Trigger><Tabs.Trigger value="activity">活动</Tabs.Trigger></Tabs.List>
        <Tabs.Content value="overview"><div className="core-master-grid"><Fact label="状态" value={product.status} /><Fact label="产品版本" value={`v${product.currentVersion}`} /><Fact label="供应来源" value={String(product.supplierCount)} /><Fact label="SKU" value={String(product.skuCount)} /><section><Text size="1" color="gray">标准描述</Text><p>{product.description || "尚未维护标准描述。"}</p></section><section><Text size="1" color="gray">媒体门禁</Text><p>当前状态：{product.imageStatus}。来源图未经独立审核不会进入客户页面或报价文件。</p></section></div></Tabs.Content>
        <Tabs.Content value="skus"><SkuPanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="prices"><PricePanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="attributes"><AttributePanel product={product} onChanged={onChanged} /></Tabs.Content>
        <Tabs.Content value="activity"><div className="core-list">{product.activity.map((row) => <div className="core-list-row" key={row.id}><ClockCounterClockwise /><div><Text weight="medium" as="div">{row.action}</Text><Text size="1" color="gray">{row.entityType} · {coreDate(row.occurredAt)}</Text></div></div>)}{!product.activity.length ? <CoreEmpty title="暂无活动记录" description="重要修改将在此处形成审计时间线。" /> : null}</div></Tabs.Content>
      </Tabs.Root>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) { return <Card><Text size="1" color="gray">{label}</Text><Heading size="4">{value}</Heading></Card>; }

function SkuPanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasAnyPermission } = useCoreAuth();
  const canEdit = hasAnyPermission("product.edit", "product.create");
  const canViewCatalog = hasAnyPermission("catalog.view", "catalog.publish");
  const canPublish = hasAnyPermission("catalog.publish");
  const [definitions, setDefinitions] = useState<AttributeDefinition[]>([]);
  const [offers, setOffers] = useState<PublicCatalogOffer[]>([]);
  const [skuCode, setSkuCode] = useState(`${product.productCode ?? "SKU"}-${product.skus.length + 1}`);
  const [skuName, setSkuName] = useState(product.name);
  const [defaultMoq, setDefaultMoq] = useState("1");
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
        defaultMoq: Math.max(1, Number(defaultMoq) || 1),
        moqUnit: product.defaultUnit ?? "piece",
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
      <label>默认 MOQ<TextField.Root type="number" min="1" value={defaultMoq} onChange={(event) => setDefaultMoq(event.target.value)} /></label>
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
        <div className="core-list-row"><Tag /><div><Text weight="medium" as="div">{sku.skuCode}</Text><Text size="1" color="gray">{sku.name || Object.values(sku.optionValues).join(" · ") || "基础款"} · MOQ {sku.defaultMoq ?? 1}</Text></div><Badge color={sku.status === "ACTIVE" ? "jade" : "gray"}>{sku.status}</Badge><Text size="1">v{sku.version}</Text>{canEdit && sku.status !== "ACTIVE" ? <Button size="1" disabled={busy} onClick={() => void changeStatus(sku, "ACTIVE")}>激活 SKU</Button> : null}{canEdit && sku.status === "ACTIVE" ? <Button size="1" variant="soft" color="gray" disabled={busy} onClick={() => void changeStatus(sku, "INACTIVE")}>下架 SKU</Button> : null}</div>
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
    <Text size="1" color="gray">公开售价必须单独填写；系统不会把供应商采购成本自动带入客户前台。</Text>
    {canPublish ? <div className="core-inline-form">
      <TextField.Root type="number" min="0" step="0.01" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="公开售价" />
      <select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option></select>
      <TextField.Root value={tags} onChange={(event) => setTags(event.target.value)} placeholder="公开标签，逗号分隔" />
      <Button variant="soft" color="gray" disabled={busy || !price} onClick={() => void save("DRAFT")}>保存草稿</Button>
      <Button disabled={busy || !price || sku.status !== "ACTIVE"} onClick={() => void save("PUBLISHED")}>{sku.status === "ACTIVE" ? "发布到前台" : "请先激活 SKU"}</Button>
      {offer?.publicationStatus === "PUBLISHED" ? <Button variant="soft" color="amber" disabled={busy} onClick={() => void save("SUSPENDED")}>暂停公开</Button> : null}
    </div> : <Text size="1" color="gray">当前角色没有目录发布权限。</Text>}
    {error ? <CoreError message={error} /> : null}
  </div>;
}

function PricePanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasAnyPermission } = useCoreAuth();
  const canWrite = hasAnyPermission("product.cost.write", "product.edit");
  const [prices, setPrices] = useState<SupplierPrice[]>([]);
  const [unitPrice, setUnitPrice] = useState("");
  const [currency, setCurrency] = useState("CNY");
  const [moq, setMoq] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const load = useCallback(() => listPrices(product.id).then(setPrices), [product.id]);
  useEffect(() => { void load().catch(() => setPrices([])); }, [load]);
  const add = async () => { if (!product.sources[0]) return; setBusy(true); setError(""); try { await createPrice({ supplierProductId: product.sources[0].supplierProductId, minQuantity: Number(moq), unitPrice: Number(unitPrice), currency, unitCode: product.defaultUnit ?? "PCS", validFrom: new Date().toISOString() }); await load(); await onChanged(); setUnitPrice(""); } catch (reason) { setError(reason instanceof Error ? reason.message : "价格保存失败"); } finally { setBusy(false); } };
  return <div className="core-tab-panel">{canWrite ? <Card className="core-inline-form"><TextField.Root type="number" value={unitPrice} onChange={(event) => setUnitPrice(event.target.value)} placeholder="采购单价" /><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>CNY</option><option>USD</option><option>EUR</option></select><TextField.Root type="number" value={moq} onChange={(event) => setMoq(event.target.value)} placeholder="MOQ" /><Button disabled={!product.sources.length || !unitPrice || busy} onClick={() => void add()}><CurrencyCircleDollar />确认价格</Button></Card> : null}{error ? <CoreError message={error} /> : null}<div className="core-list">{prices.map((price) => <div className="core-list-row" key={price.id}><CurrencyCircleDollar /><div><Text weight="medium" as="div">{price.supplierName}</Text><Text size="1" color="gray">MOQ {price.minQuantity} · {price.incoterm ?? "贸易术语未维护"}</Text></div><Text weight="bold">{price.currency} {price.unitPrice.toFixed(2)}</Text><Badge color={price.priceValidity === "VALID" ? "jade" : "amber"}>{price.priceValidity}</Badge></div>)}{!prices.length ? <CoreEmpty title="暂无可见价格" description="可能尚未录入，或当前成员缺少成本权限。" /> : null}</div></div>;
}

function AttributePanel({ product, onChanged }: { product: ProductDetail; onChanged: () => Promise<void> }) {
  const { hasAnyPermission } = useCoreAuth();
  const canEdit = hasAnyPermission("product.edit", "system.settings_manage");
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
