import {
  Badge,
  Button,
  Card,
  Dialog,
  Heading,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  ArrowRight,
  Cube,
  MagnifyingGlass,
  Storefront,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { api } from "../../lib/api";
import { money } from "../../lib/format";
import type { Sku, StoreProduct, StoreProductDetail, StoreProductList } from "../../types";

const PAGE_SIZE = 24;

export function ResellerProductsPage() {
  const { profile } = useCoreAuth();
  const { t } = useLocale();
  const tenantSlug = profile?.context.tenantSlug || "";
  const [query, setQuery] = useState("");
  const [draftQuery, setDraftQuery] = useState("");
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<StoreProductList>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<StoreProductDetail>();
  const [selectedProductId, setSelectedProductId] = useState("");
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");

  const load = useCallback(async () => {
    if (!tenantSlug) return;
    setLoading(true);
    setError("");
    try {
      setResult(await api.getStoreProducts(tenantSlug, {
        q: query || undefined,
        page,
        includeFacets: false,
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("商品目录加载失败"));
    } finally {
      setLoading(false);
    }
  }, [page, query, t, tenantSlug]);

  useEffect(() => { void load(); }, [load]);

  const openProduct = async (product: StoreProduct) => {
    setSelectedProductId(product.id);
    setSelected(undefined);
    setDetailError("");
    setDetailLoading(true);
    try {
      setSelected(await api.getStoreProduct(tenantSlug, product.id));
    } catch (caught) {
      setDetailError(caught instanceof Error ? caught.message : t("商品详情加载失败"));
    } finally {
      setDetailLoading(false);
    }
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setPage(1);
    setQuery(draftQuery.trim());
  };

  const totalPages = Math.max(1, result?.pages || Math.ceil((result?.total || 0) / PAGE_SIZE));
  const storefrontPath = tenantSlug ? `/${encodeURIComponent(tenantSlug)}` : "/";

  return (
    <div className="core-workspace reseller-products-page">
      <CorePageHeading
        eyebrow={t("商品")}
        title={t("商品目录")}
        description={t("子账号可以在这里浏览商品资料与已经生效的代理价格；内部原价、供应商和管理字段不会显示。")}
        actions={<Button asChild variant="soft"><Link to={storefrontPath} target="_blank" rel="noreferrer"><Storefront />{t("打开商品前台")}</Link></Button>}
      />
      <Card className="reseller-catalog-toolbar">
        <form onSubmit={submitSearch}>
          <TextField.Root value={draftQuery} onChange={(event) => setDraftQuery(event.target.value)} placeholder={t("搜索商品名称、SKU 或标签")}>
            <TextField.Slot><MagnifyingGlass /></TextField.Slot>
            {draftQuery ? <TextField.Slot side="right"><button type="button" className="reseller-clear-search" onClick={() => { setDraftQuery(""); setQuery(""); setPage(1); }} aria-label={t("清除搜索")}><X /></button></TextField.Slot> : null}
          </TextField.Root>
          <Button type="submit"><MagnifyingGlass />{t("搜索")}</Button>
        </form>
        <Text size="1" color="gray">{result ? t("共 {count} 个商品", { count: result.total }) : t("正在读取商品")}</Text>
      </Card>

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {loading && !result ? <CoreLoading label={t("正在读取商品目录")} /> : null}
      {!loading && !error && result && !result.items.length ? <CoreEmpty title={t("没有匹配的商品")} description={t("请更换关键词后重试。")} /> : null}
      {result?.items.length ? <>
        <Card className="reseller-catalog-card">
          <div className="reseller-catalog-table-scroll">
            <div className="reseller-catalog-table reseller-catalog-table-head"><span>{t("商品")}</span><span>{t("分类")}</span><span>{t("SKU")}</span><span>{t("代理价格")}</span><span>{t("操作")}</span></div>
            {result.items.map((product) => <ProductRow key={product.id} product={product} onOpen={() => void openProduct(product)} t={t} />)}
          </div>
        </Card>
        <div className="reseller-pagination" aria-label={t("商品分页")}>
          <Button variant="soft" color="gray" disabled={page <= 1 || loading} onClick={() => setPage((current) => Math.max(1, current - 1))}><ArrowLeft />{t("上一页")}</Button>
          <span>{t("第 {page} / {pages} 页", { page, pages: totalPages })}</span>
          <Button variant="soft" color="gray" disabled={page >= totalPages || loading} onClick={() => setPage((current) => Math.min(totalPages, current + 1))}>{t("下一页")}<ArrowRight /></Button>
        </div>
      </> : null}

      <Dialog.Root open={Boolean(selected || detailLoading || detailError)} onOpenChange={(open) => { if (!open) { setSelected(undefined); setDetailError(""); } }}>
        <Dialog.Content className="reseller-product-dialog" maxWidth="900px">
          <Dialog.Title>{selected?.name || t("商品详情")}</Dialog.Title>
          {detailLoading ? <CoreLoading label={t("正在读取商品详情")} /> : null}
          {detailError ? <CoreError message={detailError} onRetry={() => { const product = result?.items.find((item) => item.id === selectedProductId); if (product) void openProduct(product); }} /> : null}
          {selected ? <ProductDetail product={selected} t={t} /> : null}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}

function ProductRow({ product, onOpen, t }: { product: StoreProduct; onOpen: () => void; t: (value: string, variables?: Record<string, string | number>) => string }) {
  const image = product.image_url;
  return (
    <div className="reseller-catalog-table reseller-catalog-table-row" role="button" tabIndex={0} onClick={onOpen} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(); } }}>
      <span className="reseller-product-cell"><span className="reseller-product-thumb">{image ? <img src={image} alt="" loading="lazy" /> : <Cube />}</span><span><strong>{product.name}</strong><small>{product.product_code || t("未设置商品编码")}</small></span></span>
      <span>{product.category_label || product.category || "—"}</span>
      <span className="core-tabular">{product.sku_count.toLocaleString()}</span>
      <strong className="reseller-price-cell">{formatPriceRange(product)}</strong>
      <span><Button type="button" size="1" variant="soft" tabIndex={-1}>{t("查看详情")}<ArrowRight /></Button></span>
    </div>
  );
}

function ProductDetail({ product, t }: { product: StoreProductDetail; t: (value: string, variables?: Record<string, string | number>) => string }) {
  const images = product.image_urls?.length ? product.image_urls : product.image_url ? [product.image_url] : [];
  return (
    <div className="reseller-product-detail">
      <div className="reseller-product-detail-top">
        <div className="reseller-product-detail-images">{images.length ? images.slice(0, 6).map((image, index) => <img key={`${image}-${index}`} src={image} alt="" loading="lazy" />) : <div className="reseller-product-detail-placeholder"><Cube /></div>}</div>
        <div className="reseller-product-detail-copy"><div className="reseller-detail-tags">{product.category_label || product.category ? <Badge color="gray">{product.category_label || product.category}</Badge> : null}{product.tags.slice(0, 4).map((tag) => <Badge key={tag} color="blue">{tag}</Badge>)}</div><Heading size="6">{product.name}</Heading>{product.description ? <Text size="2" color="gray" className="reseller-product-description">{product.description}</Text> : <Text size="2" color="gray">{t("暂无商品描述")}</Text>}<strong className="reseller-detail-price">{formatPriceRange(product)}</strong><Text size="1" color="gray">{t("共 {count} 个 SKU", { count: product.sku_count })}</Text></div>
      </div>
      <div className="reseller-sku-list-heading"><Heading size="4">{t("SKU 规格")}</Heading><Text size="1" color="gray">{t("以下价格已应用当前子账号的代理规则")}</Text></div>
      <div className="reseller-sku-list">{product.skus.map((sku) => <SkuRow key={sku.id} sku={sku} t={t} />)}</div>
    </div>
  );
}

function SkuRow({ sku, t }: { sku: Sku; t: (value: string, variables?: Record<string, string | number>) => string }) {
  const optionText = Object.entries(sku.option_values || {}).filter(([, value]) => value !== null && value !== undefined && String(value).trim()).map(([name, value]) => `${name}: ${String(value)}`).join(" · ");
  return <div className="reseller-sku-row"><div><strong>{sku.name || sku.sku_code}</strong><small className="mono-text">{sku.sku_code}</small>{optionText ? <Text size="1" color="gray">{optionText}</Text> : null}</div><span>{sku.stock === null || sku.stock === undefined ? null : <Badge color={sku.stock > 0 ? "jade" : "gray"}>{t("库存 {count}", { count: sku.stock })}</Badge>}</span><strong>{money(sku.price, sku.currency || "CNY")}</strong></div>;
}

function formatPriceRange(product: StoreProduct) {
  const from = Number(product.price_from);
  const to = Number(product.price_to);
  if (!Number.isFinite(from) || !Number.isFinite(to)) return money(product.price_from, product.currency);
  if (from === to) return money(from, product.currency);
  return `${money(from, product.currency)} – ${money(to, product.currency)}`;
}
