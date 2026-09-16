import { Dialog, IconButton } from "@radix-ui/themes";
import { MagnifyingGlassPlus, X } from "@phosphor-icons/react";
import { useEffect, useLayoutEffect, useMemo, useState } from "react";
import { createImageSwipeHandlers } from "../lib/imageSwipe";

interface ProductImagePreviewProps {
  src: string;
  images?: string[];
  alt: string;
  openLabel: string;
  closeLabel: string;
  onError: () => void;
}

export function ProductImagePreview({
  src,
  images,
  alt,
  openLabel,
  closeLabel,
  onError,
}: ProductImagePreviewProps) {
  const imageUrls = useMemo(
    () => Array.from(new Set([...(images || []), src].filter(Boolean))),
    [images, src],
  );
  const [activeIndex, setActiveIndex] = useState(0);
  const [loadedUrls, setLoadedUrls] = useState<Set<string>>(() => new Set());
  const [failedUrls, setFailedUrls] = useState<Set<string>>(() => new Set());
  const activeSrc = imageUrls[activeIndex] || imageUrls[0] || src;
  const activeLoaded = loadedUrls.has(activeSrc);
  const swipeHandlers = useMemo(() => createImageSwipeHandlers((step) => {
    setActiveIndex((current) => Math.max(0, Math.min(imageUrls.length - 1, current + step)));
  }), [imageUrls]);

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

  useEffect(() => {
    if (!imageUrls.length || !imageUrls.every((url) => failedUrls.has(url))) return;
    onError();
  }, [failedUrls, imageUrls, onError]);

  useEffect(() => {
    if (!failedUrls.has(activeSrc)) return;
    const fallbackIndex = imageUrls.findIndex((url) => !failedUrls.has(url));
    if (fallbackIndex >= 0) setActiveIndex(fallbackIndex);
  }, [activeSrc, failedUrls, imageUrls]);

  const markLoaded = (url: string) => {
    setLoadedUrls((current) => {
      if (current.has(url)) return current;
      const next = new Set(current);
      next.add(url);
      return next;
    });
  };

  const markFailed = (url: string) => {
    setFailedUrls((current) => {
      if (current.has(url)) return current;
      const next = new Set(current);
      next.add(url);
      return next;
    });
  };

  const markDecoded = (url: string, image: HTMLImageElement) => {
    // Every gallery image is mounted eagerly. Decode it while it is still
    // hidden so a later navigation only changes visibility and never waits on
    // the main thread to decode a large product photo.
    void image.decode()
      .catch(() => undefined)
      .finally(() => markLoaded(url));
  };

  return (
    <Dialog.Root>
      <div className="sku-detail-image-gallery">
        <Dialog.Trigger>
          <button
            type="button"
            className="sku-detail-image-trigger"
            aria-label={openLabel}
            aria-busy={!activeLoaded}
            {...swipeHandlers}
          >
            {imageUrls.map((url, index) => (
              <img
                key={url}
                className={`product-image-gallery-item${index === activeIndex ? " is-active" : ""}${loadedUrls.has(url) ? " is-loaded" : ""}`}
                src={url}
                alt={index === activeIndex ? alt : ""}
                aria-hidden={index !== activeIndex}
                loading="eager"
                fetchPriority={index === activeIndex ? "high" : "low"}
                decoding="async"
                draggable={false}
                onLoad={(event) => markDecoded(url, event.currentTarget)}
                onError={() => markFailed(url)}
              />
            ))}
            {!activeLoaded ? <span className="product-image-gallery-loading" aria-hidden="true" /> : null}
            <span className="sku-detail-image-affordance" aria-hidden="true">
              <MagnifyingGlassPlus weight="bold" />
              <span>{openLabel}</span>
            </span>
          </button>
        </Dialog.Trigger>
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
        <div className="product-image-lightbox-stage" {...swipeHandlers}>
          <img
            key={activeSrc}
            src={activeSrc}
            alt={alt}
            loading="eager"
            fetchPriority="high"
            decoding="async"
            draggable={false}
            onLoad={(event) => markDecoded(activeSrc, event.currentTarget)}
            onError={() => markFailed(activeSrc)}
          />
        </div>
      </Dialog.Content>
    </Dialog.Root>
  );
}
