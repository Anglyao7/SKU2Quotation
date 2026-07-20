import { Badge, Button, Card, IconButton, Text, Tooltip } from "@radix-ui/themes";
import { Check, Image as ImageIcon, Plus, ShoppingCartSimple } from "@phosphor-icons/react";
import { useState } from "react";
import { imageFallback, money } from "../lib/format";
import type { Sku } from "../types";

export function ProductCard({ sku, quantity, onAdd }: { sku: Sku; quantity: number; onAdd: () => void }) {
  const fallback = imageFallback(sku.sku_code);
  const [imageSrc, setImageSrc] = useState(sku.image_url || fallback);
  const [imageFailed, setImageFailed] = useState(false);

  return (
    <Card className="sku-card" variant="surface">
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
        {quantity > 0 && <span className="cart-count-badge"><Check size={13} weight="bold" />已选 {quantity}</span>}
      </div>
      <div className="sku-card-body">
        <div className="sku-code-row">
          <Text size="1" color="gray" className="mono-text">{sku.sku_code}</Text>
          {sku.category && <Text size="1" color="gray">{sku.category}</Text>}
        </div>
        <Text as="div" size="3" weight="medium" className="sku-name">{sku.name}</Text>
        <div className="tag-row" aria-label="商品标签">
          {sku.tags.slice(0, 3).map((tag) => <Badge key={tag} variant="soft" color="gray">{tag}</Badge>)}
          {sku.tags.length > 3 && <Badge variant="outline" color="gray">+{sku.tags.length - 3}</Badge>}
        </div>
        <div className="sku-card-footer">
          <div>
            <Text as="div" size="3" weight="bold" className="price-text">{money(sku.price, sku.currency)}</Text>
            <Text as="div" size="1" color="gray">{sku.moq ? `${sku.moq} 件起订` : "起订量可协商"}</Text>
          </div>
          <Tooltip content="加入报价清单">
            <IconButton size="3" onClick={onAdd} aria-label={`将 ${sku.name} 加入报价清单`}>
              {quantity > 0 ? <Plus size={19} /> : <ShoppingCartSimple size={19} />}
            </IconButton>
          </Tooltip>
        </div>
      </div>
    </Card>
  );
}
