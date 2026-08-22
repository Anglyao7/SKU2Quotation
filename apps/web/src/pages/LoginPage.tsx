import { Button, Card, Heading, Text, TextField } from "@radix-ui/themes";
import {
  ArrowRight,
  Buildings,
  Eye,
  EyeSlash,
  LockKey,
  Translate,
  WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Brand } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { useCoreAuth } from "../core/AuthContext";
import { authLoginMessageKey } from "../core/authLoginError";
import { useLocale } from "../core/LocaleContext";
import { ToastNotice } from "../core/ToastContext";

export function LoginPage() {
  const { locale, setLocale, t } = useLocale();
  const {
    status,
    session,
    loginPassword,
    memberships,
    switchTenant,
    error: authError,
  } = useCoreAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const requestedDestination = (location.state as { from?: string } | null)?.from || "/console";
  const destination = requestedDestination === "/console" && session?.context.defaultWorkspace === "customer_portal"
    ? "/portal"
    : requestedDestination;
  const visibleError = error || authError;

  useEffect(() => {
    if (status === "authenticated") {
      navigate(destination, { replace: true });
    }
  }, [destination, navigate, status]);

  const submitPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submitting || status === "restoring") return;
    setSubmitting(true);
    setError("");
    try {
      await loginPassword(identifier, password);
    } catch (caught) {
      setError(t(authLoginMessageKey(caught)));
    } finally {
      setSubmitting(false);
    }
  };

  const chooseTenant = async (membershipId: string) => {
    setSubmitting(true);
    setError("");
    try {
      await switchTenant(membershipId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : t("工作区切换失败"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="login-page">
      <div className="login-topbar"><Brand /><div className="login-topbar-actions"><Button variant="ghost" color="gray" onClick={() => void setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")} aria-label={t("切换语言")}><Translate />{locale === "zh-CN" ? "EN" : "中文"}</Button><ThemeToggle /></div></div>
      <div className="login-layout">
        <Card className="login-card" variant="surface">
          <div className="login-card-heading">
            <span className="login-lock"><LockKey size={24} weight="duotone" /></span>
            <div>
              <Heading size="6">{t(status === "selecting_tenant" ? "选择工作区" : "登录商家工作台")}</Heading>
              <Text size="2" color="gray">{t(status === "selecting_tenant" ? "确认本次使用的商家空间" : "输入登录账号和密码")}</Text>
            </div>
          </div>

          {status === "selecting_tenant" ? (
            <div className="login-form">
              {memberships.map((membership) => (
                <Button
                  key={membership.id}
                  size="3"
                  variant="soft"
                  disabled={submitting || membership.status.toUpperCase() !== "ACTIVE"}
                  onClick={() => void chooseTenant(membership.id)}
                >
                  <Buildings />
                  {membership.tenantName}
                  <ArrowRight />
                </Button>
              ))}
              {!memberships.length ? <Text size="2" color="gray">{t("当前账号没有可用的商家空间。")}</Text> : null}
            </div>
          ) : (
            <form className="login-form login-credentials-form" autoComplete="on" onSubmit={submitPassword}>
              <label className="field-group" htmlFor="login-identifier">
                <Text size="2" weight="medium">{t("登录账号")}</Text>
                <TextField.Root
                  id="login-identifier"
                  name="identifier"
                  size="3"
                  value={identifier}
                  onChange={(event) => {
                    setIdentifier(event.target.value);
                    if (error) setError("");
                  }}
                  placeholder={t("请输入登录账号")}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={320}
                  required
                  aria-invalid={Boolean(visibleError)}
                  aria-describedby={visibleError ? "login-error" : undefined}
                />
              </label>

              <label className="field-group" htmlFor="login-password">
                <Text size="2" weight="medium">{t("密码")}</Text>
                <TextField.Root
                  id="login-password"
                  name="password"
                  size="3"
                  type={passwordVisible ? "text" : "password"}
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    if (error) setError("");
                  }}
                  placeholder={t("请输入密码")}
                  autoComplete="current-password"
                  maxLength={256}
                  required
                  aria-invalid={Boolean(visibleError)}
                  aria-describedby={visibleError ? "login-error" : undefined}
                >
                  <TextField.Slot side="right">
                    <button
                      type="button"
                      className="login-password-toggle"
                      aria-label={t(passwordVisible ? "隐藏密码" : "显示密码")}
                      aria-pressed={passwordVisible}
                      onClick={() => setPasswordVisible((current) => !current)}
                    >
                      {passwordVisible ? <EyeSlash size={18} /> : <Eye size={18} />}
                    </button>
                  </TextField.Slot>
                </TextField.Root>
              </label>

              <Button
                type="submit"
                size="3"
                loading={submitting || status === "restoring"}
              >
                {t("登录工作台")}
                <ArrowRight />
              </Button>
            </form>
          )}

          {visibleError ? <ToastNotice kind="error" message={visibleError} /> : null}
        </Card>
      </div>
      <Link to="/" className="login-back-link">{t("返回官网")}</Link>
    </main>
  );
}
