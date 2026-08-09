import {
  Badge,
  Button,
  Card,
  Heading,
  Switch,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  Brain,
  CheckCircle,
  Database,
  FloppyDisk,
  Key,
  ShieldCheck,
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
  getEmbeddingSettings,
  getSupportAIProviderSettings,
  updateEmbeddingSettings,
  updateSupportAIProviderSettings,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { EmbeddingSettings, SupportAIProviderSettings } from "../types";
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
  const [settings, setSettings] = useState<SupportAIProviderSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [timeoutSeconds, setTimeoutSeconds] = useState("45");
  const [maxOutputTokens, setMaxOutputTokens] = useState("2048");
  const [temperature, setTemperature] = useState("0.1");

  const apply = useCallback((next: SupportAIProviderSettings) => {
    setSettings(next);
    setEnabled(next.enabled);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName ?? "");
    setTimeoutSeconds(String(next.timeoutSeconds));
    setMaxOutputTokens(String(next.maxOutputTokens));
    setTemperature(String(next.temperature));
    setApiKey("");
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      apply(await getSupportAIProviderSettings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("大模型配置读取失败"));
    } finally {
      setLoading(false);
    }
  }, [apply, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const valid = useMemo(() => {
    const timeout = Number(timeoutSeconds);
    const tokens = Number(maxOutputTokens);
    const temp = Number(temperature);
    return Boolean(
      baseUrl.trim()
      && modelName.trim()
      && (!enabled || apiKey.trim() || settings?.apiKeyConfigured)
      && Number.isInteger(timeout) && timeout >= 1 && timeout <= 180
      && Number.isInteger(tokens) && tokens >= 128 && tokens <= 32768
      && Number.isFinite(temp) && temp >= 0 && temp <= 2,
    );
  }, [apiKey, baseUrl, enabled, maxOutputTokens, modelName, settings?.apiKeyConfigured, temperature, timeoutSeconds]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!valid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      apply(await updateSupportAIProviderSettings({
        enabled,
        baseUrl: baseUrl.trim(),
        modelName: modelName.trim(),
        apiKey: apiKey.trim() || undefined,
        timeoutSeconds: Number(timeoutSeconds),
        maxOutputTokens: Number(maxOutputTokens),
        temperature: Number(temperature),
      }));
      setMessage(t("智能客服大模型配置已保存并立即生效。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("大模型配置保存失败"));
    } finally {
      setSaving(false);
    }
  };

  if (loading && !settings) return <CoreLoading label={t("正在读取智能客服大模型配置")} />;
  if (error && !settings) return <CoreError message={error} onRetry={() => void load()} />;

  return (
    <Card className="configuration-provider-card">
      <div className="configuration-card-heading">
        <span><Brain weight="duotone" /></span>
        <div>
          <Text size="1" color="gray">{t("OpenAI-compatible /v1/chat/completions")}</Text>
          <Heading size="5">{t("智能客服生成模型")}</Heading>
          <Text size="2" color="gray">{t("负责语言确认、基于证据生成回答和置信度判断，不承担商品向量化。")}</Text>
        </div>
        <div className="configuration-statuses">
          <Badge color={settings?.enabled && settings.apiKeyConfigured ? "jade" : "gray"}>
            {t(settings?.enabled && settings.apiKeyConfigured ? "可供调用" : "未启用")}
          </Badge>
          <Badge color={settings?.source === "database" ? "blue" : "gray"}>{t(sourceLabel(settings?.source))}</Badge>
        </div>
      </div>

      <form className="configuration-form" onSubmit={(event) => void save(event)}>
        <label className="configuration-switch configuration-wide">
          <span>
            <strong>{t("启用智能客服生成模型")}</strong>
            <small>{t("关闭后，所有商家的自动回复都会停用；历史运行记录和知识库不会删除。")}</small>
          </span>
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
            placeholder={settings?.apiKeyConfigured ? t("已配置 {hint}，留空保持不变", { hint: settings.apiKeyHint ?? "" }) : t("请输入 API Key")}
            required={enabled && !settings?.apiKeyConfigured}
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
          <Button type="submit" size="3" disabled={!valid || saving}><FloppyDisk />{t(saving ? "保存中…" : "保存并生效")}</Button>
          <Text size="1" color="gray"><Key /> {t("密钥使用平台主密钥加密保存，读取接口只返回脱敏提示。")}</Text>
        </div>
      </form>
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
        description={t("集中管理全站第三方 API。密钥只在平台层保存，商家仅配置自己的智能客服运行策略。")}
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
