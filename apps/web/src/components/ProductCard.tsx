import { Button, Card, IconButton, Text } from "@radix-ui/themes";
import { Check, Image as ImageIcon, Minus, Plus, Trash } from "@phosphor-icons/react";
import { useState } from "react";
import { imageFallback, money } from "../lib/format";
import type { Sku } from "../types";

export function ProductCard({
  sku,
  quantity,
  onAdd,
  onDecrease,
}: {
  sku: Sku;
  quantity: number;
  onAdd: () => void;
  onDecrease: () => void;
}) {
  const fallback = imageFallback(sku.sku_code);
  const [imageSrc, setImageSrc] = useState(sku.image_url || fallback);
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <Card className={`sku-card${quantity > 0 ? " is-selected" : ""}`} variant="surface">
      <div className="sku-image-wrap">
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
          <div className="image-unavailable"><ImageIcon size={30} /><span>暂无图片</span></div>
        )}
        {sku.tags.length > 0 && (
          <span className="sku-glass-tag" title={sku.tags.join("、")}>
            <span>{sku.tags[0]}</span>
            {sku.tags.length > 1 && <small>+{sku.tags.length - 1}</small>}
          </span>
        )}
        {quantity > 0 && <span className="cart-count-badge"><Check size={13} weight="bold" />已选 {quantity}</span>}
      </div>
      <div className="sku-card-body">
        <Text as="div" size="3" weight="medium" className="sku-name">{sku.name}</Text>
        <div className="sku-card-footer">
          <div className="sku-price-block">
            <Text as="div" size="1" color="gray">参考单价</Text>
            <Text as="div" size="4" weight="bold" className="price-text">{money(sku.price, sku.currency)}</Text>
          </div>
          {quantity > 0 ? (
            <div className="sku-quantity-control" aria-label={`${sku.name} 已选数量`}>
              <IconButton
                size="2"
                variant="soft"
                color="gray"
                onClick={onDecrease}
                aria-label={`减少 ${sku.name} 数量`}
              >
                {quantity <= 1 ? <Trash size={16} /> : <Minus size={16} />}
              </IconButton>
              <span><small>已选</small><strong>{quantity}</strong></span>
              <IconButton size="2" onClick={onAdd} aria-label={`增加 ${sku.name} 数量`}>
                <Plus size={16} />
              </IconButton>
            </div>
          ) : (
            <Button size="2" className="sku-add-button" onClick={onAdd} aria-label={`将 ${sku.name} 加入报价清单`}>
              <Plus size={17} />
              <span className="sku-add-label">加入清单</span>
            </Button>
          )}
        </div>
      </div>
    </Card>
  );
}
