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
import { ProductImagePreview } from "../components/ProductImagePreview";
import { StorefrontAnnouncements } from "../components/StorefrontAnnouncements";
import { StorefrontSupportWidget } from "../components/StorefrontSupportWidget";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { ThemeToggle } from "../components/ThemeToggle";
import { api } from "../lib/api";
import { money } from "../lib/format";
import {
  buildProductVariantModel,
  selectedVariantValues,
  skuIdForVariantChoice,
} from "../lib/productVariantOptions";
import { subscribePublicCatalogRevision } from "../lib/publicCatalogRevision";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import {
  normalizeStorefrontLocale,
  storefrontDirection,
  storefrontText,
} from "../lib/storefrontLocale";
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
  const locale: StorefrontLocale = normalizeStorefrontLocale(store.locale);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const location = useLocation();
  const shareToken = new URLSearchParams(location.search).get("share")?.trim() || "";
  const storefrontQuery = new URLSearchParams();
  if (locale !== "zh-CN") storefrontQuery.set("lang", locale);
  const storefrontSearch = storefrontQuery.toString();
  const storefrontHome = shareToken
    ? `/${encodeURIComponent(store.slug)}/share/${encodeURIComponent(shareToken)}${storefrontSearch ? `?${storefrontSearch}` : ""}`
    : `/${encodeURIComponent(store.slug)}${storefrontSearch ? `?${storefrontSearch}` : ""}`;
  const navigate = useNavigate();
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(store.slug),
  );
  const variantModel = useMemo(
    () => buildProductVariantModel(product.skus, {
      fallbackDimension: storefrontText(locale, "款式"),
      fallbackValue: storefrontText(locale, "标准款"),
    }),
    [locale, product.skus],
  );
  const [selectedSkuId, setSelectedSkuId] = useState(
    () => product.skus[0]?.id || "",
  );
  const selectedSku = product.skus.find((sku) => sku.id === selectedSkuId)
    || product.skus[0];
  const selectedValues = selectedVariantValues(
    variantModel,
    selectedSku?.id || "",
  );
  const selectedLabel = selectedSku?.specification?.trim()
    || selectedSku?.name?.trim()
    || t("标准款");
  const selectedQuantity = selectedSku ? cart[selectedSku.id]?.quantity || 0 : 0;
  const selectedImageUrl = selectedSku?.image_url || product.image_url;
  const [imageFailed, setImageFailed] = useState(!selectedImageUrl);
  const [descriptionExpanded, setDescriptionExpanded] = useState(false);
  const [announcements, setAnnouncements] = useState(store.announcements || []);
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const description = product.description?.trim();
  const displayTag = product.display_tag || product.tags[0];
  const cameFromCatalog = Boolean(
    (location.state as { fromStorefrontCatalog?: boolean } | null)
      ?.fromStorefrontCatalog,
  );
  const priceLabel = selectedSku
    ? money(selectedSku.price, selectedSku.currency || product.currency)
    : money(product.price_from, product.currency);

  useEffect(() => {
    writeStoreCart(store.slug, cart);
  }, [cart, store.slug]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [product.id]);

  useEffect(() => {
    setSelectedSkuId(product.skus[0]?.id || "");
    setDescriptionExpanded(false);
  }, [product.id, product.skus]);

  useEffect(() => {
    setImageFailed(!selectedImageUrl);
  }, [selectedImageUrl]);

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
    const previousDirection = document.documentElement.dir;
    document.documentElement.lang = locale;
    document.documentElement.dir = storefrontDirection(locale);
    document.title = `${product.name} | ${store.name}`;
    return () => {
      document.title = previousTitle;
      document.documentElement.lang = previousLanguage;
      document.documentElement.dir = previousDirection;
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

  const selectVariantChoice = (dimensionKey: string, value: string) => {
    setSelectedSkuId((currentSkuId) => skuIdForVariantChoice(
      variantModel,
      currentSkuId,
      dimensionKey,
      value,
    ));
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
              {selectedImageUrl && !imageFailed ? (
                <ProductImagePreview
                  src={selectedImageUrl}
                  alt={`${product.name} · ${selectedLabel}`}
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
                <div
                  className={`sku-detail-description-content${description ? "" : " is-empty"}${description && !descriptionExpanded ? " is-collapsed" : ""}`}
                >
                  {description || t("商家暂未补充详细描述。")}
                </div>
                {description && description.length > 160 ? (
                  <button
                    type="button"
                    className="sku-detail-description-toggle"
                    aria-expanded={descriptionExpanded}
                    onClick={() => setDescriptionExpanded((current) => !current)}
                  >
                    {descriptionExpanded ? t("收起描述") : t("查看完整描述")}
                  </button>
                ) : null}
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
                  {t("参考单价")}
                </Text>
                <strong>{priceLabel}</strong>
              </div>
              <Text size="1" color="gray">
                {t("选择规格组合后即可加入报价清单。")}
              </Text>

              <section className="product-variant-section" aria-labelledby="product-variant-title">
                <div className="product-variant-heading">
                  <div>
                    <Text size="1" color="gray">{t("商品规格")}</Text>
                    <Heading id="product-variant-title" as="h2" size="4">
                      {t("选择规格")}
                    </Heading>
                  </div>
                  <span>
                    <Stack size={17} weight="duotone" />
                    {t("{count} 个 SKU", { count: product.sku_count })}
                  </span>
                </div>

                <div className="product-option-groups">
                  {variantModel.dimensions.map((dimension) => (
                    <fieldset className="product-option-group" key={dimension.key}>
                      <legend>
                        <span>{dimension.label}</span>
                      </legend>
                      <div className="product-option-values">
                        {dimension.choices.map((choice) => {
                          const selected = selectedValues[dimension.key] === choice.value;
                          return (
                            <button
                              type="button"
                              className={`product-option-choice${selected ? " is-selected" : ""}`}
                              key={choice.value}
                              title={choice.label}
                              aria-pressed={selected}
                              aria-label={`${dimension.label}: ${choice.label}`}
                              onClick={() => selectVariantChoice(dimension.key, choice.value)}
                            >
                              <span>{choice.label}</span>
                              {selected ? <Check size={13} weight="bold" aria-hidden="true" /> : null}
                            </button>
                          );
                        })}
                      </div>
                    </fieldset>
                  ))}
                </div>

                {selectedSku ? (
                  <div className="product-selection-bar">
                    <div className="product-selection-identity">
                      <small>{t("已选 SKU")}</small>
                      <strong>{selectedLabel}</strong>
                      <span>SKU {selectedSku.sku_code}</span>
                    </div>
                    {selectedQuantity ? (
                      <div
                        className="sku-quantity-control product-selection-quantity"
                        aria-label={t("{name} 已选数量", { name: selectedLabel })}
                      >
                        <IconButton
                          size="2"
                          variant="soft"
                          color="gray"
                          onClick={() => updateQuantity(selectedSku.id, selectedQuantity - 1)}
                          aria-label={t("减少 {name} 数量", { name: selectedLabel })}
                        >
                          {selectedQuantity <= 1 ? <Trash size={16} /> : <Minus size={16} />}
                        </IconButton>
                        <span>
                          <small>{t("已选")}</small>
                          <strong>{selectedQuantity}</strong>
                        </span>
                        <IconButton
                          size="2"
                          onClick={() => addToCart(selectedSku)}
                          aria-label={t("增加 {name} 数量", { name: selectedLabel })}
                        >
                          <Plus size={16} />
                        </IconButton>
                      </div>
                    ) : (
                      <Button
                        className="product-selection-add"
                        size="3"
                        onClick={() => addToCart(selectedSku)}
                        aria-label={t("将 {name} 加入报价清单", { name: selectedLabel })}
                      >
                        <Plus size={18} />
                        {t("加入报价清单")}
                      </Button>
                    )}
                  </div>
                ) : null}
              </section>
            </div>
          </section>
        </Container>
      </main>

      <StorefrontSupportWidget
        tenantSlug={store.slug}
        storeName={store.name}
        locale={locale}
        config={store.support_widget}
      />

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
