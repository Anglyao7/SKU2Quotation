import {
  Badge,
  Button,
  Card,
  Heading,
  Tabs,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  CheckCircle,
  Database,
  FloppyDisk,
  ShieldCheck,
  Translate,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { getEmbeddingSettings, updateEmbeddingSettings } from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { EmbeddingSettings } from "../types";
import { TranslationApiSettingsPage } from "./TranslationApiSettingsPage";
import "./ConfigurationCenterPage.css";

type ConfigurationSection = "translation" | "embedding";

const SECTIONS = new Set<ConfigurationSection>(["translation", "embedding"]);

function sourceLabel(source?: string) {
  if (source === "database") return "后台配置";
  if (source === "environment") return "环境变量";
  if (source === "deterministic") return "本地降级模型";
  return "未配置";
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
    && Number.isInteger(Number(dimensions))
    && Number(dimensions) >= 8
    && Number(dimensions) <= 8192
    && Number.isInteger(Number(timeoutSeconds))
    && Number(timeoutSeconds) >= 1
    && Number(timeoutSeconds) <= 120,
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
  const section: ConfigurationSection = requested && SECTIONS.has(requested) ? requested : "translation";

  const changeSection = (next: string) => {
    const value = next as ConfigurationSection;
    setSearchParams(value === "translation" ? {} : { section: value }, { replace: true });
  };

  return (
    <div className="core-workspace configuration-center-page">
      <CorePageHeading
        eyebrow={t("平台设置")}
        title={t("配置中心")}
        description={t("集中管理翻译与向量检索 API；智能客服的模型、店铺绑定和运行策略请在智能体详情中维护。")}
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
          <Tabs.Trigger value="translation"><Translate />{t("翻译 API")}</Tabs.Trigger>
          <Tabs.Trigger value="embedding"><Database />Embedding</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="translation" className="configuration-tab-panel"><TranslationApiSettingsPage embedded /></Tabs.Content>
        <Tabs.Content value="embedding" className="configuration-tab-panel"><EmbeddingSettingsPanel /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}
