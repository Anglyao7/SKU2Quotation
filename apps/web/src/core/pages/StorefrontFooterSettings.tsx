import { Button, Text } from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowSquareOut,
  LinkSimple,
  Plus,
  Trash,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getMerchantSettings, updateMerchantSettings } from "../api";
import { CoreError, CoreLoading } from "../CoreUi";
import { useCoreAuth } from "../AuthContext";
import { useLocale } from "../LocaleContext";
import { useToast } from "../ToastContext";
import type {
  MerchantSettings,
  StorefrontFooterSection,
} from "../types";

const MAX_SECTIONS = 4;
const MAX_LINKS_PER_SECTION = 8;

function validPublicLink(value: string, optional = false) {
  const normalized = value.trim();
  if (!normalized) return optional;
  if (normalized.startsWith("/")) {
    return !normalized.startsWith("//") && !normalized.includes("\\");
  }
  try {
    const parsed = new URL(normalized);
    return ["http:", "https:", "mailto:", "tel:"].includes(parsed.protocol);
  } catch {
    return false;
  }
}

function normalizedSections(sections: StorefrontFooterSection[]) {
  return sections.map((section) => ({
    title: section.title.trim(),
    titleUrl: section.titleUrl?.trim() || undefined,
    links: section.links.map((link) => ({
      label: link.label.trim(),
      url: link.url.trim(),
    })),
  }));
}

export function StorefrontFooterSettings() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const { notify } = useToast();
  const canManage = hasPermission("system.settings_manage");
  const [merchant, setMerchant] = useState<MerchantSettings>();
  const [sections, setSections] = useState<StorefrontFooterSection[]>([]);
  const [loading, setLoading] = useState(canManage);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    if (!canManage) return;
    setLoading(true);
    setLoadError("");
    try {
      const settings = await getMerchantSettings();
      setMerchant(settings);
      setSections(settings.storefrontFooterSections);
    } catch (caught) {
      setLoadError(caught instanceof Error ? caught.message : t("前台页脚设置加载失败"));
    } finally {
      setLoading(false);
    }
  }, [canManage, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!canManage) return null;

  const updateSection = (index: number, patch: Partial<StorefrontFooterSection>) => {
    setSections((current) => current.map((section, sectionIndex) => (
      sectionIndex === index ? { ...section, ...patch } : section
    )));
  };

  const updateLink = (
    sectionIndex: number,
    linkIndex: number,
    patch: { label?: string; url?: string },
  ) => {
    setSections((current) => current.map((section, currentSectionIndex) => (
      currentSectionIndex === sectionIndex
        ? {
            ...section,
            links: section.links.map((link, currentLinkIndex) => (
              currentLinkIndex === linkIndex ? { ...link, ...patch } : link
            )),
          }
        : section
    )));
  };

  const addSection = () => {
    if (sections.length >= MAX_SECTIONS) return;
    setSections((current) => [...current, { title: "", links: [] }]);
  };

  const removeSection = (sectionIndex: number) => {
    setSections((current) => current.filter((_, index) => index !== sectionIndex));
  };

  const addLink = (sectionIndex: number) => {
    const section = sections[sectionIndex];
    if (!section || section.links.length >= MAX_LINKS_PER_SECTION) return;
    updateSection(sectionIndex, {
      links: [...section.links, { label: "", url: "" }],
    });
  };

  const removeLink = (sectionIndex: number, linkIndex: number) => {
    const section = sections[sectionIndex];
    if (!section) return;
    updateSection(sectionIndex, {
      links: section.links.filter((_, index) => index !== linkIndex),
    });
  };

  const validate = () => {
    for (const [sectionIndex, section] of sections.entries()) {
      if (!section.title.trim()) {
        return t("请填写第 {section} 个页脚分区的标题。", { section: sectionIndex + 1 });
      }
      if (!validPublicLink(section.titleUrl || "", true)) {
        return t("第 {section} 个页脚分区的标题链接格式不正确。", { section: sectionIndex + 1 });
      }
      for (const [linkIndex, link] of section.links.entries()) {
        if (!link.label.trim() || !validPublicLink(link.url)) {
          return t("请完整填写第 {section} 个分区的第 {link} 条链接。", {
            section: sectionIndex + 1,
            link: linkIndex + 1,
          });
        }
      }
    }
    return "";
  };

  const save = async () => {
    if (busy) return;
    const validation = validate();
    if (validation) {
      notify(validation, { kind: "error" });
      return;
    }
    setBusy(true);
    try {
      const updated = await updateMerchantSettings({
        storefrontFooterSections: normalizedSections(sections),
      });
      setMerchant(updated);
      setSections(updated.storefrontFooterSections);
      notify(t("已保存并更新前台"), { kind: "success" });
    } catch (caught) {
      notify(
        caught instanceof Error ? caught.message : t("前台页脚设置保存失败"),
        { kind: "error" },
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="storefront-footer-settings" aria-labelledby="storefront-footer-title">
      <div className="storefront-footer-intro">
        <div>
          <Text size="1" color="gray">{t("客户前台")}</Text>
          <h2 id="storefront-footer-title">{t("商家页脚与外部链接")}</h2>
          <p>{t("展示商家自己的品牌介绍和联系入口；所有文字与跳转地址都可以自定义。")}</p>
        </div>
        <div className="storefront-footer-intro-actions">
          {merchant ? (
            <Button asChild variant="soft">
              <Link to={merchant.storefrontPath} target="_blank" rel="noreferrer">
                <ArrowSquareOut />{t("打开商品前台")}
              </Link>
            </Button>
          ) : null}
          <Button variant="soft" color="gray" disabled={loading || busy} onClick={() => void load()}>
            <ArrowClockwise />{t("刷新")}
          </Button>
        </div>
      </div>

      {loading ? <CoreLoading label={t("正在加载前台页脚设置")} /> : null}
      {loadError ? <CoreError message={loadError} /> : null}

      {!loading && merchant ? (
        <>
          <div className="storefront-footer-preview" aria-label={t("前台页脚预览")}>
            <div className="storefront-footer-preview-brand">
              {merchant.logoUrl ? <img src={merchant.logoUrl} alt="" /> : <span>{merchant.name.slice(0, 1)}</span>}
              <div>
                <strong>{merchant.name}</strong>
                {merchant.shareCardSubtitle ? <small>{merchant.shareCardSubtitle}</small> : null}
              </div>
            </div>
            <div className="storefront-footer-preview-links">
              {sections.map((section, index) => (
                <div key={`${section.title}-${index}`}>
                  <strong>{section.title || t("未命名分区")}</strong>
                  {section.links.map((link, linkIndex) => (
                    <span key={`${link.label}-${linkIndex}`}>{link.label || t("未命名链接")}</span>
                  ))}
                </div>
              ))}
            </div>
            <small className="storefront-footer-preview-powered">Powered by AI Trade Cloud</small>
          </div>

          <div className="storefront-footer-section-list">
            {sections.map((section, sectionIndex) => (
              <article className="storefront-footer-section-card" key={`footer-section-${sectionIndex}`}>
                <header>
                  <div>
                    <span>{t("分区 {section}", { section: sectionIndex + 1 })}</span>
                    <strong>{section.title || t("未命名分区")}</strong>
                  </div>
                  <button type="button" onClick={() => removeSection(sectionIndex)} aria-label={t("删除分区")}>
                    <Trash />
                  </button>
                </header>

                <div className="storefront-footer-section-fields">
                  <label>
                    <span>{t("分区标题")}</span>
                    <input
                      value={section.title}
                      maxLength={80}
                      placeholder="Contact Us"
                      onChange={(event) => updateSection(sectionIndex, { title: event.target.value })}
                    />
                  </label>
                  <label>
                    <span>{t("标题链接（选填）")}</span>
                    <input
                      value={section.titleUrl || ""}
                      maxLength={2_000}
                      placeholder="https://..."
                      onChange={(event) => updateSection(sectionIndex, { titleUrl: event.target.value })}
                    />
                  </label>
                </div>

                <div className="storefront-footer-link-list">
                  {section.links.map((link, linkIndex) => (
                    <div className="storefront-footer-link-row" key={`footer-link-${linkIndex}`}>
                      <LinkSimple aria-hidden="true" />
                      <input
                        value={link.label}
                        maxLength={80}
                        aria-label={t("链接文字")}
                        placeholder="WhatsApp"
                        onChange={(event) => updateLink(sectionIndex, linkIndex, { label: event.target.value })}
                      />
                      <input
                        value={link.url}
                        maxLength={2_000}
                        aria-label={t("跳转地址")}
                        placeholder="https://wa.me/..."
                        onChange={(event) => updateLink(sectionIndex, linkIndex, { url: event.target.value })}
                      />
                      <button type="button" onClick={() => removeLink(sectionIndex, linkIndex)} aria-label={t("删除链接")}>
                        <Trash />
                      </button>
                    </div>
                  ))}
                </div>

                <Button
                  type="button"
                  variant="soft"
                  color="gray"
                  disabled={section.links.length >= MAX_LINKS_PER_SECTION}
                  onClick={() => addLink(sectionIndex)}
                >
                  <Plus />{t("新增链接")}
                </Button>
              </article>
            ))}
          </div>

          <div className="storefront-footer-actions">
            <Button
              type="button"
              variant="soft"
              color="gray"
              disabled={sections.length >= MAX_SECTIONS || busy}
              onClick={addSection}
            >
              <Plus />{t("新增分区")}
            </Button>
            <div>
              <Button size="3" disabled={busy} onClick={() => void save()}>
                {busy ? t("保存中") : t("保存页脚")}
              </Button>
            </div>
          </div>
        </>
      ) : null}
    </section>
  );
}
