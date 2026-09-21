import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

type StorefrontRevealProps = {
  children: ReactNode;
  className?: string;
  index?: number;
};

/**
 * Reveals storefront content when it reaches the viewport without listening
 * to every scroll frame. The class is intentionally one-shot so returning to
 * a catalog does not make already-read products animate again.
 */
export function StorefrontReveal({
  children,
  className = "",
  index = 0,
}: StorefrontRevealProps) {
  const revealRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = revealRef.current;
    if (!node) return;

    const reducedMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion || typeof IntersectionObserver === "undefined") {
      node.classList.add("is-visible");
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        node.classList.add("is-visible");
        observer.unobserve(node);
      },
      { threshold: 0.12, rootMargin: "0px 0px -5% 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const style = {
    "--storefront-reveal-delay": `${Math.min(Math.max(index, 0) * 48, 288)}ms`,
  } as CSSProperties;

  return (
    <div
      ref={revealRef}
      className={`storefront-reveal-item${className ? ` ${className}` : ""}`}
      style={style}
    >
      {children}
    </div>
  );
}
