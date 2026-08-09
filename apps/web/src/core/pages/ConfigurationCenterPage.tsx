import {
  Badge,
  Button,
  Card,
  Checkbox,
  Heading,
  Select,
  Switch,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  Brain,
  CheckCircle,
  Copy,
  Database,
  FloppyDisk,
  Key,
  Plus,
  ShieldCheck,
  Storefront,
  Translate,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { useSearchParams } from "react-router-dom";
import {
  bulkBindSupportAIProviderProfile,
  copySupportAIProviderProfile,
  copySupportAIStoreConfiguration,
  createSupportAIProviderProfile,
  getEmbeddingSettings,
  listSupportAIProviderProfiles,
  listSupportAIStoreConfigurations,
  updateEmbeddingSettings,
  updateSupportAIProviderProfile,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  EmbeddingSettings,
  SupportAIProviderSettings,
  SupportAIStoreConfiguration,
} from "../types";
import { TranslationApiSettingsPage } from "./TranslationApiSettingsPage";
import "./ConfigurationCenterPage.css";

type ConfigurationSection = "support-ai" | "translation" | "embedding";

const SECTIONS = new Set<ConfigurationSection>([
  "support-ai",
  "translation",
  "embedding",
]);

function sourceLabel(source?: string) {
  if (source === "database") return "后台配置";
  if (source === "environment") return "环境变量";
  if (source === "deterministic") return "本地降级模型";
  return "未配置";
}

function GenerationSettingsPanel() {
  const { t } = useLocale();
  const [profiles, setProfiles] = useState<SupportAIProviderSettings[]>([]);
  const [stores, setStores] = useState<SupportAIStoreConfiguration[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [configurationName, setConfigurationName] = useState("");
  const [displayModelName, setDisplayModelName] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("45");
  const [maxOutputTokens, setMaxOutputTokens] = useState("2048");
  const [temperature, setTemperature] = useState("0.1");
  const [bindingProfileId, setBindingProfileId] = useState("");
  const [bindingTargets, setBindingTargets] = useState<string[]>([]);
  const [copySourceTenantId, setCopySourceTenantId] = useState("");
  const [copyTargets, setCopyTargets] = useState<string[]>([]);
  const [copyModelBinding, setCopyModelBinding] = useState(true);
  const [copyPolicy, setCopyPolicy] = useState(true);
  const [copyEnabledState, setCopyEnabledState] = useState(false);

  const applyProfile = useCallback((next?: SupportAIProviderSettings) => {
    setConfigurationName(next?.configurationName ?? "");
    setDisplayModelName(next?.displayModelName ?? "");
    setEnabled(next?.enabled ?? true);
    setBaseUrl(next?.baseUrl ?? "");
    setModelName(next?.modelName ?? "");
    setTimeoutSeconds(String(next?.timeoutSeconds ?? 45));
    setMaxOutputTokens(String(next?.maxOutputTokens ?? 2048));
    setTemperature(String(next?.temperature ?? 0.1));
    setApiKey("");
  }, []);

  const load = useCallback(async (preferredProfileId?: string) => {
    setLoading(true);
    setError("");
    try {
      const [nextProfiles, nextStores] = await Promise.all([
        listSupportAIProviderProfiles(),
        listSupportAIStoreConfigurations(),
      ]);
      setProfiles(nextProfiles);
      setStores(nextStores);
      const nextSelectedId = preferredProfileId
        || selectedProfileId
        || nextProfiles[0]?.id
        || "new";
      const nextSelected = nextProfiles.find((item) => item.id === nextSelectedId);
      setSelectedProfileId(nextSelected?.id || "new");
      applyProfile(nextSelected);
      setBindingProfileId((current) => current || nextProfiles[0]?.id || "");
      setCopySourceTenantId((current) => current || nextStores[0]?.tenantId || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("大模型配置读取失败"));
    } finally {
      setLoading(false);
    }
  }, [applyProfile, selectedProfileId, t]);

  useEffect(() => {
    void load();
    // Initial platform configuration load only; subsequent selections are local.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectedProfile = profiles.find((item) => item.id === selectedProfileId);

  const valid = useMemo(() => {
    const timeout = Number(timeoutSeconds);
    const tokens = Number(maxOutputTokens);
    const temp = Number(temperature);
    return Boolean(
      configurationName.trim()
      && displayModelName.trim()
      && baseUrl.trim()
      && modelName.trim()
      && (apiKey.trim() || selectedProfile?.apiKeyConfigured)
      && Number.isInteger(timeout) && timeout >= 1 && timeout <= 180
      && Number.isInteger(tokens) && tokens >= 128 && tokens <= 32768
      && Number.isFinite(temp) && temp >= 0 && temp <= 2,
    );
  }, [apiKey, baseUrl, configurationName, displayModelName, maxOutputTokens, modelName, selectedProfile?.apiKeyConfigured, temperature, timeoutSeconds]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy("save-profile");
    setError("");
    setMessage("");
    try {
      const payload = {
        configurationName: configurationName.trim(),
        displayModelName: displayModelName.trim(),
        enabled,
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        timeoutSeconds: Number(timeoutSeconds),
        maxOutputTokens: Number(maxOutputTokens),
        temperature: Number(temperature),
      };
      const saved = selectedProfile?.id
        ? await updateSupportAIProviderProfile(selectedProfile.id, payload)
        : await createSupportAIProviderProfile(payload);
      await load(saved.id);
      setMessage(t("API 配置档案已保存；已绑定店铺会在下一次请求使用最新版本。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("大模型配置保存失败"));
    } finally {
      setBusy("");
    }
  };

  const selectProfile = (profileId: string) => {
    setSelectedProfileId(profileId);
    applyProfile(profiles.find((item) => item.id === profileId));
    setError("");
    setMessage("");
  };

  const startNewProfile = () => {
    setSelectedProfileId("new");
    applyProfile(undefined);
  };

  const duplicateProfile = async () => {
    if (!selectedProfile?.id || busy) return;
    let suffix = 1;
    let name = `${selectedProfile.configurationName || t("API 配置")} - ${t("副本")}`;
    const names = new Set(profiles.map((item) => item.configurationName?.toLocaleLowerCase()));
    while (names.has(name.toLocaleLowerCase())) {
      suffix += 1;
      name = `${selectedProfile.configurationName || t("API 配置")} - ${t("副本")} ${suffix}`;
    }
    setBusy("copy-profile");
    setError("");
    try {
      const copied = await copySupportAIProviderProfile(selectedProfile.id, name);
      await load(copied.id);
      setMessage(t("API 配置已复制，密钥仍以密文保存。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("API 配置复制失败"));
    } finally {
      setBusy("");
    }
  };

  const toggleTarget = (
    current: string[],
    setter: (value: string[]) => void,
    tenantId: string,
    checked: boolean,
  ) => setter(checked ? [...new Set([...current, tenantId])] : current.filter((id) => id !== tenantId));

  const bulkBind = async () => {
    if (!bindingProfileId || !bindingTargets.length || busy) return;
    setBusy("bind-stores");
    setError("");
    try {
      await bulkBindSupportAIProviderProfile(bindingTargets, bindingProfileId);
      await load(selectedProfileId);
      setBindingTargets([]);
      setMessage(t("模型 API 配置已批量应用到所选店铺。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("批量绑定失败"));
    } finally {
      setBusy("");
    }
  };

  const copyStoreConfiguration = async () => {
    if (!copySourceTenantId || !copyTargets.length || busy) return;
    setBusy("copy-store");
    setError("");
    try {
      await copySupportAIStoreConfiguration({
        sourceTenantId: copySourceTenantId,
        targetTenantIds: copyTargets,
        copyModelBinding,
        copyPolicy,
        copyEnabledState,
      });
      await load(selectedProfileId);
      setCopyTargets([]);
      setMessage(t("店铺配置已批量复制；文件知识和 SKU 数据仍严格保留在各自店铺。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("店铺配置复制失败"));
    } finally {
      setBusy("");
    }
  };

  if (loading && !profiles.length) return <CoreLoading label={t("正在读取智能客服大模型配置")} />;
  if (error && !profiles.length) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <div className="configuration-ai-workspace">
      <Card className="configuration-provider-card">
        <div className="configuration-card-heading">
          <span><Brain weight="duotone" /></span>
          <div><Text size="1" color="gray">{t("平台内部 API 档案")}</Text><Heading size="5">{t("智能客服模型配置")}</Heading><Text size="2" color="gray">{t("真实 API、密钥和内部模型名仅平台管理员可见；店铺只看到对外模型名称。")}</Text></div>
          <Button variant="soft" onClick={startNewProfile}><Plus />{t("新增配置")}</Button>
        </div>
        <div className="configuration-profile-layout">
          <div className="configuration-profile-list">
            {profiles.map((profile) => <button type="button" className={profile.id === selectedProfileId ? "active" : ""} key={profile.id} onClick={() => selectProfile(profile.id || "")}><span><strong>{profile.configurationName}</strong><small>{profile.displayModelName} · {profile.modelName}</small></span><Badge color={profile.enabled ? "jade" : "gray"}>{t(profile.enabled ? "可用" : "停用")}</Badge></button>)}
            {!profiles.length ? <Text size="2" color="gray">{t("还没有 API 配置，请先新增一个配置档案。")}</Text> : null}
          </div>
          <form className="configuration-form" onSubmit={(event) => void save(event)}>
            <label><Text size="1" color="gray">{t("内部配置名称")}</Text><TextField.Root value={configurationName} onChange={(event) => setConfigurationName(event.target.value)} placeholder={t("例如：客户 A 专属 API")} required /></label>
            <label><Text size="1" color="gray">{t("店铺可见模型名称")}</Text><TextField.Root value={displayModelName} onChange={(event) => setDisplayModelName(event.target.value)} placeholder={t("例如：专业客服模型")} required /></label>
            <label className="configuration-switch configuration-wide"><span><strong>{t("此 API 配置可供分配")}</strong><small>{t("停用只会阻止绑定店铺调用该配置，不会删除店铺知识库和历史记录。")}</small></span><Switch checked={enabled} onCheckedChange={setEnabled} /></label>
            <label className="configuration-wide"><Text size="1" color="gray">Base URL</Text><TextField.Root type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required /><small>{t("可填写服务根地址、/v1，或完整的 /v1/chat/completions 地址。")}</small></label>
            <label><Text size="1" color="gray">{t("内部模型名称")}</Text><TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="gpt-4.1-mini" required /></label>
            <label><Text size="1" color="gray">API Key</Text><TextField.Root type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={selectedProfile?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: selectedProfile.apiKeyHint ?? "" }) : t("请输入 API Key")} required={!selectedProfile?.apiKeyConfigured} /></label>
            <label><Text size="1" color="gray">{t("请求超时（秒）")}</Text><TextField.Root type="number" min="1" max="180" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} required /></label>
            <label><Text size="1" color="gray">{t("最大输出 Tokens")}</Text><TextField.Root type="number" min="128" max="32768" step="128" value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(event.target.value)} required /></label>
            <label><Text size="1" color="gray">Temperature</Text><TextField.Root type="number" min="0" max="2" step="0.05" value={temperature} onChange={(event) => setTemperature(event.target.value)} required /></label>
            <div className="configuration-actions configuration-wide"><Button type="submit" size="3" disabled={!valid || Boolean(busy)}><FloppyDisk />{t(busy === "save-profile" ? "保存中…" : "保存配置")}</Button>{selectedProfile ? <Button type="button" variant="soft" color="gray" disabled={Boolean(busy)} onClick={() => void duplicateProfile()}><Copy />{t("复制配置")}</Button> : null}<Text size="1" color="gray"><Key /> {t("密钥加密保存，复制时不会在浏览器中解密。")}</Text></div>
          </form>
        </div>
      </Card>

      <Card className="configuration-provider-card configuration-store-card">
        <div className="configuration-card-heading"><span><Storefront weight="duotone" /></span><div><Text size="1" color="gray">{t("店铺模型映射")}</Text><Heading size="5">{t("批量分配 API 配置")}</Heading><Text size="2" color="gray">{t("同一个 API 档案可以分配给多个店铺，也可以为不同客户使用不同档案。")}</Text></div></div>
        <div className="configuration-bulk-controls"><label><Text size="1" color="gray">{t("选择 API 配置")}</Text><Select.Root value={bindingProfileId} onValueChange={setBindingProfileId}><Select.Trigger placeholder={t("选择配置")} /><Select.Content>{profiles.filter((item) => item.id).map((item) => <Select.Item key={item.id} value={item.id || ""}>{item.configurationName} · {item.displayModelName}</Select.Item>)}</Select.Content></Select.Root></label><Button disabled={!bindingProfileId || !bindingTargets.length || Boolean(busy)} onClick={() => void bulkBind()}>{t("应用到 {count} 个店铺", { count: bindingTargets.length })}</Button></div>
        <div className="configuration-store-list">{stores.map((store) => <label key={store.tenantId}><Checkbox checked={bindingTargets.includes(store.tenantId)} onCheckedChange={(value) => toggleTarget(bindingTargets, setBindingTargets, store.tenantId, value === true)} /><span><strong>{store.tenantName}</strong><small>{store.modelDisplayName || t("平台默认模型")} · {t(store.enabled ? "客服已启用" : "客服已关闭")}</small></span></label>)}</div>
      </Card>

      <Card className="configuration-provider-card configuration-store-card">
        <div className="configuration-card-heading"><span><Copy weight="duotone" /></span><div><Text size="1" color="gray">{t("店铺配置模板化")}</Text><Heading size="5">{t("从一个店铺批量复制")}</Heading><Text size="2" color="gray">{t("可复制模型绑定、提示词与阈值；文件知识和 SKU 数据绝不跨店铺复制。")}</Text></div></div>
        <div className="configuration-copy-options"><label><Text size="1" color="gray">{t("源店铺")}</Text><Select.Root value={copySourceTenantId} onValueChange={(value) => { setCopySourceTenantId(value); setCopyTargets((current) => current.filter((id) => id !== value)); }}><Select.Trigger placeholder={t("选择源店铺")} /><Select.Content>{stores.map((store) => <Select.Item value={store.tenantId} key={store.tenantId}>{store.tenantName}</Select.Item>)}</Select.Content></Select.Root></label><label><Checkbox checked={copyModelBinding} onCheckedChange={(value) => setCopyModelBinding(value === true)} />{t("模型 API 绑定")}</label><label><Checkbox checked={copyPolicy} onCheckedChange={(value) => setCopyPolicy(value === true)} />{t("提示词与阈值")}</label><label><Checkbox checked={copyEnabledState} onCheckedChange={(value) => setCopyEnabledState(value === true)} />{t("同时复制启用/关闭状态")}</label></div>
        <div className="configuration-store-list">{stores.filter((store) => store.tenantId !== copySourceTenantId).map((store) => <label key={store.tenantId}><Checkbox checked={copyTargets.includes(store.tenantId)} onCheckedChange={(value) => toggleTarget(copyTargets, setCopyTargets, store.tenantId, value === true)} /><span><strong>{store.tenantName}</strong><small>{store.modelDisplayName || t("平台默认模型")}</small></span></label>)}</div>
        <div className="configuration-actions"><Button disabled={!copySourceTenantId || !copyTargets.length || (!copyModelBinding && !copyPolicy && !copyEnabledState) || Boolean(busy)} onClick={() => void copyStoreConfiguration()}><Copy />{t("复制到 {count} 个店铺", { count: copyTargets.length })}</Button><Text size="1" color="gray">{t("默认不复制启用状态，避免批量开启尚未验收的店铺。")}</Text></div>
      </Card>
      {message ? <Text size="2" color="green"><CheckCircle weight="fill" /> {message}</Text> : null}
      {error ? <Text size="2" color="red">{error}</Text> : null}
    </div>
  );
}

function EmbeddingSettingsPanel() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<EmbeddingSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [dimensions, setDimensions] = useState("1024");
  const [timeoutSeconds, setTimeoutSeconds] = useState("20");

  const apply = useCallback((next: EmbeddingSettings) => {
    setSettings(next);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName);
    setDimensions(String(next.dimensions));
    setTimeoutSeconds(String(next.timeoutSeconds));
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await getEmbeddingSettings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Embedding 配置读取失败"));
    } finally {
      setLoading(false);
    }
  }, [apply, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const valid = Boolean(
    baseUrl.trim()
    && modelName.trim()
    && (apiKey.trim() || settings?.apiKeyConfigured)
    && Number.isInteger(Number(dimensions)) && Number(dimensions) >= 8 && Number(dimensions) <= 8192
    && Number.isInteger(Number(timeoutSeconds)) && Number(timeoutSeconds) >= 1 && Number(timeoutSeconds) <= 120,
  );

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      apply(await updateEmbeddingSettings({
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        dimensions: Number(dimensions),
        timeoutSeconds: Number(timeoutSeconds),
      }));
      setMessage(t("Embedding 配置已保存。模型或维度变更后请到 AI 搜索管理执行全量重建。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Embedding 配置保存失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !settings) return <CoreLoading label={t("正在读取 Embedding 配置")} />;
  if (error && !settings) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <Card className="configuration-provider-card">
      <div className="configuration-card-heading">
        <span><Database weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("商品与文件知识检索")}</Text>
          <Heading size="5">Embedding API</Heading>
          <Text size="2" color="gray">{t("商品知识和企业文件共用这套向量模型；供应商名称、供应商 SKU 与供应商评分不会进入向量文本。")}</Text>
        </div>
        <div className="configuration-statuses">
          <Badge color={settings?.apiKeyConfigured ? "jade" : "amber"}>{t(settings?.apiKeyConfigured ? "密钥已配置" : "使用降级模型")}</Badge>
          <Badge color={settings?.source === "database" ? "blue" : "gray"}>{t(sourceLabel(settings?.source))}</Badge>
        </div>
      </div>
      <form className="configuration-form" onSubmit={(event) => void save(event)}>
        <label className="configuration-wide">
          <Text size="1" color="gray">Base URL</Text>
          <TextField.Root type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required />
        </label>
        <label>
          <Text size="1" color="gray">{t("模型名称")}</Text>
          <TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="text-embedding-3-small" required />
        </label>
        <label>
          <Text size="1" color="gray">API Key</Text>
          <TextField.Root type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: settings.apiKeyHint ?? "" }) : t("请输入 API Key")} required={!settings?.apiKeyConfigured} />
        </label>
        <label>
          <Text size="1" color="gray">{t("向量维度")}</Text>
          <TextField.Root type="number" min="8" max="8192" value={dimensions} onChange={(event) => setDimensions(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
          <TextField.Root type="number" min="1" max="120" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} required />
        </label>
        <div className="configuration-actions configuration-wide">
          <Button type="submit" size="3" disabled={!valid || saving}><FloppyDisk />{t(saving ? "保存中…" : "保存配置")}</Button>
          <Text size="1" color="gray">{t("保存不会自动发起网络连通性测试，也不会自动重建现有索引。")}</Text>
        </div>
      </form>
      {message ? <Text size="2" color="green"><CheckCircle weight="fill" /> {message}</Text> : null}
      {error ? <Text size="2" color="red">{error}</Text> : null}
    </Card>
  );
}

export function ConfigurationCenterPage() {
  const { t } = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("section") as ConfigurationSection | null;
  const section: ConfigurationSection = requested && SECTIONS.has(requested) ? requested : "support-ai";

  const changeSection = (next: string) => {
    const value = next as ConfigurationSection;
    setSearchParams(value === "support-ai" ? {} : { section: value }, { replace: true });
  };

  return (
    <div className="core-workspace configuration-center-page">
      <CorePageHeading
        eyebrow={t("平台设置")}
        title={t("配置中心")}
        description={t("集中管理全站第三方 API 与店铺模型分配。智能客服的知识库、启停和运行策略同样只由平台管理员维护。")}
        actions={<Button variant="soft" color="gray" onClick={() => window.location.reload()}><ArrowClockwise />{t("刷新")}</Button>}
      />

      <Card className="configuration-security-note">
        <ShieldCheck weight="duotone" />
        <div>
          <Text weight="bold" as="div">{t("统一密钥边界")}</Text>
          <Text size="2" color="gray">{t("配置写入后加密保存，页面只展示脱敏状态；这里不执行额外的连接测试。")}</Text>
        </div>
      </Card>

      <Tabs.Root value={section} onValueChange={changeSection}>
        <Tabs.List className="configuration-tabs">
          <Tabs.Trigger value="support-ai"><Brain />{t("智能客服大模型")}</Tabs.Trigger>
          <Tabs.Trigger value="translation"><Translate />{t("翻译 API")}</Tabs.Trigger>
          <Tabs.Trigger value="embedding"><Database />Embedding</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="support-ai" className="configuration-tab-panel"><GenerationSettingsPanel /></Tabs.Content>
        <Tabs.Content value="translation" className="configuration-tab-panel"><TranslationApiSettingsPage embedded /></Tabs.Content>
        <Tabs.Content value="embedding" className="configuration-tab-panel"><EmbeddingSettingsPanel /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
