import {
  ArrowUpRight,
  ChatCenteredDots,
  LinkSimple,
  PaperPlaneTilt,
  Robot,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import { storefrontText } from "../lib/storefrontLocale";
import type {
  PublicSupportConversation,
  PublicSupportWidget,
  StorefrontLocale,
} from "../types";
import "./StorefrontSupportWidget.css";


interface StorefrontSupportWidgetProps {
  tenantSlug: string;
  storeName: string;
  locale: StorefrontLocale;
  config?: PublicSupportWidget;
}

function storageKey(slug: string) {
  return `atc.support.session.v1.${slug.toLocaleLowerCase()}`;
}

function storedToken(slug: string) {
  try {
    return window.localStorage.getItem(storageKey(slug)) || "";
  } catch {
    return "";
  }
}

function saveToken(slug: string, token: string) {
  try {
    if (token) window.localStorage.setItem(storageKey(slug), token);
    else window.localStorage.removeItem(storageKey(slug));
  } catch {
    // The chat still works for the current page when storage is unavailable.
  }
}

export function StorefrontSupportWidget({
  tenantSlug,
  storeName,
  locale,
  config,
}: StorefrontSupportWidgetProps) {
  const t = useCallback(
    (source: string, values?: Record<string, string | number>) =>
      storefrontText(locale, source, values),
    [locale],
  );
  const [open, setOpen] = useState(false);
  const [conversation, setConversation] = useState<PublicSupportConversation>();
  const [token, setToken] = useState(() => storedToken(tenantSlug));
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const messageListRef = useRef<HTMLDivElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const widget = config ?? {
    enabled: true,
    title: "AI 智能客服",
    welcome_message: "您好，请告诉我们您正在寻找什么商品，我们会尽快回复。",
    ai_enabled: false,
    custom_actions: [],
  };
  const actions = useMemo(
    () => (widget.custom_actions || []).filter((item) => item.visible),
    [widget.custom_actions],
  );

  useEffect(() => {
    const next = storedToken(tenantSlug);
    setToken(next);
    setConversation(undefined);
  }, [tenantSlug]);

  const refreshConversation = useCallback(async (quiet = false) => {
    if (!token) return;
    if (!quiet) setLoading(true);
    try {
      const next = await api.getSupportConversation(tenantSlug, token);
      setConversation(next);
      setError("");
    } catch (caught) {
      if (caught instanceof ApiError && [401, 404].includes(caught.status)) {
        saveToken(tenantSlug, "");
        setToken("");
        setConversation(undefined);
      } else if (!quiet) {
        setError(caught instanceof Error ? caught.message : t("消息加载失败，请稍后重试。"));
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [tenantSlug, t, token]);

  useEffect(() => {
    if (!open || !token) return;
    void refreshConversation();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void refreshConversation(true);
    }, 4_000);
    return () => window.clearInterval(interval);
  }, [open, refreshConversation, token]);

  useEffect(() => {
    if (!open) return;
    window.setTimeout(() => textAreaRef.current?.focus(), 180);
  }, [open]);

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [conversation?.messages.length, open]);

  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  const send = async () => {
    const message = draft.trim();
    if (!message || sending) return;
    setSending(true);
    setError("");
    try {
      const clientMessageId = crypto.randomUUID();
      const next = token
        ? await api.sendSupportMessage(tenantSlug, token, {
            message,
            client_message_id: clientMessageId,
          })
        : await api.createSupportConversation(tenantSlug, {
            message,
            client_message_id: clientMessageId,
            locale,
          });
      const nextToken = next.access_token || token;
      if (nextToken && nextToken !== token) {
        setToken(nextToken);
        saveToken(tenantSlug, nextToken);
      }
      setConversation(next);
      setDraft("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("消息发送失败，请稍后重试。"));
    } finally {
      setSending(false);
    }
  };

  const startNewConversation = () => {
    saveToken(tenantSlug, "");
    setToken("");
    setConversation(undefined);
    setError("");
    window.setTimeout(() => textAreaRef.current?.focus(), 0);
  };

  if (!widget.enabled) return null;

  return (
    <aside className={`storefront-support${open ? " is-open" : ""}`} aria-label={t("在线客服")}>
      <section
        id="storefront-support-panel"
        className="storefront-support-panel"
        role="dialog"
        aria-modal="false"
        aria-hidden={!open}
        aria-labelledby="storefront-support-title"
      >
        <header className="storefront-support-header">
          <span className="storefront-support-avatar"><Robot weight="duotone" /></span>
          <div>
            <strong id="storefront-support-title">{t("AI 智能客服")}</strong>
            <small>{t("AI 自动回复筹备中 · 当前由商家人工回复")}</small>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label={t("关闭客服窗口")}>
            <X weight="bold" />
          </button>
        </header>

        <div className="storefront-support-messages" ref={messageListRef} aria-live="polite">
          <div className="support-message is-merchant is-welcome">
            <span>{widget.welcome_message}</span>
            <small>{storeName}</small>
          </div>
          {loading && !conversation ? (
            <div className="support-message-loading"><i /><i /><i /></div>
          ) : null}
          {(conversation?.messages || []).map((message) => (
            <div
              className={`support-message ${message.sender_type === "VISITOR" ? "is-visitor" : "is-merchant"}`}
              key={message.id}
            >
              <span>{message.body}</span>
              <small>
                {message.sender_type === "VISITOR" ? t("我") : storeName}
                {" · "}
                {new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at))}
              </small>
            </div>
          ))}
          {conversation?.status === "CLOSED" ? (
            <div className="support-conversation-closed">
              <span>{t("本次会话已结束。")}</span>
              <button type="button" onClick={startNewConversation}>{t("发起新的咨询")}</button>
            </div>
          ) : null}
        </div>

        <footer className="storefront-support-composer">
          {error ? <p role="alert">{error}</p> : null}
          <div>
            <textarea
              ref={textAreaRef}
              rows={1}
              value={draft}
              maxLength={4_000}
              disabled={conversation?.status === "CLOSED"}
              placeholder={t("请输入您想咨询的商品或问题…")}
              aria-label={t("客服消息")}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <button
              type="button"
              disabled={!draft.trim() || sending || conversation?.status === "CLOSED"}
              onClick={() => void send()}
              aria-label={t("发送消息")}
            >
              <PaperPlaneTilt weight="fill" />
            </button>
          </div>
          <small>{t("消息会发送给商家客服，回复可能需要一些时间。")}</small>
        </footer>
      </section>

      <div className="storefront-support-actions">
        {actions
          .slice()
          .sort((left, right) => right.slot - left.slot)
          .map((action) => (
            <a
              className="storefront-support-orb is-custom"
              href={action.target_url || undefined}
              target="_blank"
              rel="noreferrer noopener"
              aria-label={action.label || t("商家快捷入口")}
              title={action.label || t("商家快捷入口")}
              key={action.slot}
            >
              {action.image_url ? <img src={action.image_url} alt="" /> : <LinkSimple weight="duotone" />}
              <span>{action.label}</span>
              <ArrowUpRight className="support-action-arrow" weight="bold" />
            </a>
          ))}
        <button
          type="button"
          className="storefront-support-orb is-chat"
          aria-expanded={open}
          aria-controls="storefront-support-panel"
          aria-label={t(open ? "关闭客服窗口" : "打开 AI 智能客服")}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? <X weight="bold" /> : <ChatCenteredDots weight="fill" />}
          <span>{t("在线客服")}</span>
        </button>
      </div>
    </aside>
  );
}
