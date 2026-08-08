import { Dialog, IconButton } from "@radix-ui/themes";
import { MagnifyingGlassPlus, X } from "@phosphor-icons/react";

interface ProductImagePreviewProps {
  src: string;
  alt: string;
  openLabel: string;
  closeLabel: string;
  onError: () => void;
}

export function ProductImagePreview({
  src,
  alt,
  openLabel,
  closeLabel,
  onError,
}: ProductImagePreviewProps) {
  return (
    <Dialog.Root>
      <Dialog.Trigger>
        <button
          type="button"
          className="sku-detail-image-trigger"
          aria-label={openLabel}
        >
          <img src={src} alt={alt} onError={onError} />
          <span className="sku-detail-image-affordance" aria-hidden="true">
            <MagnifyingGlassPlus weight="bold" />
            <span>{openLabel}</span>
          </span>
        </button>
      </Dialog.Trigger>

      <Dialog.Content className="product-image-lightbox">
        <Dialog.Title className="visually-hidden">{alt}</Dialog.Title>
        <Dialog.Description className="visually-hidden">
          {openLabel}
        </Dialog.Description>
        <Dialog.Close>
          <IconButton
            type="button"
            className="product-image-lightbox-close"
            size="3"
            variant="soft"
            color="gray"
            aria-label={closeLabel}
          >
            <X weight="bold" />
          </IconButton>
        </Dialog.Close>
        <div className="product-image-lightbox-stage">
          <img src={src} alt={alt} onError={onError} />
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}
