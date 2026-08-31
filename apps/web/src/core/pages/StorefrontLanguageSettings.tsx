import { Button, Card, Heading, Select, Spinner, Text } from "@radix-ui/themes";
import {
  Check,
  GlobeHemisphereWest,
  LockSimple,
  Plus,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { StorefrontFlag } from "../../components/StorefrontFlag";
import { STOREFRONT_LANGUAGE_OPTIONS } from "../../lib/storefrontLocale";
import type { StorefrontLocale } from "../../types";
import { useCoreAuth } from "../AuthContext";
import { getMerchantSettings, updateMerchantSettings } from "../api";
import { useLocale } from "../LocaleContext";
import { ToastNotice, useToast } from "../ToastContext";

export function StorefrontLanguageSettings() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const { notify } = useToast();
  const canManageSettings = hasPermission("system.settings_manage");
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
  const availableCount = STOREFRONT_LANGUAGE_OPTIONS.filter(
    (language) => language.code === "zh-CN" || configuredLocales.includes(language.code),
  ).length;
  const waitingCount = STOREFRONT_LANGUAGE_OPTIONS.length - availableCount;

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
            {t("选择访客可以使用的语言；只有管理员已发布语言包的语言才可以启用。")}
          </Text>
        </div>
        <div className="language-selection-toolbar">
          <div className="language-selection-summary" aria-live="polite">
            <span className="is-enabled">{t("已启用 {count} 种", { count: enabledLocales.length })}</span>
            <span>{t("可启用 {count} 种", { count: availableCount })}</span>
            {waitingCount ? <span className="is-waiting">{t("待配置 {count} 种", { count: waitingCount })}</span> : null}
          </div>
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
          <div className="language-package-options">
            {STOREFRONT_LANGUAGE_OPTIONS.map((language) => {
              const enabled = enabledLocales.includes(language.code);
              const source = language.code === "zh-CN";
              const configured = source || configuredLocales.includes(language.code);
              return (
                <button
                  type="button"
                  key={language.code}
                  className={`language-package-option${enabled ? " is-enabled" : ""}${source ? " is-source" : ""}${!configured ? " is-unavailable" : ""}`}
                  onClick={() => toggleLanguage(language.code, !enabled)}
                  disabled={source || !canManageSettings}
                  aria-pressed={enabled}
                  aria-disabled={!configured || source || !canManageSettings}
                  title={!configured ? t("该语言包未配置，请联系管理员。") : undefined}
                >
                  <StorefrontFlag locale={language.code} className="language-option-flag" />
                  <span className="language-option-copy">
                    <strong lang={language.code} dir={language.direction}>{language.label}</strong>
                    <small className="language-option-status">{source
                      ? t("源语言 · 固定保留")
                      : !configured
                        ? t("待管理员配置")
                        : enabled
                          ? t("已在前台启用")
                          : t("点击启用")}</small>
                  </span>
                  <span className="language-option-indicator" aria-hidden="true">
                    {source
                      ? <LockSimple weight="bold" />
                      : !configured
                        ? <WarningCircle weight="fill" />
                        : enabled
                          ? <Check weight="bold" />
                          : <Plus weight="bold" />}
                  </span>
                </button>
              );
            })}
          </div>
          <div className={`language-selection-state${changed ? " is-changed" : ""}`}>
            {changed
              ? <WarningCircle weight="fill" aria-hidden="true" />
              : <Check weight="bold" aria-hidden="true" />}
            <Text size="1" color="gray">
              {t(changed
                ? "有未保存的语言更改"
                : "语言包已发布后即可选择，并显示在访客的语言菜单中。")}
            </Text>
          </div>
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
