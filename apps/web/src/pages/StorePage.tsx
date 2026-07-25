import {
  Badge,
  Button,
  Container,
  Heading,
  IconButton,
  Select,
  Separator,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowCounterClockwise,
  MagnifyingGlass,
  SlidersHorizontal,
  Sparkle,
  Storefront as StoreIcon,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLoaderData } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { ProductCard } from "../components/ProductCard";
import { EmptyState, ErrorState, ProductGridSkeleton } from "../components/States";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import type { Sku, Storefront } from "../types";

export function StorePage() {
  const loadedStore = useLoaderData() as Storefront;
  const tenantSlug = loadedStore.slug;
  const [store, setStore] = useState<Storefront>(loadedStore);
  const [skus, setSkus] = useState<Sku[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [deferredSearch, setDeferredSearch] = useState("");
  const [primaryCategory, setPrimaryCategory] = useState("");
  const [secondaryCategory, setSecondaryCategory] = useState("");
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [semantic, setSemantic] = useState(true);
  const [cart, setCart] = useState<Record<string, CartLine>>({});
  const requestId = useRef(0);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDeferredSearch(search.trim()), 280);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    setStore(loadedStore);
    setSearch("");
    setDeferredSearch("");
    setPrimaryCategory("");
    setSecondaryCategory("");
    setSelectedTags([]);
    setCart({});
  }, [loadedStore]);

  const category = secondaryCategory || primaryCategory;

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${loadedStore.name} | 智贸云`;
    return () => {
      document.title = previousTitle;
    };
  }, [loadedStore.name]);

  const loadSkus = useCallback(async (targetPage = 1, append = false) => {
    const currentRequest = ++requestId.current;
    if (append) setLoadingMore(true);
    else setLoading(true);
    setError("");
    try {
      const data = await api.getStoreSkus(tenantSlug, {
        q: deferredSearch,
        category: category || undefined,
        tags: selectedTags,
        semantic: Boolean(deferredSearch) && semantic,
        page: targetPage,
      });
      if (currentRequest !== requestId.current) return;
      setSkus((current) => append ? [...current, ...data.items] : data.items);
      setTotal(data.total);
      setPage(targetPage);
      setStore((current) => current ? {
        ...current,
        categories: current.categories?.length ? current.categories : data.categories,
        tags: current.tags?.length ? current.tags : data.tags,
      } : current);
    } catch (caught) {
      if (currentRequest !== requestId.current) return;
      setError(caught instanceof Error ? caught.message : "商品加载失败。");
      if (!append) setSkus([]);
    } finally {
      if (currentRequest === requestId.current) {
        setLoading(false);
        setLoadingMore(false);
      }
    }
  }, [tenantSlug, deferredSearch, category, selectedTags, semantic]);

  useEffect(() => { setPage(1); void loadSkus(1, false); }, [loadSkus]);

  const categories = useMemo(() => {
    if (store?.categories?.length) return store.categories;
    return Array.from(new Set(skus.map((sku) => sku.category).filter(Boolean))) as string[];
  }, [store?.categories, skus]);
  const categoryTree = useMemo(() => {
    const nodes = new Map<string, { name: string; path: string; children: Array<{ name: string; path: string }> }>();
    categories.forEach((categoryPath) => {
      const [primary, secondary] = categoryPath.replace("／", "/").split("/").map((part) => part.trim());
      if (!primary) return;
      const node = nodes.get(primary) ?? { name: primary, path: primary, children: [] };
      if (secondary && !node.children.some((child) => child.name === secondary)) {
        node.children.push({ name: secondary, path: `${primary}/${secondary}` });
      }
      nodes.set(primary, node);
    });
    return Array.from(nodes.values());
  }, [categories]);
  const secondaryOptions = useMemo(
    () => categoryTree.find((node) => node.path === primaryCategory)?.children ?? [],
    [categoryTree, primaryCategory],
  );
  const tags = useMemo(() => {
    if (store?.tags?.length) return store.tags.slice(0, 10);
    return Array.from(new Set(skus.flatMap((sku) => sku.tags))).slice(0, 10);
  }, [store?.tags, skus]);
  const hasFilters = Boolean(search || category || selectedTags.length);
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const cartSkuCount = cartLines.length;

  const toggleTag = (tag: string) => {
    setSelectedTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  };
  const resetFilters = () => {
    setSearch("");
    setPrimaryCategory("");
    setSecondaryCategory("");
    setSelectedTags([]);
  };
  const addToCart = (sku: Sku) => {
    setCart((current) => ({
      ...current,
      [sku.id]: { sku, quantity: current[sku.id] ? current[sku.id].quantity + 1 : 1 },
    }));
  };
  const updateQuantity = (skuId: string, quantity: number) => {
    setCart((current) => {
      const next = { ...current };
      if (quantity < 1) delete next[skuId];
      else next[skuId] = { ...next[skuId], quantity };
      return next;
    });
  };

  return (
    <div className={`store-shell${cartSkuCount > 0 ? " has-cart" : ""}`}>
      <header className="store-header">
        <Container size="4" className="store-header-container">
          <div className="header-inner">
            <div className="store-header-branding">
              <Link to={`/${encodeURIComponent(tenantSlug)}`} className="store-identity" aria-label={`${store.name} 商品目录首页`}>
                {store.logo_url ? (
                  <img src={store.logo_url} alt={`${store.name} 标志`} />
                ) : (
                  <span className="store-identity-mark"><StoreIcon size={21} weight="duotone" /></span>
                )}
                <span>
                  <strong>{store.name}</strong>
                  <small>SKU 商品目录</small>
                </span>
              </Link>
              <span className="powered-by">由智贸云提供</span>
            </div>
            <div className="header-actions">
              <ThemeToggle />
              <CartDrawer
                slug={tenantSlug}
                storeName={store.name}
                contactEmail={store.contact_email}
                lines={cartLines}
                onQuantity={updateQuantity}
                onClear={() => setCart({})}
              />
            </div>
          </div>
        </Container>
      </header>

      <main>
        <section className="catalog-section">
          <Container size="4">
            <div className="filter-panel">
              <div className="filter-panel-heading">
                <div>
                  <Text size="2" weight="medium">查找商品</Text>
                  <Text size="1" color="gray">可按 SKU、名称、规格、类目或标签组合筛选</Text>
                </div>
                {hasFilters && (
                  <Button size="1" variant="ghost" color="gray" onClick={resetFilters}>
                    <ArrowCounterClockwise size={15} />清除筛选
                  </Button>
                )}
              </div>
              <div className="search-row">
                <TextField.Root
                  size="3"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索 SKU、名称、规格或使用场景"
                  aria-label="搜索商品"
                  className="store-search"
                >
                  <TextField.Slot><MagnifyingGlass size={19} /></TextField.Slot>
                  {search && (
                    <TextField.Slot side="right">
                      <IconButton
                        type="button"
                        size="1"
                        variant="ghost"
                        color="gray"
                        aria-label="清除搜索"
                        onClick={() => setSearch("")}
                      >
                        <X size={15} />
                      </IconButton>
                    </TextField.Slot>
                  )}
                </TextField.Root>
                <div className="category-cascade" aria-label="按两级分类筛选">
                  <Select.Root
                    value={primaryCategory || "all-primary"}
                    onValueChange={(value) => {
                      setPrimaryCategory(value === "all-primary" ? "" : value);
                      setSecondaryCategory("");
                    }}
                  >
                    <Select.Trigger className="category-select" aria-label="选择一级分类" />
                    <Select.Content>
                      <Select.Item value="all-primary">全部一级分类</Select.Item>
                      {categoryTree.map((item) => <Select.Item value={item.path} key={item.path}>{item.name}</Select.Item>)}
                    </Select.Content>
                  </Select.Root>
                  <Select.Root
                    value={secondaryCategory || "all-secondary"}
                    disabled={!primaryCategory || !secondaryOptions.length}
                    onValueChange={(value) => setSecondaryCategory(value === "all-secondary" ? "" : value)}
                  >
                    <Select.Trigger className="category-select" aria-label="选择二级分类" />
                    <Select.Content>
                      <Select.Item value="all-secondary">{!primaryCategory ? "请先选择一级分类" : secondaryOptions.length ? "全部二级分类" : "该分类没有二级"}</Select.Item>
                      {secondaryOptions.map((item) => <Select.Item value={item.path} key={item.path}>{item.name}</Select.Item>)}
                    </Select.Content>
                  </Select.Root>
                </div>
                <label className="semantic-toggle">
                  <Switch checked={Boolean(search.trim()) && semantic} onCheckedChange={setSemantic} disabled={!search.trim()} />
                  <span className="semantic-icon"><Sparkle size={17} /></span>
                  <span className="semantic-copy"><Text size="2" weight="medium">智能扩展</Text><Text size="1" color="gray">补充相关标签</Text></span>
                </label>
              </div>
              {tags.length > 0 && (
                <div className="tag-filter-row">
                  <span className="filter-label"><SlidersHorizontal size={17} /><Text size="2" color="gray">快捷标签</Text></span>
                  <div className="filter-tags">
                    {tags.map((tag) => (
                      <Button key={tag} title={tag} size="1" variant={selectedTags.includes(tag) ? "solid" : "soft"} color={selectedTags.includes(tag) ? "jade" : "gray"} onClick={() => toggleTag(tag)}>
                        {tag}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="results-header">
              <div>
                <Heading as="h2" size="5">{hasFilters ? "筛选结果" : "全部 SKU"}</Heading>
                <Text size="2" color="gray">在商品卡片上直接加入清单或调整数量。</Text>
              </div>
              <Badge color={hasFilters ? "jade" : "gray"} variant="soft" aria-live="polite">
                {loading ? "正在查找" : `${total.toLocaleString("zh-CN")} 条结果`}
              </Badge>
            </div>
            <Separator size="4" />

            <div className="results-body">
              {loading ? (
                <ProductGridSkeleton />
              ) : error ? (
                <ErrorState message={error} onRetry={() => void loadSkus(1, false)} />
              ) : skus.length === 0 ? (
                <EmptyState
                  title="没有匹配的 SKU"
                  description="换一个关键词或减少筛选标签，再试一次。"
                  action={hasFilters ? <Button variant="soft" onClick={resetFilters}>清除筛选</Button> : undefined}
                />
              ) : (
                <div className="sku-grid">
                  {skus.map((sku) => (
                    <ProductCard
                      key={sku.id}
                      sku={sku}
                      quantity={cart[sku.id]?.quantity || 0}
                      onAdd={() => addToCart(sku)}
                      onDecrease={() => updateQuantity(sku.id, (cart[sku.id]?.quantity || 0) - 1)}
                    />
                  ))}
                </div>
              )}
              {!loading && !error && skus.length > 0 && skus.length < total && (
                <div className="load-more-row">
                  <progress max={total} value={skus.length} aria-label={`已显示 ${skus.length} 个，共 ${total} 个 SKU`} />
                  <Button variant="soft" size="3" loading={loadingMore} onClick={() => void loadSkus(page + 1, true)}>
                    继续加载
                  </Button>
                  <Text size="1" color="gray">已显示 {skus.length.toLocaleString("zh-CN")} / {total.toLocaleString("zh-CN")}</Text>
                </div>
              )}
            </div>
          </Container>
        </section>
      </main>
      <footer className="store-footer">
        <Container size="4">
          <div className="store-footer-inner">
            <Text size="1" color="gray">商品与报价由 {store.name} 提供，报价草稿须经商家确认。</Text>
            <Link to="/privacy">隐私政策</Link>
          </div>
        </Container>
      </footer>
    </div>
  );
}
