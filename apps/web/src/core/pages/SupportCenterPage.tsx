import { Badge, Button, TextArea, TextField } from "@radix-ui/themes";
import {
  ArrowsLeftRight,
  ArrowClockwise,
  CheckCircle,
  MagnifyingGlass,
  PaperPlaneTilt,
  Translate,
  UserCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCoreAuth } from "../AuthContext";
import {
  getSupportConversation,
  listSupportConversations,
  previewSupportReplyTranslation,
  replySupportConversation,
  updateSupportConversationStatus,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import {
  normalizeStorefrontLocale,
  STOREFRONT_LANGUAGE_OPTIONS,
  storefrontLanguage,
} from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";
import type {
  SupportConversationDetail,
  SupportConversationStatus,
  SupportConversationSummary,
} from "../types";
import "./SupportCenterPage.css";

function dateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function SupportCenterPage() {
  const { hasPermission, profile } = useCoreAuth();
  const { locale, t } = useLocale();
  const canReply = hasPermission("support.reply");
  const [items, setItems] = useState<SupportConversationSummary[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<SupportConversationDetail>();
  const [statusFilter, setStatusFilter] = useState<SupportConversationStatus | "">("");
  const [query, setQuery] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [reply, setReply] = useState("");
  const [replyBusy, setReplyBusy] = useState(false);
  const [translationBusy, setTranslationBusy] = useState(false);
  const [translationError, setTranslationError] = useState("");
  const [translatedReply, setTranslatedReply] = useState("");
  const [replyTargetLocale, setReplyTargetLocale] = useState<StorefrontLocale>("en-US");
  const messagesRef = useRef<HTMLDivElement>(null);
  const operatorLocale: StorefrontLocale = profile?.context.businessMode === "EXPORT"
    ? "en-US"
    : "zh-CN";

  const loadList = useCallback(async (quiet = false) => {
    if (!quiet) setListLoading(true);
    try {
      const page = await listSupportConversations({
        status: statusFilter,
        query,
        pageSize: 50,
      });
      setItems(page.items);
      setError("");
      setSelectedId((current) => {
        if (current && page.items.some((item) => item.id === current)) return current;
        return page.items[0]?.id || "";
      });
    } catch (caught) {
      if (!quiet) setError(caught instanceof Error ? caught.message : t("会话加载失败"));
    } finally {
      if (!quiet) setListLoading(false);
    }
  }, [query, statusFilter, t]);

  const loadDetail = useCallback(async (conversationId: string, quiet = false) => {
    if (!conversationId) {
      setDetail(undefined);
      return;
    }
    if (!quiet) setDetailLoading(true);
    try {
      const next = await getSupportConversation(conversationId);
      setDetail(next);
      setItems((current) => current.map((item) => (
        item.id === conversationId ? { ...item, unread: false, status: next.status } : item
      )));
      setError("");
    } catch (caught) {
      if (!quiet) setError(caught instanceof Error ? caught.message : t("会话详情加载失败"));
    } finally {
      if (!quiet) setDetailLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadList(), 220);
    return () => window.clearTimeout(timer);
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) return;
    void loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadList(true);
      if (selectedId) void loadDetail(selectedId, true);
    }, 5_000);
    return () => window.clearInterval(interval);
  }, [loadDetail, loadList, selectedId]);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight });
  }, [detail?.messages.length]);

  useEffect(() => {
    if (!detail) return;
    setReply("");
    setTranslatedReply("");
    setTranslationError("");
    setReplyTargetLocale(normalizeStorefrontLocale(detail.locale));
  }, [detail?.id]);

  useEffect(() => {
    if (!detail || translatedReply) return;
    setReplyTargetLocale(normalizeStorefrontLocale(detail.locale));
  }, [detail?.locale, translatedReply]);

  const sendReply = async () => {
    const originalMessage = reply.trim();
    const translatedMessage = translatedReply.trim();
    const message = translatedMessage || originalMessage;
    if (!detail || !message || replyBusy) return;
    setReplyBusy(true);
    setError("");
    try {
      setDetail(await replySupportConversation(detail.id, {
        message,
        draftMessage: translatedMessage ? originalMessage : undefined,
        sourceLocale: translatedMessage ? operatorLocale : undefined,
        targetLocale: translatedMessage ? replyTargetLocale : undefined,
      }));
      setReply("");
      setTranslatedReply("");
      setTranslationError("");
      await loadList(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("回复发送失败"));
    } finally {
      setReplyBusy(false);
    }
  };

  const translateReply = async () => {
    const message = reply.trim();
    if (!detail || !message || translationBusy) return;
    setTranslationBusy(true);
    setTranslationError("");
    try {
      const preview = await previewSupportReplyTranslation(
        detail.id,
        message,
        replyTargetLocale,
      );
      setTranslatedReply(preview.translatedMessage);
    } catch (caught) {
      setTranslatedReply("");
      setTranslationError(caught instanceof Error ? caught.message : t("回复翻译失败"));
    } finally {
      setTranslationBusy(false);
    }
  };

  const updateReply = (value: string) => {
    setReply(value);
    if (translatedReply) setTranslatedReply("");
    if (translationError) setTranslationError("");
  };

  const changeStatus = async (status: SupportConversationStatus) => {
    if (!detail || replyBusy) return;
    setReplyBusy(true);
    try {
      setDetail(await updateSupportConversationStatus(detail.id, status));
      await loadList(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("会话状态更新失败"));
    } finally {
      setReplyBusy(false);
    }
  };

  const selectedSummary = useMemo(
    () => items.find((item) => item.id === selectedId),
    [items, selectedId],
  );

  return (
    <div className="core-page support-center-page">
      <CorePageHeading
        eyebrow={t("客户沟通")}
        title={t("客服管理")}
        description={t("查看商品前台的客户咨询，并在一个工作区内处理回复与会话状态。")}
        actions={(
          <Button variant="soft" color="gray" onClick={() => void loadList()}>
            <ArrowClockwise />{t("刷新")}
          </Button>
        )}
      />

      <section className="support-conversation-workspace">
          <aside className="support-inbox">
            <div className="support-inbox-tools">
              <TextField.Root value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t("搜索编号、姓名或邮箱")}>
                <TextField.Slot><MagnifyingGlass /></TextField.Slot>
              </TextField.Root>
              <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as SupportConversationStatus | "")} aria-label={t("会话状态")}>
                <option value="">{t("全部会话")}</option>
                <option value="OPEN">{t("进行中")}</option>
                <option value="CLOSED">{t("已结束")}</option>
              </select>
            </div>
            <div className="support-inbox-list">
              {listLoading ? <CoreLoading label={t("正在加载会话")} /> : null}
              {!listLoading && !items.length ? <CoreEmpty title={t("还没有客户咨询")} description={t("客户从商品前台发送消息后，会话会出现在这里。 ")} /> : null}
              {!listLoading && items.map((item) => (
                <button type="button" className={`${item.id === selectedId ? "is-selected" : ""}${item.unread ? " is-unread" : ""}`} onClick={() => setSelectedId(item.id)} key={item.id}>
                  <span className="support-contact-avatar"><UserCircle weight="duotone" /></span>
                  <span className="support-inbox-copy">
                    <strong>{item.visitorName || t("网站访客")}</strong>
                    <small>{item.lastMessagePreview || t("暂无消息")}</small>
                    <em>{item.referenceNumber}</em>
                  </span>
                  <span className="support-inbox-meta">
                    <time>{dateTime(item.lastMessageAt, locale)}</time>
                    {item.unread ? <i /> : null}
                    {item.status === "CLOSED" ? <Badge color="gray">{t("已结束")}</Badge> : null}
                  </span>
                </button>
              ))}
            </div>
          </aside>

          <article className="support-thread">
            {error ? <CoreError message={error} onRetry={() => selectedId ? void loadDetail(selectedId) : void loadList()} /> : null}
            {!error && !selectedId ? <CoreEmpty title={t("选择一条会话")} description={t("在左侧选择客户后即可查看消息并回复。 ")} /> : null}
            {!error && detailLoading && !detail ? <CoreLoading label={t("正在加载消息")} /> : null}
            {!error && detail ? (
              <>
                <header className="support-thread-header">
                  <div>
                    <strong>{detail.visitorName || t("网站访客")}</strong>
                    <span>{detail.visitorEmail || detail.referenceNumber} · {detail.locale}</span>
                  </div>
                  <div>
                    <Badge color={detail.status === "OPEN" ? "green" : "gray"}>{detail.status === "OPEN" ? t("进行中") : t("已结束")}</Badge>
                    {canReply ? (
                      <Button size="1" variant="soft" color={detail.status === "OPEN" ? "gray" : "green"} onClick={() => void changeStatus(detail.status === "OPEN" ? "CLOSED" : "OPEN")} disabled={replyBusy}>
                        {detail.status === "OPEN" ? <XCircle /> : <CheckCircle />}
                        {detail.status === "OPEN" ? t("结束会话") : t("重新打开")}
                      </Button>
                    ) : null}
                  </div>
                </header>
                <div className="support-thread-messages" ref={messagesRef}>
                  {detail.messages.map((message) => {
                    const isVisitor = message.senderType === "VISITOR";
                    const hasIncomingTranslation = isVisitor
                      && message.translationStatus === "READY"
                      && Boolean(message.translatedBody);
                    return (
                      <div className={`support-thread-message ${isVisitor ? "is-visitor" : "is-merchant"}`} key={message.id}>
                        <div className="support-thread-bubble">
                          <span>{hasIncomingTranslation ? message.translatedBody : message.body}</span>
                          {hasIncomingTranslation ? (
                            <details className="support-message-original">
                              <summary>{t("查看客户原文")}</summary>
                              <p dir="auto">{message.body}</p>
                            </details>
                          ) : null}
                          {!isVisitor && message.draftBody ? (
                            <details className="support-message-original">
                              <summary>{t("查看回复原稿")}</summary>
                              <p>{message.draftBody}</p>
                            </details>
                          ) : null}
                          {isVisitor && ["FAILED", "UNAVAILABLE"].includes(message.translationStatus) ? (
                            <small className="support-message-translation-note">
                              {message.translationStatus === "UNAVAILABLE"
                                ? t("翻译服务暂不可用，当前显示客户原文。")
                                : t("自动翻译失败，系统稍后会重试。")}
                            </small>
                          ) : null}
                        </div>
                        <small>
                          {isVisitor ? t("客户") : t("商家客服")}
                          {hasIncomingTranslation ? ` · ${t("已译为{language}", { language: storefrontLanguage(message.translationTargetLocale || operatorLocale).label })}` : ""}
                          {" · "}{dateTime(message.createdAt, locale)}
                        </small>
                      </div>
                    );
                  })}
                </div>
                <footer className="support-thread-composer">
                  <div className="support-composer-fields">
                    <label>
                      <span>{t("回复原文")} · {storefrontLanguage(operatorLocale).flag} {storefrontLanguage(operatorLocale).label}</span>
                      <TextArea value={reply} onChange={(event) => updateReply(event.target.value)} maxLength={4_000} disabled={!canReply || detail.status === "CLOSED"} placeholder={detail.status === "CLOSED" ? t("重新打开会话后才能回复") : t("输入回复内容，可直接发送或先翻译")} onKeyDown={(event) => {
                        if (event.key === "Enter" && !event.shiftKey && (translatedReply || replyTargetLocale === operatorLocale)) {
                          event.preventDefault();
                          void sendReply();
                        }
                      }} />
                    </label>

                    <div className="support-translation-toolbar">
                      <span>{storefrontLanguage(operatorLocale).shortLabel}</span>
                      <ArrowsLeftRight aria-hidden="true" />
                      <label>
                        <span className="sr-only">{t("目标语言")}</span>
                        <select
                          value={replyTargetLocale}
                          disabled={!canReply || detail.status === "CLOSED" || translationBusy}
                          onChange={(event) => {
                            setReplyTargetLocale(event.target.value as StorefrontLocale);
                            setTranslatedReply("");
                            setTranslationError("");
                          }}
                        >
                          {STOREFRONT_LANGUAGE_OPTIONS.map((language) => (
                            <option value={language.code} key={language.code}>{language.flag} {language.label}</option>
                          ))}
                        </select>
                      </label>
                      <Button type="button" variant="soft" color="gray" onClick={() => void translateReply()} disabled={!canReply || !reply.trim() || detail.status === "CLOSED" || translationBusy}>
                        <Translate />{translationBusy ? t("翻译中") : t("翻译回复")}
                      </Button>
                    </div>

                    {translationError ? <p className="support-translation-error" role="alert">{translationError}</p> : null}
                    {translatedReply ? (
                      <label className="support-translated-preview">
                        <span>{t("发送前译文，可继续编辑")} · {storefrontLanguage(replyTargetLocale).flag} {storefrontLanguage(replyTargetLocale).label}</span>
                        <TextArea value={translatedReply} onChange={(event) => setTranslatedReply(event.target.value)} maxLength={4_000} disabled={!canReply || detail.status === "CLOSED"} dir={storefrontLanguage(replyTargetLocale).direction} />
                      </label>
                    ) : (
                      <small className="support-translation-hint">
                        {replyTargetLocale === operatorLocale
                          ? t("当前目标语言与回复语言相同，可直接发送。")
                          : t("翻译后会先显示译文，确认或修改后再发送给客户。")}
                      </small>
                    )}
                  </div>
                  <div className="support-composer-actions">
                    {translatedReply ? (
                      <button type="button" onClick={() => setTranslatedReply("")}>{t("取消译文")}</button>
                    ) : null}
                    <Button onClick={() => void sendReply()} disabled={!canReply || !(translatedReply.trim() || reply.trim()) || replyBusy || detail.status === "CLOSED"}>
                      <PaperPlaneTilt weight="fill" />{replyBusy ? t("发送中") : translatedReply ? t("发送译文") : t("发送回复")}
                    </Button>
                  </div>
                </footer>
              </>
            ) : null}
            {!detail && selectedSummary && !detailLoading ? <CoreLoading label={t("正在打开会话")} /> : null}
          </article>
      </section>
    </div>
  );
}
