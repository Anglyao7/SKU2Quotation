import {
  AlertDialog,
  Badge,
  Button,
  Dialog,
  Switch,
  Text,
} from "@radix-ui/themes";
import {
  ArrowDown,
  ArrowSquareOut,
  ArrowUp,
  CheckCircle,
  Code,
  CurrencyDollar,
  FileCode,
  PencilSimple,
  Plus,
  Storefront,
  Trash,
  UploadSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  createStorefrontCustomPage,
  deleteStorefrontCustomPage,
  getMerchantSettings,
  listStorefrontCustomPages,
  replaceStorefrontCustomPageHtml,
  updateStorefrontCustomPage,
  updateMerchantSettings,
} from "../api";
import { CoreError, CoreLoading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type {
  MerchantSettings,
  StorefrontCustomPage,
} from "../types";


const MAX_HTML_BYTES = 2 * 1024 * 1024;
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function suggestedSlug(value: string) {
  return value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

function fileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validHtmlFile(file: File | undefined) {
  if (!file) return "请选择一个 HTML 文件。";
  if (!file.name.toLowerCase().endsWith(".html")) return "这里只接受 .html 文件。";
  if (file.size <= 0) return "HTML 文件不能为空。";
  if (file.size > MAX_HTML_BYTES) return "HTML 文件不能超过 2 MB。";
  return "";
}

function ResponsiveHtmlGuide({ compact = false }: { compact?: boolean }) {
  const { t } = useLocale();
  return (
    <aside className={`storefront-html-guide${compact ? " is-compact" : ""}`}>
      <div className="storefront-html-guide-heading">
        <Code weight="duotone" />
        <div>
          <strong>{t("HTML 页面必须支持响应式布局")}</strong>
          <span>{t("客户主要通过手机访问，请在上传前同时检查三种宽度。")}</span>
        </div>
      </div>
      <div className="storefront-html-device-grid">
        <div><b>{t("手机")}</b><span>≤ 767 px</span></div>
        <div><b>{t("平板")}</b><span>768–1199 px</span></div>
        <div><b>{t("桌面")}</b><span>≥ 1200 px</span></div>
      </div>
      <ul>
        <li>{t("加入响应式 viewport 声明")}：<code>&lt;meta name=&quot;viewport&quot; content=&quot;width=device-width, initial-scale=1&quot;&gt;</code></li>
        <li>{t("避免固定页面宽度；图片和视频请使用 max-width: 100%")}</li>
        <li>{t("按钮和链接需适合触屏，正文不要依赖鼠标悬停才能查看")}</li>
      </ul>
    </aside>
  );
}

export function StorefrontCustomPagesSettings() {
  const { t } = useLocale();
  const { notify } = useToast();
  const [merchant, setMerchant] = useState<MerchantSettings>();
  const [pages, setPages] = useState<StorefrontCustomPage[]>([]);
  const [maxPages, setMaxPages] = useState(12);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busyId, setBusyId] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [htmlFile, setHtmlFile] = useState<File>();
  const [editTarget, setEditTarget] = useState<StorefrontCustomPage>();
  const [editTitle, setEditTitle] = useState("");
  const [editSlug, setEditSlug] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<StorefrontCustomPage>();
  const createFileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const [settings, result] = await Promise.all([
        getMerchantSettings(),
        listStorefrontCustomPages(),
      ]);
      setMerchant(settings);
      setPages(result.items);
      setMaxPages(result.maxPages);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : t("前台导航页面加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const routePrefix = merchant ? `/${merchant.slug}/pages/` : "/pages/";
  const canCreate = pages.length < maxPages;
  const orderedPages = useMemo(
    () => [...pages].sort((left, right) => (
      left.sortOrder - right.sortOrder || left.createdAt.localeCompare(right.createdAt)
    )),
    [pages],
  );

  const resetCreate = () => {
    setTitle("");
    setSlug("");
    setSlugTouched(false);
    setHtmlFile(undefined);
    if (createFileRef.current) createFileRef.current.value = "";
  };

  const create = async () => {
    const normalizedTitle = title.trim();
    const normalizedSlug = slug.trim().toLowerCase();
    const fileError = validHtmlFile(htmlFile);
    if (!normalizedTitle) {
      notify(t("请填写顶部导航名称。"), { kind: "error" });
      return;
    }
    if (!SLUG_PATTERN.test(normalizedSlug)) {
      notify(t("路由只可使用小写英文字母、数字和连字符。"), { kind: "error" });
      return;
    }
    if (fileError) {
      notify(t(fileError), { kind: "error" });
      return;
    }
    setBusyId("create");
    try {
      const created = await createStorefrontCustomPage({
        title: normalizedTitle,
        slug: normalizedSlug,
        htmlFile: htmlFile!,
      });
      setPages((current) => [...current, created]);
      setCreateOpen(false);
      resetCreate();
      notify(t("自定义页面已上传并加入顶部导航"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("自定义页面上传失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const toggle = async (page: StorefrontCustomPage) => {
    setBusyId(page.id);
    try {
      const updated = await updateStorefrontCustomPage(page, { enabled: !page.enabled });
      setPages((current) => current.map((item) => item.id === page.id ? updated : item));
      notify(t(updated.enabled ? "页面已显示在顶部导航" : "页面已从顶部导航隐藏"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("页面状态更新失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const toggleCatalogExchangeRates = async () => {
    if (!merchant) return;
    setBusyId("catalog-exchange-rates");
    try {
      const updated = await updateMerchantSettings({
        exchangeRatesEnabled: !merchant.exchangeRatesEnabled,
      });
      setMerchant(updated);
      notify(t(updated.exchangeRatesEnabled ? "商品首页已显示实时汇率" : "商品首页已隐藏实时汇率"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("商品首页组件设置保存失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const togglePageExchangeRates = async (page: StorefrontCustomPage) => {
    setBusyId(page.id);
    try {
      const updated = await updateStorefrontCustomPage(page, {
        exchangeRatesEnabled: !page.exchangeRatesEnabled,
      });
      setPages((current) => current.map((item) => item.id === page.id ? updated : item));
      notify(t(updated.exchangeRatesEnabled ? "此路由已显示实时汇率" : "此路由已隐藏实时汇率"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("页面组件设置保存失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const move = async (index: number, direction: -1 | 1) => {
    const nextIndex = index + direction;
    const page = orderedPages[index];
    const neighbor = orderedPages[nextIndex];
    if (!page || !neighbor) return;
    setBusyId(page.id);
    try {
      const [updatedPage, updatedNeighbor] = await Promise.all([
        updateStorefrontCustomPage(page, { sortOrder: neighbor.sortOrder }),
        updateStorefrontCustomPage(neighbor, { sortOrder: page.sortOrder }),
      ]);
      setPages((current) => current.map((item) => {
        if (item.id === updatedPage.id) return updatedPage;
        if (item.id === updatedNeighbor.id) return updatedNeighbor;
        return item;
      }));
      notify(t("导航顺序已更新"), { kind: "success" });
    } catch (caught) {
      await load();
      notify(caught instanceof Error ? caught.message : t("导航顺序更新失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const startEdit = (page: StorefrontCustomPage) => {
    setEditTarget(page);
    setEditTitle(page.title);
    setEditSlug(page.slug);
  };

  const saveEdit = async () => {
    if (!editTarget) return;
    const normalizedTitle = editTitle.trim();
    const normalizedSlug = editSlug.trim().toLowerCase();
    if (!normalizedTitle || !SLUG_PATTERN.test(normalizedSlug)) {
      notify(t("请填写导航名称，并使用有效的英文路由。"), { kind: "error" });
      return;
    }
    setBusyId(editTarget.id);
    try {
      const updated = await updateStorefrontCustomPage(editTarget, {
        title: normalizedTitle,
        slug: normalizedSlug,
      });
      setPages((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditTarget(undefined);
      notify(t("页面名称和路由已更新"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("页面设置保存失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const replaceHtml = async (page: StorefrontCustomPage, file: File | undefined) => {
    const error = validHtmlFile(file);
    if (error) {
      notify(t(error), { kind: "error" });
      return;
    }
    setBusyId(page.id);
    try {
      const updated = await replaceStorefrontCustomPageHtml(page, file!);
      setPages((current) => current.map((item) => item.id === updated.id ? updated : item));
      notify(t("HTML 页面内容已替换"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("HTML 页面替换失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  const remove = async () => {
    if (!deleteTarget) return;
    setBusyId(deleteTarget.id);
    try {
      await deleteStorefrontCustomPage(deleteTarget.id);
      setPages((current) => current.filter((item) => item.id !== deleteTarget.id));
      setDeleteTarget(undefined);
      notify(t("自定义页面及其导航入口已删除"), { kind: "success" });
    } catch (caught) {
      notify(caught instanceof Error ? caught.message : t("自定义页面删除失败"), { kind: "error" });
    } finally {
      setBusyId("");
    }
  };

  return (
    <section className="storefront-custom-pages" aria-labelledby="storefront-custom-pages-title">
      <div className="storefront-pages-intro">
        <div>
          <Text size="1" color="gray">{t("顶部导航")}</Text>
          <h2 id="storefront-custom-pages-title">{t("自定义导航与 HTML 页面")}</h2>
          <p>{t("商品区始终是第一个入口；你可以上传独立 HTML 页面，并为每个路由单独控制实时汇率等页面组件。")}</p>
        </div>
        <Button
          size="3"
          disabled={!canCreate || loading}
          onClick={() => setCreateOpen(true)}
        >
          <Plus />{t("新增导航页面")}
        </Button>
      </div>

      <ResponsiveHtmlGuide />

      {loading ? <CoreLoading label={t("正在加载顶部导航页面")} /> : null}
      {loadError ? <CoreError message={loadError} /> : null}

      {!loading && merchant ? (
        <div className="storefront-page-list">
          <article className="storefront-page-row is-catalog">
            <span className="storefront-page-row-icon"><Storefront weight="duotone" /></span>
            <div className="storefront-page-row-copy">
              <div><strong>{merchant.name}</strong><Badge color="green">{t("商品区 · 固定首页")}</Badge></div>
              <code>/{merchant.slug}</code>
            </div>
            <label className="storefront-route-component-toggle">
              <span><CurrencyDollar weight="duotone" /><span><strong>{t("实时汇率")}</strong><small>{t("仅在当前路由显示")}</small></span></span>
              <Switch
                checked={merchant.exchangeRatesEnabled}
                disabled={Boolean(busyId)}
                onCheckedChange={() => void toggleCatalogExchangeRates()}
                aria-label={t("商品首页是否显示实时汇率")}
              />
            </label>
            <Button asChild variant="soft" color="gray">
              <Link to={merchant.storefrontPath} target="_blank" rel="noreferrer">
                <ArrowSquareOut />{t("预览")}
              </Link>
            </Button>
          </article>

          {orderedPages.map((page, index) => (
            <article className={`storefront-page-row${page.enabled ? "" : " is-disabled"}`} key={page.id}>
              <span className="storefront-page-row-icon"><FileCode weight="duotone" /></span>
              <div className="storefront-page-row-copy">
                <div>
                  <strong>{page.title}</strong>
                  <Badge color={page.enabled ? "green" : "gray"}>{t(page.enabled ? "导航中显示" : "已隐藏")}</Badge>
                </div>
                <code>{routePrefix}{page.slug}</code>
                <small>{page.originalFilename} · {fileSize(page.byteSize)} · {t("更新于")} {new Date(page.updatedAt).toLocaleString()}</small>
              </div>
              <div className="storefront-page-row-order" aria-label={t("调整导航顺序")}>
                <Button
                  variant="ghost"
                  color="gray"
                  disabled={index === 0 || Boolean(busyId)}
                  onClick={() => void move(index, -1)}
                  aria-label={t("上移")}
                ><ArrowUp /></Button>
                <Button
                  variant="ghost"
                  color="gray"
                  disabled={index === orderedPages.length - 1 || Boolean(busyId)}
                  onClick={() => void move(index, 1)}
                  aria-label={t("下移")}
                ><ArrowDown /></Button>
              </div>
              <label className="storefront-route-component-toggle">
                <span><CurrencyDollar weight="duotone" /><span><strong>{t("实时汇率")}</strong><small>{t("仅在当前路由显示")}</small></span></span>
                <Switch
                  checked={page.exchangeRatesEnabled}
                  disabled={Boolean(busyId)}
                  onCheckedChange={() => void togglePageExchangeRates(page)}
                  aria-label={t("此路由是否显示实时汇率")}
                />
              </label>
              <div className="storefront-page-row-actions">
                <label className="storefront-page-replace">
                  <input
                    type="file"
                    accept=".html,text/html"
                    disabled={Boolean(busyId)}
                    onChange={(event) => {
                      void replaceHtml(page, event.target.files?.[0]);
                      event.currentTarget.value = "";
                    }}
                  />
                  <UploadSimple />{t("替换 HTML")}
                </label>
                <Button variant="soft" color="gray" disabled={Boolean(busyId)} onClick={() => startEdit(page)}>
                  <PencilSimple />{t("编辑")}
                </Button>
                {page.enabled ? (
                  <Button asChild variant="soft" color="gray">
                    <Link to={`/${merchant.slug}/pages/${page.slug}`} target="_blank" rel="noreferrer">
                      <ArrowSquareOut />{t("预览")}
                    </Link>
                  </Button>
                ) : null}
                <label className="storefront-page-visibility">
                  <span>{t("导航显示")}</span>
                  <Switch
                    checked={page.enabled}
                    disabled={Boolean(busyId)}
                    onCheckedChange={() => void toggle(page)}
                    aria-label={t("是否在顶部导航显示")}
                  />
                </label>
                <Button variant="ghost" color="red" disabled={Boolean(busyId)} onClick={() => setDeleteTarget(page)} aria-label={t("删除页面")}>
                  <Trash />
                </Button>
              </div>
            </article>
          ))}

          {!orderedPages.length ? (
            <div className="storefront-pages-empty">
              <FileCode weight="duotone" />
              <strong>{t("还没有自定义导航页面")}</strong>
              <span>{t("上传 HTML 后，它会出现在商家名称后方的顶部导航中。")}</span>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="storefront-page-count">
        <CheckCircle weight="fill" />
        <span>{t("已使用 {current} / {total} 个自定义页面", { current: pages.length, total: maxPages })}</span>
      </div>

      <Dialog.Root open={createOpen} onOpenChange={(open) => {
        if (busyId) return;
        setCreateOpen(open);
        if (!open) resetCreate();
      }}>
        <Dialog.Content className="storefront-page-dialog" maxWidth="680px">
          <Dialog.Title>{t("新增顶部导航页面")}</Dialog.Title>
          <Dialog.Description>{t("每个导航页面对应一个独立 HTML 文件，文件会安全存储并绑定到当前商家。")}</Dialog.Description>
          <ResponsiveHtmlGuide compact />
          <div className="storefront-page-form">
            <label>
              <span>{t("导航名称")}</span>
              <input
                value={title}
                maxLength={80}
                placeholder="Pet Products Manufacturer"
                onChange={(event) => {
                  const value = event.target.value;
                  setTitle(value);
                  if (!slugTouched) setSlug(suggestedSlug(value));
                }}
              />
            </label>
            <label>
              <span>{t("英文路由")}</span>
              <div className="storefront-page-slug-field">
                <code>{routePrefix}</code>
                <input
                  value={slug}
                  maxLength={80}
                  placeholder="pet-products-manufacturer"
                  onChange={(event) => {
                    setSlugTouched(true);
                    setSlug(event.target.value.toLowerCase().replace(/\s+/g, "-"));
                  }}
                />
              </div>
              <small>{t("仅支持小写英文字母、数字和连字符，发布后仍可修改。")}</small>
            </label>
            <label className="storefront-page-file-field">
              <span>{t("HTML 文件")}</span>
              <input
                ref={createFileRef}
                type="file"
                accept=".html,text/html"
                onChange={(event) => setHtmlFile(event.target.files?.[0])}
              />
              <div>
                <UploadSimple weight="duotone" />
                <strong>{htmlFile?.name || t("选择单个 .html 文件")}</strong>
                <span>{htmlFile ? fileSize(htmlFile.size) : t("UTF-8 编码，最大 2 MB")}</span>
              </div>
            </label>
          </div>
          <div className="storefront-page-dialog-actions">
            <Dialog.Close><Button variant="soft" color="gray" disabled={busyId === "create"}>{t("取消")}</Button></Dialog.Close>
            <Button disabled={busyId === "create"} onClick={() => void create()}>
              <UploadSimple />{busyId === "create" ? t("上传中") : t("上传并发布")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={Boolean(editTarget)} onOpenChange={(open) => { if (!open && !busyId) setEditTarget(undefined); }}>
        <Dialog.Content className="storefront-page-dialog" maxWidth="520px">
          <Dialog.Title>{t("编辑导航页面")}</Dialog.Title>
          <Dialog.Description>{t("修改导航名称或地址不会改变已上传的 HTML 内容。")}</Dialog.Description>
          <div className="storefront-page-form">
            <label><span>{t("导航名称")}</span><input value={editTitle} maxLength={80} onChange={(event) => setEditTitle(event.target.value)} /></label>
            <label>
              <span>{t("英文路由")}</span>
              <div className="storefront-page-slug-field"><code>{routePrefix}</code><input value={editSlug} maxLength={80} onChange={(event) => setEditSlug(event.target.value.toLowerCase().replace(/\s+/g, "-"))} /></div>
            </label>
          </div>
          <div className="storefront-page-dialog-actions">
            <Dialog.Close><Button variant="soft" color="gray" disabled={Boolean(busyId)}>{t("取消")}</Button></Dialog.Close>
            <Button disabled={Boolean(busyId)} onClick={() => void saveEdit()}>{t("保存修改")}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={Boolean(deleteTarget)} onOpenChange={(open) => { if (!open && !busyId) setDeleteTarget(undefined); }}>
        <AlertDialog.Content maxWidth="480px">
          <AlertDialog.Title>{t("删除这个自定义页面？")}</AlertDialog.Title>
          <AlertDialog.Description>
            {t("“{title}”会立即从顶部导航消失，其 HTML 文件也会从对象存储中删除。", { title: deleteTarget?.title || "" })}
          </AlertDialog.Description>
          <div className="storefront-page-delete-warning"><WarningCircle /><span>{t("此操作无法撤销。")}</span></div>
          <div className="storefront-page-dialog-actions">
            <AlertDialog.Cancel><Button variant="soft" color="gray">{t("取消")}</Button></AlertDialog.Cancel>
            <Button color="red" disabled={Boolean(busyId)} onClick={() => void remove()}><Trash />{t("确认删除")}</Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </section>
  );
}
