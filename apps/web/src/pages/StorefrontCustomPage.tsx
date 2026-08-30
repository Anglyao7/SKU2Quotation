import { Container } from "@radix-ui/themes";
import { Storefront as StoreIcon } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLoaderData } from "react-router-dom";
import { CartDrawer, type CartLine } from "../components/CartDrawer";
import { StorefrontExchangeRates } from "../components/StorefrontExchangeRates";
import { StorefrontFooter } from "../components/StorefrontFooter";
import { StorefrontLanguageSwitch } from "../components/StorefrontLanguageSwitch";
import { StorefrontSupportWidget } from "../components/StorefrontSupportWidget";
import { StorefrontTopNavigation } from "../components/StorefrontTopNavigation";
import { StorefrontVisitorEntry } from "../components/StorefrontVisitorEntry";
import { ThemeToggle } from "../components/ThemeToggle";
import { prepareStorefrontCustomPageHtml } from "../lib/storefrontCustomPage";
import { readStoreCart, writeStoreCart } from "../lib/storeCart";
import {
  normalizeStorefrontLocale,
  storefrontDirection,
  storefrontLocaleQuery,
  storefrontText,
} from "../lib/storefrontLocale";
import type {
  Storefront,
  StorefrontCustomPageDocument,
  StorefrontLocale,
} from "../types";


interface StorefrontCustomPageLoaderData {
  store: Storefront;
  page: StorefrontCustomPageDocument;
}

function ResponsiveHtmlFrame({
  html,
  title,
}: {
  html: string;
  title: string;
}) {
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [height, setHeight] = useState(640);
  const source = useMemo(
    () => prepareStorefrontCustomPageHtml(html, title),
    [html, title],
  );

  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    let observer: ResizeObserver | undefined;
    let animationFrame = 0;
    const measure = () => {
      window.cancelAnimationFrame(animationFrame);
      animationFrame = window.requestAnimationFrame(() => {
        try {
          const document = frame.contentDocument;
          if (!document) return;
          const next = Math.max(
            320,
            document.documentElement.scrollHeight,
            document.body?.scrollHeight || 0,
          );
          setHeight(next);
        } catch {
          setHeight(640);
        }
      });
    };
    const connect = () => {
      measure();
      try {
        const document = frame.contentDocument;
        if (!document || typeof ResizeObserver === "undefined") return;
        observer = new ResizeObserver(measure);
        observer.observe(document.documentElement);
        if (document.body) observer.observe(document.body);
        document.querySelectorAll("img,video").forEach((media) => {
          media.addEventListener("load", measure, { once: true });
        });
      } catch {
        // The fixed fallback height remains usable when a browser isolates srcDoc.
      }
    };
    frame.addEventListener("load", connect);
    window.addEventListener("resize", measure);
    if (frame.contentDocument?.readyState === "complete") connect();
    return () => {
      frame.removeEventListener("load", connect);
      window.removeEventListener("resize", measure);
      observer?.disconnect();
      window.cancelAnimationFrame(animationFrame);
    };
  }, [source]);

  return (
    <iframe
      ref={frameRef}
      className="storefront-custom-page-frame"
      title={title}
      srcDoc={source}
      sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer"
      style={{ height }}
    />
  );
}

export function StorefrontCustomPage() {
  const { store, page } = useLoaderData() as StorefrontCustomPageLoaderData;
  const locale: StorefrontLocale = normalizeStorefrontLocale(store.locale);
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const storefrontHome = `/${encodeURIComponent(store.slug)}${storefrontLocaleQuery(locale)}`;
  const [cart, setCart] = useState<Record<string, CartLine>>(
    () => readStoreCart(store.slug),
  );
  const cartLines = useMemo(() => Object.values(cart), [cart]);

  useEffect(() => {
    document.title = `${page.title} · ${store.name}`;
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
    return () => { document.title = store.name; };
  }, [page.title, store.name]);

  useEffect(() => {
    writeStoreCart(store.slug, cart);
  }, [cart, store.slug]);

  const updateQuantity = (skuId: string, quantity: number) => setCart((current) => {
    const next = { ...current };
    if (quantity < 1) delete next[skuId];
    else if (next[skuId]) next[skuId] = { ...next[skuId], quantity };
    return next;
  });

  return (
    <div className={`store-shell storefront-custom-page-shell${cartLines.length ? " has-cart" : ""}`} dir={storefrontDirection(locale)}>
      <header className="store-header">
        <Container size="4" className="store-header-container">
          <div className="header-inner">
            <div className="store-header-branding">
              <Link to={storefrontHome} className="store-identity" aria-label={t("{store} 商品目录首页", { store: store.name })}>
                {store.logo_url ? <img src={store.logo_url} alt="" /> : <span className="store-identity-mark"><StoreIcon size={21} weight="duotone" /></span>}
                <span><strong>{store.name}</strong><small>{page.title}</small></span>
              </Link>
            </div>
            <div className="header-actions">
              <StorefrontLanguageSwitch locale={locale} availableLocales={store.available_locales} />
              <ThemeToggle labels={{ toDark: t("切换深色模式"), toLight: t("切换浅色模式") }} />
              <StorefrontVisitorEntry tenantSlug={store.slug} locale={locale} />
              <CartDrawer
                slug={store.slug}
                storeName={store.name}
                contactEmail={store.contact_email}
                contactImages={store.support_widget?.custom_actions?.filter((action) => Boolean(action.visible && action.image_url))}
                lines={cartLines}
                onQuantity={updateQuantity}
                onClear={() => setCart({})}
                locale={locale}
              />
            </div>
          </div>
        </Container>
      </header>
      <StorefrontTopNavigation store={store} locale={locale} activePageSlug={page.slug} />
      {page.exchange_rates_enabled ? (
        <StorefrontExchangeRates tenantSlug={store.slug} locale={locale} />
      ) : null}
      <main className="storefront-custom-page-main">
        <ResponsiveHtmlFrame html={page.html} title={page.title} />
      </main>
      <StorefrontSupportWidget tenantSlug={store.slug} storeName={store.name} locale={locale} config={store.support_widget} />
      <StorefrontFooter store={store} t={t} />
    </div>
  );
}
