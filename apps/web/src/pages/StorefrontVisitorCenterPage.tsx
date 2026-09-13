import {
  Badge,
  Button,
  Card,
  Container,
  Heading,
  Tabs,
  Text,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  ClockCounterClockwise,
  FilePdf,
  FileXls,
  Heart,
  Package,
  ShoppingCartSimple,
  Storefront as StoreIcon,
  Trash,
  UserCircle,
  WarningCircle,
  ClipboardText,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useCoreAuth } from "../core/AuthContext";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { StorefrontFooter } from "../components/StorefrontFooter";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { storefrontAccountMembershipId, storefrontBasePath, storefrontStorageScope } from "../lib/storefrontAccount";
import { readStoreCart, refreshCartSkus, setCartQuantity, writeStoreCart } from "../lib/storeCart";
import {
  clearStorefrontHistory,
  markQuoteNotificationsSeen,
  quoteNotificationKey,
  readStorefrontFavorites,
  readStorefrontHistory,
  STOREFRONT_VISITOR_EVENT,
  toggleStorefrontFavorite,
  type StorefrontVisitorProduct,
} from "../lib/storefrontVisitor";
import {
  normalizeStorefrontLocale,
  storefrontDirection,
  storefrontLayoutDirection,
  storefrontLocaleQuery,
  storefrontPriceLabel,
  storefrontText,
} from "../lib/storefrontLocale";
import type { Storefront, StorefrontLocale, StorefrontVisitorQuote } from "../types";

function ProductRows({
  items,
  store,
  locale,
  removable,
  onRemove,
  basePath,
}: {
  items: StorefrontVisitorProduct[];
  store: Storefront;
  locale: StorefrontLocale;
  removable?: boolean;
  onRemove?: (item: StorefrontVisitorProduct) => void;
  basePath: string;
}) {
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  if (!items.length) {
    return <div className="visitor-center-empty"><Package weight="duotone" /><strong>{t("这里还没有内容")}</strong><span>{t("浏览或收藏商品后，会自动保存在这里。")}</span></div>;
  }
  return <div className="visitor-product-list">{items.map((item) => (
    <Card className="visitor-product-row" key={item.id}>
      <Link to={`${basePath}/products/${encodeURIComponent(item.id)}${storefrontLocaleQuery(locale)}`} className="visitor-product-image">
        {item.imageUrl ? <img src={item.imageUrl} alt="" loading="lazy" /> : <Package weight="duotone" />}
      </Link>
      <div>
        <Link to={`${basePath}/products/${encodeURIComponent(item.id)}${storefrontLocaleQuery(locale)}`}><strong>{item.name}</strong></Link>
        <Text size="1" color="gray">{item.category || t("未分类")}</Text>
        {store.prices_visible !== false ? <Text size="2" weight="bold" color="blue">{storefrontPriceLabel(locale, item.priceFrom, item.priceTo, item.currency)}</Text> : null}
      </div>
      {removable ? <Button size="2" variant="ghost" color="gray" onClick={() => onRemove?.(item)} aria-label={t("取消收藏")}><Trash /></Button> : null}
    </Card>
  ))}</div>;
}

function QuoteRows({ quotes, locale, slug }: { quotes: StorefrontVisitorQuote[]; locale: StorefrontLocale; slug: string }) {
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState("");
  const download = async (quote: StorefrontVisitorQuote, type: "pdf" | "xlsx") => {
    setDownloading(`${quote.id}:${type}`);
    setDownloadError("");
    try {
      await api.downloadStorefrontVisitorQuote(slug, quote.id, type);
    } catch (reason) {
      setDownloadError(reason instanceof Error ? t(reason.message) : t("文件下载失败，请稍后重试。"));
    } finally {
      setDownloading(null);
    }
  };
  if (!quotes.length) {
    return <div className="visitor-center-empty"><ShoppingCartSimple weight="duotone" /><strong>{t("暂无相关记录")}</strong><span>{t("提交询价后，处理进度会显示在这里。")}</span></div>;
  }
  return <div className="visitor-quote-list">{downloadError ? <Text size="1" color="red">{downloadError}</Text> : null}{quotes.map((quote) => (
    <Card className="visitor-quote-row" key={quote.id}>
      <div className="visitor-quote-heading">
        <div><Text size="1" color="gray">{quote.quote_number}</Text><strong>{quote.customer_company || quote.customer_name}</strong></div>
        <Badge color={quote.status === "COMPLETED" ? "jade" : quote.status === "CONFIRMED" ? "blue" : quote.status === "CANCELLED" ? "red" : quote.status === "EXPIRED" ? "gray" : "amber"}>
          {t(quote.status === "COMPLETED" ? "已成交" : quote.status === "CONFIRMED" ? "商家已确认" : quote.status === "CANCELLED" ? "已取消" : quote.status === "EXPIRED" ? "已过期" : "待商家确认")}
        </Badge>
      </div>
      <Heading size="4">{quote.currency} {Number(quote.total_amount).toFixed(2)}</Heading>
      <Text size="1" color="gray">{t("提交时间")} · {new Date(quote.created_at).toLocaleString(locale)}</Text>
      {quote.status === "CONFIRMED" || quote.status === "COMPLETED" ? (
        <div className="download-actions visitor-quote-download-actions">
          <Button size="2" onClick={() => void download(quote, "pdf")} loading={downloading === `${quote.id}:pdf`}><FilePdf />{t("下载 PDF")}</Button>
          <Button size="2" variant="soft" onClick={() => void download(quote, "xlsx")} loading={downloading === `${quote.id}:xlsx`}><FileXls />{t("下载 Excel")}</Button>
        </div>
      ) : null}
    </Card>
  ))}</div>;
}

type VisitorOrderTab = "submitted" | "confirmed" | "completed" | "issues";

function normalizeVisitorOrderTab(value?: string | null): VisitorOrderTab {
  if (value === "confirmed") return "confirmed";
  if (value === "completed") return "completed";
  if (value === "issues" || value === "closed") return "issues";
  return "submitted";
}

export function StorefrontVisitorCenterPage() {
  const store = useLoaderData() as Storefront;
  const { profile } = useCoreAuth();
  const { accountKey } = useParams<{ accountKey?: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const accountId = storefrontAccountMembershipId(accountKey) || store.account_id || undefined;
  const basePath = storefrontBasePath(store.slug);
  const storageScope = storefrontStorageScope(store.slug, accountId);
  const accountName = accountId && profile?.context.membershipId?.toLocaleLowerCase() === accountId
    ? profile.user.displayName
    : undefined;
  const locale = normalizeStorefrontLocale(store.locale);
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  const [searchParams] = useSearchParams();
  const [history, setHistory] = useState(() => readStorefrontHistory(storageScope));
  const [favorites, setFavorites] = useState(() => readStorefrontFavorites(storageScope));
  const [quotes, setQuotes] = useState<StorefrontVisitorQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cart, setCart] = useState<Record<string, CartLine>>(() => readStoreCart(storageScope));
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const storefrontHome = `${basePath}${storefrontLocaleQuery(locale)}`;
  const ordersPath = `${basePath}/me/orders`;
  const routeWithQuery = (path: string, entries: Array<[string, string]> = []) => {
    const params = new URLSearchParams();
    if (locale !== "zh-CN") params.set("lang", locale);
    entries.forEach(([key, value]) => params.set(key, value));
    const query = params.toString();
    return `${path}${query ? `?${query}` : ""}`;
  };
  const requestedTab = searchParams.get("tab");
  const ordersPage = location.pathname.endsWith("/orders")
    || ["pending", "submitted", "confirmed", "completed", "closed", "issues"].includes(requestedTab || "");
  const orderTab = normalizeVisitorOrderTab(requestedTab);
  const activeView = ordersPage ? "" : searchParams.get("view");
  const orderHref = (tab: VisitorOrderTab) => routeWithQuery(ordersPath, [["tab", tab]]);

  const loadQuotes = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const rows = await api.listStorefrontVisitorQuotes(store.slug);
      setQuotes(rows);
      markQuoteNotificationsSeen(
        store.slug,
        rows.filter((row) => row.status !== "PENDING_CONFIRMATION").map(quoteNotificationKey),
      );
    } catch (reason) {
      setError(reason instanceof Error ? t(reason.message) : t("记录加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [store.slug]);

  useEffect(() => { void loadQuotes(); }, [loadQuotes]);
  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<{ slug?: string; scope?: string }>).detail;
      if (detail?.slug && detail.slug.toLocaleLowerCase() !== store.slug.toLocaleLowerCase()) return;
      setHistory(readStorefrontHistory(storageScope));
      setFavorites(readStorefrontFavorites(storageScope));
      if (detail?.scope === "quotes") void loadQuotes();
    };
    window.addEventListener(STOREFRONT_VISITOR_EVENT, update);
    return () => window.removeEventListener(STOREFRONT_VISITOR_EVENT, update);
  }, [loadQuotes, storageScope, store.slug]);
  useEffect(() => { writeStoreCart(storageScope, cart); }, [cart, storageScope]);

  const pending = quotes.filter((quote) => quote.status === "PENDING_CONFIRMATION");
  const confirmed = quotes.filter((quote) => quote.status === "CONFIRMED");
  const completed = quotes.filter((quote) => quote.status === "COMPLETED");
  const closed = quotes.filter((quote) => quote.status === "CANCELLED" || quote.status === "EXPIRED");
  const updateQuantity = (skuId: string, quantity: number) => setCart((current) => setCartQuantity(current, skuId, quantity));
  const updateCartNote = (skuId: string, note: string) => setCart((current) => (
    current[skuId]
      ? { ...current, [skuId]: { ...current[skuId], note } }
      : current
  ));
  const historyPanel = (
    <div className="visitor-center-panel">
      <div className="visitor-panel-heading">
        <Heading size="5">{t("浏览记录")}</Heading>
        {history.length ? <Button size="2" variant="ghost" color="gray" onClick={() => clearStorefrontHistory(storageScope)}><Trash />{t("清空")}</Button> : null}
      </div>
      <ProductRows items={history} store={store} locale={locale} basePath={basePath} />
    </div>
  );
  const favoritesPanel = (
    <div className="visitor-center-panel">
      <div className="visitor-panel-heading"><Heading size="5">{t("我的收藏")}</Heading></div>
      <ProductRows
        items={favorites}
        store={store}
        locale={locale}
        basePath={basePath}
        removable
        onRemove={(item) => {
          toggleStorefrontFavorite(storageScope, {
            id: item.id,
            name: item.name,
            image_url: item.imageUrl,
            price_from: item.priceFrom,
            price_to: item.priceTo,
            currency: item.currency,
            category: item.category,
            tags: [],
            unit_code: "piece",
            sku_count: 0,
            product_version: 1,
          });
        }}
      />
    </div>
  );
  const quotePanel = (title: string, rows: StorefrontVisitorQuote[]) => (
    <Tabs.Content value={
      rows === pending ? "submitted" : rows === confirmed ? "confirmed" : rows === completed ? "completed" : "issues"
    }>
      <div className="visitor-panel-heading"><Heading size="5">{title}</Heading></div>
      {loading ? <div className="visitor-center-empty">{t("正在加载…")}</div> : <QuoteRows quotes={rows} locale={locale} slug={store.slug} />}
    </Tabs.Content>
  );

  return <div
    className={`store-shell visitor-center-shell${cartLines.length ? " has-cart" : ""}`}
    dir={storefrontLayoutDirection()}
    data-locale={locale}
    data-text-direction={storefrontDirection(locale)}
  >
    <header className="store-header">
      <Container size="4" className="store-header-container"><div className="header-inner">
        <div className="store-header-branding"><Link to={storefrontHome} className="store-identity">
          {store.logo_url ? <img src={store.logo_url} alt="" /> : <span className="store-identity-mark"><StoreIcon size={21} weight="duotone" /></span>}
          <span><strong>{accountName ? `${store.name} / ${accountName}` : store.name}</strong><small>{t("个人中心")}</small></span>
        </Link></div>
        <div className="header-actions">
          <StorefrontLanguageSwitch locale={locale} availableLocales={store.available_locales} />
          <ThemeToggle labels={{ toDark: t("切换深色模式"), toLight: t("切换浅色模式") }} />
          <CartDrawer slug={store.slug} accountId={accountId} accountKey={accountKey} storeName={store.name} contactEmail={store.contact_email} contactImages={store.support_widget?.custom_actions?.filter((action) => Boolean(action.visible && action.image_url))} showPrices={store.prices_visible !== false} lines={cartLines} onQuantity={updateQuantity} onRefreshSkus={(skus) => setCart((current) => refreshCartSkus(current, skus))} onNote={updateCartNote} onClear={() => setCart({})} locale={locale} />
        </div>
      </div></Container>
    </header>
    <main className="visitor-center-main"><Container size="4">
      <Link to={storefrontHome} className="sku-detail-back"><ArrowLeft weight="bold" />{t("返回商品目录")}</Link>
      <section className="visitor-center-hero">
        <span><UserCircle weight="duotone" /></span>
        <div><Text size="1" color="gray">{t("访客个人中心")}</Text><Heading size="7">{t(ordersPage ? "我的订单" : "我的")}</Heading><Text size="2" color="gray">{t("记录仅保存在当前浏览器；商家确认询价或订单后会在这里通知你。")}</Text></div>
      </section>
      {error ? <Card className="visitor-center-error"><Text color="red">{error}</Text><Button size="2" variant="soft" onClick={() => void loadQuotes()}>{t("重试")}</Button></Card> : null}
      {ordersPage ? (
        <section className="visitor-orders-page">
          <Link to={storefrontHome} className="visitor-orders-back"><ArrowLeft weight="bold" />{t("我的")}</Link>
          <Tabs.Root
            value={orderTab}
            onValueChange={(value) => navigate(orderHref(normalizeVisitorOrderTab(value)), { replace: true })}
            className="visitor-orders-tabs"
          >
            <Tabs.List>
              <Tabs.Trigger value="submitted">{t("已提交订单")} <Badge>{pending.length}</Badge></Tabs.Trigger>
              <Tabs.Trigger value="confirmed">{t("已确认订单")} <Badge>{confirmed.length}</Badge></Tabs.Trigger>
              <Tabs.Trigger value="completed">{t("已成交订单")} <Badge>{completed.length}</Badge></Tabs.Trigger>
              <Tabs.Trigger value="issues">{t("问题订单")} <Badge>{closed.length}</Badge></Tabs.Trigger>
            </Tabs.List>
            <div className="visitor-center-panel visitor-orders-panel">
              {quotePanel(t("已提交订单"), pending)}
              {quotePanel(t("已确认订单"), confirmed)}
              {quotePanel(t("已成交订单"), completed)}
              {quotePanel(t("问题订单"), closed)}
            </div>
          </Tabs.Root>
        </section>
      ) : (
        <>
          <div className="visitor-shortcut-grid">
            <Link to={routeWithQuery(`${basePath}/me`, [["view", "history"]])} className="visitor-shortcut-card">
              <span className="visitor-shortcut-icon"><ClockCounterClockwise weight="duotone" /></span>
              <span className="visitor-shortcut-copy"><strong>{t("浏览记录")}</strong><small>{history.length}</small></span>
            </Link>
            <Link to={routeWithQuery(`${basePath}/me`, [["view", "favorites"]])} className="visitor-shortcut-card">
              <span className="visitor-shortcut-icon"><Heart weight="duotone" /></span>
              <span className="visitor-shortcut-copy"><strong>{t("我的收藏")}</strong><small>{favorites.length}</small></span>
            </Link>
            <Link to={orderHref("submitted")} className="visitor-shortcut-card">
              <span className="visitor-shortcut-icon"><ClipboardText weight="duotone" /></span>
              <span className="visitor-shortcut-copy"><strong>{t("我的订单")}</strong><small>{quotes.length}</small></span>
            </Link>
            <Link to={orderHref("issues")} className="visitor-shortcut-card">
              <span className="visitor-shortcut-icon"><WarningCircle weight="duotone" /></span>
              <span className="visitor-shortcut-copy"><strong>{t("关闭订单")}</strong><small>{closed.length}</small></span>
            </Link>
          </div>
          {activeView === "history" ? historyPanel : activeView === "favorites" ? favoritesPanel : null}
        </>
      )}
    </Container></main>
    <StorefrontFooter store={store} t={t} accountKey={accountKey} />
  </div>;
}
