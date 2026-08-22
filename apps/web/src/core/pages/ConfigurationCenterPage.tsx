import {
  Badge,
  Button,
  Card,
  Heading,
  Switch,
  Tabs,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsDownUp,
  Brain,
  CheckCircle,
  Copy,
  Database,
  FloppyDisk,
  ImageSquare,
  Plus,
  Translate,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  copySupportAIProviderProfile,
  createSupportAIProviderProfile,
  getEmbeddingSettings,
  getImageGenerationSettings,
  getRerankSettings,
  listSupportAIProviderProfiles,
  updateEmbeddingSettings,
  updateImageGenerationSettings,
  updateRerankSettings,
  updateSupportAIProviderProfile,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  EmbeddingSettings,
  ImageGenerationSettings,
  RerankSettings,
  SupportAIProviderSettings,
} from "../types";
import { TranslationApiSettingsPage } from "./TranslationApiSettingsPage";
import "./ConfigurationCenterPage.css";

type ConfigurationSection = "support-ai" | "translation" | "embedding" | "rerank" | "image-generation";

const SECTIONS = new Set<ConfigurationSection>([
  "support-ai",
  "translation",
  "embedding",
  "rerank",
  "image-generation",
]);

function GenerationSettingsPanel() {
  const { t } = useLocale();
  const [profiles, setProfiles] = useState<SupportAIProviderSettings[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState("new");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"save" | "copy" | "">("");
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

  const applyProfile = useCallback((profile?: SupportAIProviderSettings) => {
    setConfigurationName(profile?.configurationName ?? "");
    setDisplayModelName(profile?.displayModelName ?? "");
    setEnabled(profile?.enabled ?? true);
    setBaseUrl(profile?.baseUrl ?? "");
    setModelName(profile?.modelName ?? "");
    setApiKey("");
    setTimeoutSeconds(String(profile?.timeoutSeconds ?? 45));
    setMaxOutputTokens(String(profile?.maxOutputTokens ?? 2048));
    setTemperature(String(profile?.temperature ?? 0.1));
  }, []);

  const load = useCallback(async (preferredProfileId?: string) => {
    setLoading(true);
    setError("");
    try {
      const nextProfiles = await listSupportAIProviderProfiles();
      setProfiles(nextProfiles);
      const selected = nextProfiles.find((item) => item.id === preferredProfileId)
        ?? nextProfiles[0];
      setSelectedProfileId(selected?.id ?? "new");
      applyProfile(selected);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体 API 配置读取失败"));
    } finally {
      setLoading(false);
    }
  }, [applyProfile, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const selectedProfile = profiles.find((item) => item.id === selectedProfileId);
  const valid = useMemo(() => {
    const timeout = Number(timeoutSeconds);
    const tokens = Number(maxOutputTokens);
    const numericTemperature = Number(temperature);
    return Boolean(
      configurationName.trim()
      && displayModelName.trim()
      && baseUrl.trim()
      && modelName.trim()
      && (apiKey.trim() || selectedProfile?.apiKeyConfigured)
      && Number.isInteger(timeout)
      && timeout >= 1
      && timeout <= 180
      && Number.isInteger(tokens)
      && tokens >= 128
      && tokens <= 32768
      && Number.isFinite(numericTemperature)
      && numericTemperature >= 0
      && numericTemperature <= 2,
    );
  }, [apiKey, baseUrl, configurationName, displayModelName, maxOutputTokens, modelName, selectedProfile?.apiKeyConfigured, temperature, timeoutSeconds]);

  const selectProfile = (profileId: string) => {
    const profile = profiles.find((item) => item.id === profileId);
    setSelectedProfileId(profile?.id ?? "new");
    applyProfile(profile);
    setError("");
    setMessage("");
  };

  const startNewProfile = () => {
    setSelectedProfileId("new");
    applyProfile();
    setError("");
    setMessage("");
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || busy) return;
    setBusy("save");
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
      setMessage(t("智能体 API 配置已保存，可在智能体列表中按展示模型名分配。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体 API 配置保存失败"));
    } finally {
      setBusy("");
    }
  };

  const duplicate = async () => {
    if (!selectedProfile?.id || busy) return;
    const baseName = selectedProfile.configurationName || t("API 配置");
    const existing = new Set(profiles.map((item) => item.configurationName?.toLocaleLowerCase()));
    let suffix = 1;
    let copyName = `${baseName} - ${t("副本")}`;
    while (existing.has(copyName.toLocaleLowerCase())) {
      suffix += 1;
      copyName = `${baseName} - ${t("副本")} ${suffix}`;
    }
    setBusy("copy");
    setError("");
    setMessage("");
    try {
      const copied = await copySupportAIProviderProfile(selectedProfile.id, copyName);
      await load(copied.id);
      setMessage(t("配置已复制。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体 API 配置复制失败"));
    } finally {
      setBusy("");
    }
  };

  if (loading && !profiles.length) return <CoreLoading label={t("正在读取智能体 API 配置")} />;
  if (error && !profiles.length) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <Card className="configuration-provider-card">
      <div className="configuration-card-heading">
        <span><Brain weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("智能体")}</Text>
          <Heading size="5">{t("智能体 API")}</Heading>
          <Text size="2" color="gray">{t("管理智能体可使用的模型配置。")}</Text>
        </div>
        <Button variant="soft" onClick={startNewProfile}><Plus />{t("新增配置")}</Button>
      </div>

      <div className="configuration-profile-layout">
        <div className="configuration-profile-list" aria-label={t("智能体 API 配置列表")}>
          {profiles.map((profile) => (
            <button
              type="button"
              className={profile.id === selectedProfileId ? "active" : ""}
              key={profile.id}
              onClick={() => selectProfile(profile.id ?? "")}
            >
              <span>
                <strong>{profile.displayModelName || profile.configurationName}</strong>
                <small>{profile.configurationName}</small>
              </span>
              <Badge color={profile.enabled ? "jade" : "gray"}>{t(profile.enabled ? "可分配" : "已停用")}</Badge>
            </button>
          ))}
          {!profiles.length ? <Text size="2" color="gray">{t("还没有智能体 API 配置。")}</Text> : null}
        </div>

        <form className="configuration-form" onSubmit={(event) => void save(event)}>
          <label>
            <Text size="1" color="gray">{t("配置名称")}</Text>
            <TextField.Root value={configurationName} onChange={(event) => setConfigurationName(event.target.value)} placeholder={t("例如：主客服接口")} required />
          </label>
          <label>
            <Text size="1" color="gray">{t("展示模型名")}</Text>
            <TextField.Root value={displayModelName} onChange={(event) => setDisplayModelName(event.target.value)} placeholder={t("例如：专业客服模型")} required />
          </label>
          <label className="configuration-switch configuration-wide">
            <span><strong>{t("允许分配")}</strong><small>{t("停用后不会出现在新分配列表中，已有绑定仍保留。")}</small></span>
            <Switch checked={enabled} onCheckedChange={setEnabled} />
          </label>
          <label className="configuration-wide">
            <Text size="1" color="gray">Base URL</Text>
            <TextField.Root type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required />
            <small>{t("可填写服务根地址、/v1，或完整的 /v1/chat/completions 地址。")}</small>
          </label>
          <label>
            <Text size="1" color="gray">{t("模型名称")}</Text>
            <TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="gpt-4.1-mini" required />
          </label>
          <label>
            <Text size="1" color="gray">API Key</Text>
            <TextField.Root
              type="password"
              autoComplete="new-password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={selectedProfile?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: selectedProfile.apiKeyHint ?? "" }) : t("请输入 API Key")}
              required={!selectedProfile?.apiKeyConfigured}
            />
          </label>
          <label>
            <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
            <TextField.Root type="number" min="1" max="180" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} required />
          </label>
          <label>
            <Text size="1" color="gray">{t("最大输出 Tokens")}</Text>
            <TextField.Root type="number" min="128" max="32768" step="128" value={maxOutputTokens} onChange={(event) => setMaxOutputTokens(event.target.value)} required />
          </label>
          <label>
            <Text size="1" color="gray">Temperature</Text>
            <TextField.Root type="number" min="0" max="2" step="0.05" value={temperature} onChange={(event) => setTemperature(event.target.value)} required />
          </label>
          <div className="configuration-actions configuration-wide">
            <Button type="submit" size="3" disabled={!valid || Boolean(busy)} loading={busy === "save"}><FloppyDisk />{t("保存配置")}</Button>
            {selectedProfile ? <Button type="button" variant="soft" color="gray" disabled={Boolean(busy)} loading={busy === "copy"} onClick={() => void duplicate()}><Copy />{t("复制配置")}</Button> : null}
          </div>
        </form>
      </div>
      {message ? <Text size="2" color="green"><CheckCircle weight="fill" /> {message}</Text> : null}
      {error ? <Text size="2" color="red">{error}</Text> : null}
    </Card>
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
  const [maxRetryCount, setMaxRetryCount] = useState("3");

  const apply = useCallback((next: EmbeddingSettings) => {
    setSettings(next);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName);
    setDimensions(String(next.dimensions));
    setTimeoutSeconds(String(next.timeoutSeconds));
    setMaxRetryCount(String(next.maxRetryCount ?? 3));
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
    && Number.isInteger(Number(dimensions))
    && Number(dimensions) >= 8
    && Number(dimensions) <= 2000
    && Number.isInteger(Number(timeoutSeconds))
    && Number(timeoutSeconds) >= 1
    && Number(timeoutSeconds) <= 120
    && Number.isInteger(Number(maxRetryCount))
    && Number(maxRetryCount) >= 0
    && Number(maxRetryCount) <= 10,
  );

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await updateEmbeddingSettings({
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        dimensions: Number(dimensions),
        timeoutSeconds: Number(timeoutSeconds),
        maxRetryCount: Number(maxRetryCount),
      });
      apply(saved);
      setMessage(
        saved.modelChanged
          ? t(
            "检测到 Embedding 模型变化，已清空 {productVectors} 条商品向量和 {fileVectors} 条文件向量；{products} 个商品等待重新更新智能索引。",
            {
              productVectors: saved.clearedProductEmbeddings,
              fileVectors: saved.clearedFileEmbeddings,
              products: saved.invalidatedProducts,
            },
          )
          : t("Embedding 配置已保存。当前模型未变化，已有向量保持不变。"),
      );
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
          <Text size="2" color="gray">{t("管理商品搜索与知识库使用的检索配置。")}</Text>
        </div>
        <div className="configuration-statuses">
          <Badge color={settings?.apiKeyConfigured ? "jade" : "amber"}>{t(settings?.apiKeyConfigured ? "已配置" : "待配置")}</Badge>
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
          <TextField.Root
            type="password"
            autoComplete="new-password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={settings?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: settings.apiKeyHint ?? "" }) : t("请输入 API Key")}
            required={!settings?.apiKeyConfigured}
          />
        </label>
        <label>
          <Text size="1" color="gray">{t("向量维度")}</Text>
          <TextField.Root type="number" min="8" max="2000" value={dimensions} onChange={(event) => setDimensions(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
          <TextField.Root type="number" min="1" max="120" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("失败后最多重试次数")}</Text>
          <TextField.Root type="number" min="0" max="10" value={maxRetryCount} onChange={(event) => setMaxRetryCount(event.target.value)} required />
          <Text size="1" color="gray">{t("仅临时错误会自动重试；次数不包含首次请求，建议设置为 2–3。")}</Text>
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

function RerankSettingsPanel() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<RerankSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutMs, setTimeoutMs] = useState("800");
  const [maxDocuments, setMaxDocuments] = useState("30");

  const apply = useCallback((next: RerankSettings) => {
    setSettings(next);
    setEnabled(next.enabled);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName ?? "");
    setTimeoutMs(String(next.timeoutMs));
    setMaxDocuments(String(next.maxDocuments));
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await getRerankSettings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Rerank 配置读取失败"));
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
    && Number.isInteger(Number(timeoutMs))
    && Number(timeoutMs) >= 100
    && Number(timeoutMs) <= 800
    && Number.isInteger(Number(maxDocuments))
    && Number(maxDocuments) >= 5
    && Number(maxDocuments) <= 30,
  );

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      apply(await updateRerankSettings({
        enabled,
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        timeoutMs: Number(timeoutMs),
        maxDocuments: Number(maxDocuments),
      }));
      setMessage(t("Rerank 配置已保存。仅重排已召回的少量证据，超时时自动保留原排序。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("Rerank 配置保存失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !settings) return <CoreLoading label={t("正在读取 Rerank 配置")} />;
  if (error && !settings) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <Card className="configuration-provider-card">
      <div className="configuration-card-heading">
        <span><ArrowsDownUp weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("检索结果精排")}</Text>
          <Heading size="5">Rerank API</Heading>
          <Text size="2" color="gray">{t("在快速召回后重排少量候选，提升商品推荐与证据的相关性。客服调用最多等待 800ms；多语言店铺应选择多语言 Rerank 模型。")}</Text>
        </div>
        <div className="configuration-statuses">
          <Badge color={settings?.enabled ? "jade" : "gray"}>{t(settings?.enabled ? "已启用" : "已关闭")}</Badge>
        </div>
      </div>

      <form className="configuration-form" onSubmit={(event) => void save(event)}>
        <label className="configuration-switch configuration-wide">
          <span><Text weight="medium">{t("启用 Rerank")}</Text><Text size="1" color="gray">{t("失败或超时不会阻断 AI 回答。")}</Text></span>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </label>
        <label className="configuration-wide">
          <Text size="1" color="gray">Base URL</Text>
          <TextField.Root type="url" value={baseUrl} onChange={(event) => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" required />
        </label>
        <label>
          <Text size="1" color="gray">{t("模型名称")}</Text>
          <TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="Qwen/Qwen3-Reranker-0.6B" required />
        </label>
        <label>
          <Text size="1" color="gray">API Key</Text>
          <TextField.Root type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={settings?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: settings.apiKeyHint ?? "" }) : t("请输入 API Key")} required={!settings?.apiKeyConfigured} />
        </label>
        <label>
          <Text size="1" color="gray">{t("超时时间（毫秒）")}</Text>
          <TextField.Root type="number" min="100" max="800" value={timeoutMs} onChange={(event) => setTimeoutMs(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("最多重排候选数")}</Text>
          <TextField.Root type="number" min="5" max="30" value={maxDocuments} onChange={(event) => setMaxDocuments(event.target.value)} required />
        </label>
        <div className="configuration-actions configuration-wide">
          <Button type="submit" size="3" disabled={!valid || saving}><FloppyDisk />{t(saving ? "保存中…" : "保存配置")}</Button>
          <Text size="1" color="gray">{t("保存时不会发起网络连通性测试。")}</Text>
        </div>
      </form>
      {message ? <p className="configuration-message"><CheckCircle weight="fill" />{message}</p> : null}
      {error ? <p className="configuration-error">{error}</p> : null}
    </Card>
  );
}

function ImageGenerationSettingsPanel() {
  const { t } = useLocale();
  const [settings, setSettings] = useState<ImageGenerationSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState("https://apihub.agnes-ai.com/v1/images/generations");
  const [modelName, setModelName] = useState("agnes-image-2.0-flash");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("180");
  const [requestsPerMinute, setRequestsPerMinute] = useState("6");
  const [concurrencyLimit, setConcurrencyLimit] = useState("3");

  const apply = useCallback((next: ImageGenerationSettings) => {
    setSettings(next);
    setEnabled(next.enabled);
    setBaseUrl(next.baseUrl ?? "https://apihub.agnes-ai.com/v1/images/generations");
    setModelName(next.modelName ?? "agnes-image-2.0-flash");
    setSystemPrompt(next.systemPrompt ?? "");
    setTimeoutSeconds(String(next.timeoutSeconds || 180));
    setRequestsPerMinute(String(next.requestsPerMinute || 6));
    setConcurrencyLimit(String(next.concurrencyLimit || 3));
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await getImageGenerationSettings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("图生图配置读取失败"));
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
    && systemPrompt.trim()
    && (apiKey.trim() || settings?.apiKeyConfigured)
    && Number.isInteger(Number(timeoutSeconds))
    && Number(timeoutSeconds) >= 60
    && Number(timeoutSeconds) <= 360
    && Number.isInteger(Number(requestsPerMinute))
    && Number(requestsPerMinute) >= 1
    && Number(requestsPerMinute) <= 10000
    && Number.isInteger(Number(concurrencyLimit))
    && Number(concurrencyLimit) >= 1
    && Number(concurrencyLimit) <= 32,
  );

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const saved = await updateImageGenerationSettings({
        enabled,
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        systemPrompt: systemPrompt.trim(),
        apiKey: apiKey.trim() || undefined,
        timeoutSeconds: Number(timeoutSeconds),
        requestsPerMinute: Number(requestsPerMinute),
        concurrencyLimit: Number(concurrencyLimit),
      });
      apply(saved);
      setMessage(t("图生图配置已保存并立即生效。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("图生图配置保存失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !settings) return <CoreLoading label={t("正在读取图生图配置")} />;
  if (error && !settings) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <Card className="configuration-provider-card">
      <div className="configuration-card-heading">
        <span><ImageSquare weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("图片处理")}</Text>
          <Heading size="5">{t("图生图 API")}</Heading>
          <Text size="2" color="gray">{t("仅接入图生图；调用时支持 URL 或 Base64 两种返回格式。")}</Text>
          <Text size="1" color="gray">{t("图生图请求达到 RPM 或并发上限后会排队等待。")}</Text>
        </div>
        <div className="configuration-statuses">
          <Badge color={settings?.apiKeyConfigured ? "jade" : "amber"}>
            {t(settings?.apiKeyConfigured ? "已配置" : "待配置")}
          </Badge>
          <Badge color={enabled ? "blue" : "gray"}>{t(enabled ? "已启用" : "已停用")}</Badge>
        </div>
      </div>

      <form className="configuration-form" onSubmit={(event) => void save(event)}>
        <label className="configuration-wide">
          <Text size="1" color="gray">API Endpoint</Text>
          <TextField.Root
            type="url"
            value={baseUrl}
            onChange={(event) => setBaseUrl(event.target.value)}
            placeholder="https://apihub.agnes-ai.com/v1/images/generations"
            required
          />
        </label>
        <label>
          <Text size="1" color="gray">{t("模型名称")}</Text>
          <TextField.Root value={modelName} onChange={(event) => setModelName(event.target.value)} placeholder="agnes-image-2.0-flash" required />
        </label>
        <label className="configuration-wide">
          <Text size="1" color="gray">{t("首次图生图系统提示词")}</Text>
          <TextArea
            value={systemPrompt}
            onChange={(event) => setSystemPrompt(event.target.value)}
            minLength={1}
            maxLength={12000}
            rows={9}
            placeholder={t("仅平台管理员可见；首次生成时自动使用，图片审核界面不会展示。")}
            required
          />
          <Text size="1" color="gray">{t("首次生成统一使用此提示词；驳回后，操作者才可额外填写重试提示词。")}</Text>
        </label>
        <label>
          <Text size="1" color="gray">API Key</Text>
          <TextField.Root
            type="password"
            autoComplete="new-password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            placeholder={settings?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: settings.apiKeyHint ?? "" }) : t("请输入 API Key")}
            required={!settings?.apiKeyConfigured}
          />
        </label>
        <label>
          <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
          <TextField.Root type="number" min="60" max="360" value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("每分钟最大请求数（RPM）")}</Text>
          <TextField.Root type="number" min="1" max="10000" value={requestsPerMinute} onChange={(event) => setRequestsPerMinute(event.target.value)} required />
        </label>
        <label>
          <Text size="1" color="gray">{t("并发请求数")}</Text>
          <TextField.Root type="number" min="1" max="32" value={concurrencyLimit} onChange={(event) => setConcurrencyLimit(event.target.value)} required />
        </label>
        <label className="configuration-switch configuration-wide">
          <span><strong>{t("启用图生图")}</strong><small>{t("停用后，后续图像编辑请求不会调用该模型。")}</small></span>
          <Switch checked={enabled} onCheckedChange={setEnabled} />
        </label>
        <div className="configuration-wide configuration-format-summary">
          <Text size="1" color="gray">{t("支持的工作流")}</Text>
          <div className="configuration-statuses">
            <Badge color="violet">{t("图生图")}</Badge>
            <Badge color="blue">URL</Badge>
            <Badge color="jade">Base64</Badge>
          </div>
        </div>
        <div className="configuration-actions configuration-wide">
          <Button type="submit" size="3" disabled={!valid || saving} loading={saving}><FloppyDisk />{t(saving ? "保存中…" : "保存配置")}</Button>
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
        description={t("管理智能体、翻译与商品搜索配置。")}
        actions={<Button variant="soft" color="gray" onClick={() => window.location.reload()}><ArrowClockwise />{t("刷新")}</Button>}
      />

      <Tabs.Root value={section} onValueChange={changeSection}>
        <Tabs.List className="configuration-tabs">
          <Tabs.Trigger value="support-ai"><Brain />{t("智能体 API")}</Tabs.Trigger>
          <Tabs.Trigger value="translation"><Translate />{t("翻译 API")}</Tabs.Trigger>
          <Tabs.Trigger value="embedding"><Database />Embedding</Tabs.Trigger>
          <Tabs.Trigger value="rerank"><ArrowsDownUp />Rerank</Tabs.Trigger>
          <Tabs.Trigger value="image-generation"><ImageSquare />{t("图生图 API")}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="support-ai" className="configuration-tab-panel"><GenerationSettingsPanel /></Tabs.Content>
        <Tabs.Content value="translation" className="configuration-tab-panel"><TranslationApiSettingsPage embedded /></Tabs.Content>
        <Tabs.Content value="embedding" className="configuration-tab-panel"><EmbeddingSettingsPanel /></Tabs.Content>
        <Tabs.Content value="rerank" className="configuration-tab-panel"><RerankSettingsPanel /></Tabs.Content>
        <Tabs.Content value="image-generation" className="configuration-tab-panel"><ImageGenerationSettingsPanel /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
