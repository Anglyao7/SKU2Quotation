import { Avatar, Badge, Button, Callout, Card, Heading, Switch, Text, TextField } from "@radix-ui/themes";
import {
  CheckCircle,
  Circle,
  ArrowSquareOut,
  Buildings,
  Eye,
  EyeSlash,
  Fire,
  Info,
  LockKey,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useCoreAuth } from "../AuthContext";
import {
  changePassword,
  CoreApiError,
  getMerchantSettings,
  updateMerchantSettings,
} from "../api";
import {
  passwordRules,
  passwordStrength,
  validatePasswordChange,
  type PasswordChangeValidation,
} from "../accountPassword";
import { CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import { initials } from "../../lib/format";
import "./AccountSettingsPage.css";

const strengthCopy = {
  empty: { label: "尚未输入", color: "gray" },
  weak: { label: "强度较弱", color: "red" },
  progressing: { label: "接近要求", color: "amber" },
  ready: { label: "符合要求", color: "jade" },
  strong: { label: "强度较高", color: "jade" },
} as const;

type PasswordField = "current" | "next" | "confirmation";

function describedBy(...ids: Array<string | false | undefined>) {
  return ids.filter(Boolean).join(" ") || undefined;
}

export function AccountSettingsPage() {
  const {
    profile,
    memberships,
    hasPermission,
    reloadProfile,
  } = useCoreAuth();
  const { t } = useLocale();
  const [merchantName, setMerchantName] = useState("");
  const [merchantSlug, setMerchantSlug] = useState("");
  const [merchantError, setMerchantError] = useState("");
  const [merchantSuccess, setMerchantSuccess] = useState("");
  const [merchantSubmitting, setMerchantSubmitting] = useState(false);
  const [merchantSettingsLoading, setMerchantSettingsLoading] = useState(true);
  const [merchantSettingsReady, setMerchantSettingsReady] = useState(false);
  const [hotProductsEnabled, setHotProductsEnabled] = useState(false);
  const [savedHotProductsEnabled, setSavedHotProductsEnabled] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [visible, setVisible] = useState<Record<PasswordField, boolean>>({
    current: false,
    next: false,
    confirmation: false,
  });
  const [fieldErrors, setFieldErrors] = useState<PasswordChangeValidation>({});
  const [requestError, setRequestError] = useState("");
  const [success, setSuccess] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const user = profile?.user;
  const identityCandidates = useMemo(
    () => [user?.email ?? "", user?.displayName ?? ""],
    [user?.displayName, user?.email],
  );
  const rules = useMemo(
    () => passwordRules(newPassword, identityCandidates),
    [identityCandidates, newPassword],
  );
  const strength = strengthCopy[passwordStrength(newPassword, rules)];
  const activeMembership = memberships.find((membership) => membership.id === profile?.context.membershipId);
  const displayName = user?.displayName || user?.email || t("当前成员");
  const canManageMerchant = hasPermission("system.settings_manage");
  const storefrontUrl = merchantSlug
    ? `${window.location.origin}/${encodeURIComponent(merchantSlug)}`
    : "";

  useEffect(() => {
    setMerchantName(profile?.context.tenantName ?? "");
    setMerchantSlug(profile?.context.tenantSlug ?? "");
  }, [profile?.context.tenantName, profile?.context.tenantSlug]);

  useEffect(() => {
    if (!profile?.context.tenantId) return;
    let active = true;
    setMerchantSettingsLoading(true);
    setMerchantSettingsReady(false);
    void getMerchantSettings()
      .then((settings) => {
        if (!active) return;
        setMerchantName(settings.name);
        setMerchantSlug(settings.slug);
        setHotProductsEnabled(settings.hotProductsEnabled);
        setSavedHotProductsEnabled(settings.hotProductsEnabled);
        setMerchantSettingsReady(true);
      })
      .catch(() => {
        if (active) setMerchantError(t("商家资料读取失败，请刷新后重试。"));
      })
      .finally(() => {
        if (active) setMerchantSettingsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [profile?.context.tenantId, t]);

  const hotProductsChanged = hotProductsEnabled !== savedHotProductsEnabled;

  const clearFeedback = (field: keyof PasswordChangeValidation) => {
    setFieldErrors((current) => {
      if (!current[field]) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
    setRequestError("");
    setSuccess("");
  };

  const toggleVisible = (field: PasswordField) => {
    setVisible((current) => ({ ...current, [field]: !current[field] }));
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting) return;

    const errors = validatePasswordChange({
      currentPassword,
      newPassword,
      confirmation,
      identityCandidates,
    });
    setFieldErrors(errors);
    setRequestError("");
    setSuccess("");
    if (Object.keys(errors).length) return;

    setSubmitting(true);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmation("");
      setVisible({ current: false, next: false, confirmation: false });
      setFieldErrors({});
      setSuccess(t("密码已更新。当前设备保持登录，其他设备需要使用新密码重新登录。"));
    } catch (caught) {
      if (caught instanceof CoreApiError && caught.status === 401) {
        setFieldErrors({ currentPassword: t("当前密码不正确，请重新输入") });
      } else if (caught instanceof CoreApiError && caught.status === 422) {
        setFieldErrors({ newPassword: t("新密码未满足安全策略，请按下方要求重新设置") });
      } else if (caught instanceof CoreApiError && caught.status === 409) {
        setRequestError(t("当前账户暂不支持自助修改密码，请联系管理员。"));
      } else if (caught instanceof CoreApiError && caught.status === 429) {
        setRequestError(t("操作过于频繁，请稍后再试。"));
      } else if (caught instanceof CoreApiError && caught.status === 419) {
        setRequestError(t("登录状态已失效，请重新登录后再修改密码。"));
      } else {
        setRequestError(t("密码修改失败，请稍后重试。"));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const submitMerchant = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalized = merchantName.trim();
    if (
      !canManageMerchant
      || !merchantSettingsReady
      || merchantSubmitting
      || !normalized
    ) return;
    const nameChanged = normalized !== profile?.context.tenantName;
    if (!nameChanged && !hotProductsChanged) return;
    setMerchantSubmitting(true);
    setMerchantError("");
    setMerchantSuccess("");
    try {
      const updated = await updateMerchantSettings({
        name: nameChanged ? normalized : undefined,
        hotProductsEnabled: hotProductsChanged ? hotProductsEnabled : undefined,
      });
      setMerchantName(updated.name);
      setMerchantSlug(updated.slug);
      setHotProductsEnabled(updated.hotProductsEnabled);
      setSavedHotProductsEnabled(updated.hotProductsEnabled);
      await reloadProfile();
      setMerchantSuccess(t("商家资料与商品前台设置已保存。商家名称变更后，旧地址仍会自动跳转。"));
    } catch (caught) {
      if (caught instanceof CoreApiError && caught.status === 409) {
        setMerchantError(
          t("商家前台地址暂时发生冲突，请再次提交，系统会自动分配新地址。"),
        );
      } else if (caught instanceof CoreApiError && caught.status === 403) {
        setMerchantError(t("当前成员没有修改商家资料的权限。"));
      } else {
        setMerchantError(t("商家资料保存失败，请稍后重试。"));
      }
    } finally {
      setMerchantSubmitting(false);
    }
  };

  return (
    <div className="core-workspace account-settings-page">
      <CorePageHeading
        eyebrow={t("账户与安全")}
        title={t("账户与商家资料")}
        description={t("管理当前商家名称、公开前台地址与登录密码。")}
      />

      <div className="account-settings-grid">
        <aside className="account-summary" aria-label={t("账户资料摘要")}>
          <Card className="account-profile-card">
            <div className="account-profile-heading">
              <Avatar fallback={initials(displayName)} size="5" radius="large" color="jade" />
              <div>
                <Text size="1" color="gray">{t("当前登录账户")}</Text>
                <Heading size="4">{displayName}</Heading>
                <Badge color={user?.isPlatformAdmin ? "amber" : "gray"}>
                  {t(user?.isPlatformAdmin ? "平台管理员" : "商家成员")}
                </Badge>
              </div>
            </div>

            <dl className="account-detail-list">
              <div>
                <dt>{t("登录邮箱")}</dt>
                <dd>{user?.email || t("未提供")}</dd>
              </div>
              <div>
                <dt>{t("当前工作区")}</dt>
                <dd>{profile?.context.tenantName || t("未选择")}</dd>
              </div>
              <div>
                <dt>{t("成员状态")}</dt>
                <dd>{activeMembership?.status.toUpperCase() === "ACTIVE" ? t("正常") : activeMembership?.status || t("正常")}</dd>
              </div>
              <div>
                <dt>{t("可访问工作区")}</dt>
                <dd>{t("{count} 个", { count: memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").length })}</dd>
              </div>
            </dl>
          </Card>

          <Card className="account-security-note">
            <ShieldCheck size={24} aria-hidden="true" />
            <div>
              <Heading size="3">{t("账户资料")}</Heading>
              <Text size="2" color="gray">
                {t("如需修改登录邮箱或成员名称，请联系账户负责人。已配置的账号或手机号均可用于登录。")}
              </Text>
            </div>
          </Card>
        </aside>

        <div className="account-settings-content">
          <Card className="account-merchant-card">
            <div className="account-section-heading">
              <span className="account-section-icon"><Buildings size={22} aria-hidden="true" /></span>
              <div>
                <Heading size="5">{t("商家资料")}</Heading>
                <Text size="2" color="gray">{t("商家名称会同步成为商品前台地址。")}</Text>
              </div>
            </div>

            <form className="account-merchant-form" onSubmit={submitMerchant}>
              <div className="account-field">
                <label htmlFor="account-merchant-name">{t("商家名称")}</label>
                <TextField.Root
                  id="account-merchant-name"
                  size="3"
                  value={merchantName}
                  onChange={(event) => {
                    setMerchantName(event.target.value);
                    setMerchantError("");
                    setMerchantSuccess("");
                  }}
                  maxLength={200}
                  required
                  disabled={!canManageMerchant}
                  placeholder={t("请输入对外展示的商家名称")}
                />
                <Text size="1" color="gray">
                  {t("中文可直接用于路径；空格和标点会自动整理。修改后已有链接仍然有效。")}
                </Text>
              </div>

              <section
                className={`account-hot-products-setting${hotProductsEnabled ? " is-enabled" : ""}`}
                aria-labelledby="account-hot-products-title"
              >
                <span className="account-hot-products-icon">
                  <Fire size={20} weight="duotone" aria-hidden="true" />
                </span>
                <div className="account-hot-products-copy">
                  <Text id="account-hot-products-title" size="2" weight="bold">
                    {t("爆款优先展示")}
                  </Text>
                  <Text size="1" color="gray">
                    {t("开启后，访客进入“全部商品”时会优先看到近 90 天浏览与下单热度更高的商品；搜索和分类顺序不受影响。")}
                  </Text>
                </div>
                <div className="account-hot-products-control">
                  <Badge color={hotProductsEnabled ? "amber" : "gray"} variant="soft">
                    {t(hotProductsEnabled ? "已开启" : "未开启")}
                  </Badge>
                  <Switch
                    checked={hotProductsEnabled}
                    disabled={
                      !canManageMerchant
                      || merchantSettingsLoading
                      || !merchantSettingsReady
                    }
                    onCheckedChange={(checked) => {
                      setHotProductsEnabled(checked);
                      setMerchantError("");
                      setMerchantSuccess("");
                    }}
                    aria-label={t("爆款优先展示")}
                  />
                </div>
              </section>

              {storefrontUrl ? (
                <div className="account-storefront-preview">
                  <div>
                    <Text size="1" color="gray">{t("当前商品前台")}</Text>
                    <Text size="2" weight="medium">{storefrontUrl}</Text>
                  </div>
                  <Button asChild size="2" variant="soft">
                    <a href={storefrontUrl} target="_blank" rel="noreferrer">
                      {t("查看前台")}<ArrowSquareOut size={16} />
                    </a>
                  </Button>
                </div>
              ) : null}

              {merchantError ? (
                <Callout.Root color="red" role="alert">
                  <Callout.Icon><WarningCircle /></Callout.Icon>
                  <Callout.Text>{merchantError}</Callout.Text>
                </Callout.Root>
              ) : null}
              {merchantSuccess ? (
                <Callout.Root color="green" role="status">
                  <Callout.Icon><CheckCircle /></Callout.Icon>
                  <Callout.Text>{merchantSuccess}</Callout.Text>
                </Callout.Root>
              ) : null}

              <div className="account-merchant-actions">
                {!canManageMerchant ? (
                  <Text size="1" color="gray">{t("仅商家所有者或管理员可以修改。")}</Text>
                ) : <span />}
                <Button
                  type="submit"
                  size="3"
                  loading={merchantSubmitting}
                  disabled={
                    !canManageMerchant
                    || merchantSubmitting
                    || merchantSettingsLoading
                    || !merchantSettingsReady
                    || !merchantName.trim()
                    || (
                      merchantName.trim() === profile?.context.tenantName
                      && !hotProductsChanged
                    )
                  }
                >
                  {t("保存商家资料")}
                </Button>
              </div>
            </form>
          </Card>

          <Card className="account-password-card">
          <div className="account-section-heading">
            <span className="account-section-icon"><LockKey size={22} aria-hidden="true" /></span>
            <div>
              <Heading size="5">{t("修改登录密码")}</Heading>
              <Text size="2" color="gray">{t("更新后，其他设备上的登录状态将失效。")}</Text>
            </div>
          </div>

          <form className="account-password-form" onSubmit={submit} noValidate>
            <div className="account-field">
              <label htmlFor="account-current-password">{t("当前密码")}</label>
              <TextField.Root
                id="account-current-password"
                name="current-password"
                size="3"
                type={visible.current ? "text" : "password"}
                value={currentPassword}
                onChange={(event) => {
                  setCurrentPassword(event.target.value);
                  clearFeedback("currentPassword");
                }}
                autoComplete="current-password"
                maxLength={256}
                required
                aria-invalid={Boolean(fieldErrors.currentPassword)}
                aria-describedby={describedBy("account-current-password-help", fieldErrors.currentPassword && "account-current-password-error")}
              >
                <TextField.Slot side="right">
                  <button
                    type="button"
                    className="account-password-toggle"
                    aria-label={t(visible.current ? "隐藏当前密码" : "显示当前密码")}
                    aria-pressed={visible.current}
                    onClick={() => toggleVisible("current")}
                  >
                    {visible.current ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              <Text id="account-current-password-help" size="1" color="gray">{t("用于确认是你本人在操作")}</Text>
              {fieldErrors.currentPassword ? <Text id="account-current-password-error" size="1" color="red" role="alert">{t(fieldErrors.currentPassword)}</Text> : null}
            </div>

            <div className="account-field">
              <div className="account-field-label-row">
                <label htmlFor="account-new-password">{t("新密码")}</label>
                <Badge color={strength.color}>{t(strength.label)}</Badge>
              </div>
              <TextField.Root
                id="account-new-password"
                name="new-password"
                size="3"
                type={visible.next ? "text" : "password"}
                value={newPassword}
                onChange={(event) => {
                  setNewPassword(event.target.value);
                  clearFeedback("newPassword");
                }}
                autoComplete="new-password"
                maxLength={128}
                required
                aria-invalid={Boolean(fieldErrors.newPassword)}
                aria-describedby={describedBy("account-password-rules", fieldErrors.newPassword && "account-new-password-error")}
              >
                <TextField.Slot side="right">
                  <button
                    type="button"
                    className="account-password-toggle"
                    aria-label={t(visible.next ? "隐藏新密码" : "显示新密码")}
                    aria-pressed={visible.next}
                    onClick={() => toggleVisible("next")}
                  >
                    {visible.next ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              {fieldErrors.newPassword ? <Text id="account-new-password-error" size="1" color="red" role="alert">{t(fieldErrors.newPassword)}</Text> : null}

              <div id="account-password-rules" className="account-password-rules" aria-label={t("新密码安全要求")}>
                {rules.map((rule) => (
                  <span className={rule.met ? "met" : ""} key={rule.key}>
                    {rule.met ? <CheckCircle weight="fill" aria-hidden="true" /> : <Circle aria-hidden="true" />}
                    {t(rule.label)}
                  </span>
                ))}
                <Text size="1" color="gray" className="account-password-symbol-note">{t("符号可以使用，但不是必填项。")}</Text>
              </div>
            </div>

            <div className="account-field">
              <label htmlFor="account-confirm-password">{t("确认新密码")}</label>
              <TextField.Root
                id="account-confirm-password"
                name="confirm-password"
                size="3"
                type={visible.confirmation ? "text" : "password"}
                value={confirmation}
                onChange={(event) => {
                  setConfirmation(event.target.value);
                  clearFeedback("confirmation");
                }}
                autoComplete="new-password"
                maxLength={128}
                required
                aria-invalid={Boolean(fieldErrors.confirmation)}
                aria-describedby={fieldErrors.confirmation ? "account-confirm-password-error" : undefined}
              >
                <TextField.Slot side="right">
                  <button
                    type="button"
                    className="account-password-toggle"
                    aria-label={t(visible.confirmation ? "隐藏确认密码" : "显示确认密码")}
                    aria-pressed={visible.confirmation}
                    onClick={() => toggleVisible("confirmation")}
                  >
                    {visible.confirmation ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              {fieldErrors.confirmation ? <Text id="account-confirm-password-error" size="1" color="red" role="alert">{t(fieldErrors.confirmation)}</Text> : null}
            </div>

            {requestError ? (
              <Callout.Root color="red" role="alert">
                <Callout.Icon><WarningCircle /></Callout.Icon>
                <Callout.Text>{requestError}</Callout.Text>
              </Callout.Root>
            ) : null}

            {success ? (
              <Callout.Root color="green" role="status" aria-live="polite">
                <Callout.Icon><CheckCircle /></Callout.Icon>
                <Callout.Text>{success}</Callout.Text>
              </Callout.Root>
            ) : null}

            <div className="account-password-actions">
              <div className="account-session-note">
                <Info size={17} aria-hidden="true" />
                <Text size="1" color="gray">{t("当前设备会保持登录，不会中断正在处理的工作。")}</Text>
              </div>
              <Button type="submit" size="3" loading={submitting} disabled={submitting}>
                {t("保存新密码")}
              </Button>
            </div>
          </form>
          </Card>
        </div>
      </div>
    </div>
  );
}
