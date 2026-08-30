import { Container, Text } from "@radix-ui/themes";
import { Link } from "react-router-dom";
import type { Storefront, StorefrontFooterSection } from "../types";

type StorefrontTranslator = (
  source: string,
  values?: Record<string, string | number>,
) => string;

function isExternalUrl(url: string) {
  return /^https?:\/\//i.test(url);
}

function FooterLink({ url, children }: { url: string; children: string }) {
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

function fallbackSections(store: Storefront): StorefrontFooterSection[] {
  return [{
    title: `About ${store.name}`,
    links: [{ label: "Privacy Policy", url: "/privacy" }],
  }];
}

export function StorefrontFooter({
  store,
  t,
}: {
  store: Storefront;
  t: StorefrontTranslator;
}) {
  const sections = store.footer_sections ?? fallbackSections(store);
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
            <nav className="store-footer-navigation" aria-label="Footer links">
              {sections.map((section, sectionIndex) => (
                <section className="store-footer-section" key={`${section.title}-${sectionIndex}`}>
                  <h2>
                    {section.title_url ? (
                      <FooterLink url={section.title_url}>{section.title}</FooterLink>
                    ) : section.title}
                  </h2>
                  {section.links.length ? (
                    <ul>
                      {section.links.map((link, linkIndex) => (
                        <li key={`${link.label}-${linkIndex}`}>
                          <FooterLink url={link.url}>{link.label}</FooterLink>
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
          <Link className="store-footer-powered" to="/">Powered by AI Trade Cloud</Link>
        </div>
      </Container>
    </footer>
  );
}
