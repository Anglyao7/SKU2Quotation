import {
  Badge,
  Button,
  Card,
  Container,
  Heading,
  Text,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  Check,
  Image as ImageIcon,
  Package,
  Plus,
  Storefront as StoreIcon,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate, useParams } from "react-router-dom";
import { useCoreAuth } from "../core/AuthContext";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { ProductImagePreview } from "../components/ProductImagePreview";
import { StorefrontAnnouncements } from "../components/StorefrontAnnouncements";
import { StorefrontFooter } from "../components/StorefrontFooter";
import { StorefrontSupportWidget } from "../components/StorefrontSupportWidget";
import { StorefrontTopNavigation } from "../components/StorefrontTopNavigation";
import { StorefrontVisitorEntry } from "../components/StorefrontVisitorEntry";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { storefrontAccountMembershipId, storefrontBasePath, storefrontStorageScope } from "../lib/storefrontAccount";
import { money } from "../lib/format";
import { subscribePublicCatalogRevision } from "../lib/publicCatalogRevision";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import {
  normalizeStorefrontLocale,
  storefrontDirection,
  storefrontLayoutDirection,
  storefrontLocaleQuery,
  storefrontText,
} from "../lib/storefrontLocale";
import { tagGlassStyle } from "../lib/tagColors";
import type { Sku, Storefront, StorefrontLocale } from "../types";

interface SkuDetailLoaderData {
  store: Storefront;
  sku: Sku;
}

const viewEventIds = new Map<string, string>();

function storefrontViewEventId(locationKey: string, skuId: string) {
  const key = `${locationKey}:${skuId}`;
  const existing = viewEventIds.get(key);
  if (existing) return existing;
  const eventId = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  viewEventIds.set(key, eventId);
  if (viewEventIds.size > 160) {
    const oldest = viewEventIds.keys().next().value;
    if (oldest) viewEventIds.delete(oldest);
  }
  return eventId;
}

export function SkuDetailPage() {
  const { store, sku } = useLoaderData() as SkuDetailLoaderData;
  const { profile } = useCoreAuth();
  const { accountKey } = useParams<{ accountKey?: string }>();
  const accountId = storefrontAccountMembershipId(accountKey);
  const storageScope = storefrontStorageScope(store.slug, accountId);
  const accountName = accountId && profile?.context.membershipId?.toLocaleLowerCase() === accountId
    ? profile.user.displayName
    : undefined;
  const locale: StorefrontLocale = normalizeStorefrontLocale(store.locale);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const location = useLocation();
  const shareToken = new URLSearchParams(location.search).get("share")?.trim() || "";
  const localeQuery = storefrontLocaleQuery(locale);
  const storefrontHome = shareToken
    ? `/${encodeURIComponent(store.slug)}/share/${encodeURIComponent(shareToken)}${localeQuery}`
    : `${storefrontBasePath(store.slug, accountKey)}${localeQuery}`;
  const navigate = useNavigate();
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(storageScope),
  );
  const [imageFailed, setImageFailed] = useState(!sku.image_url);
  const [announcements, setAnnouncements] = useState(store.announcements || []);
  const displayTag = sku.display_tag || sku.tags[0];
  const quantity = cart[sku.id]?.quantity || 0;
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const description = sku.description?.trim();
  const cameFromCatalog = Boolean(
    (location.state as { fromStorefrontCatalog?: boolean } | null)?.fromStorefrontCatalog,
  );

  useEffect(() => {
    writeStoreCart(storageScope, cart);
  }, [cart, storageScope]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [sku.id]);

  useEffect(() => {
    setImageFailed(!sku.image_url);
  }, [sku.image_url]);

  useEffect(() => {
    setAnnouncements(store.announcements || []);
  }, [store.announcements]);

  useEffect(
    () => subscribePublicCatalogRevision(() => {
      void api.getStore(store.slug, locale, accountId)
        .then((nextStore) => setAnnouncements(nextStore.announcements || []))
        .catch(() => undefined);
    }),
    [accountId, locale, store.slug],
  );

  useEffect(() => {
    const eventId = storefrontViewEventId(location.key, sku.id);
    void api.recordStoreSkuView(store.slug, sku.id, eventId).catch(() => undefined);
  }, [location.key, sku.id, store.slug]);

  useEffect(() => {
    const previousTitle = document.title;
    const previousLanguage = document.documentElement.lang;
    const previousDirection = document.documentElement.dir;
    document.documentElement.lang = locale;
    document.documentElement.dir = storefrontLayoutDirection();
    document.title = `${sku.name} | ${store.name}`;
    return () => {
      document.title = previousTitle;
      document.documentElement.lang = previousLanguage;
      document.documentElement.dir = previousDirection;
    };
  }, [sku.name, store.name, locale]);

  const updateQuantity = (skuId: string, nextQuantity: number) => {
    setCart((current) => {
      const next = { ...current };
      if (nextQuantity < 1) delete next[skuId];
      else if (next[skuId]) next[skuId] = { ...next[skuId], quantity: nextQuantity };
      return next;
    });
  };
  const updateCartNote = (skuId: string, note: string) => {
    setCart((current) => current[skuId]
      ? { ...current, [skuId]: { ...current[skuId], note } }
      : current);
  };

  const addToCart = () => {
    setCart((current) => ({
      ...current,
      [sku.id]: {
        sku,
        quantity: (current[sku.id]?.quantity || 0) + 1,
        note: current[sku.id]?.note,
      },
    }));
  };

  const returnToCatalog = () => {
    if (cameFromCatalog) {
      navigate(-1);
      return;
    }
    navigate(storefrontHome);
  };

  return (
    <div
      className={`store-shell sku-detail-shell${cartLines.length ? " has-cart" : ""}`}
      dir={storefrontLayoutDirection()}
      data-locale={locale}
      data-text-direction={storefrontDirection(locale)}
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
                  <span className="store-identity-mark">
                    <StoreIcon size={21} weight="duotone" />
                  </span>
                )}
                <span>
                  <strong>{store.storefront_scope === "CUSTOMER_SUBACCOUNT" ? (accountName || store.name) : store.name}</strong>
                  <small>{t("商品目录")}</small>
                </span>
              </Link>
              <span className="powered-by">{t("由智贸云提供")}</span>
            </div>
            <div className="header-actions">
              <StorefrontLanguageSwitch
                locale={locale}
                availableLocales={store.available_locales}
              />
              <ThemeToggle
                labels={{
                  toDark: t("切换深色模式"),
                  toLight: t("切换浅色模式"),
                }}
              />
              <StorefrontVisitorEntry tenantSlug={store.slug} accountKey={accountKey} locale={locale} />
              <CartDrawer
                slug={store.slug}
                accountId={accountId}
                accountKey={accountKey}
                storeName={store.name}
                contactEmail={store.contact_email}
                contactImages={store.support_widget?.custom_actions?.filter((action) => Boolean(action.visible && action.image_url))}
                lines={cartLines}
                onQuantity={updateQuantity}
                onNote={updateCartNote}
                onClear={() => setCart({})}
                locale={locale}
              />
            </div>
          </div>
        </Container>
      </header>

      <StorefrontTopNavigation store={store} accountKey={accountKey} locale={locale} />

      <StorefrontAnnouncements
        announcements={announcements}
        tenantSlug={store.slug}
        locale={locale}
      />

      <main className="sku-detail-main">
        <Container size="4">
          <button
            type="button"
            className="sku-detail-back"
            onClick={returnToCatalog}
          >
            <ArrowLeft weight="bold" />
            {t("返回商品目录")}
          </button>

          <section className="sku-detail-layout" aria-labelledby="sku-detail-title">
            <Card className="sku-detail-media" variant="surface">
              {sku.image_url && !imageFailed ? (
                <ProductImagePreview
                  src={sku.image_url}
                  alt={sku.name}
                  openLabel={t("点击查看大图")}
                  closeLabel={t("关闭图片预览")}
                  onError={() => setImageFailed(true)}
                />
              ) : (
                <div className="image-unavailable">
                  <ImageIcon size={42} />
                  <span>{t("暂无图片")}</span>
                </div>
              )}
              {displayTag ? (
                <span
                  className="sku-glass-tag sku-detail-display-tag"
                  style={tagGlassStyle(displayTag, sku.tag_color)}
                >
                  <span>{displayTag}</span>
                </span>
              ) : null}
            </Card>

            <div className="sku-detail-summary">
              <div className="sku-detail-kicker">
                <Package weight="duotone" />
                <span>SKU {sku.sku_code}</span>
              </div>
              <Heading id="sku-detail-title" as="h1" size="7">
                {sku.name}
              </Heading>

              <section className="sku-detail-description" aria-labelledby="sku-description-title">
                <Text id="sku-description-title" as="div" size="1" color="gray" weight="medium">
                  {t("商品描述")}
                </Text>
                <div className={`sku-detail-description-content${description ? "" : " is-empty"}`}>
                  {description || t("商家暂未补充详细描述。")}
                </div>
              </section>

              {sku.category ? (
                <Text size="1" color="gray">
                  {sku.category_label || sku.category}
                </Text>
              ) : null}

              {sku.tags.length ? (
                <div className="sku-detail-tags" aria-label={t("商品标签")}>
                  {sku.tags.map((tag) => (
                    <Badge key={tag} color="gray" variant="soft">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <div className="sku-detail-price">
                <Text size="1" color="gray">{t("参考单价")}</Text>
                <strong>{money(sku.price, sku.currency)}</strong>
              </div>

              <Button size="3" className="sku-detail-add" onClick={addToCart}>
                {quantity ? <Check weight="bold" /> : <Plus weight="bold" />}
                {quantity
                  ? t("已选 {quantity} 件，再加一件", { quantity })
                  : t("加入报价清单")}
              </Button>
              <Text size="1" color="gray">
                {t("最终价格与交期以商家确认后的正式报价为准。")}
              </Text>
            </div>
          </section>
        </Container>
      </main>

      <StorefrontSupportWidget
        tenantSlug={store.slug}
        accountId={accountId}
        accountKey={accountKey}
        storeName={store.name}
        locale={locale}
        config={store.support_widget}
      />

      <StorefrontFooter store={store} t={t} />
    </div>
  );
}
