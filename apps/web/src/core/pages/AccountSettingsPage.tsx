import { Avatar, Badge, Button, Callout, Card, Heading, Text, TextField } from "@radix-ui/themes";
import {
  CheckCircle,
  Circle,
  Eye,
  EyeSlash,
  Info,
  LockKey,
  ShieldCheck,
  WarningCircle,
} from "@phosphor-icons/react";
import { useMemo, useState, type FormEvent } from "react";
import { useCoreAuth } from "../AuthContext";
import { changePassword, CoreApiError } from "../api";
import {
  passwordRules,
  passwordStrength,
  validatePasswordChange,
  type PasswordChangeValidation,
} from "../accountPassword";
import { CorePageHeading } from "../CoreUi";
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
  const { profile, memberships } = useCoreAuth();
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
  const displayName = user?.displayName || user?.email || "当前成员";

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
      setSuccess("密码已更新。当前设备保持登录，其他设备需要使用新密码重新登录。");
    } catch (caught) {
      if (caught instanceof CoreApiError && caught.status === 401) {
        setFieldErrors({ currentPassword: "当前密码不正确，请重新输入" });
      } else if (caught instanceof CoreApiError && caught.status === 422) {
        setFieldErrors({ newPassword: "新密码未满足安全策略，请按下方要求重新设置" });
      } else if (caught instanceof CoreApiError && caught.status === 409) {
        setRequestError("当前账户暂不支持自助修改密码，请联系管理员。");
      } else if (caught instanceof CoreApiError && caught.status === 429) {
        setRequestError("操作过于频繁，请稍后再试。");
      } else if (caught instanceof CoreApiError && caught.status === 419) {
        setRequestError("登录状态已失效，请重新登录后再修改密码。");
      } else {
        setRequestError("密码修改失败，请稍后重试。");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="core-workspace account-settings-page">
      <CorePageHeading
        eyebrow="账户与安全"
        title="管理你的账户"
        description="查看当前身份信息，并更新用于登录工作台的密码。"
      />

      <div className="account-settings-grid">
        <aside className="account-summary" aria-label="账户资料摘要">
          <Card className="account-profile-card">
            <div className="account-profile-heading">
              <Avatar fallback={initials(displayName)} size="5" radius="large" color="jade" />
              <div>
                <Text size="1" color="gray">当前登录账户</Text>
                <Heading size="4">{displayName}</Heading>
                <Badge color={user?.isPlatformAdmin ? "amber" : "gray"}>
                  {user?.isPlatformAdmin ? "平台管理员" : "商家成员"}
                </Badge>
              </div>
            </div>

            <dl className="account-detail-list">
              <div>
                <dt>登录邮箱</dt>
                <dd>{user?.email || "未提供"}</dd>
              </div>
              <div>
                <dt>当前工作区</dt>
                <dd>{profile?.context.tenantName || "未选择"}</dd>
              </div>
              <div>
                <dt>成员状态</dt>
                <dd>{activeMembership?.status.toUpperCase() === "ACTIVE" ? "正常" : activeMembership?.status || "正常"}</dd>
              </div>
              <div>
                <dt>可访问工作区</dt>
                <dd>{memberships.filter((membership) => membership.status.toUpperCase() === "ACTIVE").length} 个</dd>
              </div>
            </dl>
          </Card>

          <Card className="account-security-note">
            <ShieldCheck size={24} aria-hidden="true" />
            <div>
              <Heading size="3">账户资料</Heading>
              <Text size="2" color="gray">
                登录邮箱和成员名称由管理员统一维护。已配置的账号或手机号也可以用于登录。
              </Text>
            </div>
          </Card>
        </aside>

        <Card className="account-password-card">
          <div className="account-section-heading">
            <span className="account-section-icon"><LockKey size={22} aria-hidden="true" /></span>
            <div>
              <Heading size="5">修改登录密码</Heading>
              <Text size="2" color="gray">更新后，其他设备上的登录状态将失效。</Text>
            </div>
          </div>

          <form className="account-password-form" onSubmit={submit} noValidate>
            <div className="account-field">
              <label htmlFor="account-current-password">当前密码</label>
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
                    aria-label={visible.current ? "隐藏当前密码" : "显示当前密码"}
                    aria-pressed={visible.current}
                    onClick={() => toggleVisible("current")}
                  >
                    {visible.current ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              <Text id="account-current-password-help" size="1" color="gray">用于确认是你本人在操作</Text>
              {fieldErrors.currentPassword ? <Text id="account-current-password-error" size="1" color="red" role="alert">{fieldErrors.currentPassword}</Text> : null}
            </div>

            <div className="account-field">
              <div className="account-field-label-row">
                <label htmlFor="account-new-password">新密码</label>
                <Badge color={strength.color}>{strength.label}</Badge>
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
                    aria-label={visible.next ? "隐藏新密码" : "显示新密码"}
                    aria-pressed={visible.next}
                    onClick={() => toggleVisible("next")}
                  >
                    {visible.next ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              {fieldErrors.newPassword ? <Text id="account-new-password-error" size="1" color="red" role="alert">{fieldErrors.newPassword}</Text> : null}

              <div id="account-password-rules" className="account-password-rules" aria-label="新密码安全要求">
                {rules.map((rule) => (
                  <span className={rule.met ? "met" : ""} key={rule.key}>
                    {rule.met ? <CheckCircle weight="fill" aria-hidden="true" /> : <Circle aria-hidden="true" />}
                    {rule.label}
                  </span>
                ))}
                <Text size="1" color="gray" className="account-password-symbol-note">符号可以使用，但不是必填项。</Text>
              </div>
            </div>

            <div className="account-field">
              <label htmlFor="account-confirm-password">确认新密码</label>
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
                    aria-label={visible.confirmation ? "隐藏确认密码" : "显示确认密码"}
                    aria-pressed={visible.confirmation}
                    onClick={() => toggleVisible("confirmation")}
                  >
                    {visible.confirmation ? <EyeSlash size={18} /> : <Eye size={18} />}
                  </button>
                </TextField.Slot>
              </TextField.Root>
              {fieldErrors.confirmation ? <Text id="account-confirm-password-error" size="1" color="red" role="alert">{fieldErrors.confirmation}</Text> : null}
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
                <Text size="1" color="gray">当前设备会保持登录，不会中断正在处理的工作。</Text>
              </div>
              <Button type="submit" size="3" loading={submitting} disabled={submitting}>
                保存新密码
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
