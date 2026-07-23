import { Button, Callout, Card, Heading, Text } from "@radix-ui/themes";
import { ArrowRight, Buildings, LockKey, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Brand } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { useCoreAuth } from "../core/AuthContext";
import { getAuthConfig, type AuthPublicConfig } from "../core/api";
import {
  buildOidcAuthorizationUrl,
  consumeOidcTransaction,
  createOidcTransaction,
} from "../core/authPkce";

export function LoginPage() {
  const { status, loginDemo, loginOidc, memberships, switchTenant, error: authError } = useCoreAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const callbackStarted = useRef(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [config, setConfig] = useState<AuthPublicConfig>();
  const [callbackReturnTo, setCallbackReturnTo] = useState("/console");
  const destination = (location.state as { from?: string } | null)?.from || "/console";
  const isCallback = location.pathname === "/login/callback";

  useEffect(() => {
    void getAuthConfig()
      .then(setConfig)
      .catch((caught) => setError(caught instanceof Error ? caught.message : "认证服务配置不可用"));
  }, []);

  useEffect(() => {
    if (status === "authenticated") {
      navigate(isCallback ? callbackReturnTo : destination, { replace: true });
    }
  }, [callbackReturnTo, destination, isCallback, navigate, status]);

  useEffect(() => {
    if (!isCallback || callbackStarted.current) return;
    callbackStarted.current = true;
    setSubmitting(true);
    setError("");
    const parameters = new URLSearchParams(location.search);
    // Authorization codes are single-use secrets. Remove them from browser
    // history immediately, before any network exchange or error rendering.
    window.history.replaceState(window.history.state, "", "/login/callback");
    void (async () => {
      try {
        const transaction = consumeOidcTransaction(parameters.get("state"));
        setCallbackReturnTo(transaction.returnTo);
        const providerError = parameters.get("error");
        if (providerError) throw new Error("企业身份平台未完成授权，请重新登录。");
        const authorizationCode = parameters.get("code");
        if (!authorizationCode) throw new Error("登录回调缺少授权码，请重新登录。");
        await loginOidc({
          authorizationCode,
          codeVerifier: transaction.codeVerifier,
          redirectUri: transaction.redirectUri,
          nonce: transaction.nonce,
        });
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "企业账号登录失败");
      } finally {
        setSubmitting(false);
      }
    })();
  }, [isCallback, location.search, loginOidc]);

  const login = async () => {
    setSubmitting(true); setError("");
    try {
      if (!config) throw new Error("认证配置仍在加载，请稍后重试。");
      if (config.provider === "local_fake") {
        await loginDemo();
        return;
      }
      if (!config.clientId || !config.authorizationEndpoint) {
        throw new Error("企业身份平台配置不完整。");
      }
      const { transaction, codeChallenge } = await createOidcTransaction(destination);
      window.location.assign(buildOidcAuthorizationUrl({
        provider: "enterprise_oidc",
        clientId: config.clientId,
        authorizationEndpoint: config.authorizationEndpoint,
        scopes: config.scopes,
        codeChallengeMethod: config.codeChallengeMethod,
      }, transaction, codeChallenge));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "账号登录失败");
      setSubmitting(false);
    }
  };
  const chooseTenant = async (membershipId: string) => {
    setSubmitting(true); setError("");
    try { await switchTenant(membershipId); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "工作区切换失败"); }
    finally { setSubmitting(false); }
  };

  return <main className="login-page">
    <div className="login-topbar"><Brand /><ThemeToggle /></div>
    <div className="login-layout">
      <section className="login-story"><Text size="2" color="gray">AI Trade Cloud · 商家运营控制台</Text><Heading size="9" as="h1">让产品、供应、询盘和报价成为一条可信链路。</Heading><Text size="4" color="gray">从供应商文件到正式报价，每一步都有租户边界、来源证据和人工确认。</Text><div className="login-feature-list"><div><strong>产品唯一事实来源</strong><span>SKU、价格和供应商证据统一关联</span></div><div><strong>租户权限隔离</strong><span>服务端会话决定成员与工作区</span></div><div><strong>报价人工门禁</strong><span>版本化规则计算，批准后才可对客</span></div></div></section>
      <Card className="login-card" variant="surface"><div className="login-card-heading"><span className="login-lock"><LockKey size={24} weight="duotone" /></span><div><Heading size="6">{status === "selecting_tenant" ? "选择工作区" : isCallback ? "正在验证企业账号" : config?.provider === "local_fake" ? "进入开发演示" : "登录商家工作台"}</Heading><Text size="2" color="gray">{status === "selecting_tenant" ? "此身份属于多个租户，请确认本次上下文" : config?.provider === "local_fake" ? "当前为本地开发身份验证流程" : "使用企业身份平台安全登录"}</Text></div></div>
        {status === "selecting_tenant" ? <div className="login-form">{memberships.map((membership) => <Button key={membership.id} size="3" variant="soft" disabled={submitting || membership.status.toUpperCase() !== "ACTIVE"} onClick={() => void chooseTenant(membership.id)}><Buildings />{membership.tenantName}<ArrowRight /></Button>)}{!memberships.length ? <Text size="2" color="gray">当前身份没有可用成员关系。</Text> : null}</div> : <div className="login-form"><Callout.Root color="green"><Callout.Icon><ShieldCheck /></Callout.Icon><Callout.Text>采用 Authorization Code + PKCE；Access Token 仅保存在内存，刷新凭据使用 HttpOnly Cookie。</Callout.Text></Callout.Root>{!isCallback ? <Button size="3" loading={submitting || status === "restoring" || !config} onClick={() => void login()}>{config?.provider === "local_fake" ? "使用开发演示身份进入" : "使用企业账号登录"}<ArrowRight /></Button> : error ? <Button size="3" asChild><Link to="/login">重新登录<ArrowRight /></Link></Button> : <Button size="3" loading={submitting || status === "restoring"} disabled>正在完成安全验证</Button>}</div>}
        {(error || authError) ? <Callout.Root color="red" mt="4"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error || authError}</Callout.Text></Callout.Root> : null}
      </Card>
    </div><Link to="/" className="login-back-link">返回官网</Link>
  </main>;
}
