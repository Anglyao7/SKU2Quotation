import { Button, Callout, Card, Heading, Text } from "@radix-ui/themes";
import { ArrowRight, Buildings, LockKey, ShieldCheck, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { BRAND_FULL_NAME } from "../brand";
import { Brand } from "../components/Brand";
import { ThemeToggle } from "../components/ThemeToggle";
import { useCoreAuth } from "../core/AuthContext";

export function LoginPage() {
  const { status, loginDemo, memberships, switchTenant, error: authError } = useCoreAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const destination = (location.state as { from?: string } | null)?.from || "/console";

  useEffect(() => { if (status === "authenticated") navigate(destination, { replace: true }); }, [destination, navigate, status]);

  const login = async () => {
    setSubmitting(true); setError("");
    try { await loginDemo(); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "演示身份登录失败"); }
    finally { setSubmitting(false); }
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
      <section className="login-story"><Text size="2" color="gray">{BRAND_FULL_NAME} · 商家运营控制台</Text><Heading size="9" as="h1">让产品、供应、询盘和报价成为一条可信链路。</Heading><Text size="4" color="gray">从供应商文件到正式报价，每一步都有租户边界、来源证据和人工确认。</Text><div className="login-feature-list"><div><strong>产品唯一事实来源</strong><span>SKU、价格和供应商证据统一关联</span></div><div><strong>租户权限隔离</strong><span>服务端会话决定成员与工作区</span></div><div><strong>报价人工门禁</strong><span>版本化规则计算，批准后才可对客</span></div></div></section>
      <Card className="login-card" variant="surface"><div className="login-card-heading"><span className="login-lock"><LockKey size={24} weight="duotone" /></span><div><Heading size="6">{status === "selecting_tenant" ? "选择工作区" : "进入开发演示"}</Heading><Text size="2" color="gray">{status === "selecting_tenant" ? "此身份属于多个租户，请确认本次上下文" : "使用后端 local_fake 身份验证流程"}</Text></div></div>
        {status === "selecting_tenant" ? <div className="login-form">{memberships.map((membership) => <Button key={membership.id} size="3" variant="soft" disabled={submitting || membership.status.toUpperCase() !== "ACTIVE"} onClick={() => void chooseTenant(membership.id)}><Buildings />{membership.tenantName}<ArrowRight /></Button>)}{!memberships.length ? <Text size="2" color="gray">当前身份没有可用成员关系。</Text> : null}</div> : <div className="login-form"><Callout.Root color="green"><Callout.Icon><ShieldCheck /></Callout.Icon><Callout.Text>Access Token 仅保存在内存；刷新依赖 HttpOnly Cookie 与 sessionStorage 中的 CSRF 信息。</Callout.Text></Callout.Root><Button size="3" loading={submitting || status === "restoring"} onClick={() => void login()}>使用开发演示身份进入<ArrowRight /></Button></div>}
        {(error || authError) ? <Callout.Root color="red" mt="4"><Callout.Icon><WarningCircle /></Callout.Icon><Callout.Text>{error || authError}</Callout.Text></Callout.Root> : null}
      </Card>
    </div><Link to="/" className="login-back-link">返回官网</Link>
  </main>;
}
