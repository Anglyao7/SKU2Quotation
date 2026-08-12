import { Button, Dialog, Heading, Text } from "@radix-ui/themes";
import { BellRinging, UserCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";
import {
  markQuoteNotificationShown,
  markQuoteNotificationsSeen,
  quoteNotificationKey,
  readSeenQuoteNotifications,
  readShownQuoteNotifications,
  STOREFRONT_VISITOR_EVENT,
} from "../lib/storefrontVisitor";
import { storefrontLocaleQuery, storefrontText } from "../lib/storefrontLocale";
import type { StorefrontLocale, StorefrontVisitorQuote } from "../types";

function isMerchantUpdate(quote: StorefrontVisitorQuote) {
  return quote.status !== "PENDING_CONFIRMATION";
}

export function StorefrontVisitorEntry({
  tenantSlug,
  locale,
}: {
  tenantSlug: string;
  locale: StorefrontLocale;
}) {
  const [quotes, setQuotes] = useState<StorefrontVisitorQuote[]>([]);
  const [notice, setNotice] = useState<StorefrontVisitorQuote>();
  const t = (source: string, values?: Record<string, string | number>) => (
    storefrontText(locale, source, values)
  );
  const notificationQuotes = useMemo(() => quotes.filter(isMerchantUpdate), [quotes]);
  const unreadKeys = useMemo(() => {
    const seen = readSeenQuoteNotifications(tenantSlug);
    return notificationQuotes
      .map(quoteNotificationKey)
      .filter((value) => !seen.has(value));
  }, [notificationQuotes, tenantSlug]);

  const load = useCallback(async () => {
    try {
      const next = await api.listStorefrontVisitorQuotes(tenantSlug);
      setQuotes(next);
      const shown = readShownQuoteNotifications(tenantSlug);
      const fresh = next.find((quote) => (
        isMerchantUpdate(quote) && !shown.has(quoteNotificationKey(quote))
      ));
      if (fresh) {
        markQuoteNotificationShown(tenantSlug, quoteNotificationKey(fresh));
        setNotice(fresh);
      }
    } catch {
      // A temporary notification failure must not interrupt catalog browsing.
    }
  }, [tenantSlug]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    const onVisitorChange = (event: Event) => {
      const detail = (event as CustomEvent<{ slug?: string }>).detail;
      if (!detail?.slug || detail.slug.toLocaleLowerCase() === tenantSlug.toLocaleLowerCase()) {
        void load();
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener(STOREFRONT_VISITOR_EVENT, onVisitorChange);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener(STOREFRONT_VISITOR_EVENT, onVisitorChange);
    };
  }, [load, tenantSlug]);

  const centerHref = `/${encodeURIComponent(tenantSlug)}/me${storefrontLocaleQuery(locale)}`;
  const noticeTab = notice?.status === "COMPLETED"
    ? "completed"
    : notice?.status === "CANCELLED" || notice?.status === "EXPIRED"
      ? "closed"
      : "confirmed";
  const noticeHref = `${centerHref}${centerHref.includes("?") ? "&" : "?"}tab=${noticeTab}`;
  const markRead = () => {
    markQuoteNotificationsSeen(
      tenantSlug,
      notificationQuotes.map(quoteNotificationKey),
    );
  };

  return (
    <>
      <Button asChild size="3" variant="soft" color="gray" className="visitor-center-trigger">
        <Link to={centerHref} onClick={markRead} aria-label={t("我的个人中心")}>
          <UserCircle size={19} weight="duotone" />
          <span className="visitor-center-label">{t("我的")}</span>
          {unreadKeys.length ? (
            <span className="visitor-center-unread" aria-label={t("{count} 条新消息", { count: unreadKeys.length })}>
              {Math.min(unreadKeys.length, 99)}
            </span>
          ) : null}
        </Link>
      </Button>

      <Dialog.Root open={Boolean(notice)} onOpenChange={(open) => { if (!open) setNotice(undefined); }}>
        <Dialog.Content className="visitor-notification-dialog" maxWidth="430px">
          <span className="visitor-notification-icon"><BellRinging weight="duotone" /></span>
          <Dialog.Title>{notice?.status === "COMPLETED"
            ? t("订单状态已更新")
            : notice?.status === "CANCELLED"
              ? t("询价单已取消")
              : notice?.status === "EXPIRED"
                ? t("询价单已过期")
                : t("商家已确认你的询价单")}</Dialog.Title>
          <Dialog.Description>
            {notice
              ? t("询价单 {number} 已由商家更新，可在个人中心查看。", { number: notice.quote_number })
              : ""}
          </Dialog.Description>
          {notice ? (
            <div className="visitor-notification-summary">
              <Text size="1" color="gray">{notice.quote_number}</Text>
              <Heading size="4">{notice.currency} {Number(notice.total_amount).toFixed(2)}</Heading>
            </div>
          ) : null}
          <div className="visitor-notification-actions">
            <Dialog.Close><Button variant="soft" color="gray">{t("稍后查看")}</Button></Dialog.Close>
            <Button asChild onClick={markRead}>
              <Link to={noticeHref}>{t("前往个人中心")}</Link>
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>
    </>
  );
}
