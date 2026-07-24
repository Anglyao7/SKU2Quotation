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
import { ArrowCounterClockwise, MagnifyingGlass, SlidersHorizontal, UserCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLoaderData } from "react-router-dom";
import { BRAND_NAME_ZH } from "../brand";
import { Brand } from "../components/Brand";
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
  const [category, setCategory] = useState("");
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
    setCategory("");
    setSelectedTags([]);
    setCart({});
  }, [loadedStore]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${loadedStore.name} | ${BRAND_NAME_ZH}`;
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
  const tags = useMemo(() => {
    if (store?.tags?.length) return store.tags.slice(0, 10);
    return Array.from(new Set(skus.flatMap((sku) => sku.tags))).slice(0, 10);
  }, [store?.tags, skus]);
  const hasFilters = Boolean(search || category || selectedTags.length);

  const toggleTag = (tag: string) => {
    setSelectedTags((current) => current.includes(tag) ? current.filter((item) => item !== tag) : [...current, tag]);
  };
  const resetFilters = () => {
    setSearch("");
    setCategory("");
    setSelectedTags([]);
  };
  const addToCart = (sku: Sku) => {
    setCart((current) => ({
      ...current,
      [sku.id]: { sku, quantity: current[sku.id] ? current[sku.id].quantity + 1 : Math.max(1, sku.moq || 1) },
    }));
  };
  const updateQuantity = (skuId: string, quantity: number) => {
    setCart((current) => {
      const next = { ...current };
      const minimum = current[skuId]?.sku.moq || 1;
      if (quantity < minimum) delete next[skuId];
      else next[skuId] = { ...next[skuId], quantity };
      return next;
    });
  };

  return (
    <div className="store-shell">
      <header className="store-header">
        <Container size="4" className="header-inner">
          <Brand />
          <div className="header-actions">
            <ThemeToggle />
            <Button asChild variant="ghost" color="gray" className="console-link">
              <Link to="/console"><UserCircle size={19} />商家控制台</Link>
            </Button>
            <CartDrawer
              slug={tenantSlug}
              lines={Object.values(cart)}
              onQuantity={updateQuantity}
              onClear={() => setCart({})}
            />
          </div>
        </Container>
      </header>

      <main>
        <section className="store-intro">
          <Container size="4">
            <div className="store-intro-grid">
              <div className="store-heading">
                <Text size="2" color="gray">{store?.name || "商品目录"}</Text>
                <Heading as="h1" size="8">直接按 SKU 选品</Heading>
                <Text size="3" color="gray">搜索商品、选择数量，然后生成可下载的客户报价单。</Text>
              </div>
              <div className="catalog-stat">
                <Text size="1" color="gray">当前目录</Text>
                <strong>{total.toLocaleString("zh-CN")}</strong>
                <Text size="2" color="gray">个可选 SKU</Text>
              </div>
            </div>
          </Container>
        </section>

        <section className="catalog-section">
          <Container size="4">
            <div className="filter-panel">
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
                </TextField.Root>
                <Select.Root value={category || "all"} onValueChange={(value) => setCategory(value === "all" ? "" : value)}>
                  <Select.Trigger className="category-select" aria-label="选择类目" />
                  <Select.Content>
                    <Select.Item value="all">全部类目</Select.Item>
                    {categories.map((item) => <Select.Item value={item} key={item}>{item}</Select.Item>)}
                  </Select.Content>
                </Select.Root>
                <label className="semantic-toggle">
                  <Switch checked={semantic} onCheckedChange={setSemantic} disabled={!search.trim()} />
                  <span><Text size="2" weight="medium">智能搜索</Text><Text size="1" color="gray">名称 / SKU / 标签扩展</Text></span>
                </label>
              </div>
              {tags.length > 0 && (
                <div className="tag-filter-row">
                  <span className="filter-label"><SlidersHorizontal size={17} /><Text size="2" color="gray">标签</Text></span>
                  <div className="filter-tags">
                    {tags.map((tag) => (
                      <Button key={tag} size="1" variant={selectedTags.includes(tag) ? "solid" : "soft"} color={selectedTags.includes(tag) ? "jade" : "gray"} onClick={() => toggleTag(tag)}>
                        {tag}
                      </Button>
                    ))}
                  </div>
                  {hasFilters && <Button size="1" variant="ghost" color="gray" onClick={resetFilters}><ArrowCounterClockwise size={15} />重置</Button>}
                </div>
              )}
            </div>

            <div className="results-header">
              <div>
                <Heading as="h2" size="5">SKU 列表</Heading>
                <Text size="2" color="gray">所有卡片都是可直接加入报价的独立 SKU。</Text>
              </div>
              {!loading && <Badge color="gray" variant="soft">{total.toLocaleString("zh-CN")} 条结果</Badge>}
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
                    <ProductCard key={sku.id} sku={sku} quantity={cart[sku.id]?.quantity || 0} onAdd={() => addToCart(sku)} />
                  ))}
                </div>
              )}
              {!loading && !error && skus.length > 0 && skus.length < total && (
                <div className="load-more-row">
                  <Button variant="soft" size="3" loading={loadingMore} onClick={() => void loadSkus(page + 1, true)}>
                    加载更多 SKU
                  </Button>
                  <Text size="1" color="gray">已显示 {skus.length.toLocaleString("zh-CN")} / {total.toLocaleString("zh-CN")}</Text>
                </div>
              )}
            </div>
          </Container>
        </section>
      </main>
    </div>
  );
}
