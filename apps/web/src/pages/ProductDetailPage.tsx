import {
  Badge,
  Button,
  Card,
  Container,
  Heading,
  IconButton,
  Text,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  Check,
  Image as ImageIcon,
  Minus,
  Package,
  Plus,
  Stack,
  Storefront as StoreIcon,
  Trash,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { Link, useLoaderData, useLocation, useNavigate } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { StorefrontAnnouncements } from "../components/StorefrontAnnouncements";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { money } from "../lib/format";
import { subscribePublicCatalogRevision } from "../lib/publicCatalogRevision";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import { storefrontText } from "../lib/storefrontLocale";
import { tagGlassStyle } from "../lib/tagColors";
import type {
  Sku,
  Storefront,
  StorefrontLocale,
  StoreProductDetail,
} from "../types";

interface ProductDetailLoaderData {
  store: Storefront;
  product: StoreProductDetail;
}

const productViewEventIds = new Map<string, string>();

function productViewEventId(locationKey: string, productId: string) {
  const key = `${locationKey}:${productId}`;
  const existing = productViewEventIds.get(key);
  if (existing) return existing;
  const eventId = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  productViewEventIds.set(key, eventId);
  if (productViewEventIds.size > 160) {
    const oldest = productViewEventIds.keys().next().value;
    if (oldest) productViewEventIds.delete(oldest);
  }
  return eventId;
}

export function ProductDetailPage() {
  const { store, product } = useLoaderData() as ProductDetailLoaderData;
  const locale: StorefrontLocale = store.locale === "en-US" ? "en-US" : "zh-CN";
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const localeQuery = locale === "en-US" ? "?lang=en-US" : "";
  const storefrontHome = `/${encodeURIComponent(store.slug)}${localeQuery}`;
  const location = useLocation();
  const navigate = useNavigate();
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(store.slug),
  );
  const [imageFailed, setImageFailed] = useState(!product.image_url);
  const [announcements, setAnnouncements] = useState(store.announcements || []);
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const description = product.description?.trim();
  const displayTag = product.display_tag || product.tags[0];
  const cameFromCatalog = Boolean(
    (location.state as { fromStorefrontCatalog?: boolean } | null)
      ?.fromStorefrontCatalog,
  );
  const priceFrom = Number(product.price_from);
  const priceTo = Number(product.price_to);
  const priceLabel = (
    Number.isFinite(priceFrom)
    && Number.isFinite(priceTo)
    && Math.abs(priceFrom - priceTo) > 0.0001
  )
    ? `${money(product.price_from, product.currency)} – ${money(product.price_to, product.currency)}`
    : money(product.price_from, product.currency);

  useEffect(() => {
    writeStoreCart(store.slug, cart);
  }, [cart, store.slug]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [product.id]);

  useEffect(() => {
    setImageFailed(!product.image_url);
  }, [product.image_url]);

  useEffect(() => {
    setAnnouncements(store.announcements || []);
  }, [store.announcements]);

  useEffect(
    () => subscribePublicCatalogRevision(() => {
      void api.getStore(store.slug, locale)
        .then((nextStore) => setAnnouncements(nextStore.announcements || []))
        .catch(() => undefined);
    }),
    [locale, store.slug],
  );

  useEffect(() => {
    const firstSku = product.skus[0];
    if (!firstSku) return;
    const eventId = productViewEventId(location.key, product.id);
    void api.recordStoreSkuView(store.slug, firstSku.id, eventId)
      .catch(() => undefined);
  }, [location.key, product.id, product.skus, store.slug]);

  useEffect(() => {
    const previousTitle = document.title;
    const previousLanguage = document.documentElement.lang;
    document.documentElement.lang = locale;
    document.title = `${product.name} | ${store.name}`;
    return () => {
      document.title = previousTitle;
      document.documentElement.lang = previousLanguage;
    };
  }, [locale, product.name, store.name]);

  const updateQuantity = (skuId: string, nextQuantity: number) => {
    setCart((current) => {
      const next = { ...current };
      if (nextQuantity < 1) delete next[skuId];
      else if (next[skuId]) {
        next[skuId] = { ...next[skuId], quantity: nextQuantity };
      }
      return next;
    });
  };

  const addToCart = (sku: Sku) => {
    setCart((current) => ({
      ...current,
      [sku.id]: {
        sku,
        quantity: (current[sku.id]?.quantity || 0) + 1,
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
    <div className={`store-shell sku-detail-shell${cartLines.length ? " has-cart" : ""}`}>
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
                  <strong>{store.name}</strong>
                  <small>{t("商品目录")}</small>
                </span>
              </Link>
              <span className="powered-by">{t("由智贸云提供")}</span>
            </div>
            <div className="header-actions">
              <StorefrontLanguageSwitch locale={locale} />
              <ThemeToggle
                labels={{
                  toDark: t("切换深色模式"),
                  toLight: t("切换浅色模式"),
                }}
              />
              <CartDrawer
                slug={store.slug}
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
        announcements={announcements}
        tenantSlug={store.slug}
        locale={locale}
      />

      <main className="sku-detail-main product-detail-main">
        <Container size="4">
          <button
            type="button"
            className="sku-detail-back"
            onClick={returnToCatalog}
          >
            <ArrowLeft weight="bold" />
            {t("返回商品目录")}
          </button>

          <section className="sku-detail-layout" aria-labelledby="product-detail-title">
            <Card className="sku-detail-media" variant="surface">
              {product.image_url && !imageFailed ? (
                <img
                  src={product.image_url}
                  alt={product.name}
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
                  style={tagGlassStyle(displayTag, product.tag_color)}
                >
                  <span>{displayTag}</span>
                </span>
              ) : null}
            </Card>

            <div className="sku-detail-summary">
              <div className="sku-detail-kicker">
                <Package weight="duotone" />
                <span>
                  {product.product_code || t("商品")}
                  <i aria-hidden="true">·</i>
                  {t("{count} 个 SKU", { count: product.sku_count })}
                </span>
              </div>
              <Heading id="product-detail-title" as="h1" size="7">
                {product.name}
              </Heading>

              <section className="sku-detail-description" aria-labelledby="product-description-title">
                <Text id="product-description-title" as="div" size="1" color="gray" weight="medium">
                  {t("商品描述")}
                </Text>
                <div className={`sku-detail-description-content${description ? "" : " is-empty"}`}>
                  {description || t("商家暂未补充详细描述。")}
                </div>
              </section>

              {product.category ? (
                <Text size="1" color="gray">
                  {product.category_label || product.category}
                </Text>
              ) : null}

              {product.tags.length ? (
                <div className="sku-detail-tags" aria-label={t("商品标签")}>
                  {product.tags.map((tag) => (
                    <Badge key={tag} color="gray" variant="soft">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <div className="sku-detail-price">
                <Text size="1" color="gray">
                  {product.sku_count > 1 ? t("参考价格区间") : t("参考单价")}
                </Text>
                <strong>{priceLabel}</strong>
              </div>
              <Text size="1" color="gray">
                {t("请选择下方具体 SKU 后加入报价清单。")}
              </Text>
            </div>
          </section>

          <section className="product-variant-section" aria-labelledby="product-variant-title">
            <div className="product-variant-heading">
              <div>
                <Text size="1" color="gray">{t("商品规格")}</Text>
                <Heading id="product-variant-title" as="h2" size="5">
                  {t("选择 SKU")}
                </Heading>
              </div>
              <span>
                <Stack size={17} weight="duotone" />
                {t("共 {count} 个可选项", { count: product.sku_count })}
              </span>
            </div>

            <div className="product-variant-list">
              {product.skus.map((sku) => {
                const quantity = cart[sku.id]?.quantity || 0;
                const label = sku.specification || t("标准款");
                return (
                  <article
                    className={`product-variant-row${quantity ? " is-selected" : ""}`}
                    key={sku.id}
                  >
                    <div className="product-variant-identity">
                      <strong>{label}</strong>
                      <span>SKU {sku.sku_code}</span>
                    </div>
                    <div className="product-variant-price">
                      <small>{t("参考单价")}</small>
                      <strong>{money(sku.price, sku.currency)}</strong>
                    </div>
                    {quantity ? (
                      <div className="sku-quantity-control" aria-label={t("{name} 已选数量", { name: label })}>
                        <IconButton
                          size="2"
                          variant="soft"
                          color="gray"
                          onClick={() => updateQuantity(sku.id, quantity - 1)}
                          aria-label={t("减少 {name} 数量", { name: label })}
                        >
                          {quantity <= 1 ? <Trash size={16} /> : <Minus size={16} />}
                        </IconButton>
                        <span>
                          <small>{t("已选")}</small>
                          <strong>{quantity}</strong>
                        </span>
                        <IconButton
                          size="2"
                          onClick={() => addToCart(sku)}
                          aria-label={t("增加 {name} 数量", { name: label })}
                        >
                          <Plus size={16} />
                        </IconButton>
                      </div>
                    ) : (
                      <Button
                        size="2"
                        onClick={() => addToCart(sku)}
                        aria-label={t("将 {name} 加入报价清单", { name: label })}
                      >
                        <Plus size={17} />
                        {t("加入清单")}
                      </Button>
                    )}
                    {quantity ? (
                      <span className="product-variant-selected">
                        <Check size={13} weight="bold" />
                        {t("已加入")}
                      </span>
                    ) : null}
                  </article>
                );
              })}
            </div>
          </section>
        </Container>
      </main>

      <footer className="store-footer">
        <Container size="4">
          <div className="store-footer-inner">
            <Text size="1" color="gray">
              {t("商品与报价由 {store} 提供，报价草稿须经商家确认。", { store: store.name })}
            </Text>
            <Link to="/privacy">{t("隐私政策")}</Link>
          </div>
        </Container>
      </footer>
    </div>
  );
}
