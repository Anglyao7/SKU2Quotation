import { Container, Text } from "@radix-ui/themes";
import { Link } from "react-router-dom";
import { storefrontBasePath } from "../lib/storefrontAccount";
import type { Storefront, StorefrontFooterSection } from "../types";

type StorefrontTranslator = (
  source: string,
  values?: Record<string, string | number>,
) => string;

function isExternalUrl(url: string) {
  return /^https?:\/\//i.test(url);
}

function isPlatformDestination(url: string) {
  const normalized = url.trim();
  if (/^\/(?:$|[?#]|main(?:[/?#]|$)|login(?:[/?#]|$)|privacy(?:[/?#]|$))/i.test(normalized)) {
    return true;
  }
  if (!isExternalUrl(normalized)) return false;
  try {
    const target = new URL(normalized);
    const hostname = target.hostname.toLocaleLowerCase().replace(/^www\./, "");
    return hostname === "aitradecloud.top";
  } catch {
    return false;
  }
}

function FooterLink({ url, children }: { url: string; children: string }) {
  if (isPlatformDestination(url)) {
    return <span>{children}</span>;
  }
  if (url.startsWith("/")) {
    return <Link to={url}>{children}</Link>;
  }
  return (
    <a
      href={url}
      target={isExternalUrl(url) ? "_blank" : undefined}
      rel={isExternalUrl(url) ? "noreferrer noopener" : undefined}
    >
      {children}
    </a>
  );
}

function fallbackSections(store: Storefront, t: StorefrontTranslator): StorefrontFooterSection[] {
  return [{
    title: t("关于 {store}", { store: store.name }),
    links: [{ label: t("隐私政策"), url: "/privacy" }],
  }];
}

function scopedFooterUrl(url: string, store: Storefront, accountKey?: string) {
  if (!accountKey || !url.startsWith("/")) return url;
  const encodedRoot = `/${encodeURIComponent(store.slug)}`;
  const rawRoot = `/${store.slug}`;
  const root = url === encodedRoot || url.startsWith(`${encodedRoot}/`)
    ? encodedRoot
    : url === rawRoot || url.startsWith(`${rawRoot}/`)
      ? rawRoot
      : undefined;
  if (!root) return url;
  return `${storefrontBasePath(store.slug)}${url.slice(root.length)}`;
}

export function StorefrontFooter({
  store,
  t,
  accountKey,
}: {
  store: Storefront;
  t: StorefrontTranslator;
  accountKey?: string;
}) {
  const sections = store.footer_sections ?? fallbackSections(store, t);
  const merchantInitial = Array.from(store.name.trim())[0]?.toLocaleUpperCase() || "S";

  return (
    <footer className="store-footer">
      <Container size="4">
        <div className="store-footer-main">
          <div className="store-footer-brand">
            <div className="store-footer-identity">
              {store.logo_url ? (
                <img src={store.logo_url} alt="" />
              ) : (
                <span aria-hidden="true">{merchantInitial}</span>
              )}
              <div>
                <strong>{store.name}</strong>
                {store.description ? <p>{store.description}</p> : null}
              </div>
            </div>
          </div>

          {sections.length ? (
            <nav className="store-footer-navigation" aria-label={t("页脚链接")}>
              {sections.map((section, sectionIndex) => (
                <section className="store-footer-section" key={`${section.title}-${sectionIndex}`}>
                  <h2>
                    {section.title_url ? (
                      <FooterLink url={scopedFooterUrl(section.title_url, store, accountKey)}>{section.title}</FooterLink>
                    ) : section.title}
                  </h2>
                  {section.links.length ? (
                    <ul>
                      {section.links.map((link, linkIndex) => (
                        <li key={`${link.label}-${linkIndex}`}>
                          <FooterLink url={scopedFooterUrl(link.url, store, accountKey)}>{link.label}</FooterLink>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              ))}
            </nav>
          ) : null}
        </div>

        <div className="store-footer-bottom">
          <Text size="1" color="gray">
            {t("商品与报价由 {store} 提供，报价草稿须经商家确认。", { store: store.name })}
          </Text>
          <span className="store-footer-powered">Powered by AI Trade Cloud</span>
        </div>
      </Container>
    </footer>
  );
}
