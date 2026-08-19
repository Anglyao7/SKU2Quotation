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
  FolderOpen,
  MagnifyingGlass,
  Rows,
  ShareNetwork,
  Storefront as StoreIcon,
  X,
} from "@phosphor-icons/react";
import { ThinkingOrb } from "thinking-orbs";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { Link, useLoaderData, useLocation, useParams } from "react-router-dom";
import { BRAND_NAME_ZH } from "../brand";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { ProductCard } from "../components/ProductCard";
import { EmptyState, ErrorState, ProductGridSkeleton } from "../components/States";
import { StorefrontAnnouncements } from "../components/StorefrontAnnouncements";
import { StorefrontSupportWidget } from "../components/StorefrontSupportWidget";
import { StorefrontVisitorEntry } from "../components/StorefrontVisitorEntry";
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
import {
  readStorefrontCatalogSnapshot,
  readStorefrontViewState,
  writeStorefrontCatalogSnapshot,
  writeStorefrontViewState,
} from "../lib/storefrontViewState";
import type { CatalogSharePublic, StoreProduct, Storefront, StorefrontCategoryOption, StorefrontLocale } from "../types";

type PaginationItem = number | "start-ellipsis" | "end-ellipsis";

const DEFAULT_RECOMMENDED_QUESTIONS = [
  "适合巴西市场的小型防水狗玩具有哪些？",
  "请推荐一款适合户外使用、容易收纳的商品。",
  "有哪些商品支持定制，并且 MOQ 比较友好？",
];

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

function catalogRequestKey(
  slug: string,
  locale: StorefrontLocale,
  shareToken: string,
  search: string,
  category: string,
) {
  return JSON.stringify([
    slug.toLocaleLowerCase(),
    locale,
    shareToken,
    search.trim(),
    category,
  ]);
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
  const location = useLocation();
  const { shareId } = useParams<{ shareId?: string }>();
  const tenantSlug = loadedStore.slug;
  const locale: StorefrontLocale = normalizeStorefrontLocale(loadedStore.locale);
  const t = useCallback(
    (source: string, values?: Record<string, string | number>) => (
      storefrontText(locale, source, values)
    ),
    [locale],
  );
  const shareToken = useMemo(
    () => shareId?.trim() || new URLSearchParams(location.search).get("share")?.trim() || "",
    [location.search, shareId],
  );
  const sharedQuery = useMemo(() => {
    const query = new URLSearchParams();
    if (locale !== "zh-CN") query.set("lang", locale);
    if (shareToken) query.set("share", shareToken);
    const value = query.toString();
    return value ? `?${value}` : "";
  }, [locale, shareToken]);
  const storefrontHome = shareId && shareToken
    ? `/${encodeURIComponent(tenantSlug)}/share/${encodeURIComponent(shareToken)}${storefrontLocaleQuery(locale)}`
    : `/${encodeURIComponent(tenantSlug)}${sharedQuery}`;
  const [initialCatalogSnapshot] = useState(() => (
    shareToken
      ? null
      : readStorefrontCatalogSnapshot(loadedStore.slug, locale)
  ));
  const [initialView] = useState(() => (
    initialCatalogSnapshot?.view
      ?? (shareToken ? undefined : readStorefrontViewState(loadedStore.slug))
  ));
  const [store, setStore] = useState<Storefront>(() => ({
    ...(initialCatalogSnapshot?.store ?? loadedStore),
    ai_search_questions: loadedStore.ai_search_questions
      ?? initialCatalogSnapshot?.store.ai_search_questions,
  }));
  const [products, setProducts] = useState<StoreProduct[]>(
    initialCatalogSnapshot?.products ?? [],
  );
  const [total, setTotal] = useState(initialCatalogSnapshot?.total ?? 0);
  const [loading, setLoading] = useState(!initialCatalogSnapshot);
  const [pageTransitioning, setPageTransitioning] = useState(false);
  const [pageTransitionError, setPageTransitionError] = useState("");
  const [page, setPage] = useState(
    initialCatalogSnapshot?.page ?? initialView?.page ?? 1,
  );
  const [pages, setPages] = useState(initialCatalogSnapshot?.pages ?? 0);
  const [error, setError] = useState("");
  const [catalogShare, setCatalogShare] = useState<CatalogSharePublic>();
  const [shareError, setShareError] = useState("");
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
  const hasCatalogResultsRef = useRef(Boolean(initialCatalogSnapshot?.products.length));
  const resultsHeaderRef = useRef<HTMLDivElement>(null);
  const paginationRef = useRef<HTMLElement>(null);
  const activeTenantRef = useRef(loadedStore.slug);
  const activeLocaleRef = useRef<StorefrontLocale>(locale);
  const activeShareTokenRef = useRef(shareToken);
  const facetsLoadedRef = useRef(Boolean(
    !initialCatalogSnapshot && loadedStore.categories?.length,
  ));
  const snapshotFacetRefreshRef = useRef(Boolean(initialCatalogSnapshot));
  const initialLoadPageRef = useRef<number | null>(
    initialCatalogSnapshot ? null : initialView?.page ?? 1,
  );
  const pendingScrollRestoreRef = useRef<number | null>(initialView?.scrollY ?? null);
  const restoredCatalogQueryRef = useRef<string | null>(
    initialCatalogSnapshot
      ? catalogRequestKey(
          loadedStore.slug,
          locale,
          shareToken,
          initialView?.search ?? "",
          initialView?.secondaryCategory || initialView?.primaryCategory || "",
        )
      : null,
  );

  useEffect(() => {
    const timeout = window.setTimeout(() => setDeferredSearch(search.trim()), 280);
    return () => window.clearTimeout(timeout);
  }, [search]);

  useEffect(() => {
    setStore(loadedStore);
    const tenantChanged = activeTenantRef.current !== loadedStore.slug;
    const localeChanged = activeLocaleRef.current !== locale;
    const shareChanged = activeShareTokenRef.current !== shareToken;
    if (!tenantChanged && !localeChanged && !shareChanged) return;
    activeTenantRef.current = loadedStore.slug;
    activeLocaleRef.current = locale;
    activeShareTokenRef.current = shareToken;
    facetsLoadedRef.current = false;
    const nextView = shareToken ? undefined : readStorefrontViewState(loadedStore.slug);
    const nextSnapshot = shareToken
      ? null
      : readStorefrontCatalogSnapshot(loadedStore.slug, locale);
    const restoredView = nextSnapshot?.view ?? nextView;
    setStore(nextSnapshot ? {
      ...nextSnapshot.store,
      ai_search_questions: loadedStore.ai_search_questions
        ?? nextSnapshot.store.ai_search_questions,
    } : loadedStore);
    setSearch(restoredView?.search ?? "");
    setDeferredSearch(restoredView?.search.trim() ?? "");
    setPrimaryCategory(restoredView?.primaryCategory ?? "");
    setSecondaryCategory(restoredView?.secondaryCategory ?? "");
    setCategoryLayout(restoredView?.categoryLayout ?? "horizontal");
    setExpandedCategories(new Set(restoredView?.expandedCategories ?? []));
    if (tenantChanged) {
      setCart(readStoreCart(loadedStore.slug));
      setCartTenant(loadedStore.slug);
    }
    restoredCatalogQueryRef.current = nextSnapshot
      ? catalogRequestKey(
          loadedStore.slug,
          locale,
          shareToken,
          restoredView?.search ?? "",
          restoredView?.secondaryCategory || restoredView?.primaryCategory || "",
        )
      : null;
    facetsLoadedRef.current = Boolean(
      nextSnapshot || loadedStore.categories?.length,
    );
    initialLoadPageRef.current = nextSnapshot ? null : restoredView?.page ?? 1;
    pendingScrollRestoreRef.current = restoredView?.scrollY ?? null;
    setProducts(nextSnapshot?.products ?? []);
    setTotal(nextSnapshot?.total ?? 0);
    setPage(nextSnapshot?.page ?? restoredView?.page ?? 1);
    setPages(nextSnapshot?.pages ?? 0);
    setLoading(!nextSnapshot);
    hasCatalogResultsRef.current = Boolean(nextSnapshot?.products.length);
    setPageTransitioning(false);
    setPageTransitionError("");
  }, [loadedStore, locale, shareToken]);

  useEffect(() => {
    if (!shareToken) {
      setCatalogShare(undefined);
      setShareError("");
      return;
    }
    let active = true;
    setCatalogShare(undefined);
    setShareError("");
    void api.getCatalogShare(tenantSlug, shareToken)
      .then((value) => { if (active) setCatalogShare(value); })
      .catch((reason) => {
        if (active) setShareError(reason instanceof Error ? reason.message : t("分享内容加载失败。"));
      });
    return () => { active = false; };
  }, [shareToken, t, tenantSlug]);

  useEffect(() => {
    if (cartTenant === tenantSlug) writeStoreCart(tenantSlug, cart);
  }, [cart, cartTenant, tenantSlug]);

  const category = secondaryCategory || primaryCategory;
  const currentCatalogRequestKey = catalogRequestKey(
    tenantSlug,
    locale,
    shareToken,
    deferredSearch,
    category,
  );

  useEffect(() => {
    const previousTitle = document.title;
    const previousLanguage = document.documentElement.lang;
    const previousDirection = document.documentElement.dir;
    document.documentElement.lang = locale;
    document.documentElement.dir = storefrontDirection(locale);
    document.title = `${loadedStore.name} | ${BRAND_NAME_ZH}`;
    return () => {
      document.title = previousTitle;
      document.documentElement.lang = previousLanguage;
      document.documentElement.dir = previousDirection;
    };
  }, [loadedStore.name, locale]);

  const loadProducts = useCallback(async (
    targetPage = 1,
    options: { preserveCurrent?: boolean; keepCurrentResults?: boolean } = {},
  ) => {
    const preserveCurrent = options.preserveCurrent === true;
    const keepCurrentResults = options.keepCurrentResults
      ?? (!preserveCurrent && hasCatalogResultsRef.current);
    const currentRequest = ++requestId.current;
    const includeFacets = !facetsLoadedRef.current;
    setPage(targetPage);
    if (!preserveCurrent) {
      setPageTransitionError("");
      setPageTransitioning(keepCurrentResults);
      if (!keepCurrentResults) setLoading(true);
    }
    setError("");
    try {
      const data = await api.getStoreProducts(tenantSlug, {
        q: deferredSearch,
        category: category || undefined,
        semantic: Boolean(deferredSearch),
        includeFacets,
        page: targetPage,
        locale,
        shareToken: shareToken || undefined,
      });
      if (currentRequest !== requestId.current) return;
      if (includeFacets) facetsLoadedRef.current = true;
      setProducts(data.items);
      hasCatalogResultsRef.current = data.items.length > 0;
      setTotal(data.total);
      setPage(data.page ?? targetPage);
      setPages(data.pages ?? Math.ceil(data.total / 24));
      setStore((current) => current ? {
        ...current,
        categories: includeFacets && data.categories?.length
          ? data.categories
          : current.categories,
        category_options: includeFacets && data.category_options?.length
          ? data.category_options
          : current.category_options,
        tags: data.tags?.length ? data.tags : current.tags,
        all_products_position: includeFacets
          ? data.all_products_position ?? current.all_products_position ?? 0
          : current.all_products_position,
        hot_products_enabled: data.hot_products_enabled
          ?? current.hot_products_enabled
          ?? false,
        category_showcase_enabled: data.category_showcase_enabled
          ?? current.category_showcase_enabled
          ?? true,
        ai_search_questions: loadedStore.ai_search_questions
          ?? current.ai_search_questions,
      } : current);
    } catch (caught) {
      if (currentRequest !== requestId.current) return;
      if (keepCurrentResults) {
        setPageTransitionError(caught instanceof Error ? caught.message : t("商品加载失败。"));
      } else if (!preserveCurrent) {
        setError(caught instanceof Error ? caught.message : t("商品加载失败。"));
        setProducts([]);
        hasCatalogResultsRef.current = false;
      }
    } finally {
      if (!preserveCurrent && currentRequest === requestId.current) {
        setLoading(false);
        setPageTransitioning(false);
      }
    }
  }, [tenantSlug, deferredSearch, category, locale, shareToken, t]);

  useEffect(() => {
    if (restoredCatalogQueryRef.current === currentCatalogRequestKey) {
      return;
    }
    restoredCatalogQueryRef.current = null;
    const targetPage = initialLoadPageRef.current ?? 1;
    void loadProducts(targetPage);
  }, [currentCatalogRequestKey, loadProducts]);

  useEffect(() => {
    if (!snapshotFacetRefreshRef.current || !initialCatalogSnapshot) return;
    snapshotFacetRefreshRef.current = false;
    facetsLoadedRef.current = false;
    void loadProducts(initialCatalogSnapshot.page, { preserveCurrent: true });
  }, [initialCatalogSnapshot, loadProducts]);

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
    if (
      loading
      || pageTransitioning
      || error
      || page < 1
      || page >= pages
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
        shareToken: shareToken || undefined,
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
    pageTransitioning,
    pages,
    shareToken,
    tenantSlug,
  ]);

  useEffect(() => {
    if (loading || pendingScrollRestoreRef.current === null) return;
    const targetScrollY = pendingScrollRestoreRef.current;
    let secondFrame = 0;
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => {
        pendingScrollRestoreRef.current = null;
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
      void api.prefetchStoreProduct(tenantSlug, productId, locale, shareToken || undefined)
        .catch(() => undefined);
    },
    [locale, shareToken, tenantSlug],
  );

  useEffect(() => {
    if (loading || pageTransitioning || error || products.length === 0) return;
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
          api.prefetchStoreProduct(tenantSlug, product.id, locale, shareToken || undefined)
        )),
      );
    }, 280);
    return () => window.clearTimeout(timer);
  }, [
    error,
    loading,
    locale,
    pageTransitioning,
    products,
    shareToken,
    store.source_locale,
    tenantSlug,
  ]);

  const categories = useMemo(() => {
    if (store?.categories?.length) return store.categories;
    return Array.from(
      new Set(products.map((product) => product.category).filter(Boolean)),
    ) as string[];
  }, [store?.categories, products]);
  const categoryOptions = useMemo<StorefrontCategoryOption[]>(() => {
    const configured = store.category_options ?? [];
    if (configured.length) return configured;
    return categories.map((value) => ({ value, label: value }));
  }, [categories, store.category_options]);
  const categoryTree = useMemo(() => {
    type CategoryChild = {
      id?: string;
      name: string;
      path: string;
      coverImageUrl?: string;
    };
    type CategoryNode = {
      id?: string;
      name: string;
      path: string;
      children: CategoryChild[];
    };
    const nodes = new Map<string, CategoryNode>();
    const nodesById = new Map<string, CategoryNode>();
    const ensureRoot = (path: string, name: string, id?: string) => {
      const node = nodes.get(path) ?? { name, path, children: [] };
      if (name) node.name = name;
      if (id) {
        node.id = id;
        nodesById.set(id, node);
      }
      nodes.set(path, node);
      return node;
    };
    categoryOptions.forEach((option) => {
      const { value, label } = option;
      const [primaryValue, secondaryValue] = value.replace("／", "/").split("/").map((part) => part.trim());
      const [primaryLabel, secondaryLabel] = label.replace("／", "/").split("/").map((part) => part.trim());
      if (!primaryValue) return;
      if (!option.parent_id && !secondaryValue) {
        ensureRoot(primaryValue, primaryLabel || primaryValue, option.id);
        return;
      }
      const node = (option.parent_id && nodesById.get(option.parent_id))
        || ensureRoot(primaryValue, primaryLabel || primaryValue);
      if (!node.children.some((child) => child.path === value)) {
        node.children.push({
          id: option.id,
          name: secondaryLabel || secondaryValue || label || value,
          path: value,
          coverImageUrl: option.cover_image_url || undefined,
        });
      }
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
  const selectedPrimary = useMemo(
    () => categoryTree.find((node) => node.path === primaryCategory),
    [categoryTree, primaryCategory],
  );
  const selectedSecondary = useMemo(
    () => secondaryOptions.find((item) => item.path === secondaryCategory),
    [secondaryCategory, secondaryOptions],
  );
  const visibleSecondaryOptions = useMemo(() => {
    if (!primaryCategory) return [];
    return secondaryOptions.map((item) => ({
      ...item,
      parentName: selectedPrimary?.name ?? "",
      parentPath: primaryCategory,
    }));
  }, [primaryCategory, secondaryOptions, selectedPrimary?.name]);
  const categoryShowcaseOptions = visibleSecondaryOptions;
  const recommendedQuestions = useMemo(
    () => {
      const configured = (store.ai_search_questions ?? [])
        .map((question) => question.trim())
        .filter(Boolean)
        .slice(0, 3);
      const values = configured.length === 3
        ? configured
        : DEFAULT_RECOMMENDED_QUESTIONS;
      return values.map((question) => t(question));
    },
    [store.ai_search_questions, t],
  );
  const categoryShowcaseEnabled = store.category_showcase_enabled !== false;
  const showCategoryShowcase = Boolean(
    !shareToken
    && categoryShowcaseEnabled
    && Boolean(primaryCategory)
    && !search.trim()
    && !secondaryCategory
    && categoryShowcaseOptions.length,
  );
  const hasFilters = Boolean(search || category);
  const shareDisplayTitle = useMemo(() => {
    if (!catalogShare) return "";
    if (catalogShare.target_type === "PRODUCTS") {
      if (catalogShare.item_count === 1 && products[0]) return products[0].name;
      return t("{count} 件商品精选", { count: catalogShare.item_count });
    }
    return store.category_options?.find(
      (option) => option.value === catalogShare.category_path,
    )?.label ?? catalogShare.category_name ?? catalogShare.title;
  }, [catalogShare, products, store.category_options, t]);
  const hotSortActive = Boolean(store.hot_products_enabled && !hasFilters);
  const searchPending = Boolean(search.trim()) && (
    search.trim() !== deferredSearch || loading
  );
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const cartSkuCount = cartLines.length;
  const visiblePaginationItems = useMemo(() => paginationItems(page, pages), [page, pages]);
  const [pageJumpInput, setPageJumpInput] = useState(String(page));

  useEffect(() => {
    setPageJumpInput(String(page));
  }, [page]);

  const resetFilters = () => {
    setSearch("");
    setPrimaryCategory("");
    setSecondaryCategory("");
  };
  const toggleCategoryExpansion = (path: string) => {
    setExpandedCategories((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
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
    if (shareToken) return;
    const viewState = {
      page,
      scrollY: window.scrollY,
      search,
      primaryCategory,
      secondaryCategory,
      categoryLayout,
      expandedCategories: Array.from(expandedCategories),
    };
    writeStorefrontViewState(tenantSlug, viewState);
    if (!loading && !error && products.length > 0) {
      writeStorefrontCatalogSnapshot(tenantSlug, locale, {
        store,
        products,
        total,
        page,
        pages,
        view: viewState,
      });
    }
  };
  const goToPage = (targetPage: number) => {
    if (
      loading
      || pageTransitioning
      || targetPage === page
      || targetPage < 1
      || targetPage > pages
    ) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    resultsHeaderRef.current?.scrollIntoView({
      behavior: reducedMotion ? "auto" : "smooth",
      block: "start",
    });
    void loadProducts(targetPage, { keepCurrentResults: true });
  };
  const submitPageJump = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const parsedPage = Number.parseInt(pageJumpInput, 10);
    if (!Number.isFinite(parsedPage)) {
      setPageJumpInput(String(page));
      return;
    }
    const targetPage = Math.min(Math.max(parsedPage, 1), pages);
    setPageJumpInput(String(targetPage));
    goToPage(targetPage);
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
              <StorefrontVisitorEntry tenantSlug={tenantSlug} locale={locale} />
              <CartDrawer
                slug={tenantSlug}
                storeName={store.name}
                contactEmail={store.contact_email}
                contactImages={store.support_widget?.custom_actions?.filter((action) => Boolean(action.visible && action.image_url))}
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

      {shareToken ? (
        <Container size="4" className="store-share-banner-wrap">
          <section className={`store-share-banner${shareError ? " has-error" : ""}`} role="status">
            <span className="store-share-banner-icon"><ShareNetwork weight="duotone" /></span>
            <div>
              <Text size="1" color="gray">{t("商家分享")}</Text>
              <strong>{shareDisplayTitle || (shareError ? t("分享内容暂时不可用") : t("正在读取分享内容…"))}</strong>
              <small>
                {catalogShare
                  ? t("{store} 为你分享了 {count} 件商品", {
                      store: catalogShare.store_name,
                      count: catalogShare.item_count,
                    })
                  : shareError || t("商品范围正在加载")}
              </small>
            </div>
          </section>
        </Container>
      ) : null}

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
                  {!shareToken ? (
                    <div className="category-layout-toggle" role="group" aria-label={t("分类展示方式")}>
                      <Button
                        type="button"
                        size="1"
                        variant={categoryLayout === "horizontal" ? "soft" : "ghost"}
                        color={categoryLayout === "horizontal" ? "jade" : "gray"}
                        aria-pressed={categoryLayout === "horizontal"}
                        onClick={() => setCategoryLayout("horizontal")}
                      >
                        <Rows size={15} weight="duotone" />
                        {t("横向展示")}
                      </Button>
                      <Button
                        type="button"
                        size="1"
                        variant={categoryLayout === "vertical" ? "soft" : "ghost"}
                        color={categoryLayout === "vertical" ? "jade" : "gray"}
                        aria-pressed={categoryLayout === "vertical"}
                        onClick={() => setCategoryLayout("vertical")}
                      >
                        <Columns size={15} weight="duotone" />
                        {t("竖向展示")}
                      </Button>
                    </div>
                  ) : null}
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
              {!shareToken && !search.trim() && recommendedQuestions.length ? (
                <div className="store-recommended-questions" aria-label={t("推荐问题")}>
                  <Text size="1" color="gray">{t("推荐问题")}</Text>
                  <div className="store-recommended-question-list">
                    {recommendedQuestions.map((question) => (
                      <button
                        type="button"
                        className="store-recommended-question"
                        key={question}
                        onClick={() => {
                          setPrimaryCategory("");
                          setSecondaryCategory("");
                          setSearch(question);
                        }}
                      >
                        <span>{question}</span>
                        <CaretRight size={14} weight="bold" />
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {!shareToken && categoryLayout === "horizontal" ? (
                <nav className="category-browser" aria-label={t("商品分类")}>
                  <div className="category-browser-row">
                    <span className="category-browser-label">{t("一级分类")}</span>
                    <CategoryScrollTrack
                      ariaLabel={t("一级分类")}
                      contentKey={`primary|${primaryNavigationItems.map((item) => item.key).join("|")}`}
                      locale={locale}
                    >
                      {primaryNavigationItems.map((item) => item.kind === "all" ? (
                        <button
                          type="button"
                          className={`category-browser-option${!primaryCategory && !secondaryCategory ? " is-active" : ""}`}
                          aria-pressed={!primaryCategory && !secondaryCategory}
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
                  {visibleSecondaryOptions.length && (!categoryShowcaseEnabled || secondaryCategory) ? (
                    <div className="category-browser-row">
                      <span className="category-browser-label">{t("二级分类")}</span>
                      <CategoryScrollTrack
                        ariaLabel={t("二级分类")}
                        contentKey={`secondary|${primaryCategory}|${visibleSecondaryOptions.map((item) => item.path).join("|")}`}
                        locale={locale}
                      >
                        <button
                          type="button"
                          className={`category-browser-option${!secondaryCategory ? " is-active" : ""}`}
                          aria-pressed={!secondaryCategory}
                          onClick={() => setSecondaryCategory("")}
                        >
                          {primaryCategory ? t("全部分类") : t("全部商品")}
                        </button>
                        {visibleSecondaryOptions.map((item) => (
                          <button
                            type="button"
                            className={`category-browser-option${secondaryCategory === item.path ? " is-active" : ""}`}
                            aria-pressed={secondaryCategory === item.path}
                            title={primaryCategory ? undefined : item.parentName}
                            onClick={() => {
                              setPrimaryCategory(item.parentPath);
                              setSecondaryCategory(item.path);
                            }}
                            key={`${item.parentPath}:${item.path}`}
                          >
                            {primaryCategory ? item.name : `${item.parentName} / ${item.name}`}
                          </button>
                        ))}
                      </CategoryScrollTrack>
                    </div>
                  ) : null}
                </nav>
              ) : null}
            </div>

            <div className={`results-container${!shareToken && categoryLayout === "vertical" ? " has-sidebar" : ""}`}>
              {!shareToken && categoryLayout === "vertical" && (
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
                      <div className="category-sidebar-group" key={item.key}>
                        <button
                          type="button"
                          className={`category-sidebar-item is-primary${primaryCategory === item.node.path ? " is-active" : ""}`}
                          title={item.node.name}
                          aria-expanded={!categoryShowcaseEnabled && item.node.children.length ? expandedCategories.has(item.node.path) : undefined}
                          onClick={() => {
                            setPrimaryCategory(item.node.path);
                            setSecondaryCategory("");
                            if (!categoryShowcaseEnabled && item.node.children.length) {
                              toggleCategoryExpansion(item.node.path);
                            }
                          }}
                        >
                          <span>{item.node.name}</span>
                          {!categoryShowcaseEnabled && item.node.children.length ? <CaretDown className={expandedCategories.has(item.node.path) ? "is-expanded" : undefined} size={14} /> : null}
                        </button>
                        {!categoryShowcaseEnabled && item.node.children.length && expandedCategories.has(item.node.path) ? (
                          <div className="category-sidebar-children">
                            {item.node.children.map((child) => (
                              <button
                                type="button"
                                className={`category-sidebar-item is-secondary${secondaryCategory === child.path ? " is-active" : ""}`}
                                title={child.name}
                                onClick={() => {
                                  setPrimaryCategory(item.node.path);
                                  setSecondaryCategory(child.path);
                                }}
                                key={child.path}
                              >
                                <span>{child.name}</span>
                              </button>
                            ))}
                          </div>
                        ) : null}
                      </div>
                    ))}
                  </nav>
                </aside>
              )}
              <div className="results-main">
            {!shareToken && categoryLayout === "vertical" && selectedPrimary && secondaryOptions.length > 0 && !showCategoryShowcase ? (
              <nav className="category-secondary-nav" aria-label={t("二级分类")}>
                <CategoryScrollTrack
                  ariaLabel={t("二级分类")}
                  contentKey={`${primaryCategory}|${secondaryOptions.map((item) => item.path).join("|")}`}
                  locale={locale}
                >
                  <button
                    type="button"
                    className={`category-browser-option${!secondaryCategory ? " is-active" : ""}`}
                    aria-pressed={!secondaryCategory}
                    onClick={() => setSecondaryCategory("")}
                  >
                    {categoryShowcaseEnabled ? t("返回分类门面") : t("全部商品")}
                  </button>
                  {secondaryOptions.map((item) => (
                    <button
                      type="button"
                      className={`category-browser-option${secondaryCategory === item.path ? " is-active" : ""}`}
                      aria-pressed={secondaryCategory === item.path}
                      onClick={() => setSecondaryCategory(item.path)}
                      key={item.path}
                    >
                      {item.name}
                    </button>
                  ))}
                </CategoryScrollTrack>
              </nav>
            ) : null}
            <div className="results-header" ref={resultsHeaderRef}>
              <div>
                <div className="results-title-row">
                  <Heading as="h2" size="5">
                    {shareDisplayTitle
                      || selectedSecondary?.name
                      || selectedPrimary?.name
                      || t(hasFilters ? "筛选结果" : "全部商品")}
                  </Heading>
                  {hotSortActive ? (
                    <Badge color="amber" variant="soft">
                      <Fire size={14} weight="fill" aria-hidden="true" />
                      {t("爆款优先")}
                    </Badge>
                  ) : null}
                </div>
                <Text size="2" color="gray">
                  {t(
                    showCategoryShowcase
                      ? "选择一个二级分类查看商品。"
                      : hotSortActive
                      ? "根据近 90 天浏览与下单热度优先展示，手动置顶商品仍排在最前。"
                      : "点击商品查看可选规格与 SKU。",
                  )}
                </Text>
              </div>
              <Badge color={hasFilters ? "jade" : "gray"} variant="soft" aria-live="polite">
                {showCategoryShowcase
                  ? t("{count} 个分类", { count: categoryShowcaseOptions.length.toLocaleString(locale) })
                  : searchPending
                  ? t("搜索中……")
                  : loading
                    ? t("正在查找")
                  : pageTransitioning
                    ? t("切换中…")
                  : t("{count} 条结果", { count: total.toLocaleString(locale) })}
              </Badge>
            </div>
            <Separator size="4" />

            <div className="results-body">
              {showCategoryShowcase ? (
                <div className="category-showcase-grid">
                  {categoryShowcaseOptions.map((item) => (
                    <button
                      type="button"
                      className="category-showcase-card"
                      onClick={() => {
                        setPrimaryCategory(item.parentPath);
                        setSecondaryCategory(item.path);
                      }}
                      key={`${item.parentPath}:${item.path}`}
                    >
                      <span className="category-showcase-image">
                        {item.coverImageUrl ? (
                          <img src={item.coverImageUrl} alt="" loading="lazy" />
                        ) : (
                          <span><FolderOpen weight="duotone" /></span>
                        )}
                      </span>
                      <strong>{primaryCategory ? item.name : `${item.parentName} / ${item.name}`}</strong>
                      <span>{t("查看商品")}<CaretRight weight="bold" /></span>
                    </button>
                  ))}
                </div>
              ) : searchPending ? (
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
                <div
                  className={`sku-grid-shell${pageTransitioning ? " is-transitioning" : ""}`}
                  aria-busy={pageTransitioning}
                >
                  <div className="sku-grid">
                    {products.map((product) => (
                      <ProductCard
                        key={product.id}
                        product={product}
                        tenantSlug={tenantSlug}
                        detailsHref={`/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(product.id)}${sharedQuery}`}
                        onOpenDetails={rememberCatalogPosition}
                        onPrefetchDetails={() => prefetchProductDetails(product.id)}
                        locale={locale}
                      />
                    ))}
                  </div>
                  {pageTransitioning ? (
                    <div className="store-grid-transition-indicator" role="status" aria-live="polite">
                      <ArrowCounterClockwise className="is-spinning" size={15} aria-hidden="true" />
                      <span>{t("正在切换")}</span>
                    </div>
                  ) : null}
                  {pageTransitionError ? (
                    <div className="store-grid-transition-error" role="status">
                      <span>{pageTransitionError}</span>
                      <Button
                        type="button"
                        size="1"
                        variant="soft"
                        onClick={() => void loadProducts(page, { keepCurrentResults: true })}
                      >
                        {t("重试")}
                      </Button>
                    </div>
                  ) : null}
                </div>
              )}
              {!showCategoryShowcase && !searchPending && !loading && !error && products.length > 0 && pages > 1 && (
                <nav
                  className="store-pagination"
                  aria-label={t("商品分页")}
                  ref={paginationRef}
                >
                  <div className="store-pagination-controls">
                    <Button
                      type="button"
                      size="2"
                      variant="soft"
                      color="gray"
                      disabled={page <= 1 || pageTransitioning}
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
                            disabled={loading || pageTransitioning}
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
                      disabled={page >= pages || pageTransitioning}
                      aria-label={t("下一页")}
                      onClick={() => goToPage(page + 1)}
                    >
                      <span className="store-pagination-button-label">{t("下一页")}</span>
                      <CaretRight weight="bold" />
                    </Button>
                  </div>
                  <form className="store-pagination-jump" onSubmit={submitPageJump}>
                    <label htmlFor="store-page-jump">{t("跳转到")}</label>
                    <TextField.Root
                      id="store-page-jump"
                      type="number"
                      min={1}
                      max={pages}
                      inputMode="numeric"
                      size="2"
                      value={pageJumpInput}
                      onChange={(event) => setPageJumpInput(event.target.value)}
                      aria-label={t("页码")}
                      disabled={pageTransitioning}
                    />
                    <Button type="submit" size="2" variant="soft" disabled={pageTransitioning}>
                      {t("跳转")}
                    </Button>
                  </form>
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
