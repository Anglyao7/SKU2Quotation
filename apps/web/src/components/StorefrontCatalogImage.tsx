import { useEffect, useState, type ReactNode } from "react";

export function StorefrontCatalogImage({ src, alt, className, fallback, enabled = true }: {
  src: string;
  alt: string;
  className?: string;
  fallback: ReactNode;
  enabled?: boolean;
}) {
  const [state, setState] = useState<{ src: string; status: "loading" | "loaded" | "error" }>({
    src,
    status: "loading",
  });

  useEffect(() => {
    setState({ src, status: "loading" });
  }, [src]);

  if (state.src === src && state.status === "error") return fallback;
  return <img
    className={className}
    src={src}
    alt={alt}
    loading="lazy"
    fetchPriority={enabled ? "auto" : "low"}
    decoding="async"
    data-image-state={state.src === src ? state.status : "loading"}
    onLoad={() => setState({ src, status: "loaded" })}
    onError={() => setState({ src, status: "error" })}
  />;
}
