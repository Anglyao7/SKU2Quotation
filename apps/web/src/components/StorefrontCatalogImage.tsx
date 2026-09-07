import { useEffect, useRef, useState, type ReactNode } from "react";
import { observeCatalogImage, storefrontImageQueue } from "../lib/storefrontImageQueue";

export function StorefrontCatalogImage({ src, alt, className, fallback, enabled = true }: {
  src: string;
  alt: string;
  className?: string;
  fallback: ReactNode;
  enabled?: boolean;
}) {
  const element = useRef<HTMLImageElement>(null);
  const [result, setResult] = useState({ src: "", loaded: false });
  const settled = result.src === src;

  useEffect(() => {
    if (!enabled || !element.current) return;
    let request: ReturnType<typeof storefrontImageQueue.request> | undefined;
    let active = true;
    let complete = false;
    const stopObserving = observeCatalogImage(element.current, (priority) => {
      if (complete) return;
      if (priority === null) {
        request?.cancel();
        request = undefined;
      } else if (request) {
        request.setPriority(priority);
      } else {
        request = storefrontImageQueue.request(src, priority, (loaded) => {
          if (!active) return;
          complete = true;
          setResult({ src, loaded });
          stopObserving();
        });
      }
    });
    return () => { active = false; stopObserving(); request?.cancel(); };
  }, [src, enabled]);

  if (settled && !result.loaded) return fallback;
  return <img
    ref={element}
    className={className}
    src={settled ? src : undefined}
    alt={settled ? alt : ""}
    decoding="async"
    data-image-state={settled ? "ready" : "pending"}
    style={{ visibility: settled ? undefined : "hidden" }}
    onError={() => setResult({ src, loaded: false })}
  />;
}
