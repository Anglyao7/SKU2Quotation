import { Button, Spinner, Text, TextField } from "@radix-ui/themes";
import {
  ArrowRight,
  ArrowLeft,
  Buildings,
  Eye,
  EyeSlash,
  LockKey,
  Translate,
  WarningCircle,
  Package,
  MagnifyingGlass,
  FilePdf,
  ShieldCheck,
} from "@phosphor-icons/react";
import { useEffect, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Brand } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { useCoreAuth } from "../core/AuthContext";
import { authLoginMessageKey } from "../core/authLoginError";
import { useLocale } from "../core/LocaleContext";
import publicStyles from "./PublicPage.module.css";
import styles from "./LoginPage.module.css";
import { BRAND_FULL_NAME } from "../brand";

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
  const requestedDestination =
    (location.state as { from?: string } | null)?.from || "/console";
  const destination =
    session?.context.defaultWorkspace === "customer_portal"
      ? "/console"
      : requestedDestination;
  const visibleError = error || (authError ? t(authError) : "");
  const busy = submitting || status === "restoring";
  const selectingTenant =
    status === "selecting_tenant" ||
    (status === "restoring" && Boolean(session?.requiresTenantSelection));
  const copy =
    locale === "en-US"
      ? {
          headline: "Bring your products",
          accent: "closer to your customers.",
          intro:
            "One connected workspace for your catalog, product matching and customer quotations.",
          products: "Catalog",
          matching: "Matching",
          quotation: "Quotation",
          note: "Your business starts with your own product data.",
          formNote:
            "Use the account provided when your workspace was activated.",
          restoring: "Restoring session…",
          submitting: "Signing in…",
          switching: "Switching workspace…",
        }
      : {
          headline: "让商品资料，",
          accent: "连接下一次合作。",
          intro:
            "从商品归整到客户报价，在同一个工作台里，让每一步业务都有清晰的起点。",
          products: "商品资料",
          matching: "需求匹配",
          quotation: "报价交付",
          note: "围绕企业自己的资料，开展每一步业务。",
          formNote: "使用开通工作台时提供的账号登录。",
          restoring: "正在恢复会话…",
          submitting: "正在登录…",
          switching: "正在切换工作区…",
        };

  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${t(selectingTenant ? "选择工作区" : "登录商家工作台")} | ${BRAND_FULL_NAME}`;
    return () => {
      document.title = previousTitle;
    };
  }, [selectingTenant, t]);

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
    if (busy) return;
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
    <main className={`${publicStyles.page} ${styles.page}`}>
      <div className={styles.topbar}>
        <Brand subtitle="AI TRADE CLOUD" />
        <div className={styles.actions}>
          <Button
            variant="ghost"
            color="gray"
            onClick={() =>
              void setLocale(locale === "zh-CN" ? "en-US" : "zh-CN")
            }
            aria-label={t("切换语言")}
          >
            <Translate />
            {locale === "zh-CN" ? "EN" : "中文"}
          </Button>
          <ThemeToggle />
        </div>
      </div>
      <div className={styles.layout}>
        <section className={styles.intro} aria-labelledby="login-intro">
          <span className={publicStyles.kicker}>
            YOUR NEXT BUSINESS STARTS HERE
          </span>
          <h1 id="login-intro">
            {copy.headline}
            <br />
            <span>{copy.accent}</span>
          </h1>
          <p>{copy.intro}</p>
          <div className={styles.pipeline}>
            <div>
              <Package size={25} weight="duotone" />
              <span>{copy.products}</span>
            </div>
            <ArrowRight size={16} />
            <div>
              <MagnifyingGlass size={25} weight="duotone" />
              <span>{copy.matching}</span>
            </div>
            <ArrowRight size={16} />
            <div>
              <FilePdf size={25} weight="duotone" />
              <span>{copy.quotation}</span>
            </div>
          </div>
          <div className={styles.introNote}>
            <ShieldCheck size={17} />
            {copy.note}
          </div>
        </section>
        <section
          className={styles.card}
          aria-labelledby="login-heading"
          aria-busy={busy}
        >
          <div className={styles.cardMeta}>
            <span>AI TRADE CLOUD / WORKSPACE</span>
            <LockKey size={17} />
          </div>
          <h2 id="login-heading">
            {t(selectingTenant ? "选择工作区" : "登录商家工作台")}
          </h2>
          <span className={styles.cardDescription}>
            {t(
              selectingTenant
                ? "确认本次使用的商家空间"
                : "使用账号、邮箱或手机号登录",
            )}
          </span>

          {selectingTenant ? (
            <div className={styles.form}>
              {memberships.map((membership) => (
                <Button
                  key={membership.id}
                  size="3"
                  className={styles.tenant}
                  variant="soft"
                  disabled={
                    busy || membership.status.toUpperCase() !== "ACTIVE"
                  }
                  onClick={() => void chooseTenant(membership.id)}
                >
                  <Buildings />
                  <span>{membership.tenantName}</span>
                  <ArrowRight />
                </Button>
              ))}
              {!memberships.length ? (
                <Text size="2" color="gray">
                  {t("当前账号没有可用的商家空间。")}
                </Text>
              ) : null}
              {busy ? (
                <span role="status" className={publicStyles.muted}>
                  {copy.switching}
                </span>
              ) : null}
            </div>
          ) : (
            <form
              className={styles.form}
              autoComplete="on"
              onSubmit={submitPassword}
            >
              <label className={styles.field} htmlFor="login-identifier">
                <Text size="2" weight="medium">
                  {t("登录账号")}
                </Text>
                <TextField.Root
                  id="login-identifier"
                  className={styles.input}
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
                  disabled={busy}
                  aria-invalid={Boolean(visibleError)}
                  aria-describedby={visibleError ? "login-error" : undefined}
                />
              </label>

              <label className={styles.field} htmlFor="login-password">
                <Text size="2" weight="medium">
                  {t("密码")}
                </Text>
                <TextField.Root
                  id="login-password"
                  className={styles.input}
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
                  disabled={busy}
                  aria-invalid={Boolean(visibleError)}
                  aria-describedby={visibleError ? "login-error" : undefined}
                >
                  <TextField.Slot side="right">
                    <button
                      type="button"
                      className={styles.passwordToggle}
                      disabled={busy}
                      aria-label={t(passwordVisible ? "隐藏密码" : "显示密码")}
                      aria-pressed={passwordVisible}
                      onClick={() => setPasswordVisible((current) => !current)}
                    >
                      {passwordVisible ? (
                        <EyeSlash size={18} />
                      ) : (
                        <Eye size={18} />
                      )}
                    </button>
                  </TextField.Slot>
                </TextField.Root>
              </label>

              <button type="submit" className={styles.submit} disabled={busy}>
                {busy ? (
                  <>
                    <Spinner size="2" />
                    <span role="status">
                      {submitting ? copy.submitting : copy.restoring}
                    </span>
                  </>
                ) : (
                  <>
                    {t("登录工作台")}
                    <ArrowRight />
                  </>
                )}
              </button>
            </form>
          )}

          {visibleError ? (
            <div className={styles.error} id="login-error" role="alert">
              <WarningCircle size={17} />
              <span>{visibleError}</span>
            </div>
          ) : null}
          <p className={styles.formNote}>{copy.formNote}</p>
        </section>
      </div>
      <footer className={styles.footer}>
        <Link to="/">
          <ArrowLeft size={14} />
          {t("返回官网")}
        </Link>
        <div>
          <Link to="/privacy">{t("隐私政策")}</Link>
          <span>© {new Date().getFullYear()} AI Trade Cloud</span>
        </div>
      </footer>
    </main>
  );
}
