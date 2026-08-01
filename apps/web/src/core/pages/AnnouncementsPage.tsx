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
  CheckCircle,
  Clock,
  ImageSquare,
  LinkSimple,
  ListBullets,
  MagnifyingGlass,
  Megaphone,
  NotePencil,
  Package,
  Plus,
  TextAa,
  Trash,
  VideoCamera,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createAnnouncement,
  deleteAnnouncement,
  listAnnouncements,
  listSkus,
  updateAnnouncement,
} from "../api";
import {
  DEFAULT_ANNOUNCEMENT_TICKER_SPEED,
  MAX_ANNOUNCEMENT_TICKER_SPEED,
  MIN_ANNOUNCEMENT_TICKER_SPEED,
  normalizeAnnouncementTickerSpeed,
} from "../announcementSpeed";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  AnnouncementBlockType,
  AnnouncementContentBlock,
  AnnouncementDisplayType,
  AnnouncementPayload,
  AnnouncementRelatedSku,
  AnnouncementStatus,
  SkuListItem,
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
  tickerSpeedPxPerSecond: number;
  publicationStatus: AnnouncementStatus;
  relatedSkus: AnnouncementRelatedSku[];
}

type Translate = (
  source: string,
  values?: Record<string, string | number>,
) => string;

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
    tickerSpeedPxPerSecond: DEFAULT_ANNOUNCEMENT_TICKER_SPEED,
    publicationStatus: "PUBLISHED",
    relatedSkus: [],
  };
}

function formFromAnnouncement(row: StorefrontAnnouncement): AnnouncementForm {
  return {
    title: row.title || "",
    displayType: row.displayType,
    tickerText: row.tickerText || "",
    contentBlocks: row.contentBlocks,
    startsAt: localInputValue(new Date(row.startsAt)),
    endsAt: localInputValue(new Date(row.endsAt)),
    scheduleMode: "range",
    durationDays: 7,
    tickerSpeedPxPerSecond: normalizeAnnouncementTickerSpeed(
      row.tickerSpeedPxPerSecond,
    ),
    publicationStatus: row.publicationStatus,
    relatedSkus: row.relatedSkus || [],
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

function isSafeWebUrl(value: string | undefined) {
  if (!value?.trim()) return false;
  try {
    const parsed = new URL(value.trim());
    return ["http:", "https:"].includes(parsed.protocol)
      && Boolean(parsed.hostname)
      && !parsed.username
      && !parsed.password;
  } catch {
    return false;
  }
}

function contentBlockError(
  block: AnnouncementContentBlock,
  index: number,
  t: Translate,
) {
  const position = index + 1;
  const label = t(blockLabels[block.type]);
  if (["heading", "paragraph", "bullet_list"].includes(block.type) && !block.text?.trim()) {
    return t("请填写第 {index} 个“{type}”内容。", { index: position, type: label });
  }
  if (block.type === "link" && !block.text?.trim()) {
    return t("请填写第 {index} 个链接的显示文字。", { index: position });
  }
  if (["link", "image", "video"].includes(block.type) && !block.url?.trim()) {
    return t("请填写第 {index} 个“{type}”的网址。", { index: position, type: label });
  }
  if (block.url && !isSafeWebUrl(block.url)) {
    return t("第 {index} 个“{type}”的网址无效，请使用 http:// 或 https://。", {
      index: position,
      type: label,
    });
  }
  return "";
}

function AnnouncementPreview({
  form,
  t,
}: {
  form: AnnouncementForm;
  t: Translate;
}) {
  if (form.displayType === "TICKER") {
    const previewDuration = Math.max(
      5,
      720 / normalizeAnnouncementTickerSpeed(form.tickerSpeedPxPerSecond),
    );
    return (
      <div className="announcement-ticker-preview">
        <Megaphone size={17} weight="duotone" />
        <div>
          <span style={{ animationDuration: `${previewDuration}s` }}>
            {form.tickerText || t("滚动字幕内容会显示在这里")}
          </span>
        </div>
      </div>
    );
  }
  return (
    <div className="announcement-modal-preview">
      <Text size="1" color="gray">{t("弹窗预览")}</Text>
      {form.title.trim() ? <Heading size="5">{form.title}</Heading> : null}
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

function relatedSkuFromListItem(row: SkuListItem): AnnouncementRelatedSku {
  return {
    id: row.id,
    productId: row.productId,
    skuCode: row.skuCode,
    name: row.name || row.productName,
    productName: row.productName,
    isPublic: row.status === "ACTIVE" && row.publicOfferStatus === "PUBLISHED",
  };
}

function RelatedSkuPicker({
  selected,
  onChange,
  t,
}: {
  selected: AnnouncementRelatedSku[];
  onChange: (rows: AnnouncementRelatedSku[]) => void;
  t: Translate;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SkuListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    const timeout = window.setTimeout(async () => {
      setLoading(true);
      setError("");
      try {
        const page = await listSkus({
          q: query.trim() || undefined,
          statuses: ["ACTIVE"],
          page: 1,
          pageSize: 12,
        });
        if (!cancelled) setResults(page.items);
      } catch (caught) {
        if (!cancelled) {
          setResults([]);
          setError(caught instanceof Error ? caught.message : t("SKU 加载失败"));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 240);
    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [query, t]);

  const selectedIds = new Set(selected.map((row) => row.id));
  const available = results.filter((row) => !selectedIds.has(row.id));

  return (
    <div className="announcement-sku-picker">
      {selected.length ? (
        <div className="announcement-selected-skus" aria-label={t("已关联 SKU")}>
          {selected.map((sku) => (
            <div className="announcement-selected-sku" key={sku.id}>
              <Package weight="duotone" />
              <span>
                <strong>{sku.productName}</strong>
                <small>{sku.skuCode}{sku.name !== sku.productName ? ` · ${sku.name}` : ""}</small>
              </span>
              {!sku.isPublic ? <Badge color="amber" variant="soft">{t("未上架")}</Badge> : null}
              <button
                type="button"
                aria-label={t("取消关联 {sku}", { sku: sku.skuCode })}
                onClick={() => onChange(selected.filter((row) => row.id !== sku.id))}
              >
                <X />
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {selected.length < 20 ? (
        <div className="announcement-sku-search">
          <TextField.Root
            value={query}
            placeholder={t("搜索 SKU 编号、SKU 名称或商品名")}
            onChange={(event) => setQuery(event.target.value)}
          >
            <TextField.Slot><MagnifyingGlass /></TextField.Slot>
          </TextField.Root>
          <div className="announcement-sku-results" aria-live="polite">
            {loading ? <Text size="1" color="gray">{t("正在搜索 SKU…")}</Text> : null}
            {!loading && error ? <Text size="1" color="red">{error}</Text> : null}
            {!loading && !error && available.length === 0 ? (
              <Text size="1" color="gray">{t(query.trim() ? "没有找到可关联的 SKU" : "暂无可关联 SKU")}</Text>
            ) : null}
            {!loading && !error ? available.map((row) => (
              <button
                type="button"
                className="announcement-sku-result"
                key={row.id}
                onClick={() => onChange([...selected, relatedSkuFromListItem(row)])}
              >
                <span>
                  <strong>{row.productName}</strong>
                  <small>{row.skuCode}{row.name !== row.productName ? ` · ${row.name}` : ""}</small>
                </span>
                <Badge color={row.publicOfferStatus === "PUBLISHED" ? "jade" : "amber"} variant="soft">
                  {t(row.publicOfferStatus === "PUBLISHED" ? "已上架" : "未上架")}
                </Badge>
              </button>
            )) : null}
          </div>
        </div>
      ) : <Text size="1" color="gray">{t("每条公告最多关联 20 个 SKU。")}</Text>}
    </div>
  );
}

function RichBlockEditor({
  blocks,
  onChange,
  t,
  invalidIndex,
}: {
  blocks: AnnouncementContentBlock[];
  onChange: (blocks: AnnouncementContentBlock[]) => void;
  t: Translate;
  invalidIndex?: number;
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
        <section
          className={`announcement-block-row${invalidIndex === index ? " is-invalid" : ""}`}
          data-announcement-block-index={index}
          key={`${block.type}-${index}`}
        >
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
  const [invalidBlockIndex, setInvalidBlockIndex] = useState<number>();
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
  const formTickerSpeed = normalizeAnnouncementTickerSpeed(
    form.tickerSpeedPxPerSecond,
  );

  const openCreate = () => {
    setEditingId(undefined);
    setForm(defaultForm());
    setFormError("");
    setInvalidBlockIndex(undefined);
    setEditorOpen(true);
  };

  const openEdit = (row: StorefrontAnnouncement) => {
    setEditingId(row.id);
    setForm(formFromAnnouncement(row));
    setFormError("");
    setInvalidBlockIndex(undefined);
    setEditorOpen(true);
  };

  const save = async () => {
    setInvalidBlockIndex(undefined);
    if (form.displayType === "TICKER" && !form.tickerText.trim()) {
      setFormError(t("请填写滚动字幕内容。"));
      return;
    }
    if (form.displayType === "MODAL" && form.contentBlocks.length === 0) {
      setFormError(t("请至少添加一个弹窗内容块。"));
      return;
    }
    if (form.displayType === "MODAL") {
      const invalidIndex = form.contentBlocks.findIndex((block, index) => (
        Boolean(contentBlockError(block, index, t))
      ));
      if (invalidIndex >= 0) {
        setInvalidBlockIndex(invalidIndex);
        setFormError(contentBlockError(form.contentBlocks[invalidIndex], invalidIndex, t));
        window.requestAnimationFrame(() => {
          document.querySelector<HTMLElement>(
            `[data-announcement-block-index="${invalidIndex}"]`,
          )?.scrollIntoView({ behavior: "smooth", block: "center" });
        });
        return;
      }
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
    const tickerSpeedPxPerSecond = normalizeAnnouncementTickerSpeed(
      form.tickerSpeedPxPerSecond,
    );
    setSaving(true);
    setFormError("");
    try {
      const payload: AnnouncementPayload = {
        title: form.title.trim() || undefined,
        displayType: form.displayType,
        tickerText: form.displayType === "TICKER" ? form.tickerText.trim() : undefined,
        contentBlocks: form.displayType === "MODAL" ? form.contentBlocks : [],
        startsAt: startsAt.toISOString(),
        endsAt: form.scheduleMode === "range"
          ? endsAt?.toISOString()
          : undefined,
        durationDays: form.scheduleMode === "duration" ? form.durationDays : undefined,
        tickerSpeedPxPerSecond,
        publicationStatus: form.publicationStatus,
        relatedSkuIds: form.relatedSkus.map((sku) => sku.id),
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
        description={t("按时间发布顶部滚动字幕或富内容弹窗；进入有效期后立即生效，访客可在本次访问中关闭。")}
        actions={(
          <Button onClick={openCreate}>
            <Plus size={17} />{t("新建公告")}
          </Button>
        )}
      />

      <div className="announcement-summary">
        <div><Megaphone size={22} weight="duotone" /><span><strong>{items.length}</strong><small>{t("全部公告")}</small></span></div>
        <div><CalendarDots size={22} weight="duotone" /><span><strong>{activeCount}</strong><small>{t("当前展示中")}</small></span></div>
        <div><Clock size={22} weight="duotone" /><span><strong>{t("本次访问")}</strong><small>{t("关闭后不再显示")}</small></span></div>
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
                  <Heading size="4">{row.title || row.tickerText || t("富内容公告")}</Heading>
                  <Badge color={statusColor(row.publicationStatus)} variant="soft">
                    {t(scheduleState(row))}
                  </Badge>
                  <Badge color="gray" variant="outline">
                    {t(row.displayType === "TICKER" ? "滚动字幕" : "富内容弹窗")}
                  </Badge>
                </div>
                <Text size="2" color="gray">
                  {row.displayType === "TICKER"
                    ? t("{text} · 滚动速度 {speed} px/s", {
                        text: row.tickerText || "",
                        speed: normalizeAnnouncementTickerSpeed(
                          row.tickerSpeedPxPerSecond,
                        ),
                      })
                    : t("{count} 个内容块 · 本次访问可选择不再显示", {
                        count: row.contentBlocks.length,
                      })}
                </Text>
                {row.relatedSkus.length ? (
                  <div className="announcement-related-summary">
                    <Package size={14} />
                    <span>{t("关联 {count} 个 SKU", { count: row.relatedSkus.length })}</span>
                  </div>
                ) : null}
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
                <span>{t("公告标题")}<small>{t("选填")}</small></span>
                <TextField.Root value={form.title} maxLength={200} placeholder={t("例如：国庆假期发货安排（选填）")} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} />
              </label>

              <div className="announcement-field">
                <span>{t("展示方式")}<small>{t("当前：{mode}", { mode: t(form.displayType === "TICKER" ? "顶部滚动字幕" : "富内容弹窗") })}</small></span>
                <div className="announcement-segmented">
                  <button
                    type="button"
                    aria-pressed={form.displayType === "TICKER"}
                    className={form.displayType === "TICKER" ? "is-active" : ""}
                    onClick={() => {
                      setForm((current) => ({ ...current, displayType: "TICKER" }));
                      setFormError("");
                      setInvalidBlockIndex(undefined);
                    }}
                  >
                    <span className="announcement-mode-icon"><Megaphone /></span>
                    <span><strong>{t("顶部滚动字幕")}</strong><small>{t("前台顶部持续滚动，可由访客关闭")}</small></span>
                    <CheckCircle className="announcement-mode-check" weight="fill" />
                  </button>
                  <button
                    type="button"
                    aria-pressed={form.displayType === "MODAL"}
                    className={form.displayType === "MODAL" ? "is-active" : ""}
                    onClick={() => {
                      setForm((current) => ({
                        ...current,
                        displayType: "MODAL",
                        contentBlocks: current.contentBlocks.length
                          ? current.contentBlocks
                          : [initialBlock("paragraph")],
                      }));
                      setFormError("");
                    }}
                  >
                    <span className="announcement-mode-icon"><NotePencil /></span>
                    <span><strong>{t("富内容弹窗")}</strong><small>{t("支持文字、图片、视频与商品关联")}</small></span>
                    <CheckCircle className="announcement-mode-check" weight="fill" />
                  </button>
                </div>
              </div>

              {form.displayType === "TICKER" ? (
                <div className="announcement-ticker-fields">
                  <label className="announcement-field">
                    <span>{t("字幕内容")}<small>{t("仅支持纯文本")}</small></span>
                    <TextArea value={form.tickerText} maxLength={2000} rows={4} placeholder={t("输入需要在商品前台顶部滚动展示的内容")} onChange={(event) => setForm((current) => ({ ...current, tickerText: event.target.value }))} />
                  </label>
                  <label className="announcement-field announcement-speed-field">
                    <span>
                      {t("滚动速度")}
                      <small>{t("{speed} 像素/秒", { speed: formTickerSpeed })}</small>
                    </span>
                    <input
                      type="range"
                      min={MIN_ANNOUNCEMENT_TICKER_SPEED}
                      max={MAX_ANNOUNCEMENT_TICKER_SPEED}
                      step={5}
                      value={formTickerSpeed}
                      onChange={(event) => setForm((current) => ({
                        ...current,
                        tickerSpeedPxPerSecond: Number(event.target.value),
                      }))}
                    />
                    <span className="announcement-speed-scale" aria-hidden="true">
                      <small>{t("慢")}</small>
                      <small>{t("快")}</small>
                    </span>
                  </label>
                </div>
              ) : (
                <div className="announcement-field">
                  <span>{t("弹窗内容")}<small>{t("按内容块安全组合文字、图片、视频与链接")}</small></span>
                  <RichBlockEditor
                    blocks={form.contentBlocks}
                    t={t}
                    invalidIndex={invalidBlockIndex}
                    onChange={(contentBlocks) => {
                      setForm((current) => ({ ...current, contentBlocks }));
                      setFormError("");
                      setInvalidBlockIndex(undefined);
                    }}
                  />
                </div>
              )}

              <div className="announcement-form-section">
                <div className="announcement-form-section-title">
                  <Package />
                  <span>
                    <strong>{t("关联商品 SKU")}</strong>
                    <small>{t("选填；前台访客可从公告直接进入商品详情")}</small>
                  </span>
                </div>
                <RelatedSkuPicker
                  selected={form.relatedSkus}
                  t={t}
                  onChange={(relatedSkus) => setForm((current) => ({ ...current, relatedSkus }))}
                />
              </div>

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

              <div className="announcement-publication-fields">
                <label className="announcement-field">
                  <span>{t("发布状态")}</span>
                  <select value={form.publicationStatus} onChange={(event) => setForm((current) => ({ ...current, publicationStatus: event.target.value as AnnouncementStatus }))}>
                    <option value="DRAFT">{t("保存为草稿")}</option>
                    <option value="PUBLISHED">{t("按计划发布")}</option>
                    <option value="PAUSED">{t("暂停展示")}</option>
                  </select>
                </label>
              </div>

              <div className={`announcement-publication-state is-${form.publicationStatus.toLowerCase()}`}>
                {form.publicationStatus === "PUBLISHED" ? <CheckCircle weight="fill" /> : <Clock weight="duotone" />}
                <span>
                  <strong>{t(statusLabel(form.publicationStatus))}</strong>
                  <small>
                    {t(form.publicationStatus === "PUBLISHED"
                      ? "保存后将在设定时间内展示到商家前台。"
                      : form.publicationStatus === "PAUSED"
                        ? "该公告保存后不会在商家前台展示。"
                        : "草稿仅保存在后台，不会在商家前台展示。")}
                  </small>
                </span>
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
                      ? t("访客可选择“以后不显示”；本次访问中翻页不会再次弹出，完整刷新或开始新会话后恢复。")
                      : t("访客关闭后，本次访问中翻页不会再次显示；完整刷新或开始新会话后恢复。")}
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
            {t("删除“{name}”后，商品前台会停止展示，且无法恢复。", { name: deleting?.title || deleting?.tickerText || t("未命名公告") })}
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
