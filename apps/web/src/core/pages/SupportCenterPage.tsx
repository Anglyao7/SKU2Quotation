import { Badge, Button, TextArea, TextField } from "@radix-ui/themes";
import {
  ArrowsLeftRight,
  ArrowClockwise,
  CheckCircle,
  MagnifyingGlass,
  PaperPlaneTilt,
  Robot,
  Translate,
  UserCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useCoreAuth } from "../AuthContext";
import {
  getSupportConversation,
  listSupportConversations,
  previewSupportReplyTranslation,
  replySupportConversation,
  resumeSupportConversationAI,
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

function countryFlag(countryCode?: string) {
  const normalized = countryCode?.trim().toUpperCase();
  if (!normalized || normalized.length !== 2 || !/^[A-Z]{2}$/.test(normalized)) {
    return "🌐";
  }
  return Array.from(normalized)
    .map((character) => String.fromCodePoint(127397 + character.charCodeAt(0)))
    .join("");
}

function countryName(countryCode: string | undefined, locale: string) {
  const normalized = countryCode?.trim().toUpperCase();
  if (!normalized || normalized === "ZZ" || normalized === "T1") return "";
  try {
    return new Intl.DisplayNames([locale, "en"], { type: "region" }).of(normalized) || normalized;
  } catch {
    return normalized;
  }
}

function visitorLocalTime(timestamp: number, timezone: string | undefined, locale: string) {
  if (!timezone) return "";
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(timestamp));
  } catch {
    return "";
  }
}

export function SupportCenterPage() {
  const { hasPermission, profile } = useCoreAuth();
  const { locale, t } = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const canReply = hasPermission("support.reply");
  const isPlatformAdmin = Boolean(profile?.user.isPlatformAdmin);
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
  const [automationBusy, setAutomationBusy] = useState(false);
  const [translationBusy, setTranslationBusy] = useState(false);
  const [translationError, setTranslationError] = useState("");
  const [translatedReply, setTranslatedReply] = useState("");
  const [replyTargetLocale, setReplyTargetLocale] = useState<StorefrontLocale>("en-US");
  const [clockNow, setClockNow] = useState(() => Date.now());
  const messagesRef = useRef<HTMLDivElement>(null);
  const selectedIdRef = useRef("");
  const detailRequestSequenceRef = useRef(0);
  const operatorLocale: StorefrontLocale = profile?.context.businessMode === "EXPORT"
    ? "en-US"
    : "zh-CN";
  const requestedConversationId = searchParams.get("conversation") || "";

  const selectConversation = useCallback((conversationId: string) => {
    if (selectedIdRef.current === conversationId) return;
    selectedIdRef.current = conversationId;
    detailRequestSequenceRef.current += 1;
    setSelectedId(conversationId);
    setDetail(undefined);
    setDetailLoading(Boolean(conversationId));
    setError("");
    setReply("");
    setTranslatedReply("");
    setTranslationError("");
  }, []);

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
      const current = selectedIdRef.current;
      const nextSelectedId = current && page.items.some((item) => item.id === current)
        ? current
        : requestedConversationId
          && page.items.some((item) => item.id === requestedConversationId)
          ? requestedConversationId
          : page.items[0]?.id || "";
      selectConversation(nextSelectedId);
    } catch (caught) {
      if (!quiet) setError(caught instanceof Error ? caught.message : t("会话加载失败"));
    } finally {
      if (!quiet) setListLoading(false);
    }
  }, [query, requestedConversationId, selectConversation, statusFilter, t]);

  useEffect(() => {
    if (!requestedConversationId) return;
    selectConversation(requestedConversationId);
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.delete("conversation");
      return next;
    }, { replace: true });
  }, [requestedConversationId, selectConversation, setSearchParams]);

  const loadDetail = useCallback(async (conversationId: string, quiet = false) => {
    if (!conversationId) {
      setDetail(undefined);
      return;
    }
    const requestSequence = ++detailRequestSequenceRef.current;
    if (!quiet) setDetailLoading(true);
    try {
      const next = await getSupportConversation(conversationId);
      if (
        selectedIdRef.current !== conversationId
        || detailRequestSequenceRef.current !== requestSequence
      ) return;
      setDetail(next);
      setItems((current) => current.map((item) => (
        item.id === conversationId ? {
          ...item,
          unread: false,
          status: next.status,
          automationState: next.automationState,
          aiProcessing: next.aiProcessing,
        } : item
      )));
      setError("");
    } catch (caught) {
      if (
        !quiet
        && selectedIdRef.current === conversationId
        && detailRequestSequenceRef.current === requestSequence
      ) setError(caught instanceof Error ? caught.message : t("会话详情加载失败"));
    } finally {
      if (
        selectedIdRef.current === conversationId
        && detailRequestSequenceRef.current === requestSequence
      ) setDetailLoading(false);
    }
  }, [t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadList(), 220);
    return () => window.clearTimeout(timer);
  }, [loadList]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(undefined);
      setDetailLoading(false);
      return;
    }
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
    const interval = window.setInterval(() => setClockNow(Date.now()), 1_000);
    return () => window.clearInterval(interval);
  }, []);

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
    if (
      !detail
      || detail.id !== selectedIdRef.current
      || detailLoading
      || !message
      || replyBusy
    ) return;
    const conversationId = detail.id;
    setReplyBusy(true);
    setError("");
    try {
      const next = await replySupportConversation(conversationId, {
        message,
        draftMessage: translatedMessage ? originalMessage : undefined,
        sourceLocale: translatedMessage ? operatorLocale : undefined,
        targetLocale: translatedMessage ? replyTargetLocale : undefined,
      });
      if (selectedIdRef.current !== conversationId) return;
      setDetail(next);
      setReply("");
      setTranslatedReply("");
      setTranslationError("");
      await loadList(true);
      window.dispatchEvent(new Event("atc:support-human-requests-changed"));
    } catch (caught) {
      if (selectedIdRef.current === conversationId) {
        setError(caught instanceof Error ? caught.message : t("回复发送失败"));
      }
    } finally {
      setReplyBusy(false);
    }
  };

  const translateReply = async () => {
    const message = reply.trim();
    if (
      !detail
      || detail.id !== selectedIdRef.current
      || detailLoading
      || !message
      || translationBusy
    ) return;
    const conversationId = detail.id;
    setTranslationBusy(true);
    setTranslationError("");
    try {
      const preview = await previewSupportReplyTranslation(
        conversationId,
        message,
        replyTargetLocale,
      );
      if (selectedIdRef.current === conversationId) {
        setTranslatedReply(preview.translatedMessage);
      }
    } catch (caught) {
      if (selectedIdRef.current === conversationId) {
        setTranslatedReply("");
        setTranslationError(caught instanceof Error ? caught.message : t("回复翻译失败"));
      }
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
    if (
      !detail
      || detail.id !== selectedIdRef.current
      || detailLoading
      || replyBusy
    ) return;
    const conversationId = detail.id;
    setReplyBusy(true);
    try {
      const next = await updateSupportConversationStatus(conversationId, status);
      if (selectedIdRef.current !== conversationId) return;
      setDetail(next);
      await loadList(true);
      window.dispatchEvent(new Event("atc:support-human-requests-changed"));
    } catch (caught) {
      if (selectedIdRef.current === conversationId) {
        setError(caught instanceof Error ? caught.message : t("会话状态更新失败"));
      }
    } finally {
      setReplyBusy(false);
    }
  };

  const resumeAutomation = async () => {
    if (
      !detail
      || detail.id !== selectedIdRef.current
      || detailLoading
      || automationBusy
      || detail.automationState !== "HUMAN_TAKEOVER"
      || !isPlatformAdmin
    ) return;
    const conversationId = detail.id;
    setAutomationBusy(true);
    setError("");
    try {
      const next = await resumeSupportConversationAI(conversationId);
      if (selectedIdRef.current !== conversationId) return;
      setDetail(next);
      setItems((current) => current.map((item) => item.id === next.id ? {
        ...item,
        automationState: next.automationState,
        aiProcessing: next.aiProcessing,
      } : item));
      window.dispatchEvent(new Event("atc:support-human-requests-changed"));
    } catch (caught) {
      if (selectedIdRef.current === conversationId) {
        setError(caught instanceof Error ? caught.message : t("恢复 AI 接待失败"));
      }
    } finally {
      setAutomationBusy(false);
    }
  };

  const selectedSummary = useMemo(
    () => items.find((item) => item.id === selectedId),
    [items, selectedId],
  );
  const visitorCountry = useMemo(() => {
    if (!detail?.visitorCountryCode && !detail?.visitorTimezone) return "";
    return `${countryFlag(detail?.visitorCountryCode)} ${countryName(detail?.visitorCountryCode, locale) || t("未知国家")}`;
  }, [detail?.visitorCountryCode, detail?.visitorTimezone, locale, t]);
  const visitorTime = useMemo(
    () => visitorLocalTime(clockNow, detail?.visitorTimezone, locale),
    [clockNow, detail?.visitorTimezone, locale],
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
                <button type="button" className={`${item.id === selectedId ? "is-selected" : ""}${item.unread ? " is-unread" : ""}`} onClick={() => selectConversation(item.id)} key={item.id}>
                  <span className="support-contact-avatar"><UserCircle weight="duotone" /></span>
                  <span className="support-inbox-copy">
                    <strong>{item.visitorName || t("网站访客")}</strong>
                    <small>{item.lastMessagePreview || t("暂无消息")}</small>
                    <em>{item.referenceNumber}</em>
                  </span>
                  <span className="support-inbox-meta">
                    <time>{dateTime(item.lastMessageAt, locale)}</time>
                    {item.unread ? <i /> : null}
                    {item.aiProcessing ? <Badge color="blue">AI</Badge> : null}
                    {item.humanAssistanceState === "REQUESTED" ? (
                      <Badge color="amber">{t("待人工处理")}</Badge>
                    ) : null}
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
            {!error && detail && detail.id === selectedId ? (
              <>
                <header className="support-thread-header">
                  <div>
                    <strong>{detail.visitorName || t("网站访客")}</strong>
                    <span>{detail.visitorEmail || detail.referenceNumber} · {detail.locale}</span>
                    {visitorCountry ? (
                      <span className="support-visitor-location" title={detail.visitorTimezone || undefined}>
                        {visitorCountry}
                        {visitorTime
                          ? ` · ${t("当地时间")} ${visitorTime}`
                          : ` · ${t("当地时间不可用")}`}
                      </span>
                    ) : null}
                  </div>
                  <div>
                    <Badge color={detail.automationState === "AI_ACTIVE" ? "blue" : "amber"}>
                      {detail.aiProcessing ? t("AI 回答中") : detail.automationState === "AI_ACTIVE" ? t("AI 可接待") : t("人工接管")}
                    </Badge>
                    {detail.humanAssistanceState === "REQUESTED" ? (
                      <Badge color="red">{t("客户已请求人工")}</Badge>
                    ) : null}
                    {detail.automationState === "HUMAN_TAKEOVER" && isPlatformAdmin ? (
                      <Button size="1" variant="soft" color="blue" onClick={() => void resumeAutomation()} disabled={automationBusy || detailLoading}>
                        <Robot />
                        {t("恢复 AI")}
                      </Button>
                    ) : null}
                    <Badge color={detail.status === "OPEN" ? "green" : "gray"}>{detail.status === "OPEN" ? t("进行中") : t("已结束")}</Badge>
                    {canReply ? (
                      <Button size="1" variant="soft" color={detail.status === "OPEN" ? "gray" : "green"} onClick={() => void changeStatus(detail.status === "OPEN" ? "CLOSED" : "OPEN")} disabled={replyBusy || detailLoading}>
                        {detail.status === "OPEN" ? <XCircle /> : <CheckCircle />}
                        {detail.status === "OPEN" ? t("结束会话") : t("重新打开")}
                      </Button>
                    ) : null}
                  </div>
                </header>
                <div className="support-thread-messages" ref={messagesRef}>
                  {detail.messages.map((message) => {
                    const isVisitor = message.senderType === "VISITOR";
                    const isAI = message.senderType === "AI";
                    const isSystem = message.senderType === "SYSTEM";
                    const hasIncomingTranslation = isVisitor
                      && message.translationStatus === "READY"
                      && Boolean(message.translatedBody);
                    return (
                      <div className={`support-thread-message ${isVisitor ? "is-visitor" : isAI ? "is-ai" : isSystem ? "is-system" : "is-merchant"}`} key={message.id}>
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
                          {isAI && message.citations.length ? (
                            <details className="support-message-citations">
                              <summary>{t("查看 {count} 条引用来源", { count: message.citations.length })}</summary>
                              <div>
                                {message.citations.map((citation) => (
                                  <article key={`${message.id}:${citation.citationNumber}`}>
                                    <b>[{citation.citationNumber}] {citation.sourceTitle}</b>
                                    <small>{citation.sourceType === "SKU" ? "SKU" : t("企业文件")} · v{citation.sourceVersion}</small>
                                    <p>{citation.excerpt}</p>
                                  </article>
                                ))}
                              </div>
                            </details>
                          ) : null}
                        </div>
                        <small>
                          {isVisitor ? t("客户") : isAI ? t("AI 客服") : isSystem ? t("系统") : t("商家客服")}
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
                      <TextArea value={reply} onChange={(event) => updateReply(event.target.value)} maxLength={4_000} disabled={!canReply || detail.status === "CLOSED" || detailLoading} placeholder={detail.status === "CLOSED" ? t("重新打开会话后才能回复") : t("输入回复内容，可直接发送或先翻译")} onKeyDown={(event) => {
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
                        <select
                          value={replyTargetLocale}
                          aria-label={t("目标语言")}
                          disabled={!canReply || detail.status === "CLOSED" || detailLoading || translationBusy}
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
                      <Button type="button" variant="soft" color="gray" onClick={() => void translateReply()} disabled={!canReply || !reply.trim() || detail.status === "CLOSED" || detailLoading || translationBusy}>
                        <Translate />{translationBusy ? t("翻译中") : t("翻译回复")}
                      </Button>
                    </div>

                    {translationError ? <p className="support-translation-error" role="alert">{translationError}</p> : null}
                    {translatedReply ? (
                      <label className="support-translated-preview">
                        <span>{t("发送前译文，可继续编辑")} · {storefrontLanguage(replyTargetLocale).flag} {storefrontLanguage(replyTargetLocale).label}</span>
                        <TextArea value={translatedReply} onChange={(event) => setTranslatedReply(event.target.value)} maxLength={4_000} disabled={!canReply || detail.status === "CLOSED" || detailLoading} dir={storefrontLanguage(replyTargetLocale).direction} />
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
                    <Button onClick={() => void sendReply()} disabled={!canReply || !(translatedReply.trim() || reply.trim()) || replyBusy || detailLoading || detail.status === "CLOSED"}>
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
