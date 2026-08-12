import { Badge, Button, DropdownMenu } from "@radix-ui/themes";
import {
  ArrowRight,
  Bell,
  CheckCircle,
  Headset,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getSupportHumanRequests } from "../api";
import { useLocale } from "../LocaleContext";
import type {
  SupportHumanRequest,
  SupportHumanRequestSummary,
} from "../types";

const EMPTY_SUMMARY: SupportHumanRequestSummary = {
  pendingCount: 0,
  items: [],
};

function requestKey(request: SupportHumanRequest) {
  return `${request.conversationId}:${request.requestedAt}`;
}

export function SupportNotificationBell({
  tenantId,
  enabled,
}: {
  tenantId: string;
  enabled: boolean;
}) {
  const { locale, t } = useLocale();
  const [summary, setSummary] = useState(EMPTY_SUMMARY);
  const [toastRequest, setToastRequest] = useState<SupportHumanRequest>();
  const [toastAdditionalCount, setToastAdditionalCount] = useState(0);
  const knownRequestsRef = useRef<Set<string> | null>(null);
  const activeTenantRef = useRef(tenantId);

  const refresh = useCallback(async (notify = true) => {
    if (!enabled || !tenantId) return;
    try {
      const next = await getSupportHumanRequests(10);
      if (activeTenantRef.current !== tenantId) return;
      const nextKeys = new Set(next.items.map(requestKey));
      const known = knownRequestsRef.current;
      if (notify && known !== null) {
        const arrivals = next.items.filter((item) => !known.has(requestKey(item)));
        if (arrivals.length) {
          setToastRequest(arrivals[0]);
          setToastAdditionalCount(Math.max(0, arrivals.length - 1));
        }
      }
      knownRequestsRef.current = nextKeys;
      setSummary(next);
    } catch {
      // The bell must never interrupt other console work. The next poll retries.
    }
  }, [enabled, tenantId]);

  useEffect(() => {
    activeTenantRef.current = tenantId;
    knownRequestsRef.current = null;
    setSummary(EMPTY_SUMMARY);
    setToastRequest(undefined);
    setToastAdditionalCount(0);
    if (!enabled || !tenantId) return;
    void refresh(false);
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refresh(true);
    }, 4_000);
    const refreshQuietly = () => void refresh(false);
    const refreshOnVisible = () => {
      if (document.visibilityState === "visible") void refresh(true);
    };
    window.addEventListener("focus", refreshOnVisible);
    document.addEventListener("visibilitychange", refreshOnVisible);
    window.addEventListener(
      "atc:support-human-requests-changed",
      refreshQuietly,
    );
    return () => {
      window.clearInterval(interval);
      window.removeEventListener("focus", refreshOnVisible);
      document.removeEventListener("visibilitychange", refreshOnVisible);
      window.removeEventListener(
        "atc:support-human-requests-changed",
        refreshQuietly,
      );
    };
  }, [enabled, refresh, tenantId]);

  useEffect(() => {
    if (!toastRequest) return;
    const timer = window.setTimeout(() => {
      setToastRequest(undefined);
      setToastAdditionalCount(0);
    }, 8_000);
    return () => window.clearTimeout(timer);
  }, [toastRequest]);

  if (!enabled) return null;
  const badge = summary.pendingCount > 99 ? "99+" : String(summary.pendingCount);

  return (
    <>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          <Button
            className="support-notification-trigger"
            variant="ghost"
            color="gray"
            aria-label={t("人工客服提醒，{count} 条待处理", {
              count: summary.pendingCount,
            })}
            title={t("人工客服提醒")}
          >
            <Bell size={19} weight={summary.pendingCount ? "fill" : "regular"} />
            {summary.pendingCount ? (
              <span className="support-notification-count">{badge}</span>
            ) : null}
          </Button>
        </DropdownMenu.Trigger>
        <DropdownMenu.Content
          align="end"
          sideOffset={10}
          className="support-notification-menu"
        >
          <DropdownMenu.Label>
            <span className="support-notification-menu-heading">
              <span>
                <Headset weight="duotone" />
                {t("人工客服提醒")}
              </span>
              <Badge color={summary.pendingCount ? "amber" : "gray"}>
                {summary.pendingCount}
              </Badge>
            </span>
          </DropdownMenu.Label>
          <DropdownMenu.Separator />
          {summary.items.length ? summary.items.map((item) => (
            <DropdownMenu.Item asChild key={requestKey(item)}>
              <Link
                className="support-notification-item"
                to={`/console/support?conversation=${encodeURIComponent(item.conversationId)}`}
              >
                <span><Headset weight="duotone" /></span>
                <span>
                  <strong>{item.visitorName || t("网站访客")}</strong>
                  <small>{item.messagePreview || t("客户请求人工客服介入")}</small>
                  <em>
                    {item.referenceNumber} · {new Intl.DateTimeFormat(locale, {
                      hour: "2-digit",
                      minute: "2-digit",
                    }).format(new Date(item.requestedAt))}
                  </em>
                </span>
                <ArrowRight aria-hidden="true" />
              </Link>
            </DropdownMenu.Item>
          )) : (
            <div className="support-notification-empty">
              <CheckCircle weight="duotone" />
              <strong>{t("暂无待处理的人工请求")}</strong>
              <small>{t("新的人工请求会显示在这里")}</small>
            </div>
          )}
          <DropdownMenu.Separator />
          <DropdownMenu.Item asChild>
            <Link className="support-notification-all" to="/console/support">
              {t("进入客服管理")}
              <ArrowRight />
            </Link>
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>

      {toastRequest ? (
        <aside className="support-request-toast" role="status" aria-live="assertive">
          <span className="support-request-toast-icon">
            <Headset weight="duotone" />
          </span>
          <Link
            to={`/console/support?conversation=${encodeURIComponent(toastRequest.conversationId)}`}
            onClick={() => setToastRequest(undefined)}
          >
            <small>{t("新的人工客服请求")}</small>
            <strong>{toastRequest.visitorName || t("网站访客")}</strong>
            <span>{toastRequest.messagePreview || t("客户请求人工客服介入")}</span>
            {toastAdditionalCount ? (
              <em>{t("另有 {count} 条新请求", { count: toastAdditionalCount })}</em>
            ) : null}
          </Link>
          <button
            type="button"
            aria-label={t("关闭提醒")}
            onClick={() => setToastRequest(undefined)}
          >
            <X weight="bold" />
          </button>
        </aside>
      ) : null}
    </>
  );
}
