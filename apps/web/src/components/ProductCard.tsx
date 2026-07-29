import { Button, Card, IconButton, Text } from "@radix-ui/themes";
import { Check, Image as ImageIcon, Minus, Plus, Trash } from "@phosphor-icons/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { imageFallback, money } from "../lib/format";
import { storefrontText } from "../lib/storefrontLocale";
import { tagGlassStyle } from "../lib/tagColors";
import type { Sku, StorefrontLocale } from "../types";

export function ProductCard({
  sku,
  detailsHref,
  quantity,
  onAdd,
  onDecrease,
  onOpenDetails,
  locale,
}: {
  sku: Sku;
  detailsHref: string;
  quantity: number;
  onAdd: () => void;
  onDecrease: () => void;
  onOpenDetails: () => void;
  locale: StorefrontLocale;
}) {
  const fallback = imageFallback(sku.sku_code);
  const [imageSrc, setImageSrc] = useState(sku.image_url || fallback);
  const [imageFailed, setImageFailed] = useState(false);
  const displayTag = sku.display_tag || sku.tags[0];
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );

  return (
    <Card className={`sku-card${quantity > 0 ? " is-selected" : ""}`} variant="surface">
      <Link
        to={detailsHref}
        state={{ fromStorefrontCatalog: true }}
        className="sku-image-wrap sku-detail-link"
        aria-label={t("查看 {name} 商品详情", { name: sku.name })}
        onClick={onOpenDetails}
      >
        {!imageFailed ? (
          <img
            className="sku-image"
            src={imageSrc}
            alt={sku.name}
            loading="lazy"
            onError={() => {
              if (imageSrc !== fallback) setImageSrc(fallback);
              else setImageFailed(true);
            }}
          />
        ) : (
          <div className="image-unavailable"><ImageIcon size={30} /><span>{t("暂无图片")}</span></div>
        )}
        {displayTag && (
          <span
            className="sku-glass-tag"
            style={tagGlassStyle(displayTag, sku.tag_color)}
            title={displayTag}
          >
            <span>{displayTag}</span>
          </span>
        )}
        {quantity > 0 && <span className="cart-count-badge"><Check size={13} weight="bold" />{t("已选 {quantity}", { quantity })}</span>}
      </Link>
      <div className="sku-card-body">
        <Text as="div" size="3" weight="medium" className="sku-name">
          <Link
            to={detailsHref}
            state={{ fromStorefrontCatalog: true }}
            onClick={onOpenDetails}
          >
            {sku.name}
          </Link>
        </Text>
        <div className="sku-card-footer">
          <div className="sku-price-block">
            <Text as="div" size="1" color="gray">{t("参考单价")}</Text>
            <Text as="div" size="4" weight="bold" className="price-text">{money(sku.price, sku.currency)}</Text>
          </div>
          {quantity > 0 ? (
            <div className="sku-quantity-control" aria-label={t("{name} 已选数量", { name: sku.name })}>
              <IconButton
                size="2"
                variant="soft"
                color="gray"
                onClick={onDecrease}
                aria-label={t("减少 {name} 数量", { name: sku.name })}
              >
                {quantity <= 1 ? <Trash size={16} /> : <Minus size={16} />}
              </IconButton>
              <span><small>{t("已选")}</small><strong>{quantity}</strong></span>
              <IconButton size="2" onClick={onAdd} aria-label={t("增加 {name} 数量", { name: sku.name })}>
                <Plus size={16} />
              </IconButton>
            </div>
          ) : (
            <Button size="2" className="sku-add-button" onClick={onAdd} aria-label={t("将 {name} 加入报价清单", { name: sku.name })}>
              <Plus size={17} />
              <span className="sku-add-label">{t("加入清单")}</span>
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
