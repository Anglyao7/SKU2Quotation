import { Dialog, IconButton } from "@radix-ui/themes";
import { CaretLeft, CaretRight, MagnifyingGlassPlus, X } from "@phosphor-icons/react";
import { useLayoutEffect, useMemo, useState, type MouseEvent } from "react";

interface ProductImagePreviewProps {
  src: string;
  images?: string[];
  alt: string;
  openLabel: string;
  closeLabel: string;
  previousLabel?: string;
  nextLabel?: string;
  onError: () => void;
}

export function ProductImagePreview({
  src,
  images,
  alt,
  openLabel,
  closeLabel,
  previousLabel = "查看上一张图片",
  nextLabel = "查看下一张图片",
  onError,
}: ProductImagePreviewProps) {
  const imageUrls = useMemo(
    () => Array.from(new Set([src, ...(images || [])].filter(Boolean))),
    [images, src],
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const activeSrc = imageUrls[activeIndex] || imageUrls[0] || src;

  // Keep the first frame in sync with the selected SKU/image.  Using a layout
  // effect avoids painting the previous gallery index for one frame when the
  // parent changes `src` (which made variant changes feel like they were stuck).
  useLayoutEffect(() => {
    const sourceIndex = imageUrls.indexOf(src);
    setActiveIndex((current) => {
      const next = sourceIndex >= 0 ? sourceIndex : 0;
      return current === next ? current : next;
    });
  }, [imageUrls, src]);

  const showPrevious = imageUrls.length > 1 && activeIndex > 0;
  const showNext = imageUrls.length > 1 && activeIndex < imageUrls.length - 1;
  const goPrevious = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setActiveIndex((current) => Math.max(0, current - 1));
  };
  const goNext = (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    setActiveIndex((current) => Math.min(imageUrls.length - 1, current + 1));
  };

  return (
    <Dialog.Root>
      <div className="sku-detail-image-gallery">
        <Dialog.Trigger>
          <button
            type="button"
            className="sku-detail-image-trigger"
            aria-label={openLabel}
          >
            <img
              src={activeSrc}
              alt={alt}
              loading="eager"
              decoding="async"
              onError={onError}
            />
            <span className="sku-detail-image-affordance" aria-hidden="true">
              <MagnifyingGlassPlus weight="bold" />
              <span>{openLabel}</span>
            </span>
          </button>
        </Dialog.Trigger>
        {showPrevious ? (
          <button
            type="button"
            className="product-image-gallery-nav is-previous"
            aria-label={previousLabel}
            onClick={goPrevious}
          >
            <CaretLeft weight="bold" />
          </button>
        ) : null}
        {showNext ? (
          <button
            type="button"
            className="product-image-gallery-nav is-next"
            aria-label={nextLabel}
            onClick={goNext}
          >
            <CaretRight weight="bold" />
          </button>
        ) : null}
        {imageUrls.length > 1 ? (
          <span className="product-image-gallery-count" aria-live="polite">
            {activeIndex + 1} / {imageUrls.length}
          </span>
        ) : null}
      </div>

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
          <img
            src={activeSrc}
            alt={alt}
            loading="eager"
            decoding="async"
            onError={onError}
          />
          {showPrevious ? (
            <button
              type="button"
              className="product-image-lightbox-nav is-previous"
              aria-label={previousLabel}
              onClick={goPrevious}
            >
              <CaretLeft weight="bold" />
            </button>
          ) : null}
          {showNext ? (
            <button
              type="button"
              className="product-image-lightbox-nav is-next"
              aria-label={nextLabel}
              onClick={goNext}
            >
              <CaretRight weight="bold" />
            </button>
          ) : null}
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}
