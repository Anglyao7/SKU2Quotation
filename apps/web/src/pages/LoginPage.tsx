import { Button, Callout, Card, Heading, Text, TextField } from "@radix-ui/themes";
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
        <section className="login-story">
          <Text size="2" color="gray">{t("智贸云 · 商家运营控制台")}</Text>
          <Heading size="9" as="h1">{t("让商品、询盘和报价成为一条可信链路。")}</Heading>
          <Text size="4" color="gray">{t("从商品模版到正式报价，每一步都有租户边界、来源记录和人工确认。")}</Text>
          <div className="login-feature-list">
            <div><strong>{t("商品唯一事实来源")}</strong><span>{t("SKU、价格、规格与图片统一归档")}</span></div>
            <div><strong>{t("租户权限隔离")}</strong><span>{t("服务端会话决定成员与工作区")}</span></div>
            <div><strong>{t("报价人工门禁")}</strong><span>{t("版本化规则计算，批准后才可对客")}</span></div>
          </div>
        </section>

        <Card className="login-card" variant="surface">
          <div className="login-card-heading">
            <span className="login-lock"><LockKey size={24} weight="duotone" /></span>
            <div>
              <Heading size="6">{t(status === "selecting_tenant" ? "选择工作区" : "登录商家工作台")}</Heading>
              <Text size="2" color="gray">{t(status === "selecting_tenant" ? "确认本次使用的商家空间" : "使用账号、邮箱或手机号登录")}</Text>
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
                <Text size="2" weight="medium">{t("账号")}</Text>
                <TextField.Root
                  id="login-identifier"
                  name="identifier"
                  size="3"
                  value={identifier}
                  onChange={(event) => {
                    setIdentifier(event.target.value);
                    if (error) setError("");
                  }}
                  placeholder={t("账号、邮箱或手机号")}
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  maxLength={320}
                  required
                  aria-invalid={Boolean(visibleError)}
                  aria-describedby={visibleError ? "login-error" : "login-identifier-help"}
                />
                <Text id="login-identifier-help" size="1" color="gray">{t("可使用商家账号、登录邮箱或绑定手机号")}</Text>
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

          {visibleError ? (
            <Callout.Root id="login-error" color="red" mt="4" role="alert">
              <Callout.Icon><WarningCircle /></Callout.Icon>
              <Callout.Text>{visibleError}</Callout.Text>
            </Callout.Root>
          ) : null}
        </Card>
      </div>
      <Link to="/" className="login-back-link">{t("返回官网")}</Link>
    </main>
  );
}
