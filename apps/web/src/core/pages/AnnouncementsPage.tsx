import {
  AlertDialog,
  Badge,
  Button,
  Dialog,
  Heading,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowDown,
  ArrowUp,
  CalendarDots,
  Clock,
  ImageSquare,
  LinkSimple,
  ListBullets,
  Megaphone,
  NotePencil,
  Plus,
  TextAa,
  Trash,
  VideoCamera,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createAnnouncement,
  deleteAnnouncement,
  listAnnouncements,
  updateAnnouncement,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  AnnouncementBlockType,
  AnnouncementContentBlock,
  AnnouncementDisplayType,
  AnnouncementPayload,
  AnnouncementStatus,
  StorefrontAnnouncement,
} from "../types";
import "./AnnouncementsPage.css";


interface AnnouncementForm {
  title: string;
  displayType: AnnouncementDisplayType;
  tickerText: string;
  contentBlocks: AnnouncementContentBlock[];
  startsAt: string;
  endsAt: string;
  scheduleMode: "range" | "duration";
  durationDays: number;
  repeatIntervalHours: number;
  publicationStatus: AnnouncementStatus;
}

const blockLabels: Record<AnnouncementBlockType, string> = {
  heading: "小标题",
  paragraph: "正文",
  bullet_list: "项目列表",
  image: "图片",
  video: "视频",
  link: "链接",
};

const blockIcons = {
  heading: TextAa,
  paragraph: NotePencil,
  bullet_list: ListBullets,
  image: ImageSquare,
  video: VideoCamera,
  link: LinkSimple,
} satisfies Record<AnnouncementBlockType, typeof TextAa>;

function localInputValue(date: Date) {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return shifted.toISOString().slice(0, 16);
}

function defaultForm(): AnnouncementForm {
  const start = new Date();
  start.setSeconds(0, 0);
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  return {
    title: "",
    displayType: "TICKER",
    tickerText: "",
    contentBlocks: [],
    startsAt: localInputValue(start),
    endsAt: localInputValue(end),
    scheduleMode: "range",
    durationDays: 7,
    repeatIntervalHours: 24,
    publicationStatus: "DRAFT",
  };
}

function formFromAnnouncement(row: StorefrontAnnouncement): AnnouncementForm {
  return {
    title: row.title,
    displayType: row.displayType,
    tickerText: row.tickerText || "",
    contentBlocks: row.contentBlocks,
    startsAt: localInputValue(new Date(row.startsAt)),
    endsAt: localInputValue(new Date(row.endsAt)),
    scheduleMode: "range",
    durationDays: 7,
    repeatIntervalHours: row.repeatIntervalHours,
    publicationStatus: row.publicationStatus,
  };
}

function initialBlock(type: AnnouncementBlockType): AnnouncementContentBlock {
  if (type === "image") return { type, url: "", alt: "", caption: "" };
  if (type === "video") return { type, url: "", caption: "" };
  if (type === "link") return { type, text: "", url: "" };
  return { type, text: "" };
}

function statusLabel(status: AnnouncementStatus) {
  if (status === "PUBLISHED") return "已发布";
  if (status === "PAUSED") return "已暂停";
  return "草稿";
}

function statusColor(status: AnnouncementStatus) {
  if (status === "PUBLISHED") return "jade" as const;
  if (status === "PAUSED") return "amber" as const;
  return "gray" as const;
}

function scheduleState(row: StorefrontAnnouncement) {
  const now = Date.now();
  if (row.publicationStatus !== "PUBLISHED") return statusLabel(row.publicationStatus);
  if (new Date(row.startsAt).getTime() > now) return "等待开始";
  if (new Date(row.endsAt).getTime() <= now) return "已结束";
  return "展示中";
}

function formatDate(value: string, locale: string) {
  return new Intl.DateTimeFormat(locale, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function AnnouncementPreview({
  form,
  t,
}: {
  form: AnnouncementForm;
  t: (source: string) => string;
}) {
  if (form.displayType === "TICKER") {
    return (
      <div className="announcement-ticker-preview">
        <Megaphone size={17} weight="duotone" />
        <span>{form.tickerText || t("滚动字幕内容会显示在这里")}</span>
      </div>
    );
  }
  return (
    <div className="announcement-modal-preview">
      <Text size="1" color="gray">{t("弹窗预览")}</Text>
      <Heading size="5">{form.title || t("公告标题")}</Heading>
      <div className="announcement-preview-blocks">
        {form.contentBlocks.length === 0 ? (
          <Text size="2" color="gray">{t("添加正文、图片或视频内容")}</Text>
        ) : form.contentBlocks.map((block, index) => {
          if (block.type === "heading") return <h4 key={index}>{block.text || t("小标题")}</h4>;
          if (block.type === "paragraph") return <p key={index}>{block.text || t("正文内容")}</p>;
          if (block.type === "bullet_list") {
            return (
              <ul key={index}>
                {(block.text || t("列表内容")).split("\n").filter(Boolean).map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            );
          }
          if (block.type === "image") {
            return block.url ? (
              <figure key={index}>
                <img src={block.url} alt={block.alt || ""} />
                {block.caption ? <figcaption>{block.caption}</figcaption> : null}
              </figure>
            ) : <div className="announcement-media-placeholder" key={index}><ImageSquare />{t("图片")}</div>;
          }
          if (block.type === "video") {
            return block.url ? (
              <video key={index} src={block.url} controls preload="metadata" />
            ) : <div className="announcement-media-placeholder" key={index}><VideoCamera />{t("视频")}</div>;
          }
          return (
            <a key={index} href={block.url || "#"} onClick={(event) => event.preventDefault()}>
              {block.text || t("链接文字")}
            </a>
          );
        })}
      </div>
    </div>
  );
}

function RichBlockEditor({
  blocks,
  onChange,
  t,
}: {
  blocks: AnnouncementContentBlock[];
  onChange: (blocks: AnnouncementContentBlock[]) => void;
  t: (source: string) => string;
}) {
  const update = (index: number, changes: Partial<AnnouncementContentBlock>) => {
    onChange(blocks.map((block, position) => (
      position === index ? { ...block, ...changes } : block
    )));
  };
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= blocks.length) return;
    const next = [...blocks];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };
  return (
    <div className="announcement-block-editor">
      <div className="announcement-add-blocks">
        {(Object.keys(blockLabels) as AnnouncementBlockType[]).map((type) => {
          const Icon = blockIcons[type];
          return (
            <Button
              type="button"
              size="1"
              variant="soft"
              color="gray"
              onClick={() => onChange([...blocks, initialBlock(type)])}
              key={type}
            >
              <Icon size={15} />{t(blockLabels[type])}
            </Button>
          );
        })}
      </div>
      {blocks.map((block, index) => (
        <section className="announcement-block-row" key={`${block.type}-${index}`}>
          <div className="announcement-block-row-heading">
            <span>{index + 1}. {t(blockLabels[block.type])}</span>
            <div>
              <button type="button" aria-label={t("上移")} disabled={index === 0} onClick={() => move(index, -1)}><ArrowUp /></button>
              <button type="button" aria-label={t("下移")} disabled={index === blocks.length - 1} onClick={() => move(index, 1)}><ArrowDown /></button>
              <button type="button" aria-label={t("删除内容块")} onClick={() => onChange(blocks.filter((_, position) => position !== index))}><Trash /></button>
            </div>
          </div>
          {["heading", "paragraph", "bullet_list"].includes(block.type) ? (
            <TextArea
              value={block.text || ""}
              rows={block.type === "paragraph" ? 4 : block.type === "bullet_list" ? 4 : 2}
              placeholder={t(block.type === "bullet_list" ? "每行填写一项" : "输入内容")}
              onChange={(event) => update(index, { text: event.target.value })}
            />
          ) : null}
          {block.type === "link" ? (
            <div className="announcement-block-fields">
              <TextField.Root value={block.text || ""} placeholder={t("链接文字")} onChange={(event) => update(index, { text: event.target.value })} />
              <TextField.Root value={block.url || ""} type="url" placeholder="https://…" onChange={(event) => update(index, { url: event.target.value })} />
            </div>
          ) : null}
          {block.type === "image" || block.type === "video" ? (
            <div className="announcement-block-fields">
              <TextField.Root value={block.url || ""} type="url" placeholder={`${t(block.type === "image" ? "图片" : "视频")} URL（https://…）`} onChange={(event) => update(index, { url: event.target.value })} />
              {block.type === "image" ? (
                <TextField.Root value={block.alt || ""} placeholder={t("图片替代文字（建议填写）")} onChange={(event) => update(index, { alt: event.target.value })} />
              ) : null}
              <TextField.Root value={block.caption || ""} placeholder={t("说明文字（可选）")} onChange={(event) => update(index, { caption: event.target.value })} />
            </div>
          ) : null}
        </section>
      ))}
    </div>
  );
}

export function AnnouncementsPage() {
  const { locale, t } = useLocale();
  const [items, setItems] = useState<StorefrontAnnouncement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string>();
  const [form, setForm] = useState<AnnouncementForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");
  const [deleting, setDeleting] = useState<StorefrontAnnouncement>();
  const [deleteBusy, setDeleteBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await listAnnouncements();
      setItems(result.items);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("公告加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${t("公告管理")} | ${t("智贸云")}`;
    return () => {
      document.title = previousTitle;
    };
  }, [t]);

  const activeCount = useMemo(
    () => items.filter((item) => item.isActive).length,
    [items],
  );

  const openCreate = () => {
    setEditingId(undefined);
    setForm(defaultForm());
    setFormError("");
    setEditorOpen(true);
  };

  const openEdit = (row: StorefrontAnnouncement) => {
    setEditingId(row.id);
    setForm(formFromAnnouncement(row));
    setFormError("");
    setEditorOpen(true);
  };

  const save = async () => {
    if (!form.title.trim()) {
      setFormError(t("请填写公告标题。"));
      return;
    }
    if (form.displayType === "TICKER" && !form.tickerText.trim()) {
      setFormError(t("请填写滚动字幕内容。"));
      return;
    }
    if (form.displayType === "MODAL" && form.contentBlocks.length === 0) {
      setFormError(t("请至少添加一个弹窗内容块。"));
      return;
    }
    const startsAt = new Date(form.startsAt);
    if (!form.startsAt || Number.isNaN(startsAt.getTime())) {
      setFormError(t("请填写有效的开始时间。"));
      return;
    }
    let endsAt: Date | undefined;
    if (form.scheduleMode === "range") {
      endsAt = new Date(form.endsAt);
      if (!form.endsAt || Number.isNaN(endsAt.getTime()) || endsAt <= startsAt) {
        setFormError(t("结束时间必须晚于开始时间。"));
        return;
      }
    } else if (!Number.isInteger(form.durationDays) || form.durationDays < 1 || form.durationDays > 365) {
      setFormError(t("持续天数应为 1 到 365 天。"));
      return;
    }
    if (
      form.displayType === "MODAL"
      && (!Number.isInteger(form.repeatIntervalHours)
        || form.repeatIntervalHours < 1
        || form.repeatIntervalHours > 720)
    ) {
      setFormError(t("再次显示间隔应为 1 到 720 小时。"));
      return;
    }
    setSaving(true);
    setFormError("");
    try {
      const payload: AnnouncementPayload = {
        title: form.title.trim(),
        displayType: form.displayType,
        tickerText: form.displayType === "TICKER" ? form.tickerText.trim() : undefined,
        contentBlocks: form.displayType === "MODAL" ? form.contentBlocks : [],
        startsAt: startsAt.toISOString(),
        endsAt: form.scheduleMode === "range"
          ? endsAt?.toISOString()
          : undefined,
        durationDays: form.scheduleMode === "duration" ? form.durationDays : undefined,
        repeatIntervalHours: form.repeatIntervalHours,
        publicationStatus: form.publicationStatus,
      };
      const saved = editingId
        ? await updateAnnouncement(editingId, payload)
        : await createAnnouncement(payload);
      setItems((current) => editingId
        ? current.map((item) => item.id === saved.id ? saved : item)
        : [saved, ...current]);
      setEditorOpen(false);
    } catch (caught) {
      setFormError(caught instanceof Error ? caught.message : t("公告保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await deleteAnnouncement(deleting.id);
      setItems((current) => current.filter((item) => item.id !== deleting.id));
      setDeleting(undefined);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("公告删除失败"));
      setDeleting(undefined);
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div className="core-workspace announcements-page">
      <CorePageHeading
        eyebrow={t("商家前台")}
        title={t("公告管理")}
        description={t("按时间发布顶部滚动字幕或富内容弹窗，并控制访客再次看到弹窗的间隔。")}
        actions={(
          <Button onClick={openCreate}>
            <Plus size={17} />{t("新建公告")}
          </Button>
        )}
      />

      <div className="announcement-summary">
        <div><Megaphone size={22} weight="duotone" /><span><strong>{items.length}</strong><small>{t("全部公告")}</small></span></div>
        <div><CalendarDots size={22} weight="duotone" /><span><strong>{activeCount}</strong><small>{t("当前展示中")}</small></span></div>
        <div><Clock size={22} weight="duotone" /><span><strong>1–720h</strong><small>{t("弹窗再次提醒间隔")}</small></span></div>
      </div>

      {loading ? (
        <CoreLoading label={t("正在读取公告")} />
      ) : error && items.length === 0 ? (
        <CoreError message={error} onRetry={() => void load()} />
      ) : items.length === 0 ? (
        <CoreEmpty
          title={t("还没有公告")}
          description={t("创建一条定时公告，让访客在商品前台及时看到新品、放假或交易提示。")}
          action={<Button onClick={openCreate}><Plus />{t("创建第一条公告")}</Button>}
        />
      ) : (
        <div className="announcement-list">
          {error ? <div className="announcement-inline-error">{error}</div> : null}
          {items.map((row) => (
            <article className="announcement-list-card" key={row.id}>
              <div className={`announcement-type-icon is-${row.displayType.toLowerCase()}`}>
                {row.displayType === "TICKER" ? <Megaphone weight="duotone" /> : <NotePencil weight="duotone" />}
              </div>
              <div className="announcement-list-content">
                <div className="announcement-list-title">
                  <Heading size="4">{row.title}</Heading>
                  <Badge color={statusColor(row.publicationStatus)} variant="soft">
                    {t(scheduleState(row))}
                  </Badge>
                  <Badge color="gray" variant="outline">
                    {t(row.displayType === "TICKER" ? "滚动字幕" : "富内容弹窗")}
                  </Badge>
                </div>
                <Text size="2" color="gray">
                  {row.displayType === "TICKER"
                    ? row.tickerText
                    : t("{count} 个内容块 · 每 {hours} 小时最多显示一次", {
                        count: row.contentBlocks.length,
                        hours: row.repeatIntervalHours,
                      })}
                </Text>
                <div className="announcement-schedule">
                  <CalendarDots size={15} />
                  <span>{formatDate(row.startsAt, locale)} — {formatDate(row.endsAt, locale)}</span>
                </div>
              </div>
              <div className="announcement-list-actions">
                <Button size="1" variant="soft" color="gray" onClick={() => openEdit(row)}>
                  <NotePencil />{t("编辑")}
                </Button>
                <Button size="1" variant="ghost" color="red" onClick={() => setDeleting(row)}>
                  <Trash />{t("删除")}
                </Button>
              </div>
            </article>
          ))}
        </div>
      )}

      <Dialog.Root open={editorOpen} onOpenChange={(open) => !saving && setEditorOpen(open)}>
        <Dialog.Content className="announcement-editor-dialog">
          <div className="announcement-editor-heading">
            <div>
              <Text size="1" color="gray">{editingId ? t("编辑公告") : t("新建公告")}</Text>
              <Dialog.Title>{form.title || t("未命名公告")}</Dialog.Title>
            </div>
            <Badge variant="soft" color={form.publicationStatus === "PUBLISHED" ? "jade" : "gray"}>
              {t(statusLabel(form.publicationStatus))}
            </Badge>
          </div>

          <div className="announcement-editor-grid">
            <div className="announcement-form-column">
              <label className="announcement-field">
                <span>{t("公告标题")}</span>
                <TextField.Root value={form.title} maxLength={200} placeholder={t("例如：国庆假期发货安排")} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} />
              </label>

              <div className="announcement-field">
                <span>{t("展示方式")}</span>
                <div className="announcement-segmented">
                  <button type="button" className={form.displayType === "TICKER" ? "is-active" : ""} onClick={() => setForm((current) => ({ ...current, displayType: "TICKER", contentBlocks: [] }))}>
                    <Megaphone />{t("顶部滚动字幕")}
                  </button>
                  <button type="button" className={form.displayType === "MODAL" ? "is-active" : ""} onClick={() => setForm((current) => ({ ...current, displayType: "MODAL", tickerText: "", contentBlocks: current.contentBlocks.length ? current.contentBlocks : [initialBlock("paragraph")] }))}>
                    <NotePencil />{t("富内容弹窗")}
                  </button>
                </div>
              </div>

              {form.displayType === "TICKER" ? (
                <label className="announcement-field">
                  <span>{t("字幕内容")}<small>{t("仅支持纯文本")}</small></span>
                  <TextArea value={form.tickerText} maxLength={2000} rows={4} placeholder={t("输入需要在商品前台顶部滚动展示的内容")} onChange={(event) => setForm((current) => ({ ...current, tickerText: event.target.value }))} />
                </label>
              ) : (
                <div className="announcement-field">
                  <span>{t("弹窗内容")}<small>{t("按内容块安全组合文字、图片、视频与链接")}</small></span>
                  <RichBlockEditor blocks={form.contentBlocks} t={t} onChange={(contentBlocks) => setForm((current) => ({ ...current, contentBlocks }))} />
                </div>
              )}

              <div className="announcement-form-section">
                <div className="announcement-form-section-title">
                  <CalendarDots />
                  <span><strong>{t("展示时间")}</strong><small>{t("按访客所在时刻自动开始和结束")}</small></span>
                </div>
                <div className="announcement-two-fields">
                  <label className="announcement-field">
                    <span>{t("开始时间")}</span>
                    <input type="datetime-local" value={form.startsAt} onChange={(event) => setForm((current) => ({ ...current, startsAt: event.target.value }))} />
                  </label>
                  <label className="announcement-field">
                    <span>{t("结束方式")}</span>
                    <select value={form.scheduleMode} onChange={(event) => setForm((current) => ({ ...current, scheduleMode: event.target.value as "range" | "duration" }))}>
                      <option value="range">{t("指定结束日期")}</option>
                      <option value="duration">{t("持续若干天")}</option>
                    </select>
                  </label>
                  {form.scheduleMode === "range" ? (
                    <label className="announcement-field">
                      <span>{t("结束时间")}</span>
                      <input type="datetime-local" value={form.endsAt} onChange={(event) => setForm((current) => ({ ...current, endsAt: event.target.value }))} />
                    </label>
                  ) : (
                    <label className="announcement-field">
                      <span>{t("持续天数")}</span>
                      <input type="number" min={1} max={365} value={form.durationDays} onChange={(event) => setForm((current) => ({ ...current, durationDays: Number(event.target.value) }))} />
                    </label>
                  )}
                </div>
              </div>

              <div className="announcement-two-fields">
                <label className="announcement-field">
                  <span>{t("发布状态")}</span>
                  <select value={form.publicationStatus} onChange={(event) => setForm((current) => ({ ...current, publicationStatus: event.target.value as AnnouncementStatus }))}>
                    <option value="DRAFT">{t("保存为草稿")}</option>
                    <option value="PUBLISHED">{t("按计划发布")}</option>
                    <option value="PAUSED">{t("暂停展示")}</option>
                  </select>
                </label>
                {form.displayType === "MODAL" ? (
                  <label className="announcement-field">
                    <span>{t("再次显示间隔（小时）")}</span>
                    <input type="number" min={1} max={720} value={form.repeatIntervalHours} onChange={(event) => setForm((current) => ({ ...current, repeatIntervalHours: Number(event.target.value) }))} />
                  </label>
                ) : <div />}
              </div>
            </div>

            <aside className="announcement-preview-column">
              <div className="announcement-preview-sticky">
                <Text size="1" color="gray">{t("前台效果预览")}</Text>
                <AnnouncementPreview form={form} t={t} />
                <div className="announcement-preview-note">
                  <Clock size={17} />
                  <Text size="1" color="gray">
                    {form.displayType === "MODAL"
                      ? t("同一浏览器看过后，至少间隔 {hours} 小时才会再次出现。", { hours: form.repeatIntervalHours })
                      : t("滚动字幕在公告有效期内持续显示，不使用富文本。")}
                  </Text>
                </div>
              </div>
            </aside>
          </div>

          {formError ? <div className="announcement-form-error" role="alert">{formError}</div> : null}
          <div className="announcement-editor-actions">
            <Dialog.Close><Button variant="soft" color="gray" disabled={saving}>{t("取消")}</Button></Dialog.Close>
            <Button loading={saving} onClick={() => void save()}>{t(saving ? "正在保存" : "保存公告")}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={Boolean(deleting)} onOpenChange={(open) => !open && !deleteBusy && setDeleting(undefined)}>
        <AlertDialog.Content maxWidth="440px">
          <AlertDialog.Title>{t("删除公告")}</AlertDialog.Title>
          <AlertDialog.Description>
            {t("删除“{name}”后，商品前台会停止展示，且无法恢复。", { name: deleting?.title || "" })}
          </AlertDialog.Description>
          <div className="core-dialog-actions">
            <AlertDialog.Cancel><Button variant="soft" color="gray" disabled={deleteBusy}>{t("取消")}</Button></AlertDialog.Cancel>
            <Button color="red" loading={deleteBusy} onClick={() => void remove()}>{t("确认删除")}</Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
