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
import { Link, useLoaderData, useLocation, useNavigate } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { ThemeToggle } from "../components/ThemeToggle";
import { imageFallback, money } from "../lib/format";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import { tagGlassStyle } from "../lib/tagColors";
import type { Sku, Storefront } from "../types";

interface SkuDetailLoaderData {
  store: Storefront;
  sku: Sku;
}

export function SkuDetailPage() {
  const { store, sku } = useLoaderData() as SkuDetailLoaderData;
  const location = useLocation();
  const navigate = useNavigate();
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(store.slug),
  );
  const fallback = imageFallback(sku.sku_code);
  const [imageSrc, setImageSrc] = useState(sku.image_url || fallback);
  const [imageFailed, setImageFailed] = useState(false);
  const displayTag = sku.display_tag || sku.tags[0];
  const quantity = cart[sku.id]?.quantity || 0;
  const cartLines = useMemo(() => Object.values(cart), [cart]);
  const description = sku.description?.trim();
  const cameFromCatalog = Boolean(
    (location.state as { fromStorefrontCatalog?: boolean } | null)?.fromStorefrontCatalog,
  );

  useEffect(() => {
    writeStoreCart(store.slug, cart);
  }, [cart, store.slug]);

  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [sku.id]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${sku.name} | ${store.name}`;
    return () => {
      document.title = previousTitle;
    };
  }, [sku.name, store.name]);

  const updateQuantity = (skuId: string, nextQuantity: number) => {
    setCart((current) => {
      const next = { ...current };
      if (nextQuantity < 1) delete next[skuId];
      else if (next[skuId]) next[skuId] = { ...next[skuId], quantity: nextQuantity };
      return next;
    });
  };

  const addToCart = () => {
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
    navigate(`/${encodeURIComponent(store.slug)}`);
  };

  return (
    <div className={`store-shell sku-detail-shell${cartLines.length ? " has-cart" : ""}`}>
      <header className="store-header">
        <Container size="4" className="store-header-container">
          <div className="header-inner">
            <div className="store-header-branding">
              <Link
                to={`/${encodeURIComponent(store.slug)}`}
                className="store-identity"
                aria-label={`${store.name} 商品目录首页`}
              >
                {store.logo_url ? (
                  <img src={store.logo_url} alt={`${store.name} 标志`} />
                ) : (
                  <span className="store-identity-mark">
                    <StoreIcon size={21} weight="duotone" />
                  </span>
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
                slug={store.slug}
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

      <main className="sku-detail-main">
        <Container size="4">
          <button
            type="button"
            className="sku-detail-back"
            onClick={returnToCatalog}
          >
            <ArrowLeft weight="bold" />
            返回商品目录
          </button>

          <section className="sku-detail-layout" aria-labelledby="sku-detail-title">
            <Card className="sku-detail-media" variant="surface">
              {!imageFailed ? (
                <img
                  src={imageSrc}
                  alt={sku.name}
                  onError={() => {
                    if (imageSrc !== fallback) setImageSrc(fallback);
                    else setImageFailed(true);
                  }}
                />
              ) : (
                <div className="image-unavailable">
                  <ImageIcon size={42} />
                  <span>暂无图片</span>
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
                  商品描述
                </Text>
                <div className={`sku-detail-description-content${description ? "" : " is-empty"}`}>
                  {description || "商家暂未补充详细描述。"}
                </div>
              </section>

              {sku.category ? (
                <Text size="1" color="gray">
                  {sku.category}
                </Text>
              ) : null}

              {sku.tags.length ? (
                <div className="sku-detail-tags" aria-label="商品标签">
                  {sku.tags.map((tag) => (
                    <Badge key={tag} color="gray" variant="soft">
                      {tag}
                    </Badge>
                  ))}
                </div>
              ) : null}

              <div className="sku-detail-price">
                <Text size="1" color="gray">参考单价</Text>
                <strong>{money(sku.price, sku.currency)}</strong>
              </div>

              <Button size="3" className="sku-detail-add" onClick={addToCart}>
                {quantity ? <Check weight="bold" /> : <Plus weight="bold" />}
                {quantity ? `已选 ${quantity} 件，再加一件` : "加入报价清单"}
              </Button>
              <Text size="1" color="gray">
                最终价格与交期以商家确认后的正式报价为准。
              </Text>
            </div>
          </section>
        </Container>
      </main>

      <footer className="store-footer">
        <Container size="4">
          <div className="store-footer-inner">
            <Text size="1" color="gray">
              商品与报价由 {store.name} 提供，报价草稿须经商家确认。
            </Text>
            <Link to="/privacy">隐私政策</Link>
          </div>
        </Container>
      </footer>
    </div>
  );
}
