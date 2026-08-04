import { Badge, Button, Text, TextArea, TextField } from "@radix-ui/themes";
import {
  ArrowClockwise,
  ChatCircleDots,
  CheckCircle,
  ImageSquare,
  MagnifyingGlass,
  PaperPlaneTilt,
  SlidersHorizontal,
  UserCircle,
  XCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useCoreAuth } from "../AuthContext";
import {
  getSupportConversation,
  getSupportSettings,
  listSupportConversations,
  replySupportConversation,
  updateSupportConversationStatus,
  updateSupportSettings,
  uploadSupportActionImage,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportActionSettings,
  SupportConversationDetail,
  SupportConversationStatus,
  SupportConversationSummary,
  SupportSettings,
} from "../types";
import "./SupportCenterPage.css";


type Tab = "conversations" | "settings";

function dateTime(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function blankAction(slot: 2 | 3): SupportActionSettings {
  return { slot, visible: false, hasUploadedImage: false };
}

function normalizeSettings(settings: SupportSettings): SupportSettings {
  const actions = new Map(settings.customActions.map((item) => [item.slot, item]));
  return {
    ...settings,
    customActions: [actions.get(2) || blankAction(2), actions.get(3) || blankAction(3)],
  };
}

export function SupportCenterPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canReply = hasPermission("support.reply");
  const canManageSettings = hasPermission("support.settings_manage");
  const [tab, setTab] = useState<Tab>("conversations");
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
  const [settings, setSettings] = useState<SupportSettings>();
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsError, setSettingsError] = useState("");
  const [settingsSaved, setSettingsSaved] = useState(false);
  const messagesRef = useRef<HTMLDivElement>(null);

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
    if (tab !== "conversations") return;
    const interval = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      void loadList(true);
      if (selectedId) void loadDetail(selectedId, true);
    }, 5_000);
    return () => window.clearInterval(interval);
  }, [loadDetail, loadList, selectedId, tab]);

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight });
  }, [detail?.messages.length]);

  const loadSettings = useCallback(async () => {
    if (!canManageSettings) return;
    setSettingsLoading(true);
    setSettingsError("");
    try {
      setSettings(normalizeSettings(await getSupportSettings()));
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : t("悬浮球设置加载失败"));
    } finally {
      setSettingsLoading(false);
    }
  }, [canManageSettings, t]);

  useEffect(() => {
    if (tab === "settings" && !settings && canManageSettings) void loadSettings();
  }, [canManageSettings, loadSettings, settings, tab]);

  const sendReply = async () => {
    const message = reply.trim();
    if (!detail || !message || replyBusy) return;
    setReplyBusy(true);
    setError("");
    try {
      setDetail(await replySupportConversation(detail.id, message));
      setReply("");
      await loadList(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("回复发送失败"));
    } finally {
      setReplyBusy(false);
    }
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

  const updateAction = (slot: 2 | 3, patch: Partial<SupportActionSettings>) => {
    setSettingsSaved(false);
    setSettings((current) => current ? {
      ...current,
      customActions: current.customActions.map((item) => (
        item.slot === slot ? { ...item, ...patch } : item
      )),
    } : current);
  };

  const validateSettings = (value: SupportSettings) => {
    if (!value.welcomeMessage.trim()) return t("请填写客服欢迎语。 ");
    for (const action of value.customActions) {
      if (!action.visible) continue;
      if (!action.targetUrl?.trim()) return t("请为第 {slot} 个悬浮球填写跳转链接。", { slot: action.slot });
      if (!action.imageUrl && !action.externalImageUrl) return t("请为第 {slot} 个悬浮球上传或填写图片。", { slot: action.slot });
    }
    return "";
  };

  const saveSettings = async () => {
    if (!settings || settingsBusy) return;
    const validation = validateSettings(settings);
    if (validation) {
      setSettingsError(validation);
      return;
    }
    setSettingsBusy(true);
    setSettingsError("");
    setSettingsSaved(false);
    try {
      setSettings(normalizeSettings(await updateSupportSettings(settings)));
      setSettingsSaved(true);
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : t("设置保存失败"));
    } finally {
      setSettingsBusy(false);
    }
  };

  const uploadImage = async (slot: 2 | 3, file?: File) => {
    if (!file || !settings || settingsBusy) return;
    setSettingsBusy(true);
    setSettingsError("");
    setSettingsSaved(false);
    try {
      const persisted = await updateSupportSettings(settings);
      setSettings(normalizeSettings(await uploadSupportActionImage(slot, file)));
      if (!persisted) return;
      setSettingsSaved(true);
    } catch (caught) {
      setSettingsError(caught instanceof Error ? caught.message : t("图片上传失败"));
    } finally {
      setSettingsBusy(false);
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
        description={t("查看商品前台的咨询、人工回复客户，并管理右下角悬浮入口。")}
        actions={(
          <Button variant="soft" color="gray" onClick={() => void (tab === "conversations" ? loadList() : loadSettings())}>
            <ArrowClockwise />{t("刷新")}
          </Button>
        )}
      />

      <div className="support-center-tabs" role="tablist" aria-label={t("客服管理模块")}>
        <button type="button" role="tab" aria-selected={tab === "conversations"} className={tab === "conversations" ? "is-active" : ""} onClick={() => setTab("conversations")}>
          <ChatCircleDots weight="duotone" />{t("客户会话")}
          {items.some((item) => item.unread) ? <i aria-label={t("有未读消息")} /> : null}
        </button>
        {canManageSettings ? (
          <button type="button" role="tab" aria-selected={tab === "settings"} className={tab === "settings" ? "is-active" : ""} onClick={() => setTab("settings")}>
            <SlidersHorizontal weight="duotone" />{t("悬浮球设置")}
          </button>
        ) : null}
      </div>

      {tab === "conversations" ? (
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
              {listLoading ? <CoreLoading label="正在加载会话" /> : null}
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
            {!error && detailLoading && !detail ? <CoreLoading label="正在加载消息" /> : null}
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
                  {detail.messages.map((message) => (
                    <div className={`support-thread-message ${message.senderType === "VISITOR" ? "is-visitor" : "is-merchant"}`} key={message.id}>
                      <span>{message.body}</span>
                      <small>{message.senderType === "VISITOR" ? t("客户") : t("商家客服")} · {dateTime(message.createdAt, locale)}</small>
                    </div>
                  ))}
                </div>
                <footer className="support-thread-composer">
                  <TextArea value={reply} onChange={(event) => setReply(event.target.value)} maxLength={4_000} disabled={!canReply || detail.status === "CLOSED"} placeholder={detail.status === "CLOSED" ? t("重新打开会话后才能回复") : t("输入回复，Enter 发送，Shift + Enter 换行")} onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey) {
                      event.preventDefault();
                      void sendReply();
                    }
                  }} />
                  <Button onClick={() => void sendReply()} disabled={!canReply || !reply.trim() || replyBusy || detail.status === "CLOSED"}>
                    <PaperPlaneTilt weight="fill" />{replyBusy ? t("发送中") : t("发送回复")}
                  </Button>
                </footer>
              </>
            ) : null}
            {!detail && selectedSummary && !detailLoading ? <CoreLoading label="正在打开会话" /> : null}
          </article>
        </section>
      ) : (
        <section className="support-settings-panel">
          {settingsLoading ? <CoreLoading label="正在加载悬浮球设置" /> : null}
          {settingsError ? <CoreError message={settingsError} onRetry={() => void loadSettings()} /> : null}
          {!settingsLoading && settings ? (
            <>
              <div className="support-settings-intro">
                <div>
                  <Text size="1" color="gray">{t("客服悬浮球")}</Text>
                  <h2>{t("前台右下角入口")}</h2>
                  <p>{t("第一个客服球固定展示；另外两个入口可独立设置图片、链接和显隐。 ")}</p>
                </div>
                <div className="support-orb-preview" aria-label={t("悬浮球预览")}>
                  <span className="is-chat"><ChatCircleDots weight="fill" /></span>
                  {settings.customActions.map((action) => action.visible ? (
                    <span key={action.slot}>{action.imageUrl || action.externalImageUrl ? <img src={action.externalImageUrl || action.imageUrl} alt="" /> : <ImageSquare />}</span>
                  ) : null)}
                </div>
              </div>

              <label className="support-welcome-field">
                <span>{t("客服欢迎语")}</span>
                <TextArea value={settings.welcomeMessage} maxLength={500} onChange={(event) => {
                  setSettingsSaved(false);
                  setSettings({ ...settings, welcomeMessage: event.target.value });
                }} />
                <small>{t("客户首次打开对话框时会看到这段内容；AI 自动回复暂未启用。 ")}</small>
              </label>

              <div className="support-action-settings-grid">
                {settings.customActions.map((action) => (
                  <article className="support-action-settings-card" key={action.slot}>
                    <header>
                      <span>{action.imageUrl || action.externalImageUrl ? <img src={action.externalImageUrl || action.imageUrl} alt="" /> : <ImageSquare weight="duotone" />}</span>
                      <div><strong>{t("自定义悬浮球 {slot}", { slot: action.slot })}</strong><small>{action.visible ? t("前台已显示") : t("前台已隐藏")}</small></div>
                      <label className="support-visibility-switch">
                        <input type="checkbox" checked={action.visible} onChange={(event) => updateAction(action.slot, { visible: event.target.checked })} />
                        <i />
                      </label>
                    </header>
                    <label><span>{t("入口名称")}</span><input value={action.label || ""} maxLength={40} placeholder={t("例如：WhatsApp")} onChange={(event) => updateAction(action.slot, { label: event.target.value })} /></label>
                    <label><span>{t("点击跳转链接")}</span><input value={action.targetUrl || ""} maxLength={2_000} placeholder="https://" onChange={(event) => updateAction(action.slot, { targetUrl: event.target.value })} /></label>
                    <label><span>{t("外链图片（选填）")}</span><input value={action.externalImageUrl || ""} maxLength={2_000} placeholder="https://.../icon.png" onChange={(event) => updateAction(action.slot, { externalImageUrl: event.target.value })} /><small>{t("填写后优先使用外链图片；留空则使用已上传图片。 ")}</small></label>
                    <label className="support-image-upload">
                      <input type="file" accept="image/png,image/jpeg,image/webp" disabled={settingsBusy} onChange={(event) => void uploadImage(action.slot, event.target.files?.[0])} />
                      <ImageSquare />{action.hasUploadedImage ? t("替换已上传图片") : t("上传图片")}
                    </label>
                  </article>
                ))}
              </div>
              <div className="support-settings-actions">
                {settingsSaved ? <span><CheckCircle weight="fill" />{t("已保存并更新前台")}</span> : <span />}
                <Button size="3" onClick={() => void saveSettings()} disabled={settingsBusy}>{settingsBusy ? t("保存中") : t("保存设置")}</Button>
              </div>
            </>
          ) : null}
        </section>
      )}
    </div>
  );
}
