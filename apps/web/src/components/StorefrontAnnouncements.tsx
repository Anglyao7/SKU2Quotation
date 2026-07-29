import { Button, Dialog, Text } from "@radix-ui/themes";
import { Megaphone, X } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { storefrontText } from "../lib/storefrontLocale";
import type {
  AnnouncementContentBlock,
  PublicAnnouncement,
  StorefrontLocale,
} from "../types";
import "./StorefrontAnnouncements.css";


const SEEN_PREFIX = "zhimaoyun.storefront.announcement.seen";

function seenKey(slug: string, announcement: PublicAnnouncement) {
  return `${SEEN_PREFIX}.${slug}.${announcement.id}.v${announcement.version}`;
}

function lastSeen(slug: string, announcement: PublicAnnouncement) {
  try {
    const value = Number(window.localStorage.getItem(seenKey(slug, announcement)));
    return Number.isFinite(value) ? value : 0;
  } catch {
    return 0;
  }
}

function markSeen(slug: string, announcement: PublicAnnouncement) {
  try {
    window.localStorage.setItem(seenKey(slug, announcement), String(Date.now()));
  } catch {
    // Storage may be unavailable in strict privacy modes. The announcement
    // still works for this page view; the browser simply cannot persist it.
  }
}

function shouldShowModal(slug: string, announcement: PublicAnnouncement) {
  const elapsed = Date.now() - lastSeen(slug, announcement);
  return elapsed >= announcement.repeat_interval_hours * 60 * 60 * 1000;
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
  const [activeModal, setActiveModal] = useState<PublicAnnouncement>();

  useEffect(() => {
    setActiveModal(undefined);
    const eligible = modals.find((announcement) => shouldShowModal(tenantSlug, announcement));
    if (!eligible) return;
    const timeout = window.setTimeout(() => {
      markSeen(tenantSlug, eligible);
      setActiveModal(eligible);
    }, 700);
    return () => window.clearTimeout(timeout);
  }, [modals, tenantSlug]);

  return (
    <>
      {tickers.length ? (
        <aside className="store-announcement-ticker" aria-label={t("商家公告")}>
          <Megaphone size={17} weight="duotone" aria-hidden="true" />
          <div className="store-announcement-ticker-window">
            <div className="store-announcement-ticker-track">
              {[...tickers, ...tickers].map((announcement, index) => (
                <span key={`${announcement.id}-${index}`}>
                  {announcement.ticker_text}
                  <i aria-hidden="true">◆</i>
                </span>
              ))}
            </div>
          </div>
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
                <Dialog.Title>{activeModal.title}</Dialog.Title>
              </div>
              <RichContent blocks={activeModal.content_blocks} />
              <div className="store-announcement-dialog-actions">
                <Dialog.Close>
                  <Button size="3">{t("我知道了")}</Button>
                </Dialog.Close>
                <Text size="1" color="gray">{t("关闭后不会在短时间内重复弹出")}</Text>
              </div>
            </>
          ) : null}
        </Dialog.Content>
      </Dialog.Root>
    </>
  );
}
