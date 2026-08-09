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
  CheckCircle,
  Database,
  FloppyDisk,
  Key,
  Robot,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  createSupportAIProviderProfile,
  getSupportAIAgent,
  listSupportAIProviderProfiles,
  listSupportAIStoreConfigurations,
  updateSupportAIAgent,
  updateSupportAIProviderProfile,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIAgent,
  SupportAIProviderSettings,
  SupportAIStoreConfiguration,
} from "../types";
import "./SupportAIAgentManagement.css";

export function SupportAIAgentDetailPage() {
  const { agentId = "" } = useParams();
  const { t } = useLocale();
  const [agent, setAgent] = useState<SupportAIAgent>();
  const [stores, setStores] = useState<SupportAIStoreConfiguration[]>([]);
  const [profiles, setProfiles] = useState<SupportAIProviderSettings[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"basic" | "api" | "">("");

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
  const [systemPrompt, setSystemPrompt] = useState("");

  const [apiEnabled, setApiEnabled] = useState(true);
  const [configurationName, setConfigurationName] = useState("");
  const [displayModelName, setDisplayModelName] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("45");
  const [maxOutputTokens, setMaxOutputTokens] = useState("2048");
  const [temperature, setTemperature] = useState("0.1");

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
    setSystemPrompt(next.systemPrompt || "");
  }, []);

  const applyProfile = useCallback((nextAgent: SupportAIAgent, nextProfiles: SupportAIProviderSettings[]) => {
    const profile = nextProfiles.find((item) => item.id === nextAgent.providerProfileId);
    setConfigurationName(profile?.configurationName || `${t("智能体")} ${nextAgent.agentCode} API`);
    setDisplayModelName(profile?.displayModelName || "");
    setApiEnabled(profile?.enabled ?? true);
    setBaseUrl(profile?.baseUrl || "");
    setModelName(profile?.modelName || "");
    setApiKey("");
    setTimeoutSeconds(String(profile?.timeoutSeconds ?? 45));
    setMaxOutputTokens(String(profile?.maxOutputTokens ?? 2048));
    setTemperature(String(profile?.temperature ?? 0.1));
  }, [t]);

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError("");
    try {
      const [nextAgent, nextStores, nextProfiles] = await Promise.all([
        getSupportAIAgent(agentId),
        listSupportAIStoreConfigurations(),
        listSupportAIProviderProfiles(),
      ]);
      applyAgent(nextAgent);
      setStores(nextStores);
      setProfiles(nextProfiles);
      applyProfile(nextAgent, nextProfiles);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体详情加载失败"));
    } finally {
      setLoading(false);
    }
  }, [agentId, applyAgent, applyProfile, t]);

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

  const saveApi = async (event: FormEvent) => {
    event.preventDefault();
    if (!agent || busy) return;
    if (!apiFormValid) {
      setError(t("请完整填写模型 API 配置"));
      return;
    }
    if (!agent.providerProfileId && !apiKey.trim()) {
      setError(t("首次配置需要填写 API Key"));
      return;
    }
    setBusy("api");
    setError("");
    setMessage("");
    try {
      const payload = {
        configurationName: configurationName.trim(),
        displayModelName: displayModelName.trim(),
        enabled: apiEnabled,
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        timeoutSeconds: Number(timeoutSeconds),
        maxOutputTokens: Number(maxOutputTokens),
        temperature: Number(temperature),
      };
      const profile = agent.providerProfileId
        ? await updateSupportAIProviderProfile(agent.providerProfileId, payload)
        : await createSupportAIProviderProfile(payload);
      if (!profile.id) throw new Error(t("模型 API 配置保存失败"));
      const next = await updateSupportAIAgent(agent.id, {
        providerProfileId: profile.id,
        enabled: apiEnabled ? agent.enabled : false,
      });
      const nextProfiles = [profile, ...profiles.filter((item) => item.id !== profile.id)];
      setProfiles(nextProfiles);
      applyAgent(next);
      applyProfile(next, nextProfiles);
      setMessage(t("模型 API 配置已保存"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("模型 API 配置保存失败"));
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
  const apiFormValid = Boolean(
    configurationName.trim()
    && displayModelName.trim()
    && baseUrl.trim()
    && modelName.trim()
    && Number.isInteger(Number(timeoutSeconds))
    && Number(timeoutSeconds) >= 1
    && Number(timeoutSeconds) <= 180
    && Number.isInteger(Number(maxOutputTokens))
    && Number(maxOutputTokens) >= 128
    && Number(maxOutputTokens) <= 32768
    && Number.isFinite(Number(temperature))
    && Number(temperature) >= 0
    && Number(temperature) <= 2,
  );

  return (
    <div className="core-workspace support-agent-page">
      <CorePageHeading
        eyebrow={t("智能体管理")}
        title={agent?.name || t("智能体详情")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray"><Link to="/console/agents"><ArrowLeft />{t("返回列表")}</Link></Button>
            {agent ? <Button asChild variant="soft"><Link to={`/console/agents/knowledge?agent_id=${agent.id}`}><Database />{t("知识库")}</Link></Button> : null}
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
            <div><Text size="1" color="gray">{t("模型状态")}</Text><Badge color={agent.apiConfigured ? "jade" : "amber"}>{t(agent.apiConfigured ? "已配置" : "未配置")}</Badge></div>
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
                <label className="support-agent-switch"><span><strong>{t("文件知识库")}</strong><small>{t("使用已批准知识文件")}</small></span><Switch checked={fileKnowledgeEnabled} onCheckedChange={setFileKnowledgeEnabled} /></label>
                <label className="support-agent-switch"><span><strong>{t("多语言回答")}</strong><small>{t("按访客语言回复")}</small></span><Switch checked={multilingualEnabled} onCheckedChange={setMultilingualEnabled} /></label>
              </div>
              <div className="support-agent-form-grid">
                <label><Text size="1" color="gray">{t("最低检索分数")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={minRetrievalScore} onChange={(event) => setMinRetrievalScore(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("最低回答置信度")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={minAnswerConfidence} onChange={(event) => setMinAnswerConfidence(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("单次最大来源数")}</Text><TextField.Root type="number" min="1" max="12" value={maxSources} onChange={(event) => setMaxSources(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("每日自动回复上限")}</Text><TextField.Root type="number" min="1" max="100000" value={dailyLimit} onChange={(event) => setDailyLimit(event.target.value)} /></label>
                <label className="support-agent-wide"><Text size="1" color="gray">{t("系统提示词（选填）")}</Text><TextArea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} maxLength={12000} /></label>
              </div>
              <div className="support-agent-card-actions"><Button type="submit" loading={busy === "basic"} disabled={!name.trim() || !policyValid || Boolean(busy)}><FloppyDisk />{t("保存智能体配置")}</Button></div>
            </Card>
          </form>

          <form onSubmit={(event) => void saveApi(event)}>
            <Card className="support-agent-config-card support-agent-api-card">
              <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("模型接入")}</Text><Heading size="5">{t("API 配置")}</Heading></div><Key weight="duotone" /></div>
              <div className="support-agent-form-grid support-agent-api-grid">
                <label><Text size="1" color="gray">{t("配置名称")}</Text><TextField.Root value={configurationName} onChange={(event) => setConfigurationName(event.target.value)} required /></label>
                <label><Text size="1" color="gray">{t("展示模型名")}</Text><TextField.Root value={displayModelName} onChange={(event) => setDisplayModelName(event.target.value)} required /></label>
                <label className="support-agent-wide"><Text size="1" color="gray">Base URL</Text><TextField.Root type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required /></label>
                <label><Text size="1" color="gray">Model</Text><TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} required /></label>
                <label><Text size="1" color="gray">API Key</Text><TextField.Root type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={agent.apiConfigured ? t("留空则保持原密钥") : t("首次配置必须填写")} /></label>
                <label><Text size="1" color="gray">{t("超时时间（秒）")}</Text><TextField.Root type="number" min="1" max="180" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} /></label>
                <label><Text size="1" color="gray">{t("最大输出 Token")}</Text><TextField.Root type="number" min="128" max="32768" value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(event.target.value)} /></label>
                <label><Text size="1" color="gray">Temperature</Text><TextField.Root type="number" min="0" max="2" step="0.05" value={temperature} onChange={(event) => setTemperature(event.target.value)} /></label>
                <label className="support-agent-switch"><span><strong>{t("启用 API")}</strong><small>{t("关闭后智能体无法生成回复")}</small></span><Switch checked={apiEnabled} onCheckedChange={setApiEnabled} /></label>
              </div>
              <div className="support-agent-card-actions"><Button type="submit" loading={busy === "api"} disabled={Boolean(busy) || !apiFormValid}><FloppyDisk />{t("保存 API 配置")}</Button></div>
            </Card>
          </form>
        </>
      ) : null}
    </div>
  );
}
