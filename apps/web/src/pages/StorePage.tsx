import {
  Badge,
  Button,
  Container,
  Heading,
  IconButton,
  Separator,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowCounterClockwise,
  CaretDown,
  CaretLeft,
  CaretRight,
  Columns,
  Fire,
  MagnifyingGlass,
  Rows,
  Storefront as StoreIcon,
  X,
} from "@phosphor-icons/react";
import { ThinkingOrb } from "thinking-orbs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLoaderData } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { ProductCard } from "../components/ProductCard";
import { EmptyState, ErrorState, ProductGridSkeleton } from "../components/States";
import { StorefrontAnnouncements } from "../components/StorefrontAnnouncements";
import { StorefrontSupportWidget } from "../components/StorefrontSupportWidget";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { subscribePublicCatalogRevision } from "../lib/publicCatalogRevision";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import {
  normalizeStorefrontLocale,
  storefrontDirection,
  storefrontLocaleQuery,
  storefrontText,
} from "../lib/storefrontLocale";
import { readStorefrontViewState, writeStorefrontViewState } from "../lib/storefrontViewState";
import type { StoreProduct, Storefront, StorefrontLocale } from "../types";

type PaginationItem = number | "start-ellipsis" | "end-ellipsis";

function importProductDetailModule() {
  return import("./ProductDetailPage");
}

let productDetailModulePromise: ReturnType<
  typeof importProductDetailModule
> | null = null;

function preloadProductDetailModule() {
  if (!productDetailModulePromise) {
    productDetailModulePromise = importProductDetailModule().catch((error) => {
      productDetailModulePromise = null;
      throw error;
    });
  }
  return productDetailModulePromise;
}

function paginationItems(currentPage: number, pageCount: number): PaginationItem[] {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "end-ellipsis", pageCount];
  }
  if (currentPage >= pageCount - 3) {
    return [1, "start-ellipsis", pageCount - 4, pageCount - 3, pageCount - 2, pageCount - 1, pageCount];
  }
  return [1, "start-ellipsis", currentPage - 1, currentPage, currentPage + 1, "end-ellipsis", pageCount];
}

function hidePaginationItemOnMobile(index: number, currentPage: number, pageCount: number) {
  if (pageCount <= 7) return false;
  if (currentPage <= 4) return index === 3 || index === 4;
  if (currentPage >= pageCount - 3) return index === 2 || index === 3;
  return index === 2 || index === 4;
}

function CategoryScrollTrack({
  ariaLabel,
  contentKey,
  locale,
  children,
}: {
  ariaLabel: string;
  contentKey: string;
  locale: StorefrontLocale;
  children: ReactNode;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [scrollState, setScrollState] = useState({ left: false, right: false });

  const updateScrollState = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const maxScrollLeft = Math.max(0, track.scrollWidth - track.clientWidth);
    const next = {
      left: track.scrollLeft > 2,
      right: track.scrollLeft < maxScrollLeft - 2,
    };
    setScrollState((current) => (
      current.left === next.left && current.right === next.right ? current : next
    ));
  }, []);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    track.scrollTo({ left: 0 });
    const frame = window.requestAnimationFrame(updateScrollState);
    track.addEventListener("scroll", updateScrollState, { passive: true });
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(updateScrollState);
    resizeObserver?.observe(track);
    return () => {
      window.cancelAnimationFrame(frame);
      track.removeEventListener("scroll", updateScrollState);
      resizeObserver?.disconnect();
    };
  }, [contentKey, updateScrollState]);

  const scrollByItem = (direction: -1 | 1) => {
    const track = trackRef.current;
    if (!track) return;
    const options = Array.from(
      track.querySelectorAll<HTMLElement>(".category-browser-option"),
    );
    const leadingInset = options[0]?.offsetLeft ?? 0;
    const currentLeadingEdge = track.scrollLeft + leadingInset;
    const target = direction > 0
      ? options.find((option) => option.offsetLeft > currentLeadingEdge + 4)
      : [...options].reverse().find((option) => option.offsetLeft < currentLeadingEdge - 4);
    const maxScrollLeft = Math.max(0, track.scrollWidth - track.clientWidth);
    const fallbackStep = Math.min(140, Math.max(72, track.clientWidth * 0.32));
    const targetLeft = target
      ? target.offsetLeft - leadingInset
      : track.scrollLeft + direction * fallbackStep;
    const maxStep = Math.min(120, Math.max(72, track.clientWidth * 0.3));
    const targetDelta = targetLeft - track.scrollLeft;
    const nextLeft = track.scrollLeft
      + Math.sign(targetDelta) * Math.min(Math.abs(targetDelta), maxStep);
    track.scrollTo({
      left: Math.max(0, Math.min(maxScrollLeft, nextLeft)),
      behavior: "smooth",
    });
  };

  return (
    <div className="category-browser-track-shell">
      {scrollState.left && (
        <button
          type="button"
          className="category-browser-scroll-button is-left"
          aria-label={`${storefrontText(locale, "上一页")} · ${ariaLabel}`}
          onClick={() => scrollByItem(-1)}
        >
          <CaretLeft weight="bold" />
        </button>
      )}
      <div className="category-browser-track" role="group" aria-label={ariaLabel} ref={trackRef}>
        {children}
      </div>
      {scrollState.right && (
        <button
          type="button"
          className="category-browser-scroll-button is-right"
          aria-label={`${storefrontText(locale, "下一页")} · ${ariaLabel}`}
          onClick={() => scrollByItem(1)}
        >
          <CaretRight weight="bold" />
        </button>
      )}
    </div>
  );
}

export function StorePage() {
  const loadedStore = useLoaderData() as Storefront;
  const tenantSlug = loadedStore.slug;
  const locale: StorefrontLocale = normalizeStorefrontLocale(loadedStore.locale);
  const t = useCallback(
    (source: string, values?: Record<string, string | number>) => (
      storefrontText(locale, source, values)
    ),
    [locale],
  );
  const localeQuery = storefrontLocaleQuery(locale);
  const storefrontHome = `/${encodeURIComponent(tenantSlug)}${localeQuery}`;
  const [initialView] = useState(() => readStorefrontViewState(loadedStore.slug));
  const [store, setStore] = useState<Storefront>(loadedStore);
  const [products, setProducts] = useState<StoreProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(initialView?.page ?? 1);
  const [pages, setPages] = useState(0);
  const [error, setError] = useState("");
  const [search, setSearch] = useState(initialView?.search ?? "");
  const [deferredSearch, setDeferredSearch] = useState(initialView?.search.trim() ?? "");
  const [primaryCategory, setPrimaryCategory] = useState(initialView?.primaryCategory ?? "");
  const [secondaryCategory, setSecondaryCategory] = useState(initialView?.secondaryCategory ?? "");
  const [categoryLayout, setCategoryLayout] = useState<"horizontal" | "vertical">(
    initialView?.categoryLayout ?? "horizontal",
  );
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    () => new Set(initialView?.expandedCategories ?? []),
  );
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(loadedStore.slug),
  );
  const [cartTenant, setCartTenant] = useState(loadedStore.slug);
  const requestId = useRef(0);
  const resultsHeaderRef = useRef<HTMLDivElement>(null);
  const paginationRef = useRef<HTMLElement>(null);
  const activeTenantRef = useRef(loadedStore.slug);
  const activeLocaleRef = useRef<StorefrontLocale>(locale);
  const facetsLoadedRef = useRef(Boolean(loadedStore.categories?.length));
  const initialLoadPageRef = useRef<number | null>(initialView?.page ?? 1);
  const pendingScrollRestoreRef = useRef<number | null>(initialView?.scrollY ?? null);

  useEffect(() => {
    const timeout = window.setTimeout(() => setDeferredSearch(search.trim()), 280);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    setStore(loadedStore);
    const tenantChanged = activeTenantRef.current !== loadedStore.slug;
    const localeChanged = activeLocaleRef.current !== locale;
    if (!tenantChanged && !localeChanged) return;
    activeTenantRef.current = loadedStore.slug;
    activeLocaleRef.current = locale;
    facetsLoadedRef.current = false;
    const nextView = readStorefrontViewState(loadedStore.slug);
    setSearch(nextView?.search ?? "");
    setDeferredSearch(nextView?.search.trim() ?? "");
    setPrimaryCategory(nextView?.primaryCategory ?? "");
    setSecondaryCategory(nextView?.secondaryCategory ?? "");
    setCategoryLayout(nextView?.categoryLayout ?? "horizontal");
    setExpandedCategories(new Set(nextView?.expandedCategories ?? []));
    if (tenantChanged) {
      setCart(readStoreCart(loadedStore.slug));
      setCartTenant(loadedStore.slug);
    }
    initialLoadPageRef.current = nextView?.page ?? 1;
    pendingScrollRestoreRef.current = nextView?.scrollY ?? null;
    setPage(nextView?.page ?? 1);
    setPages(0);
  }, [loadedStore, locale]);

  useEffect(() => {
    if (cartTenant === tenantSlug) writeStoreCart(tenantSlug, cart);
  }, [cart, cartTenant, tenantSlug]);

  const category = secondaryCategory || primaryCategory;

  useEffect(() => {
    const previousTitle = document.title;
    const previousLanguage = document.documentElement.lang;
    const previousDirection = document.documentElement.dir;
    document.documentElement.lang = locale;
    document.documentElement.dir = storefrontDirection(locale);
    document.title = `${loadedStore.name} | 智贸云`;
    return () => {
      document.title = previousTitle;
      document.documentElement.lang = previousLanguage;
      document.documentElement.dir = previousDirection;
    };
  }, [loadedStore.name, locale]);

  const loadProducts = useCallback(async (targetPage = 1) => {
    const currentRequest = ++requestId.current;
    const includeFacets = !facetsLoadedRef.current;
    setPage(targetPage);
    setLoading(true);
    setError("");
    try {
      const data = await api.getStoreProducts(tenantSlug, {
        q: deferredSearch,
        category: category || undefined,
        semantic: Boolean(deferredSearch),
        includeFacets,
        page: targetPage,
        locale,
      });
      if (currentRequest !== requestId.current) return;
      if (includeFacets) facetsLoadedRef.current = true;
      setProducts(data.items);
      setTotal(data.total);
      setPage(data.page ?? targetPage);
      setPages(data.pages ?? Math.ceil(data.total / 24));
      setStore((current) => current ? {
        ...current,
        categories: data.categories?.length ? data.categories : current.categories,
        category_options: data.category_options?.length
          ? data.category_options
          : current.category_options,
        tags: data.tags?.length ? data.tags : current.tags,
        all_products_position: includeFacets
          ? data.all_products_position ?? current.all_products_position ?? 0
          : current.all_products_position,
        hot_products_enabled: data.hot_products_enabled
          ?? current.hot_products_enabled
          ?? false,
      } : current);
    } catch (caught) {
      if (currentRequest !== requestId.current) return;
      setError(caught instanceof Error ? caught.message : t("商品加载失败。"));
      setProducts([]);
    } finally {
      if (currentRequest === requestId.current) {
        setLoading(false);
      }
    }
  }, [tenantSlug, deferredSearch, category, locale, t]);

  useEffect(() => {
    const targetPage = initialLoadPageRef.current ?? 1;
    void loadProducts(targetPage);
  }, [loadProducts]);

  useEffect(
    () => subscribePublicCatalogRevision(() => {
      facetsLoadedRef.current = false;
      void api.getStore(tenantSlug, locale)
        .then((nextStore) => setStore(nextStore))
        .catch(() => undefined);
      void loadProducts(page);
    }),
    [loadProducts, locale, page, tenantSlug],
  );

  useEffect(() => {
    if (!loading) initialLoadPageRef.current = null;
  }, [loading]);

  useEffect(() => {
    const sourceLocale = store.source_locale ?? "zh-CN";
    if (
      loading
      || error
      || page < 1
      || page >= pages
      || locale === sourceLocale
    ) {
      return;
    }
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (connection?.saveData) return;

    const prefetch = () => {
      if (document.visibilityState !== "visible") return;
      void api.prefetchStoreProducts(tenantSlug, {
        q: deferredSearch,
        category: category || undefined,
        semantic: Boolean(deferredSearch),
        includeFacets: false,
        page: page + 1,
        locale,
      }).catch(() => undefined);
    };
    const target = paginationRef.current;
    if (!target || typeof IntersectionObserver === "undefined") {
      const timeout = window.setTimeout(prefetch, 1_500);
      return () => window.clearTimeout(timeout);
    }
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();
        prefetch();
      },
      { rootMargin: "700px 0px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [
    category,
    deferredSearch,
    error,
    loading,
    locale,
    page,
    pages,
    store.source_locale,
    tenantSlug,
  ]);

  useEffect(() => {
    if (loading || pendingScrollRestoreRef.current === null) return;
    const targetScrollY = pendingScrollRestoreRef.current;
    pendingScrollRestoreRef.current = null;
    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        window.scrollTo({ top: targetScrollY, left: 0, behavior: "auto" });
      });
    });
    return () => {
      window.cancelAnimationFrame(firstFrame);
      if (secondFrame) window.cancelAnimationFrame(secondFrame);
    };
  }, [loading, page, products.length]);

  const prefetchProductDetails = useCallback(
    (productId: string) => {
      void preloadProductDetailModule().catch(() => undefined);
      void api.prefetchStoreProduct(tenantSlug, productId, locale)
        .catch(() => undefined);
    },
    [locale, tenantSlug],
  );

  useEffect(() => {
    if (loading || error || products.length === 0) return;
    void preloadProductDetailModule().catch(() => undefined);

    const sourceLocale = store.source_locale ?? "zh-CN";
    const connection = (
      navigator as Navigator & { connection?: { saveData?: boolean } }
    ).connection;
    if (locale !== sourceLocale || connection?.saveData) return;

    // Warm only the first visible row after the catalog itself is usable.
    // Intent prefetch below covers every other card without turning one page
    // view into 24 detail requests.
    const timer = window.setTimeout(() => {
      void Promise.allSettled(
        products.slice(0, 3).map((product) => (
          api.prefetchStoreProduct(tenantSlug, product.id, locale)
        )),
      );
    }, 280);
    return () => window.clearTimeout(timer);
  }, [
    error,
    loading,
    locale,
    products,
    store.source_locale,
    tenantSlug,
  ]);

  const categories = useMemo(() => {
    if (store?.categories?.length) return store.categories;
    return Array.from(
      new Set(products.map((product) => product.category).filter(Boolean)),
    ) as string[];
  }, [store?.categories, products]);
  const categoryOptions = useMemo(() => {
    const configured = store.category_options ?? [];
    const labelByValue = new Map(
      configured.map((option) => [option.value, option.label]),
    );
    return categories.map((value) => ({
      value,
      label: labelByValue.get(value) ?? value,
    }));
  }, [categories, store.category_options]);
  const categoryTree = useMemo(() => {
    const nodes = new Map<string, { name: string; path: string; children: Array<{ name: string; path: string }> }>();
    categoryOptions.forEach(({ value, label }) => {
      const [primaryValue, secondaryValue] = value.replace("／", "/").split("/").map((part) => part.trim());
      const [primaryLabel, secondaryLabel] = label.replace("／", "/").split("/").map((part) => part.trim());
      if (!primaryValue) return;
      const node = nodes.get(primaryValue) ?? {
        name: primaryLabel || primaryValue,
        path: primaryValue,
        children: [],
      };
      if (secondaryValue && !node.children.some((child) => child.path === value)) {
        node.children.push({
          name: secondaryLabel || secondaryValue,
          path: value,
        });
      }
      nodes.set(primaryValue, node);
    });
    return Array.from(nodes.values());
  }, [categoryOptions]);
  const primaryNavigationItems = useMemo(() => {
    const position = Math.max(
      0,
      Math.min(store.all_products_position ?? 0, categoryTree.length),
    );
    const items: Array<
      | { kind: "all"; key: "all" }
      | { kind: "category"; key: string; node: (typeof categoryTree)[number] }
    > = categoryTree.map((node) => ({
      kind: "category",
      key: node.path,
      node,
    }));
    items.splice(position, 0, { kind: "all", key: "all" });
    return items;
  }, [categoryTree, store.all_products_position]);
  const secondaryOptions = useMemo(
    () => categoryTree.find((node) => node.path === primaryCategory)?.children ?? [],
    [categoryTree, primaryCategory],
  );
  const visibleSecondaryOptions = useMemo(
    () => {
      if (primaryCategory) {
        const parent = categoryTree.find((node) => node.path === primaryCategory);
        return (parent?.children ?? []).map((child) => ({
          ...child,
          parentName: parent?.name ?? "",
          parentPath: parent?.path ?? "",
        }));
      }
      return categoryTree.flatMap((parent) => parent.children.map((child) => ({
        ...child,
        parentName: parent.name,
        parentPath: parent.path,
      })));
    },
    [categoryTree, primaryCategory],
  );
  const hasFilters = Boolean(search || category);
  const hotSortActive = Boolean(store.hot_products_enabled && !hasFilters);
  const searchPending = Boolean(search.trim()) && (
    search.trim() !== deferredSearch || loading
  );
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const cartSkuCount = cartLines.length;
  const visiblePaginationItems = useMemo(() => paginationItems(page, pages), [page, pages]);

  const resetFilters = () => {
    setSearch("");
    setPrimaryCategory("");
    setSecondaryCategory("");
  };
  const toggleCategoryExpansion = (categoryPath: string) => {
    setExpandedCategories((current) => {
      const next = new Set(current);
      if (next.has(categoryPath)) {
        next.delete(categoryPath);
      } else {
        next.add(categoryPath);
      }
      return next;
    });
  };
  const updateQuantity = (skuId: string, quantity: number) => {
    setCart((current) => {
      const next = { ...current };
      if (quantity < 1) delete next[skuId];
      else next[skuId] = { ...next[skuId], quantity };
      return next;
    });
  };
  const rememberCatalogPosition = () => {
    writeStorefrontViewState(tenantSlug, {
      page,
      scrollY: window.scrollY,
      search,
      primaryCategory,
      secondaryCategory,
      categoryLayout,
      expandedCategories: Array.from(expandedCategories),
    });
  };
  const goToPage = (targetPage: number) => {
    if (loading || targetPage === page || targetPage < 1 || targetPage > pages) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsHeaderRef.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });
    void loadProducts(targetPage);
  };

  return (
    <div
      className={`store-shell${cartSkuCount > 0 ? " has-cart" : ""}`}
      dir={storefrontDirection(locale)}
    >
      <header className="store-header">
        <Container size="4" className="store-header-container">
          <div className="header-inner">
            <div className="store-header-branding">
              <Link
                to={storefrontHome}
                className="store-identity"
                aria-label={t("{store} 商品目录首页", { store: store.name })}
              >
                {store.logo_url ? (
                  <img src={store.logo_url} alt={t("{store} 标志", { store: store.name })} />
                ) : (
                  <span className="store-identity-mark"><StoreIcon size={21} weight="duotone" /></span>
                )}
                <span>
                  <strong>{store.name}</strong>
                  <small>{t("商品目录")}</small>
                </span>
              </Link>
              <span className="powered-by">{t("由智贸云提供")}</span>
            </div>
            <div className="header-actions">
              <StorefrontLanguageSwitch
                locale={locale}
                availableLocales={store.available_locales}
                onBeforeLocaleChange={rememberCatalogPosition}
              />
              <ThemeToggle
                labels={{
                  toDark: t("切换深色模式"),
                  toLight: t("切换浅色模式"),
                }}
              />
              <CartDrawer
                slug={tenantSlug}
                storeName={store.name}
                contactEmail={store.contact_email}
                lines={cartLines}
                onQuantity={updateQuantity}
                onClear={() => setCart({})}
                locale={locale}
              />
            </div>
          </div>
        </Container>
      </header>

      <StorefrontAnnouncements
        announcements={store.announcements || []}
        tenantSlug={tenantSlug}
        locale={locale}
      />

      <main>
        <section className="catalog-section">
          <Container size="4">
            <div className="filter-panel">
              <div className="filter-panel-heading">
                <div>
                  <Text size="2" weight="medium">{t("查找商品")}</Text>
                  <Text size="1" color="gray">{t("输入 SKU、商品特征或使用场景，AI 会结合类目与标签查找")}</Text>
                </div>
                <div className="filter-panel-actions">
                  <Button
                    type="button"
                    size="1"
                    variant="soft"
                    color="gray"
                    aria-label={t(categoryLayout === "horizontal" ? "切换到左侧分类" : "切换到顶部分类")}
                    title={t(categoryLayout === "horizontal" ? "切换到左侧分类" : "切换到顶部分类")}
                    onClick={() => setCategoryLayout(categoryLayout === "horizontal" ? "vertical" : "horizontal")}
                  >
                    {categoryLayout === "horizontal" ? <Columns size={15} weight="duotone" /> : <Rows size={15} weight="duotone" />}
                    {t(categoryLayout === "horizontal" ? "左侧分类" : "顶部分类")}
                  </Button>
                  {hasFilters && (
                    <Button className="filter-reset-button" size="1" variant="ghost" color="gray" onClick={resetFilters}>
                      <ArrowCounterClockwise size={15} />{t("清除筛选")}
                    </Button>
                  )}
                </div>
              </div>
              <div className="search-row">
                <TextField.Root
                  size="3"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t("搜索 SKU、名称、规格或使用场景")}
                  aria-label={t("查找商品")}
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
                        aria-label={t("清除搜索")}
                        onClick={() => setSearch("")}
                      >
                        <X size={15} />
                      </IconButton>
                    </TextField.Slot>
                  )}
                </TextField.Root>
              </div>
              <nav className="category-browser" aria-label={t("按两级分类筛选")}>
                {categoryLayout === "horizontal" ? (
                  <>
                    <div className="category-browser-row">
                      <span className="category-browser-label">{t("一级分类")}</span>
                      <CategoryScrollTrack
                        ariaLabel={t("一级分类")}
                        contentKey={primaryNavigationItems.map((item) => item.key).join("|")}
                        locale={locale}
                      >
                        {primaryNavigationItems.map((item) => item.kind === "all" ? (
                          <button
                            type="button"
                            className={`category-browser-option${!primaryCategory ? " is-active" : ""}`}
                            aria-pressed={!primaryCategory}
                            onClick={() => {
                              setPrimaryCategory("");
                              setSecondaryCategory("");
                            }}
                            key={item.key}
                          >
                            {t("全部商品")}
                          </button>
                        ) : (
                          <button
                            type="button"
                            className={`category-browser-option${primaryCategory === item.node.path ? " is-active" : ""}`}
                            aria-pressed={primaryCategory === item.node.path}
                            onClick={() => {
                              setPrimaryCategory(item.node.path);
                              setSecondaryCategory("");
                            }}
                            key={item.key}
                          >
                            {item.node.name}
                          </button>
                        ))}
                      </CategoryScrollTrack>
                    </div>
                    <div className="category-browser-row">
                      <span className="category-browser-label">{t("二级分类")}</span>
                      <CategoryScrollTrack
                        ariaLabel={t("二级分类")}
                        contentKey={`${primaryCategory}|${visibleSecondaryOptions.map((item) => item.path).join("|")}`}
                        locale={locale}
                      >
                        <button
                          type="button"
                          className={`category-browser-option${!secondaryCategory ? " is-active" : ""}`}
                          aria-pressed={!secondaryCategory}
                          onClick={() => setSecondaryCategory("")}
                        >
                          {t("全部二级")}
                        </button>
                        {visibleSecondaryOptions.map((item) => (
                          <button
                            type="button"
                            className={`category-browser-option${secondaryCategory === item.path ? " is-active" : ""}`}
                            aria-pressed={secondaryCategory === item.path}
                            title={primaryCategory ? item.name : `${item.parentName} / ${item.name}`}
                            onClick={() => {
                              setPrimaryCategory(item.parentPath);
                              setSecondaryCategory(item.path);
                            }}
                            key={item.path}
                          >
                            {primaryCategory ? item.name : `${item.parentName} · ${item.name}`}
                          </button>
                        ))}
                        {!visibleSecondaryOptions.length && (
                          <span className="category-browser-empty">
                            {t(primaryCategory && !secondaryOptions.length ? "该分类暂无二级分类" : "暂无二级分类")}
                          </span>
                        )}
                      </CategoryScrollTrack>
                    </div>
                  </>
                ) : null}
              </nav>
            </div>

            <div className={`results-container${categoryLayout === "vertical" ? " has-sidebar" : ""}`}>
              {categoryLayout === "vertical" && (
                <aside className="category-sidebar">
                  <div className="category-sidebar-header">
                    <Text size="2" weight="medium">{t("商品分类")}</Text>
                  </div>
                  <nav className="category-sidebar-nav">
                    {primaryNavigationItems.map((item) => item.kind === "all" ? (
                      <button
                        type="button"
                        className={`category-sidebar-item is-all${!primaryCategory && !secondaryCategory ? " is-active" : ""}`}
                        onClick={() => {
                          setPrimaryCategory("");
                          setSecondaryCategory("");
                        }}
                        key={item.key}
                      >
                        <span>{t("全部商品")}</span>
                      </button>
                    ) : (
                      <div key={item.key} className="category-sidebar-group">
                        <button
                          type="button"
                          className={`category-sidebar-item is-primary${primaryCategory === item.node.path && !secondaryCategory ? " is-active" : ""}${item.node.children.length > 0 ? " has-children" : ""}`}
                          title={item.node.name}
                          onClick={() => {
                            if (item.node.children.length > 0) {
                              toggleCategoryExpansion(item.node.path);
                            }
                            setPrimaryCategory(item.node.path);
                            setSecondaryCategory("");
                          }}
                        >
                          <span>{item.node.name}</span>
                          {item.node.children.length > 0 && (
                            <CaretDown
                              size={14}
                              weight="bold"
                              className={expandedCategories.has(item.node.path) ? "is-expanded" : ""}
                            />
                          )}
                        </button>
                        {item.node.children.length > 0 && expandedCategories.has(item.node.path) && (
                          <div className="category-sidebar-children">
                            {item.node.children.map((child) => (
                              <button
                                type="button"
                                key={child.path}
                                className={`category-sidebar-item is-secondary${secondaryCategory === child.path ? " is-active" : ""}`}
                                title={child.name}
                                onClick={() => {
                                  setPrimaryCategory(item.node.path);
                                  setSecondaryCategory(child.path);
                                }}
                              >
                                <span>{child.name}</span>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </nav>
                </aside>
              )}
              <div className="results-main">
            <div className="results-header" ref={resultsHeaderRef}>
              <div>
                <div className="results-title-row">
                  <Heading as="h2" size="5">{t(hasFilters ? "筛选结果" : "全部商品")}</Heading>
                  {hotSortActive ? (
                    <Badge color="amber" variant="soft">
                      <Fire size={14} weight="fill" aria-hidden="true" />
                      {t("爆款优先")}
                    </Badge>
                  ) : null}
                </div>
                <Text size="2" color="gray">
                  {t(
                    hotSortActive
                      ? "根据近 90 天浏览与下单热度优先展示，手动置顶商品仍排在最前。"
                      : "点击商品查看可选规格与 SKU。",
                  )}
                </Text>
              </div>
              <Badge color={hasFilters ? "jade" : "gray"} variant="soft" aria-live="polite">
                {searchPending
                  ? t("搜索中……")
                  : loading
                    ? t("正在查找")
                  : t("{count} 条结果", { count: total.toLocaleString(locale) })}
              </Badge>
            </div>
            <Separator size="4" />

            <div className="results-body">
              {searchPending ? (
                <div className="store-search-feedback" role="status" aria-live="polite">
                  <ThinkingOrb
                    state="working"
                    size={64}
                    speed={1.3}
                    aria-hidden="true"
                  />
                  <Text size="3" weight="medium">{t("搜索中……")}</Text>
                </div>
              ) : loading ? (
                <ProductGridSkeleton />
              ) : error ? (
                <ErrorState message={error} onRetry={() => void loadProducts(page)} />
              ) : products.length === 0 ? (
                <EmptyState
                  title={t("没有匹配的商品")}
                  description={t("换一个关键词、使用场景或分类，再试一次。")}
                  action={hasFilters ? <Button variant="soft" onClick={resetFilters}>{t("清除筛选")}</Button> : undefined}
                />
              ) : (
                <div className="sku-grid">
                  {products.map((product) => (
                    <ProductCard
                      key={product.id}
                      product={product}
                      detailsHref={`/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(product.id)}${localeQuery}`}
                      onOpenDetails={rememberCatalogPosition}
                      onPrefetchDetails={() => prefetchProductDetails(product.id)}
                      locale={locale}
                    />
                  ))}
                </div>
              )}
              {!searchPending && !loading && !error && products.length > 0 && pages > 1 && (
                <nav
                  className="store-pagination"
                  aria-label={t("商品分页")}
                  ref={paginationRef}
                >
                  <Button
                    type="button"
                    size="2"
                    variant="soft"
                    color="gray"
                    disabled={page <= 1}
                    aria-label={t("上一页")}
                    onClick={() => goToPage(page - 1)}
                  >
                    <CaretLeft weight="bold" />
                    <span className="store-pagination-button-label">{t("上一页")}</span>
                  </Button>
                  <div className="store-pagination-pages">
                    {visiblePaginationItems.map((item, index) => (
                      typeof item === "number" ? (
                        <button
                          type="button"
                          className={`store-pagination-page${item === page ? " is-active" : ""}${hidePaginationItemOnMobile(index, page, pages) ? " is-mobile-hidden" : ""}`}
                          aria-label={t("第 {page} 页", { page: item })}
                          aria-current={item === page ? "page" : undefined}
                          disabled={loading}
                          onClick={() => goToPage(item)}
                          key={item}
                        >
                          {item}
                        </button>
                      ) : (
                        <span className="store-pagination-ellipsis" aria-hidden="true" key={item}>…</span>
                      )
                    ))}
                  </div>
                  <Button
                    type="button"
                    size="2"
                    variant="soft"
                    color="gray"
                    disabled={page >= pages}
                    aria-label={t("下一页")}
                    onClick={() => goToPage(page + 1)}
                  >
                    <span className="store-pagination-button-label">{t("下一页")}</span>
                    <CaretRight weight="bold" />
                  </Button>
                  <Text className="store-pagination-status" size="1" color="gray" aria-live="polite">
                    {t("第 {page} / {pages} 页", {
                      page: page.toLocaleString(locale),
                      pages: pages.toLocaleString(locale),
                    })}
                  </Text>
                </nav>
              )}
            </div>
              </div>
            </div>
          </Container>
        </section>
      </main>
      <StorefrontSupportWidget
        tenantSlug={tenantSlug}
        storeName={store.name}
        locale={locale}
        config={store.support_widget}
      />
      <footer className="store-footer">
        <Container size="4">
          <div className="store-footer-inner">
            <Text size="1" color="gray">{t("商品与报价由 {store} 提供，报价草稿须经商家确认。", { store: store.name })}</Text>
            <Link to="/privacy">{t("隐私政策")}</Link>
          </div>
        </Container>
      </footer>
    </div>
  );
}
