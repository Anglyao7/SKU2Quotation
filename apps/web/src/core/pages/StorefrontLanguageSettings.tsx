import { Button, Card, Heading, Select, Spinner, Text } from "@radix-ui/themes";
import {
  Check,
  GlobeHemisphereWest,
  LockSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { StorefrontFlag } from "../../components/StorefrontFlag";
import { STOREFRONT_LANGUAGE_OPTIONS } from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";
import { useCoreAuth } from "../AuthContext";
import { canManageOwnStorefront } from "../storefrontPermissions";
import { useUnsavedChanges } from "../UnsavedChanges";
import { getMerchantSettings, updateMerchantSettings } from "../api";
import { useLocale } from "../LocaleContext";
import { ToastNotice, useToast } from "../ToastContext";

export function StorefrontLanguageSettings() {
  const { hasPermission, profile } = useCoreAuth();
  const { t } = useLocale();
  const { notify } = useToast();
  const canManageSettings = canManageOwnStorefront(profile?.context.accountScope, hasPermission);
  const [enabledLocales, setEnabledLocales] = useState<StorefrontLocale[]>(["zh-CN"]);
  const [savedLocales, setSavedLocales] = useState<StorefrontLocale[]>(["zh-CN"]);
  const [configuredLocales, setConfiguredLocales] = useState<StorefrontLocale[]>(["zh-CN"]);
  const [defaultLocale, setDefaultLocale] = useState<StorefrontLocale>("zh-CN");
  const [savedDefaultLocale, setSavedDefaultLocale] = useState<StorefrontLocale>("zh-CN");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const changed = enabledLocales.join(",") !== savedLocales.join(",")
    || defaultLocale !== savedDefaultLocale;
  useUnsavedChanges(!loading && (changed || saving));
  const enabledLanguages = STOREFRONT_LANGUAGE_OPTIONS.filter(
    (language) => enabledLocales.includes(language.code),
  );

  useEffect(() => {
    let active = true;
    void getMerchantSettings()
      .then((settings) => {
        if (!active) return;
        setEnabledLocales(settings.storefrontLocales);
        setSavedLocales(settings.storefrontLocales);
        setConfiguredLocales(settings.configuredStorefrontLocales);
        setDefaultLocale(settings.storefrontDefaultLocale);
        setSavedDefaultLocale(settings.storefrontDefaultLocale);
      })
      .catch((reason) => {
        if (active) {
          setError(reason instanceof Error ? reason.message : t("语言设置读取失败。"));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [t]);

  const toggleLanguage = (locale: StorefrontLocale, enabled: boolean) => {
    if (enabled && locale !== "zh-CN" && !configuredLocales.includes(locale)) {
      setSuccess("");
      setError("");
      notify(t("该语言包未配置，请联系管理员。"), { kind: "error" });
      return;
    }
    setEnabledLocales((current) => {
      const values = new Set(current);
      if (enabled) values.add(locale);
      else values.delete(locale);
      values.add("zh-CN");
      return STOREFRONT_LANGUAGE_OPTIONS
        .map((language) => language.code)
        .filter((code) => values.has(code));
    });
    if (!enabled && defaultLocale === locale) setDefaultLocale("zh-CN");
    setError("");
    setSuccess("");
  };

  const save = async () => {
    if (!canManageSettings || !changed || saving) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const settings = await updateMerchantSettings({
        storefrontLocales: enabledLocales,
        storefrontDefaultLocale: defaultLocale,
      });
      setEnabledLocales(settings.storefrontLocales);
      setSavedLocales(settings.storefrontLocales);
      setConfiguredLocales(settings.configuredStorefrontLocales);
      setDefaultLocale(settings.storefrontDefaultLocale);
      setSavedDefaultLocale(settings.storefrontDefaultLocale);
      setSuccess(t("前台语言已更新。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("前台语言保存失败。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card className="language-selection-card storefront-language-settings">
      <div className="language-card-heading language-selection-heading">
        <span><GlobeHemisphereWest weight="duotone" /></span>
        <div className="language-heading-copy">
          <Heading size="5">{t("前台语言")}</Heading>
          <Text size="2" color="gray">
            {t("点击选择语言，保存后生效。")}
          </Text>
        </div>
        <div className="language-selection-toolbar">
          <Button
            variant={changed ? "solid" : "soft"}
            onClick={() => void save()}
            loading={saving}
            disabled={!canManageSettings || !changed || saving || loading}
          >
            {t(changed ? "保存前台语言" : "已保存")}
          </Button>
        </div>
      </div>

      {error ? <ToastNotice kind="error" message={error} /> : null}
      {success ? <ToastNotice kind="success" message={success} /> : null}

      {loading ? (
        <div className="language-history-loading">
          <Spinner size="3" />
          <Text color="gray">{t("正在读取语言包配置")}</Text>
        </div>
      ) : (
        <>
          <div className="language-options-heading">
            <div aria-live="polite">
              <Text size="2" weight="bold">
                {t("已选择 {count} 种前台语言", { count: enabledLanguages.length })}
              </Text>
            </div>
            <div className="language-state-legend" aria-label={t("语言状态说明")}>
              <span className="is-enabled"><i />{t("已选中")}</span>
              <span><i />{t("未选中")}</span>
              <span className="is-waiting"><i />{t("暂不可选")}</span>
            </div>
          </div>

          <div className="language-package-options">
            {STOREFRONT_LANGUAGE_OPTIONS.map((language) => {
              const enabled = enabledLocales.includes(language.code);
              const source = language.code === "zh-CN";
              const configured = source || configuredLocales.includes(language.code);
              const unavailable = !configured || (!source && !canManageSettings);
              let statusLabel = enabled ? t("已选中") : "";
              if (source) {
                statusLabel = t("已选中 · 固定保留");
              } else if (!configured) {
                statusLabel = t("语言包未发布");
              } else if (!canManageSettings) {
                statusLabel = t("无权限修改");
              }
              return (
                <button
                  type="button"
                  key={language.code}
                  className={`language-package-option${enabled ? " is-enabled" : ""}${unavailable ? " is-unavailable" : ""}`}
                  onClick={() => toggleLanguage(language.code, !enabled)}
                  disabled={source || !canManageSettings || saving}
                  aria-pressed={enabled}
                  aria-disabled={unavailable || source || saving}
                  title={!configured ? t("该语言包未配置，请联系管理员。") : undefined}
                >
                  <StorefrontFlag locale={language.code} className="language-option-flag" />
                  <span className="language-option-copy">
                    <strong lang={language.code} dir={language.direction}>{language.label}</strong>
                    {statusLabel ? <small className="language-option-status">{statusLabel}</small> : null}
                  </span>
                  {enabled || unavailable ? (
                    <span className="language-option-indicator" aria-hidden="true">
                      {enabled ? <Check weight="bold" /> : <LockSimple weight="bold" />}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>
          {changed ? (
            <div className="language-selection-state is-changed" role="status">
              <WarningCircle weight="fill" aria-hidden="true" />
              <Text size="1" color="gray">{t("有未保存的语言更改")}</Text>
            </div>
          ) : null}
          <div className="language-default-row">
            <div>
              <Text size="2" weight="bold">{t("默认语言")}</Text>
              <Text size="1" color="gray">{t("访客首次打开商品前台时使用；访客主动切换后以选择为准。")}</Text>
            </div>
            <Select.Root
              value={defaultLocale}
              onValueChange={(value) => {
                setDefaultLocale(value as StorefrontLocale);
                setError("");
                setSuccess("");
              }}
              disabled={!canManageSettings}
            >
              <Select.Trigger aria-label={t("选择默认语言")} />
              <Select.Content position="popper">
                {STOREFRONT_LANGUAGE_OPTIONS
                  .filter((language) => enabledLocales.includes(language.code))
                  .map((language) => (
                    <Select.Item key={language.code} value={language.code}>
                      {language.flag} {language.label}
                    </Select.Item>
                  ))}
              </Select.Content>
            </Select.Root>
          </div>
        </>
      )}
    </Card>
  );
}
