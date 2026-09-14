import { Button, Card, Text } from "@radix-ui/themes";
import { ArrowRight, Image as ImageIcon } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { storefrontPriceLabel, storefrontText } from "../lib/storefrontLocale";
import type { StoreProduct, StorefrontLocale } from "../types";
import { StorefrontCatalogImage } from "./StorefrontCatalogImage";

export function ProductCard({
  product,
  tenantSlug,
  detailsHref,
  onOpenDetails,
  onPrefetchDetails,
  locale,
  showPrice = true,
  visualMatch,
  deferImages = false,
}: {
  product: StoreProduct;
  tenantSlug: string;
  detailsHref: string;
  onOpenDetails: () => void;
  onPrefetchDetails: () => void;
  locale: StorefrontLocale;
  showPrice?: boolean;
  deferImages?: boolean;
  visualMatch?: {
    percent: number;
    label: string;
  };
}) {
  const prefetchedDetails = useRef(false);
  const prefetchTimer = useRef<number | null>(null);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const priceLabel = storefrontPriceLabel(
    locale,
    product.price_from,
    product.price_to,
    product.currency,
  );

  useEffect(() => () => {
    if (prefetchTimer.current !== null) window.clearTimeout(prefetchTimer.current);
  }, []);

  const cancelPrefetch = () => {
    if (prefetchTimer.current === null) return;
    window.clearTimeout(prefetchTimer.current);
    prefetchTimer.current = null;
  };

  const prefetchDetails = (immediate = false) => {
    if (prefetchedDetails.current) return;
    if (!immediate) {
      if (prefetchTimer.current !== null) return;
      prefetchTimer.current = window.setTimeout(() => {
        prefetchTimer.current = null;
        prefetchDetails(true);
      }, 140);
      return;
    }
    cancelPrefetch();
    prefetchedDetails.current = true;
    onPrefetchDetails();
  };

  return (
    <Card
      className="sku-card product-card"
      variant="surface"
      onPointerEnter={() => prefetchDetails()}
      onPointerLeave={cancelPrefetch}
      onPointerDown={() => prefetchDetails(true)}
      onFocus={() => prefetchDetails()}
      onBlur={cancelPrefetch}
    >
      <Link
        to={detailsHref}
        state={{ fromStorefrontCatalog: true }}
        className="sku-image-wrap sku-detail-link"
        aria-label={t("查看 {name} 商品详情", { name: product.name })}
        onClick={onOpenDetails}
      >
        {product.image_url ? (
          <StorefrontCatalogImage
            key={product.image_url}
            enabled={!deferImages}
            className="sku-image"
            src={product.image_url}
            alt={product.name}
            fallback={<div className="image-unavailable"><ImageIcon size={30} /><span>{t("暂无图片")}</span></div>}
          />
        ) : (
          <div className="image-unavailable"><ImageIcon size={30} /><span>{t("暂无图片")}</span></div>
        )}
      </Link>
      <div className="sku-card-body">
        {visualMatch ? (
          <div className="product-visual-match">
            <span className="product-visual-match-label">
              <ImageIcon size={14} weight="duotone" aria-hidden="true" />
              <span>{visualMatch.label}</span>
            </span>
            <strong>{visualMatch.percent.toFixed(1)}%</strong>
          </div>
        ) : null}
        <Text as="div" size="3" weight="medium" className="sku-name">
          <Link
            to={detailsHref}
            state={{ fromStorefrontCatalog: true }}
            onClick={onOpenDetails}
          >
            {product.name}
          </Link>
        </Text>
        <div className={`sku-card-footer${showPrice ? "" : " is-price-hidden"}`}>
          {showPrice ? <div className="sku-price-block">
            <Text
              as="div"
              size="4"
              weight="bold"
              className="price-text"
              title={priceLabel}
            >
              {priceLabel}
            </Text>
          </div> : null}
          <Button
            asChild
            size="2"
            className="sku-add-button sku-add-button-icon"
            aria-label={t("查看规格")}
            title={t("查看规格")}
          >
            <Link
              to={detailsHref}
              state={{ fromStorefrontCatalog: true }}
              onClick={onOpenDetails}
            >
              <span className="visually-hidden">{t("查看规格")}</span>
              <ArrowRight size={17} aria-hidden="true" />
            </Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}
