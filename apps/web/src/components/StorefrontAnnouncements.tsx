import { Button, Dialog, Text } from "@radix-ui/themes";
import { ArrowRight, Megaphone, Package, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  announcementDismissedForVisit,
  dismissAnnouncementForVisit,
} from "../lib/storefrontAnnouncementVisit";
import { storefrontLocaleQuery, storefrontText } from "../lib/storefrontLocale";
import type {
  AnnouncementContentBlock,
  PublicAnnouncement,
  PublicAnnouncementRelatedSku,
  StorefrontLocale,
} from "../types";
import "./StorefrontAnnouncements.css";


function modalVisitKey(slug: string, announcement: PublicAnnouncement) {
  return `modal.${slug}.${announcement.id}.v${announcement.version}`;
}

function dismissModalForVisit(slug: string, announcement: PublicAnnouncement) {
  dismissAnnouncementForVisit(modalVisitKey(slug, announcement));
}

function tickerSignature(announcements: PublicAnnouncement[]) {
  return announcements
    .map((announcement) => `${announcement.id}.v${announcement.version}`)
    .sort()
    .join("-");
}

function tickerDismissedKey(slug: string, signature: string) {
  return `ticker.${slug}.${signature}`;
}

function wasTickerDismissed(slug: string, signature: string) {
  return Boolean(signature)
    && announcementDismissedForVisit(tickerDismissedKey(slug, signature));
}

function markTickerDismissed(slug: string, signature: string) {
  if (!signature) return;
  dismissAnnouncementForVisit(tickerDismissedKey(slug, signature));
}

function productDetailPath(
  tenantSlug: string,
  productId: string,
  locale: StorefrontLocale,
) {
  const query = storefrontLocaleQuery(locale);
  return `/${encodeURIComponent(tenantSlug)}/products/${encodeURIComponent(productId)}${query}`;
}

function RelatedSkus({
  skus,
  tenantSlug,
  locale,
  label,
}: {
  skus: PublicAnnouncementRelatedSku[];
  tenantSlug: string;
  locale: StorefrontLocale;
  label: string;
}) {
  if (!skus.length) return null;
  return (
    <section className="store-announcement-related-products" aria-label={label}>
      <div className="store-announcement-related-heading">
        <Package weight="duotone" />
        <span>{label}</span>
      </div>
      <div className="store-announcement-related-list">
        {skus.map((sku) => (
          <Link
            key={sku.id}
            to={productDetailPath(tenantSlug, sku.product_id, locale)}
            state={{ fromStorefrontCatalog: false }}
          >
            <span>
              <strong>{sku.product_name}</strong>
              <small>{sku.sku_code}{sku.name !== sku.product_name ? ` · ${sku.name}` : ""}</small>
            </span>
            <ArrowRight />
          </Link>
        ))}
      </div>
    </section>
  );
}

function RichContent({ blocks }: { blocks: AnnouncementContentBlock[] }) {
  return (
    <div className="store-announcement-content">
      {blocks.map((block, index) => {
        const key = `${block.type}-${index}`;
        if (block.type === "heading") return <h3 key={key}>{block.text}</h3>;
        if (block.type === "paragraph") return <p key={key}>{block.text}</p>;
        if (block.type === "bullet_list") {
          return (
            <ul key={key}>
              {(block.text || "").split("\n").map((line) => line.trim()).filter(Boolean).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          );
        }
        if (block.type === "image" && block.url) {
          return (
            <figure key={key}>
              <img src={block.url} alt={block.alt || ""} loading="lazy" />
              {block.caption ? <figcaption>{block.caption}</figcaption> : null}
            </figure>
          );
        }
        if (block.type === "video" && block.url) {
          return (
            <figure key={key}>
              <video src={block.url} controls preload="metadata" playsInline />
              {block.caption ? <figcaption>{block.caption}</figcaption> : null}
            </figure>
          );
        }
        if (block.type === "link" && block.url) {
          return (
            <p key={key}>
              <a href={block.url} target="_blank" rel="noopener noreferrer">
                {block.text || block.url}
              </a>
            </p>
          );
        }
        return null;
      })}
    </div>
  );
}

export function StorefrontAnnouncements({
  announcements,
  tenantSlug,
  locale,
}: {
  announcements: PublicAnnouncement[];
  tenantSlug: string;
  locale: StorefrontLocale;
}) {
  const t = (source: string) => storefrontText(locale, source);
  const tickers = useMemo(
    () => announcements.filter((announcement) => announcement.display_type === "TICKER" && announcement.ticker_text),
    [announcements],
  );
  const modals = useMemo(
    () => announcements.filter((announcement) => announcement.display_type === "MODAL"),
    [announcements],
  );
  const currentTickerSignature = useMemo(() => tickerSignature(tickers), [tickers]);
  const modalSignature = useMemo(() => tickerSignature(modals), [modals]);
  const tickerSpeed = tickers[0]?.ticker_speed_px_per_second || 60;
  const [activeModal, setActiveModal] = useState<PublicAnnouncement>();
  const [tickerHidden, setTickerHidden] = useState(() => (
    wasTickerDismissed(tenantSlug, currentTickerSignature)
  ));
  const [tickerDurationSeconds, setTickerDurationSeconds] = useState(34);
  const tickerTrackRef = useRef<HTMLDivElement>(null);
  const presentedModalKeys = useRef(new Set<string>());

  useEffect(() => {
    setTickerHidden(wasTickerDismissed(tenantSlug, currentTickerSignature));
  }, [currentTickerSignature, tenantSlug]);

  useEffect(() => {
    setActiveModal(undefined);
    const eligible = modals.find((announcement) => {
      const key = modalVisitKey(tenantSlug, announcement);
      return !announcementDismissedForVisit(key) && !presentedModalKeys.current.has(key);
    });
    if (!eligible) return;
    presentedModalKeys.current.add(modalVisitKey(tenantSlug, eligible));
    const timeout = window.setTimeout(() => {
      setActiveModal(eligible);
    }, 250);
    return () => window.clearTimeout(timeout);
  }, [modalSignature, tenantSlug]);

  useEffect(() => {
    const track = tickerTrackRef.current;
    if (!track || tickerHidden) return;
    const updateDuration = () => {
      const travelDistance = track.scrollWidth / 2;
      setTickerDurationSeconds(Math.max(8, travelDistance / tickerSpeed));
    };
    updateDuration();
    const resizeObserver = typeof ResizeObserver === "undefined"
      ? undefined
      : new ResizeObserver(updateDuration);
    resizeObserver?.observe(track);
    window.addEventListener("resize", updateDuration);
    return () => {
      resizeObserver?.disconnect();
      window.removeEventListener("resize", updateDuration);
    };
  }, [currentTickerSignature, tickerHidden, tickerSpeed]);

  const closeTicker = () => {
    markTickerDismissed(tenantSlug, currentTickerSignature);
    setTickerHidden(true);
  };

  const dismissActiveModalForVisit = () => {
    if (activeModal) dismissModalForVisit(tenantSlug, activeModal);
    setActiveModal(undefined);
  };

  return (
    <>
      {tickers.length && !tickerHidden ? (
        <aside className="store-announcement-ticker" aria-label={t("商家公告")}>
          <Megaphone size={17} weight="duotone" aria-hidden="true" />
          <div className="store-announcement-ticker-window">
            <div
              ref={tickerTrackRef}
              className="store-announcement-ticker-track"
              style={{ animationDuration: `${tickerDurationSeconds}s` }}
            >
              {[...tickers, ...tickers].map((announcement, index) => (
                <span key={`${announcement.id}-${index}`}>
                  {announcement.ticker_text}
                  {announcement.related_skus?.[0] ? (
                    <Link
                      className="store-announcement-ticker-product"
                      to={productDetailPath(
                        tenantSlug,
                        announcement.related_skus[0].product_id,
                        locale,
                      )}
                    >
                      {t("查看商品")}<ArrowRight />
                    </Link>
                  ) : null}
                  <i aria-hidden="true">◆</i>
                </span>
              ))}
            </div>
          </div>
          <button
            type="button"
            className="store-announcement-ticker-close"
            aria-label={t("关闭滚动字幕")}
            title={t("关闭滚动字幕")}
            onClick={closeTicker}
          >
            <X />
          </button>
        </aside>
      ) : null}

      <Dialog.Root
        open={Boolean(activeModal)}
        onOpenChange={(open) => !open && setActiveModal(undefined)}
      >
        <Dialog.Content className="store-announcement-dialog" aria-describedby={undefined}>
          <Dialog.Close>
            <button type="button" className="store-announcement-close" aria-label={t("关闭公告")}>
              <X />
            </button>
          </Dialog.Close>
          {activeModal ? (
            <>
              <div className="store-announcement-dialog-heading">
                <span><Megaphone weight="duotone" />{t("商家公告")}</span>
                <Dialog.Title className={activeModal.title ? undefined : "visually-hidden"}>
                  {activeModal.title || t("商家公告")}
                </Dialog.Title>
              </div>
              <RichContent blocks={activeModal.content_blocks} />
              <RelatedSkus
                skus={activeModal.related_skus || []}
                tenantSlug={tenantSlug}
                locale={locale}
                label={t("相关商品")}
              />
              <div className="store-announcement-dialog-actions">
                <Text size="1" color="gray">{t("完整刷新或开始新会话后，公告会重新出现")}</Text>
                <div>
                  <Button size="3" variant="soft" color="gray" onClick={dismissActiveModalForVisit}>
                    {t("以后不显示")}
                  </Button>
                  <Dialog.Close>
                    <Button size="3">{t("我知道了")}</Button>
                  </Dialog.Close>
                </div>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Root>
    </>
  );
}
