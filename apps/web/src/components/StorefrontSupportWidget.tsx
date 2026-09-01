import {
  ArrowRight,
  ChatCenteredDots,
  CheckCircle,
  Headset,
  ImageSquare,
  PaperPlaneTilt,
  Robot,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError } from "../lib/api";
import { money } from "../lib/format";
import { storefrontBasePath, storefrontStorageScope } from "../lib/storefrontAccount";
import { storefrontLocaleQuery, storefrontText } from "../lib/storefrontLocale";
import type {
  PublicSupportConversation,
  PublicSupportMessage,
  PublicSupportStreamEvent,
  PublicSupportWidget,
  StoreProduct,
  StorefrontLocale,
} from "../types";
import "./StorefrontSupportWidget.css";


interface StorefrontSupportWidgetProps {
  tenantSlug: string;
  accountId?: string;
  accountKey?: string;
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

function supportProductPrice(product: StoreProduct) {
  const priceFrom = Number(product.price_from);
  const priceTo = Number(product.price_to);
  if (
    Number.isFinite(priceFrom)
    && Number.isFinite(priceTo)
    && Math.abs(priceFrom - priceTo) > 0.0001
  ) {
    return (
      `${money(product.price_from, product.currency)} – `
      + money(product.price_to, product.currency)
    );
  }
  return money(product.price_from, product.currency);
}

function SupportProductCard({
  product,
  citationNumber,
  detailsHref,
  locale,
  onOpen,
}: {
  product: StoreProduct;
  citationNumber: number;
  detailsHref: string;
  locale: StorefrontLocale;
  onOpen: () => void;
}) {
  const [imageFailed, setImageFailed] = useState(!product.image_url);
  const t = (source: string) => storefrontText(locale, source);

  useEffect(() => {
    setImageFailed(!product.image_url);
  }, [product.image_url]);

  return (
    <Link
      className="support-product-card"
      to={detailsHref}
      state={{ fromStorefrontCatalog: true }}
      onClick={onOpen}
      aria-label={`${t("查看商品")}：${product.name}`}
    >
      <span className="support-product-image">
        {product.image_url && !imageFailed ? (
          <img
            src={product.image_url}
            alt=""
            loading="lazy"
            decoding="async"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <ImageSquare weight="duotone" aria-hidden="true" />
        )}
      </span>
      <span className="support-product-copy">
        <small>
          [{citationNumber}]
          {product.product_code ? ` · ${product.product_code}` : ""}
        </small>
        <strong dir="auto">{product.name}</strong>
        <span>{supportProductPrice(product)}</span>
        <em>
          {t("查看商品")}
          <ArrowRight weight="bold" aria-hidden="true" />
        </em>
      </span>
    </Link>
  );
}

export function StorefrontSupportWidget({
  tenantSlug,
  accountId,
  accountKey,
  storeName,
  locale,
  config,
}: StorefrontSupportWidgetProps) {
  const storageScope = storefrontStorageScope(tenantSlug, accountId);
  const storefrontRoot = storefrontBasePath(tenantSlug, accountKey);
  const t = useCallback(
    (source: string, values?: Record<string, string | number>) =>
      storefrontText(locale, source, values),
    [locale],
  );
  const [open, setOpen] = useState(false);
  const [activeActionSlot, setActiveActionSlot] = useState<2 | 3 | null>(null);
  const [hoveredActionSlot, setHoveredActionSlot] = useState<2 | 3 | null>(null);
  const [conversation, setConversation] = useState<PublicSupportConversation>();
  const [streamingMessage, setStreamingMessage] = useState<PublicSupportMessage>();
  const [supportProducts, setSupportProducts] = useState<
    Record<string, StoreProduct | null>
  >({});
  const [token, setToken] = useState(() => storedToken(storageScope));
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [humanRequestBusy, setHumanRequestBusy] = useState(false);
  const [error, setError] = useState("");
  const messageListRef = useRef<HTMLDivElement>(null);
  const textAreaRef = useRef<HTMLTextAreaElement>(null);
  const widgetRef = useRef<HTMLElement>(null);
  const requestedProductIdsRef = useRef(new Set<string>());
  const productScopeRef = useRef("");
  const streamingMessageIdRef = useRef<string | undefined>(undefined);
  const streamingQueueRef = useRef<string[]>([]);
  const streamingFlushTimerRef = useRef<number | undefined>(undefined);
  const streamingEndRef = useRef<
    Extract<PublicSupportStreamEvent, { type: "message_end" }> | undefined
  >(undefined);
  const knownMessageIdsRef = useRef(new Set<string>());
  const awaitingAIResponseRef = useRef(false);
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
  const supportProductCount = Object.keys(supportProducts).length;
  const processingLabel = useMemo(() => {
    if (conversation?.ai_processing_stage === "USING_TOOLS") {
      return t("正在使用工具…");
    }
    if (conversation?.ai_processing_stage === "RAG_SEARCH") {
      return t("正在进行 RAG 搜索…");
    }
    return t("正在组织可信回复…");
  }, [conversation?.ai_processing_stage, t]);

  const resetStreamingPlayback = useCallback(() => {
    if (streamingFlushTimerRef.current !== undefined) {
      window.clearTimeout(streamingFlushTimerRef.current);
      streamingFlushTimerRef.current = undefined;
    }
    streamingMessageIdRef.current = undefined;
    streamingQueueRef.current = [];
    streamingEndRef.current = undefined;
  }, []);

  const settleStreamingEnd = useCallback(() => {
    if (streamingQueueRef.current.length > 0) return;
    const pending = streamingEndRef.current;
    if (!pending) return;
    streamingEndRef.current = undefined;
    streamingMessageIdRef.current = undefined;
    pending.conversation.messages.forEach((message) => {
      knownMessageIdsRef.current.add(message.id);
    });
    awaitingAIResponseRef.current = false;
    setConversation(pending.conversation);
    setStreamingMessage(undefined);
  }, []);

  const flushStreamingCharacter = useCallback(() => {
    streamingFlushTimerRef.current = undefined;
    const character = streamingQueueRef.current.shift();
    if (character !== undefined) {
      setStreamingMessage((current) => (
        current
          ? { ...current, body: `${current.body}${character}` }
          : current
      ));
    }
    if (streamingQueueRef.current.length > 0) {
      streamingFlushTimerRef.current = window.setTimeout(
        flushStreamingCharacter,
        18,
      );
    } else {
      settleStreamingEnd();
    }
  }, [settleStreamingEnd]);

  const enqueueStreamingDelta = useCallback((delta: string) => {
    streamingQueueRef.current.push(...Array.from(delta));
    if (streamingFlushTimerRef.current === undefined) {
      streamingFlushTimerRef.current = window.setTimeout(
        flushStreamingCharacter,
        18,
      );
    }
  }, [flushStreamingCharacter]);

  const applyConversationSnapshot = useCallback((next: PublicSupportConversation) => {
    if (next.ai_processing) {
      awaitingAIResponseRef.current = true;
      next.messages.forEach((message) => knownMessageIdsRef.current.add(message.id));
      setConversation(next);
      return;
    }
    const completedAI = next.messages
      .slice()
      .reverse()
      .find((message) => (
        message.sender_type === "AI"
        && !knownMessageIdsRef.current.has(message.id)
      ));
    if (
      awaitingAIResponseRef.current
      && completedAI
      && !streamingMessageIdRef.current
    ) {
      const stagedConversation = {
        ...next,
        messages: next.messages.filter((message) => message.id !== completedAI.id),
      };
      resetStreamingPlayback();
      streamingMessageIdRef.current = completedAI.id;
      streamingEndRef.current = {
        type: "message_end",
        message: completedAI,
        conversation: next,
      };
      setConversation(stagedConversation);
      setStreamingMessage({ ...completedAI, body: "", citations: [] });
      enqueueStreamingDelta(completedAI.body);
      return;
    }
    next.messages.forEach((message) => knownMessageIdsRef.current.add(message.id));
    awaitingAIResponseRef.current = false;
    setConversation(next);
  }, [enqueueStreamingDelta, resetStreamingPlayback]);

  useEffect(() => {
    const next = storedToken(storageScope);
    setToken(next);
    setConversation(undefined);
    setStreamingMessage(undefined);
    resetStreamingPlayback();
    knownMessageIdsRef.current.clear();
    awaitingAIResponseRef.current = false;
    setActiveActionSlot(null);
    setHoveredActionSlot(null);
  }, [resetStreamingPlayback, storageScope]);

  useEffect(() => {
    productScopeRef.current = `${storageScope}:${locale}`;
    requestedProductIdsRef.current.clear();
    setSupportProducts({});
  }, [locale, storageScope]);

  useEffect(() => {
    if (!open) return;
    const scope = `${storageScope}:${locale}`;
    const productIds = Array.from(new Set(
      (conversation?.messages || []).flatMap((message) => (
        message.sender_type === "AI"
          ? (message.citations || [])
            .filter((citation) => citation.source_type === "SKU")
            .map((citation) => citation.source_entity_id)
          : []
      )),
    ));
    for (const productId of productIds) {
      if (requestedProductIdsRef.current.has(productId)) continue;
      requestedProductIdsRef.current.add(productId);
      void api.getStoreProduct(tenantSlug, productId, locale, undefined, accountId)
        .then((product) => {
          if (productScopeRef.current !== scope) return;
          setSupportProducts((current) => ({ ...current, [productId]: product }));
        })
        .catch(() => {
          if (productScopeRef.current !== scope) return;
          setSupportProducts((current) => ({ ...current, [productId]: null }));
        });
    }
  }, [accountId, conversation?.messages, locale, open, storageScope, tenantSlug]);

  const refreshConversation = useCallback(async (quiet = false) => {
    if (!token) return;
    if (!quiet) setLoading(true);
    try {
      const next = await api.getSupportConversation(tenantSlug, token, accountId);
      applyConversationSnapshot(next);
      setError("");
    } catch (caught) {
      if (caught instanceof ApiError && [401, 404].includes(caught.status)) {
        saveToken(storageScope, "");
        setToken("");
        setConversation(undefined);
      } else if (!quiet) {
        setError(caught instanceof Error ? caught.message : t("消息加载失败，请稍后重试。"));
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [accountId, applyConversationSnapshot, storageScope, tenantSlug, t, token]);

  useEffect(() => {
    if (!open || !token) return;
    let stopped = false;
    let reconnectTimer: number | undefined;
    const controller = new AbortController();

    const handleStreamEvent = (event: PublicSupportStreamEvent) => {
      if (event.type === "conversation") {
        applyConversationSnapshot(event.conversation);
      } else if (event.type === "message_start") {
        resetStreamingPlayback();
        awaitingAIResponseRef.current = true;
        streamingMessageIdRef.current = event.message.id;
        setStreamingMessage(event.message);
      } else if (event.type === "message_delta") {
        if (streamingMessageIdRef.current === event.message_id) {
          enqueueStreamingDelta(event.delta);
        }
      } else if (event.type === "message_reset") {
        if (streamingMessageIdRef.current === event.message_id) {
          resetStreamingPlayback();
          streamingMessageIdRef.current = event.message_id;
          setStreamingMessage((current) => (
            current ? { ...current, body: event.body } : current
          ));
        }
      } else if (event.type === "message_end") {
        const endingStreamId = event.stream_id || event.message.id;
        if (streamingMessageIdRef.current !== endingStreamId) {
          applyConversationSnapshot(event.conversation);
          return;
        }
        streamingEndRef.current = event;
        settleStreamingEnd();
      } else if (event.type === "message_abort") {
        if (streamingMessageIdRef.current === event.message_id) {
          resetStreamingPlayback();
          setStreamingMessage(undefined);
        }
        awaitingAIResponseRef.current = Boolean(event.conversation.ai_processing);
        setConversation(event.conversation);
      }
    };

    const connect = async () => {
      try {
        await api.streamSupportConversation(
          tenantSlug,
          token,
          handleStreamEvent,
          controller.signal,
          accountId,
        );
      } catch (caught) {
        if (stopped || controller.signal.aborted) return;
        if (caught instanceof ApiError && [401, 404].includes(caught.status)) {
          saveToken(storageScope, "");
          setToken("");
          setConversation(undefined);
          setStreamingMessage(undefined);
          return;
        }
        await refreshConversation(true);
      }
      if (!stopped && !controller.signal.aborted) {
        reconnectTimer = window.setTimeout(() => void connect(), 750);
      }
    };

    void refreshConversation();
    void connect();
    return () => {
      stopped = true;
      controller.abort();
      if (reconnectTimer !== undefined) window.clearTimeout(reconnectTimer);
      resetStreamingPlayback();
    };
  }, [
    enqueueStreamingDelta,
    applyConversationSnapshot,
    accountId,
    open,
    refreshConversation,
    resetStreamingPlayback,
    settleStreamingEnd,
    storageScope,
    tenantSlug,
    token,
  ]);

  useEffect(() => {
    if (!open) return;
    window.setTimeout(() => textAreaRef.current?.focus(), 180);
  }, [open]);

  useEffect(() => {
    messageListRef.current?.scrollTo({
      top: messageListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [
    conversation?.messages.length,
    open,
    streamingMessage?.body.length,
    supportProductCount,
  ]);

  useEffect(() => {
    if (!open && activeActionSlot === null) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      setActiveActionSlot(null);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [activeActionSlot, open]);

  useEffect(() => {
    if (activeActionSlot === null) return;
    const closeOnOutsidePress = (event: PointerEvent) => {
      if (!widgetRef.current?.contains(event.target as Node)) {
        setActiveActionSlot(null);
      }
    };
    window.addEventListener("pointerdown", closeOnOutsidePress);
    return () => window.removeEventListener("pointerdown", closeOnOutsidePress);
  }, [activeActionSlot]);

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
            locale,
          }, accountId)
        : await api.createSupportConversation(tenantSlug, {
            message,
            client_message_id: clientMessageId,
            locale,
          }, accountId);
      const nextToken = next.access_token || token;
      if (nextToken && nextToken !== token) {
        setToken(nextToken);
        saveToken(storageScope, nextToken);
      }
      setConversation(next);
      awaitingAIResponseRef.current = Boolean(next.ai_processing);
      next.messages.forEach((item) => knownMessageIdsRef.current.add(item.id));
      setDraft("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("消息发送失败，请稍后重试。"));
    } finally {
      setSending(false);
    }
  };

  const requestHumanAssistance = async () => {
    if (
      !token
      || humanRequestBusy
      || conversation?.human_assistance_state !== "OFFERED"
    ) return;
    setHumanRequestBusy(true);
    setError("");
    try {
      setConversation(await api.requestHumanSupport(tenantSlug, token, accountId));
    } catch (caught) {
      setError(caught instanceof Error
        ? caught.message
        : t("暂时无法联系人工客服，请稍后重试。"));
    } finally {
      setHumanRequestBusy(false);
    }
  };

  const startNewConversation = () => {
    saveToken(storageScope, "");
    setToken("");
    setConversation(undefined);
    setStreamingMessage(undefined);
    resetStreamingPlayback();
    knownMessageIdsRef.current.clear();
    awaitingAIResponseRef.current = false;
    setError("");
    window.setTimeout(() => textAreaRef.current?.focus(), 0);
  };

  if (!widget.enabled) return null;

  return (
    <aside
      ref={widgetRef}
      className={`storefront-support${open ? " is-open" : ""}`}
      aria-label={t("在线客服")}
    >
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
            <strong id="storefront-support-title">{widget.title && widget.title !== "AI 智能客服" ? widget.title : t("AI 智能客服")}</strong>
            <small>
              {widget.ai_enabled
                ? conversation?.human_assistance_state === "REQUESTED"
                  ? t("已通知人工客服，请稍候")
                  : conversation?.human_assistance_state === "OFFERED"
                    ? t("需要人工协助")
                    : conversation?.automation_state === "HUMAN_TAKEOVER"
                      ? t("人工客服已接管本次会话")
                  : t("AI 基于已批准资料回答 · 必要时转人工")
                : t("当前由商家人工回复")}
            </small>
          </div>
          <button type="button" onClick={() => setOpen(false)} aria-label={t("关闭客服窗口")}>
            <X weight="bold" />
          </button>
        </header>

        <div className="storefront-support-messages" ref={messageListRef} aria-live="polite">
          <div className="support-message is-merchant is-welcome">
            <div className="support-message-content"><span dir="auto">{widget.welcome_message}</span></div>
            <small>{storeName}</small>
          </div>
          {loading && !conversation ? (
            <div className="support-message-loading"><i /><i /><i /></div>
          ) : null}
          {(conversation?.messages || []).map((message) => {
            const senderClass = message.sender_type === "VISITOR"
              ? "is-visitor"
              : message.sender_type === "AI"
                ? "is-ai"
                : message.sender_type === "SYSTEM"
                  ? "is-system"
                  : "is-merchant";
            const productCitations = (message.citations || []).filter(
              (citation, index, citations) => (
                citation.source_type === "SKU"
                && citations.findIndex((candidate) => (
                  candidate.source_type === "SKU"
                  && candidate.source_entity_id === citation.source_entity_id
                )) === index
                && supportProducts[citation.source_entity_id] !== null
              ),
            );
            return (
              <div
                className={
                  `support-message ${senderClass}`
                  + (productCitations.length ? " has-product-cards" : "")
                }
                key={message.id}
              >
                <div className="support-message-content">
                  <span dir="auto">{message.body}</span>
                  {message.sender_type === "AI" && message.citations?.length ? (
                    <details className="storefront-support-citations">
                      <summary>{t("查看 {count} 条资料来源", { count: message.citations.length })}</summary>
                      <div>
                        {message.citations.map((citation) => (
                          <article key={`${message.id}:${citation.citation_number}`}>
                            <strong>[{citation.citation_number}] {citation.source_title}</strong>
                            <small>{citation.source_type === "SKU" ? "SKU" : t("企业文件")} · v{citation.source_version}</small>
                            <p dir="auto">{citation.excerpt}</p>
                          </article>
                        ))}
                      </div>
                    </details>
                  ) : null}
                </div>
                {productCitations.length ? (
                  <section
                    className="storefront-support-products"
                    aria-label={t("相关商品")}
                  >
                    <strong>{t("相关商品")}</strong>
                    <div>
                      {productCitations.map((citation) => {
                        const product = supportProducts[citation.source_entity_id];
                        if (!product) {
                          return (
                            <span
                              className="support-product-card is-loading"
                              key={citation.source_entity_id}
                              aria-hidden="true"
                            >
                              <i />
                              <span><i /><i /><i /></span>
                            </span>
                          );
                        }
                        return (
                          <SupportProductCard
                            key={citation.source_entity_id}
                            product={product}
                            citationNumber={citation.citation_number}
                            detailsHref={
                              `${storefrontRoot}/products/`
                              + encodeURIComponent(product.id)
                              + storefrontLocaleQuery(locale)
                            }
                            locale={locale}
                            onOpen={() => setOpen(false)}
                          />
                        );
                      })}
                    </div>
                  </section>
                ) : null}
                <small>
                  {message.sender_type === "VISITOR" ? t("我") : message.sender_type === "AI" ? t("AI 客服") : message.sender_type === "SYSTEM" ? t("系统") : storeName}
                  {" · "}
                  {new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(new Date(message.created_at))}
                </small>
              </div>
            );
          })}
          {streamingMessage && !conversation?.messages.some(
            (message) => message.id === streamingMessage.id,
          ) ? (
            <div className="support-message is-ai is-streaming" key={streamingMessage.id}>
              <div className="support-message-content">
                <span dir="auto">
                  {streamingMessage.body}
                  <i className="support-stream-caret" aria-hidden="true" />
                </span>
              </div>
              <small>
                {t("AI 客服")}
                {" · "}
                {new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(
                  new Date(streamingMessage.created_at),
                )}
              </small>
            </div>
          ) : null}
          {conversation?.ai_processing && !streamingMessage ? (
            <div className="support-ai-processing" role="status">
              <div className="support-message-loading"><i /><i /><i /></div>
              <small>{processingLabel}</small>
            </div>
          ) : null}
          {conversation?.status === "OPEN"
          && ["OFFERED", "REQUESTED"].includes(
            conversation.human_assistance_state || "NONE",
          ) ? (
            <section
              className={`support-human-assistance is-${(
                conversation.human_assistance_state || "NONE"
              ).toLowerCase()}`}
              aria-live="polite"
            >
              <span>
                {conversation.human_assistance_state === "REQUESTED"
                  ? <CheckCircle weight="fill" />
                  : <Headset weight="duotone" />}
              </span>
              <div>
                <strong>
                  {conversation.human_assistance_state === "REQUESTED"
                    ? t("已通知人工客服")
                    : t("需要人工客服继续处理？")}
                </strong>
                <small>
                  {conversation.human_assistance_state === "REQUESTED"
                    ? t("客服人员会在后台看到提醒，请在当前会话中等待回复。")
                    : t("点击后会立即通知商家客服，并将本次会话加入待处理列表。")}
                </small>
              </div>
              {conversation.human_assistance_state === "OFFERED" ? (
                <button
                  type="button"
                  disabled={humanRequestBusy}
                  onClick={() => void requestHumanAssistance()}
                >
                  <Headset weight="bold" />
                  {humanRequestBusy ? t("正在通知…") : t("联系人工客服")}
                </button>
              ) : null}
            </section>
          ) : null}
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
          <small>
            {widget.ai_enabled
              ? t("AI 只会依据公开商品与已批准资料回答；证据不足时转交人工客服。")
              : t("消息会发送给商家客服，回复可能需要一些时间。")}
          </small>
        </footer>
      </section>

      <div className="storefront-support-actions">
        {actions
          .slice()
          .sort((left, right) => right.slot - left.slot)
          .map((action) => {
            const previewVisible = !open && (
              activeActionSlot === action.slot || hoveredActionSlot === action.slot
            );
            const previewId = `storefront-support-action-${action.slot}`;
            const titleId = `${previewId}-title`;
            return (
            <div
              className={`storefront-support-action-item${previewVisible ? " is-preview-visible" : ""}`}
              key={action.slot}
              onMouseEnter={() => setHoveredActionSlot(action.slot)}
              onMouseLeave={() => setHoveredActionSlot((slot) => (
                slot === action.slot ? null : slot
              ))}
            >
              <section
                id={previewId}
                className="storefront-support-action-preview"
                aria-hidden={!previewVisible}
                aria-labelledby={titleId}
              >
                <header>
                  <strong id={titleId}>{action.label || t("商家快捷入口")}</strong>
                </header>
                <div>
                  {action.image_url ? (
                    <img
                      src={action.image_url}
                      alt={action.label || t("商家快捷入口")}
                      loading="lazy"
                      decoding="async"
                    />
                  ) : (
                    <span className="storefront-support-action-placeholder">
                      <ImageSquare weight="duotone" />
                    </span>
                  )}
                </div>
              </section>
              <button
                type="button"
                className="storefront-support-orb is-custom"
                aria-label={action.label || t("商家快捷入口")}
                aria-expanded={previewVisible}
                aria-controls={previewId}
                onClick={() => {
                  setOpen(false);
                  setHoveredActionSlot(null);
                  setActiveActionSlot((slot) => (
                    slot === action.slot ? null : action.slot
                  ));
                }}
                onFocus={() => setHoveredActionSlot(action.slot)}
                onBlur={() => setHoveredActionSlot((slot) => (
                  slot === action.slot ? null : slot
                ))}
              >
                <ImageSquare weight="duotone" />
                <span>{action.label}</span>
              </button>
            </div>
            );
          })}
        <button
          type="button"
          className="storefront-support-orb is-chat"
          aria-expanded={open}
          aria-controls="storefront-support-panel"
          aria-label={t(open ? "关闭客服窗口" : "打开 AI 智能客服")}
          onClick={() => {
            setActiveActionSlot(null);
            setHoveredActionSlot(null);
            setOpen((value) => !value);
          }}
        >
          {open ? <X weight="bold" /> : <ChatCenteredDots weight="fill" />}
          <span>{t("在线客服")}</span>
        </button>
      </div>
    </aside>
  );
}
