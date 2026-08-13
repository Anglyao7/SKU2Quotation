import {
  Badge,
  Button,
  Card,
  Checkbox,
  Heading,
  Switch,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowLeft,
  Brain,
  CheckCircle,
  Database,
  FloppyDisk,
  Robot,
  SlidersHorizontal,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getSupportAIAgent,
  listSupportAIStoreConfigurations,
  updateSupportAIAgent,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIAgent,
  SupportAIStoreConfiguration,
} from "../types";
import "./SupportAIAgentManagement.css";

export function SupportAIAgentDetailPage() {
  const { agentId = "" } = useParams();
  const { t } = useLocale();
  const [agent, setAgent] = useState<SupportAIAgent>();
  const [stores, setStores] = useState<SupportAIStoreConfiguration[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"basic" | "">("");

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [tenantIds, setTenantIds] = useState<string[]>([]);
  const [skuKnowledgeEnabled, setSkuKnowledgeEnabled] = useState(true);
  const [fileKnowledgeEnabled, setFileKnowledgeEnabled] = useState(true);
  const [multilingualEnabled, setMultilingualEnabled] = useState(true);
  const [minRetrievalScore, setMinRetrievalScore] = useState("0.12");
  const [minAnswerConfidence, setMinAnswerConfidence] = useState("0.65");
  const [maxSources, setMaxSources] = useState("5");
  const [dailyLimit, setDailyLimit] = useState("500");
  const [publicCompanyIntroduction, setPublicCompanyIntroduction] = useState("");
  const [publicServiceScope, setPublicServiceScope] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");

  const applyAgent = useCallback((next: SupportAIAgent) => {
    setAgent(next);
    setName(next.name);
    setDescription(next.description || "");
    setEnabled(next.enabled);
    setTenantIds(next.stores.map((store) => store.tenantId));
    setSkuKnowledgeEnabled(next.skuKnowledgeEnabled);
    setFileKnowledgeEnabled(next.fileKnowledgeEnabled);
    setMultilingualEnabled(next.multilingualEnabled);
    setMinRetrievalScore(String(next.minRetrievalScore));
    setMinAnswerConfidence(String(next.minAnswerConfidence));
    setMaxSources(String(next.maxSources));
    setDailyLimit(String(next.dailyAutoReplyLimit));
    setPublicCompanyIntroduction(next.publicCompanyIntroduction || "");
    setPublicServiceScope(next.publicServiceScope || "");
    setSystemPrompt(next.systemPrompt || "");
  }, []);

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError("");
    try {
      const [nextAgent, nextStores] = await Promise.all([
        getSupportAIAgent(agentId),
        listSupportAIStoreConfigurations(),
      ]);
      applyAgent(nextAgent);
      setStores(nextStores);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体详情加载失败"));
    } finally {
      setLoading(false);
    }
  }, [agentId, applyAgent, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleStore = (tenantId: string, selected: boolean) => {
    setTenantIds((current) => selected
      ? Array.from(new Set([...current, tenantId]))
      : current.filter((item) => item !== tenantId));
  };

  const saveBasic = async (event: FormEvent) => {
    event.preventDefault();
    if (!agent || !name.trim() || busy) return;
    setBusy("basic");
    setError("");
    setMessage("");
    try {
      const next = await updateSupportAIAgent(agent.id, {
        name: name.trim(),
        description: description.trim() || null,
        enabled,
        tenantIds,
        skuKnowledgeEnabled,
        fileKnowledgeEnabled,
        multilingualEnabled,
        minRetrievalScore: Number(minRetrievalScore),
        minAnswerConfidence: Number(minAnswerConfidence),
        maxSources: Number(maxSources),
        dailyAutoReplyLimit: Number(dailyLimit),
        publicCompanyIntroduction: publicCompanyIntroduction.trim() || null,
        publicServiceScope: publicServiceScope.trim() || null,
        systemPrompt: systemPrompt.trim() || null,
      });
      applyAgent(next);
      setMessage(t("智能体配置已保存"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体配置保存失败"));
    } finally {
      setBusy("");
    }
  };

  const policyValid = Number(minRetrievalScore) >= 0
    && Number(minRetrievalScore) <= 1
    && Number(minAnswerConfidence) >= 0
    && Number(minAnswerConfidence) <= 1
    && Number(maxSources) >= 1
    && Number(maxSources) <= 12
    && Number(dailyLimit) >= 1;
  return (
    <div className="core-workspace support-agent-page">
      <CorePageHeading
        eyebrow={t("智能体管理")}
        title={agent?.name || t("智能体详情")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray"><Link to="/console/agents"><ArrowLeft />{t("返回列表")}</Link></Button>
            <Button asChild variant="soft" color="gray"><Link to="/console/system/configuration"><SlidersHorizontal />{t("API 配置中心")}</Link></Button>
            {agent ? <Button asChild variant="soft"><Link to={`/console/agents/knowledge?agent_id=${agent.id}`}><Database />{t("知识库")}</Link></Button> : null}
            {agent ? <Button asChild><Link to={`/console/agents/${agent.id}/training`}><Brain />{t("人工训练")}</Link></Button> : null}
          </>
        )}
      />

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {message ? <Card className="support-agent-success"><CheckCircle weight="fill" /><Text size="2">{message}</Text></Card> : null}
      {loading ? <CoreLoading label={t("正在读取智能体详情")} /> : null}

      {!loading && agent ? (
        <>
          <Card className="support-agent-identity-strip">
            <span><Robot weight="duotone" /></span>
            <div><Text size="1" color="gray">{t("智能体 ID")}</Text><code>{agent.agentCode}</code></div>
            <div><Text size="1" color="gray">{t("绑定店铺")}</Text><strong>{agent.stores.length}</strong></div>
            <div><Text size="1" color="gray">{t("模型状态")}</Text><Badge color={agent.apiConfigured ? "jade" : "amber"}>{agent.apiConfigured ? (agent.modelDisplayName || t("已配置")) : t("未配置")}</Badge></div>
            <div><Text size="1" color="gray">{t("运行状态")}</Text><Badge color={agent.enabled ? "jade" : "gray"}>{t(agent.enabled ? "启用" : "停用")}</Badge></div>
          </Card>

          <form className="support-agent-detail-form" onSubmit={(event) => void saveBasic(event)}>
            <Card className="support-agent-config-card">
              <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("基础信息")}</Text><Heading size="5">{t("智能体与店铺")}</Heading></div><Storefront weight="duotone" /></div>
              <div className="support-agent-form-grid">
                <label><Text size="1" color="gray">{t("智能体名称")}</Text><TextField.Root value={name} onChange={(event) => setName(event.target.value)} maxLength={160} required /></label>
                <label className="support-agent-wide"><Text size="1" color="gray">{t("说明（选填）")}</Text><TextArea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={4000} /></label>
                <label className={`support-agent-switch support-agent-wide${!agent.apiConfigured ? " is-disabled" : ""}`}>
                  <span><strong>{t("启用智能体")}</strong><small>{agent.apiConfigured ? t("启用后，绑定店铺可使用自动回复。") : t("完成模型 API 配置后才能启用。")}</small></span>
                  <Switch checked={enabled} disabled={!agent.apiConfigured} onCheckedChange={setEnabled} />
                </label>
              </div>
              <div className="support-agent-store-section">
                <div><Text size="2" weight="medium">{t("绑定店铺")}</Text><Badge color="gray">{tenantIds.length}</Badge></div>
                <div className="support-agent-store-grid">
                  {stores.map((store) => {
                    const selected = tenantIds.includes(store.tenantId);
                    return <label className={selected ? "is-selected" : ""} key={store.tenantId}>
                      <Checkbox checked={selected} onCheckedChange={(value) => toggleStore(store.tenantId, value === true)} />
                      <span><strong>{store.tenantName}</strong><small>{store.modelDisplayName || t("未绑定模型")}</small></span>
                    </label>;
                  })}
                </div>
              </div>
            </Card>

            <Card className="support-agent-config-card">
              <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("回答策略")}</Text><Heading size="5">{t("知识与回复")}</Heading></div><Robot weight="duotone" /></div>
              <div className="support-agent-policy-switches">
                <label className="support-agent-switch"><span><strong>{t("SKU 商品知识")}</strong><small>{t("检索公开商品资料")}</small></span><Switch checked={skuKnowledgeEnabled} onCheckedChange={setSkuKnowledgeEnabled} /></label>
                <label className="support-agent-switch"><span><strong>{t("文件知识库")}</strong><small>{t("使用已处理知识文件")}</small></span><Switch checked={fileKnowledgeEnabled} onCheckedChange={setFileKnowledgeEnabled} /></label>
                <label className="support-agent-switch"><span><strong>{t("多语言回答")}</strong><small>{t("按访客语言回复")}</small></span><Switch checked={multilingualEnabled} onCheckedChange={setMultilingualEnabled} /></label>
              </div>
              <div className="support-agent-form-grid">
                <label className="support-agent-wide"><Text size="1" color="gray">{t("企业对客简介（AI 可引用）")}</Text><TextArea value={publicCompanyIntroduction} onChange={(event) => setPublicCompanyIntroduction(event.target.value)} maxLength={2000} placeholder={t("填写经管理员确认、允许向客户公开的一句话或短介绍。")} /></label>
                <label className="support-agent-wide"><Text size="1" color="gray">{t("对客服务范围（AI 可引用）")}</Text><TextArea value={publicServiceScope} onChange={(event) => setPublicServiceScope(event.target.value)} maxLength={2000} placeholder={t("例如产品选型、规格、MOQ、包装与售前咨询。")} /></label>
                <label><Text size="1" color="gray">{t("最低检索分数")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={minRetrievalScore} onChange={(event) => setMinRetrievalScore(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("最低回答置信度")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={minAnswerConfidence} onChange={(event) => setMinAnswerConfidence(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("单次最大来源数")}</Text><TextField.Root type="number" min="1" max="12" value={maxSources} onChange={(event) => setMaxSources(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("每日自动回复上限")}</Text><TextField.Root type="number" min="1" max="100000" value={dailyLimit} onChange={(event) => setDailyLimit(event.target.value)} /></label>
                <label className="support-agent-wide"><Text size="1" color="gray">{t("系统提示词（选填）")}</Text><TextArea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} maxLength={12000} /></label>
              </div>
              <Text size="1" color="gray">{t("寒暄回复会由 AI 基于以上对客内容生成；内部说明和系统提示词不会被当作企业事实。")}</Text>
              <div className="support-agent-card-actions"><Button type="submit" loading={busy === "basic"} disabled={!name.trim() || !policyValid || Boolean(busy)}><FloppyDisk />{t("保存智能体配置")}</Button></div>
            </Card>
          </form>

        </>
      ) : null}
    </div>
  );
}
