import { Link, useLocation } from "react-router-dom";
import { storefrontLocaleQuery } from "../lib/storefrontLocale";
import { storefrontBasePath } from "../lib/storefrontAccount";
import type { Storefront, StorefrontLocale } from "../types";


export function StorefrontTopNavigation({
  store,
  locale,
  accountKey,
  activePageSlug,
}: {
  store: Storefront;
  locale: StorefrontLocale;
  accountKey?: string;
  activePageSlug?: string;
}) {
  const location = useLocation();
  const pages = store.custom_pages || [];
  if (!pages.length) return null;
  const localeQuery = storefrontLocaleQuery(locale);
  const basePath = storefrontBasePath(store.slug, accountKey);
  const home = `${basePath}${localeQuery}`;
  const onCatalog = !activePageSlug && !location.pathname.includes("/pages/");

  return (
    <nav className="storefront-top-navigation" aria-label="Storefront navigation">
      <div className="storefront-top-navigation-track">
        <Link to={home} className={onCatalog ? "is-active" : ""} aria-current={onCatalog ? "page" : undefined}>
          {store.name}
        </Link>
        {pages.map((page) => {
          const active = activePageSlug === page.slug;
          return (
            <Link
              key={page.slug}
              to={`${basePath}/pages/${encodeURIComponent(page.slug)}${localeQuery}`}
              className={active ? "is-active" : ""}
              aria-current={active ? "page" : undefined}
            >
              {page.title}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
