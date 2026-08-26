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
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLoaderData, useSearchParams } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { StorefrontExchangeRates } from "../components/StorefrontExchangeRates";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
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
  storefrontLocaleQuery,
  storefrontText,
} from "../lib/storefrontLocale";
import type { Storefront, StorefrontLocale, StorefrontVisitorQuote } from "../types";

function ProductRows({
  items,
  store,
  locale,
  removable,
  onRemove,
}: {
  items: StorefrontVisitorProduct[];
  store: Storefront;
  locale: StorefrontLocale;
  removable?: boolean;
  onRemove?: (item: StorefrontVisitorProduct) => void;
}) {
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  if (!items.length) {
    return <div className="visitor-center-empty"><Package weight="duotone" /><strong>{t("这里还没有内容")}</strong><span>{t("浏览或收藏商品后，会自动保存在这里。")}</span></div>;
  }
  return <div className="visitor-product-list">{items.map((item) => (
    <Card className="visitor-product-row" key={item.id}>
      <Link to={`/${encodeURIComponent(store.slug)}/products/${encodeURIComponent(item.id)}${storefrontLocaleQuery(locale)}`} className="visitor-product-image">
        {item.imageUrl ? <img src={item.imageUrl} alt="" loading="lazy" /> : <Package weight="duotone" />}
      </Link>
      <div>
        <Link to={`/${encodeURIComponent(store.slug)}/products/${encodeURIComponent(item.id)}${storefrontLocaleQuery(locale)}`}><strong>{item.name}</strong></Link>
        <Text size="1" color="gray">{item.category || t("未分类")}</Text>
        <Text size="2" weight="bold" color="blue">{money(item.priceFrom, item.currency)}</Text>
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
      setDownloadError(reason instanceof Error ? reason.message : t("文件下载失败，请稍后重试。"));
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

export function StorefrontVisitorCenterPage() {
  const store = useLoaderData() as Storefront;
  const locale = normalizeStorefrontLocale(store.locale);
  const t = (source: string, values?: Record<string, string | number>) => storefrontText(locale, source, values);
  const [searchParams] = useSearchParams();
  const [history, setHistory] = useState(() => readStorefrontHistory(store.slug));
  const [favorites, setFavorites] = useState(() => readStorefrontFavorites(store.slug));
  const [quotes, setQuotes] = useState<StorefrontVisitorQuote[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [cart, setCart] = useState<Record<string, CartLine>>(() => readStoreCart(store.slug));
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const storefrontHome = `/${encodeURIComponent(store.slug)}${storefrontLocaleQuery(locale)}`;

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
      setError(reason instanceof Error ? reason.message : t("记录加载失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, [store.slug]);

  useEffect(() => { void loadQuotes(); }, [loadQuotes]);
  useEffect(() => {
    const update = (event: Event) => {
      const detail = (event as CustomEvent<{ slug?: string; scope?: string }>).detail;
      if (detail?.slug && detail.slug.toLocaleLowerCase() !== store.slug.toLocaleLowerCase()) return;
      setHistory(readStorefrontHistory(store.slug));
      setFavorites(readStorefrontFavorites(store.slug));
      if (detail?.scope === "quotes") void loadQuotes();
    };
    window.addEventListener(STOREFRONT_VISITOR_EVENT, update);
    return () => window.removeEventListener(STOREFRONT_VISITOR_EVENT, update);
  }, [loadQuotes, store.slug]);
  useEffect(() => { writeStoreCart(store.slug, cart); }, [cart, store.slug]);

  const pending = quotes.filter((quote) => quote.status === "PENDING_CONFIRMATION");
  const confirmed = quotes.filter((quote) => quote.status === "CONFIRMED");
  const completed = quotes.filter((quote) => quote.status === "COMPLETED");
  const closed = quotes.filter((quote) => quote.status === "CANCELLED" || quote.status === "EXPIRED");
  const requestedTab = searchParams.get("tab");
  const defaultTab = requestedTab && [
    "history",
    "favorites",
    "pending",
    "confirmed",
    "completed",
    "closed",
  ].includes(requestedTab)
    ? requestedTab
    : requestedTab === "quotes" ? "pending" : "history";
  const updateQuantity = (skuId: string, quantity: number) => setCart((current) => {
    const next = { ...current };
    if (quantity < 1) delete next[skuId];
    else if (next[skuId]) next[skuId] = { ...next[skuId], quantity };
    return next;
  });

  return <div className={`store-shell visitor-center-shell${cartLines.length ? " has-cart" : ""}`} dir={storefrontDirection(locale)}>
    <header className="store-header">
      <Container size="4" className="store-header-container"><div className="header-inner">
        <div className="store-header-branding"><Link to={storefrontHome} className="store-identity">
          {store.logo_url ? <img src={store.logo_url} alt="" /> : <span className="store-identity-mark"><StoreIcon size={21} weight="duotone" /></span>}
          <span><strong>{store.name}</strong><small>{t("个人中心")}</small></span>
        </Link></div>
        <div className="header-actions">
          <StorefrontLanguageSwitch locale={locale} availableLocales={store.available_locales} />
          <ThemeToggle labels={{ toDark: t("切换深色模式"), toLight: t("切换浅色模式") }} />
          <CartDrawer slug={store.slug} storeName={store.name} contactEmail={store.contact_email} contactImages={store.support_widget?.custom_actions?.filter((action) => Boolean(action.visible && action.image_url))} lines={cartLines} onQuantity={updateQuantity} onClear={() => setCart({})} locale={locale} />
        </div>
      </div></Container>
    </header>
    <StorefrontExchangeRates tenantSlug={store.slug} locale={locale} />
    <main className="visitor-center-main"><Container size="4">
      <Link to={storefrontHome} className="sku-detail-back"><ArrowLeft weight="bold" />{t("返回商品目录")}</Link>
      <section className="visitor-center-hero">
        <span><UserCircle weight="duotone" /></span>
        <div><Text size="1" color="gray">{t("访客个人中心")}</Text><Heading size="7">{t("我的")}</Heading><Text size="2" color="gray">{t("记录仅保存在当前浏览器；商家确认询价或订单后会在这里通知你。")}</Text></div>
      </section>
      {error ? <Card className="visitor-center-error"><Text color="red">{error}</Text><Button size="2" variant="soft" onClick={() => void loadQuotes()}>{t("重试")}</Button></Card> : null}
      <Tabs.Root defaultValue={defaultTab} className="visitor-center-tabs">
        <Tabs.List>
          <Tabs.Trigger value="history"><ClockCounterClockwise />{t("浏览记录")} <Badge>{history.length}</Badge></Tabs.Trigger>
          <Tabs.Trigger value="favorites"><Heart />{t("我的收藏")} <Badge>{favorites.length}</Badge></Tabs.Trigger>
          <Tabs.Trigger value="pending">{t("待确认询价单")} <Badge>{pending.length}</Badge></Tabs.Trigger>
          <Tabs.Trigger value="confirmed">{t("已确认询价单")} <Badge>{confirmed.length}</Badge></Tabs.Trigger>
          <Tabs.Trigger value="completed">{t("已成交订单")} <Badge>{completed.length}</Badge></Tabs.Trigger>
          <Tabs.Trigger value="closed">{t("已关闭")} <Badge>{closed.length}</Badge></Tabs.Trigger>
        </Tabs.List>
        <div className="visitor-center-panel">
          <Tabs.Content value="history"><div className="visitor-panel-heading"><Heading size="5">{t("浏览记录")}</Heading>{history.length ? <Button size="2" variant="ghost" color="gray" onClick={() => clearStorefrontHistory(store.slug)}><Trash />{t("清空")}</Button> : null}</div><ProductRows items={history} store={store} locale={locale} /></Tabs.Content>
          <Tabs.Content value="favorites"><div className="visitor-panel-heading"><Heading size="5">{t("我的收藏")}</Heading></div><ProductRows items={favorites} store={store} locale={locale} removable onRemove={(item) => { toggleStorefrontFavorite(store.slug, { id: item.id, name: item.name, image_url: item.imageUrl, price_from: item.priceFrom, price_to: item.priceTo, currency: item.currency, category: item.category, tags: [], unit_code: "piece", sku_count: 0, product_version: 1 }); }} /></Tabs.Content>
          <Tabs.Content value="pending"><div className="visitor-panel-heading"><Heading size="5">{t("待确认询价单")}</Heading></div>{loading ? <div className="visitor-center-empty">{t("正在加载…")}</div> : <QuoteRows quotes={pending} locale={locale} slug={store.slug} />}</Tabs.Content>
          <Tabs.Content value="confirmed"><div className="visitor-panel-heading"><Heading size="5">{t("已确认询价单")}</Heading></div>{loading ? <div className="visitor-center-empty">{t("正在加载…")}</div> : <QuoteRows quotes={confirmed} locale={locale} slug={store.slug} />}</Tabs.Content>
          <Tabs.Content value="completed"><div className="visitor-panel-heading"><Heading size="5">{t("已成交订单")}</Heading></div>{loading ? <div className="visitor-center-empty">{t("正在加载…")}</div> : <QuoteRows quotes={completed} locale={locale} slug={store.slug} />}</Tabs.Content>
          <Tabs.Content value="closed"><div className="visitor-panel-heading"><Heading size="5">{t("已关闭")}</Heading></div>{loading ? <div className="visitor-center-empty">{t("正在加载…")}</div> : <QuoteRows quotes={closed} locale={locale} slug={store.slug} />}</Tabs.Content>
        </div>
      </Tabs.Root>
    </Container></main>
  </div>;
}
