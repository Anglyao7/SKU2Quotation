import { Button, Card, Text } from "@radix-ui/themes";
import { ArrowRight, Image as ImageIcon } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { money } from "../lib/format";
import { storefrontText } from "../lib/storefrontLocale";
import type { StoreProduct, StorefrontLocale } from "../types";

export function ProductCard({
  product,
  detailsHref,
  onOpenDetails,
  onPrefetchDetails,
  locale,
}: {
  product: StoreProduct;
  detailsHref: string;
  onOpenDetails: () => void;
  onPrefetchDetails: () => void;
  locale: StorefrontLocale;
}) {
  const [imageFailed, setImageFailed] = useState(!product.image_url);
  const prefetchedDetails = useRef(false);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
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
    setImageFailed(!product.image_url);
  }, [product.image_url]);

  const prefetchDetails = () => {
    if (prefetchedDetails.current) return;
    prefetchedDetails.current = true;
    onPrefetchDetails();
  };

  return (
    <Card
      className="sku-card product-card"
      variant="surface"
      onPointerEnter={prefetchDetails}
      onPointerDown={prefetchDetails}
      onFocus={prefetchDetails}
    >
      <Link
        to={detailsHref}
        state={{ fromStorefrontCatalog: true }}
        className="sku-image-wrap sku-detail-link"
        aria-label={t("查看 {name} 商品详情", { name: product.name })}
        onClick={onOpenDetails}
      >
        {product.image_url && !imageFailed ? (
          <img
            className="sku-image"
            src={product.image_url}
            alt={product.name}
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <div className="image-unavailable"><ImageIcon size={30} /><span>{t("暂无图片")}</span></div>
        )}
      </Link>
      <div className="sku-card-body">
        <Text as="div" size="3" weight="medium" className="sku-name">
          <Link
            to={detailsHref}
            state={{ fromStorefrontCatalog: true }}
            onClick={onOpenDetails}
          >
            {product.name}
          </Link>
        </Text>
        <div className="sku-card-footer">
          <div className="sku-price-block">
            <Text as="div" size="4" weight="bold" className="price-text">
              {priceLabel}
            </Text>
          </div>
          <Button asChild size="2" className="sku-add-button">
            <Link
              to={detailsHref}
              state={{ fromStorefrontCatalog: true }}
              onClick={onOpenDetails}
            >
              <span className="sku-add-label">{t("查看规格")}</span>
              <ArrowRight size={16} />
            </Link>
          </Button>
        </div>
      </div>
    </Card>
  );
}
