import { Button, Text, TextArea } from "@radix-ui/themes";
import {
  ArrowClockwise,
  ChatCircleDots,
  CheckCircle,
  ImageSquare,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import {
  getSupportSettings,
  updateSupportSettings,
  uploadSupportActionImage,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { SupportActionSettings, SupportSettings } from "../types";
import "./PersonalCenterPage.css";

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

export function PersonalCenterPage() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<SupportSettings>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setSettings(normalizeSettings(await getSupportSettings()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("悬浮球设置加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const updateAction = (slot: 2 | 3, patch: Partial<SupportActionSettings>) => {
    setSaved(false);
    setSettings((current) => current ? {
      ...current,
      customActions: current.customActions.map((item) => (
        item.slot === slot ? { ...item, ...patch } : item
      )),
    } : current);
  };

  const validateSettings = (value: SupportSettings) => {
    if (!value.welcomeMessage.trim()) return t("请填写客服欢迎语。");
    for (const action of value.customActions) {
      if (!action.visible) continue;
      if (!action.label?.trim()) {
        return t("请为第 {slot} 个悬浮球填写标题。", { slot: action.slot });
      }
      if (!action.imageUrl && !action.externalImageUrl) {
        return t("请为第 {slot} 个悬浮球上传或填写图片。", { slot: action.slot });
      }
    }
    return "";
  };

  const saveSettings = async () => {
    if (!settings || busy) return;
    const validation = validateSettings(settings);
    if (validation) {
      setError(validation);
      return;
    }
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      setSettings(normalizeSettings(await updateSupportSettings(settings)));
      setSaved(true);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("设置保存失败"));
    } finally {
      setBusy(false);
    }
  };

  const uploadImage = async (slot: 2 | 3, file?: File) => {
    if (!file || !settings || busy) return;
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      const uploaded = normalizeSettings(await uploadSupportActionImage(slot, file));
      const uploadedAction = uploaded.customActions.find((action) => action.slot === slot);
      const nextSettings: SupportSettings = {
        ...settings,
        customActions: settings.customActions.map((action) => (
          action.slot === slot && uploadedAction
            ? {
                ...action,
                imageUrl: uploadedAction.imageUrl,
                hasUploadedImage: uploadedAction.hasUploadedImage,
          }
            : action
        )),
      };
      setSettings(normalizeSettings(nextSettings));
      setSaved(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("图片上传失败"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="core-page personal-center-page">
      <CorePageHeading
        eyebrow={t("个人设置")}
        title={t("个人中心")}
        description={t("集中管理常用账户入口与商品前台展示设置。")}
        actions={(
          <Button variant="soft" color="gray" onClick={() => void loadSettings()} disabled={loading || busy}>
            <ArrowClockwise />{t("刷新")}
          </Button>
        )}
      />

      <section className="personal-floating-settings" aria-labelledby="personal-floating-title">
        {loading ? <CoreLoading label={t("正在加载悬浮球设置")} /> : null}
        {error ? <CoreError message={error} onRetry={() => void loadSettings()} /> : null}
        {!loading && settings ? (
          <>
            <div className="personal-floating-intro">
              <div>
                <Text size="1" color="gray">{t("悬浮球设置")}</Text>
                <h2 id="personal-floating-title">{t("前台右下角入口")}</h2>
                <p>{t("第一个客服球固定展示；另外两个入口可独立设置图片、标题和显隐。 ")}</p>
              </div>
              <div className="personal-orb-preview" aria-label={t("悬浮球预览")}>
                <span className="is-chat"><ChatCircleDots weight="fill" /></span>
                {settings.customActions.map((action) => action.visible ? (
                  <span key={action.slot}>
                    {action.imageUrl || action.externalImageUrl
                      ? <img src={action.externalImageUrl || action.imageUrl} alt="" />
                      : <ImageSquare />}
                  </span>
                ) : null)}
              </div>
            </div>

            <label className="personal-welcome-field">
              <span>{t("客服欢迎语")}</span>
              <TextArea value={settings.welcomeMessage} maxLength={500} onChange={(event) => {
                setSaved(false);
                setSettings({ ...settings, welcomeMessage: event.target.value });
              }} />
              <small>{t("客户首次打开对话框时会看到这段内容；AI 自动回复暂未启用。 ")}</small>
            </label>

            <div className="personal-action-settings-grid">
              {settings.customActions.map((action) => (
                <article className="personal-action-settings-card" key={action.slot}>
                  <header>
                    <span>
                      {action.imageUrl || action.externalImageUrl
                        ? <img src={action.externalImageUrl || action.imageUrl} alt="" />
                        : <ImageSquare weight="duotone" />}
                    </span>
                    <div>
                      <strong>{t("自定义悬浮球 {slot}", { slot: action.slot })}</strong>
                      <small>{action.visible ? t("前台已显示") : t("前台已隐藏")}</small>
                    </div>
                    <label className="personal-visibility-switch">
                      <input
                        type="checkbox"
                        checked={action.visible}
                        aria-label={t("自定义悬浮球 {slot}", { slot: action.slot })}
                        onChange={(event) => updateAction(action.slot, { visible: event.target.checked })}
                      />
                      <i />
                    </label>
                  </header>
                  <label>
                    <span>{t("悬浮球标题")}</span>
                    <input value={action.label || ""} maxLength={40} required={action.visible} placeholder={t("例如：WhatsApp")} onChange={(event) => updateAction(action.slot, { label: event.target.value })} />
                  </label>
                  <label>
                    <span>{t("外链图片（选填）")}</span>
                    <input value={action.externalImageUrl || ""} maxLength={2_000} placeholder="https://.../icon.png" onChange={(event) => updateAction(action.slot, { externalImageUrl: event.target.value })} />
                    <small>{t("填写后优先使用外链图片；留空则使用已上传图片。 ")}</small>
                  </label>
                  <label className="personal-image-upload">
                    <input type="file" accept="image/png,image/jpeg,image/webp" disabled={busy} onChange={(event) => void uploadImage(action.slot, event.target.files?.[0])} />
                    <ImageSquare />{action.hasUploadedImage ? t("替换已上传图片") : t("上传图片")}
                  </label>
                </article>
              ))}
            </div>

            <div className="personal-settings-actions">
              {saved ? <span><CheckCircle weight="fill" />{t("已保存并更新前台")}</span> : <span />}
              <Button size="3" onClick={() => void saveSettings()} disabled={busy}>
                {busy ? t("保存中") : t("保存设置")}
              </Button>
            </div>
          </>
        ) : null}
      </section>
    </div>
  );
}
