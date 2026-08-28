import {
  Badge,
  Button,
  Card,
  Heading,
  Select,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  FloppyDisk,
  Translate,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  getTranslationSettings,
  updateTranslationSettings,
  type TranslationSettingsWriteInput,
} from "../api";
import { CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  CatalogTranslationExecutionMode,
  TranslationApiSettings,
  TranslationProviderKind,
  TranslationReasoningEffort,
} from "../types";


const reasoningOptions: TranslationReasoningEffort[] = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
];

const ALIYUN_ENDPOINT = "mt.cn-hangzhou.aliyuncs.com";
const ALIYUN_REGION = "cn-hangzhou";
const ALIYUN_EDITION = "translate_standard";
const DEEPLX_MODEL = "DeepLX";
const QWEN_BATCH_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1";
const QWEN_BATCH_MODEL = "qwen3.7-flash-2026-07-15";


export function TranslationApiSettingsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const { t } = useLocale();
  const [settings, setSettings] = useState<TranslationApiSettings>();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [provider, setProvider] =
    useState<TranslationProviderKind>("openai-compatible");
  const [catalogExecutionMode, setCatalogExecutionMode] =
    useState<CatalogTranslationExecutionMode>("REALTIME");
  const [enabled, setEnabled] = useState(true);
  const [baseUrl, setBaseUrl] = useState("");
  const [modelName, setModelName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [accessKeyId, setAccessKeyId] = useState("");
  const [batchBaseUrl, setBatchBaseUrl] = useState(QWEN_BATCH_BASE_URL);
  const [batchModelName, setBatchModelName] = useState(QWEN_BATCH_MODEL);
  const [batchApiKey, setBatchApiKey] = useState("");
  const [regionId, setRegionId] = useState(ALIYUN_REGION);
  const [timeoutSeconds, setTimeoutSeconds] = useState("20");
  const [maxTokens, setMaxTokens] = useState("16384");
  const [requestsPerMinute, setRequestsPerMinute] = useState("60");
  const [maxRetryCount, setMaxRetryCount] = useState("3");
  const [catalogBatchSize, setCatalogBatchSize] = useState("50");
  const [catalogBatchCharacters, setCatalogBatchCharacters] =
    useState("10000");
  const [catalogConcurrency, setCatalogConcurrency] = useState("3");
  const [reasoningEffort, setReasoningEffort] =
    useState<TranslationReasoningEffort>("low");

  const applySettings = useCallback((next: TranslationApiSettings) => {
    setSettings(next);
    setProvider(next.provider);
    setCatalogExecutionMode(next.catalogExecutionMode);
    setEnabled(next.enabled);
    setBaseUrl(next.baseUrl ?? "");
    setModelName(next.modelName ?? "");
    setRegionId(next.regionId ?? ALIYUN_REGION);
    setTimeoutSeconds(String(next.timeoutSeconds));
    setMaxTokens(String(next.maxTokens));
    setRequestsPerMinute(String(next.requestsPerMinute));
    setMaxRetryCount(String(next.maxRetryCount));
    setCatalogBatchSize(String(next.catalogBatchSize));
    setCatalogBatchCharacters(String(next.catalogBatchCharacters));
    setCatalogConcurrency(String(next.catalogConcurrency));
    setReasoningEffort(next.reasoningEffort);
    setApiKey("");
    setAccessKeyId("");
    setBatchBaseUrl(next.batchBaseUrl || QWEN_BATCH_BASE_URL);
    setBatchModelName(next.batchModelName || QWEN_BATCH_MODEL);
    setBatchApiKey("");
  }, []);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      applySettings(await getTranslationSettings());
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("翻译 API 配置读取失败"),
      );
    } finally {
      setLoading(false);
    }
  }, [applySettings, t]);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const clearResult = () => {
    setMessage("");
    setError("");
  };

  const input = useMemo<TranslationSettingsWriteInput>(() => ({
    provider,
    baseUrl: baseUrl.trim(),
    apiKey: apiKey.trim() || undefined,
    accessKeyId: accessKeyId.trim() || undefined,
    modelName: modelName.trim(),
    regionId: regionId.trim() || undefined,
    timeoutSeconds: Number(timeoutSeconds),
    maxTokens: Number(maxTokens),
    requestsPerMinute: Number(requestsPerMinute),
    maxRetryCount: Number(maxRetryCount),
    catalogBatchSize: Number(catalogBatchSize),
    catalogBatchCharacters: Number(catalogBatchCharacters),
    catalogConcurrency: Number(catalogConcurrency),
    catalogExecutionMode,
    batchBaseUrl: batchBaseUrl.trim(),
    batchModelName: batchModelName.trim(),
    batchApiKey: batchApiKey.trim() || undefined,
    reasoningEffort,
  }), [
    accessKeyId,
    apiKey,
    baseUrl,
    batchApiKey,
    batchBaseUrl,
    batchModelName,
    catalogBatchCharacters,
    catalogConcurrency,
    catalogExecutionMode,
    catalogBatchSize,
    maxRetryCount,
    maxTokens,
    modelName,
    provider,
    requestsPerMinute,
    reasoningEffort,
    regionId,
    timeoutSeconds,
  ]);

  const isAliyun = provider === "aliyun-alimt";
  const isDeepLX = provider === "deeplx";
  const isOpenAICompatible = provider === "openai-compatible";
  const storedCredentialsMatch = settings?.provider === provider;
  const hasApiSecret = Boolean(
    input.apiKey
      || (storedCredentialsMatch && settings?.apiKeyConfigured)
      || !enabled,
  );
  const hasDeepLXEndpoint = Boolean(
    input.baseUrl
      || (storedCredentialsMatch && settings?.apiKeyConfigured),
  );
  const hasAccessKeyId = Boolean(
    input.accessKeyId
      || (storedCredentialsMatch && settings?.accessKeyIdConfigured)
      || !enabled,
  );
  const hasBatchApiSecret = Boolean(
    input.batchApiKey
      || settings?.batchApiKeyConfigured,
  );
  const validRpm = Number.isInteger(input.requestsPerMinute)
    && input.requestsPerMinute >= 1
    && input.requestsPerMinute <= 10_000;
  const validRetryCount = Number.isInteger(input.maxRetryCount)
    && input.maxRetryCount >= 0
    && input.maxRetryCount <= 10;
  const validBatchSize = Number.isInteger(input.catalogBatchSize)
    && input.catalogBatchSize >= 1
    && input.catalogBatchSize <= 200;
  const validBatchCharacters = Number.isInteger(input.catalogBatchCharacters)
    && input.catalogBatchCharacters >= 1_000
    && input.catalogBatchCharacters <= 100_000;
  const validConcurrency = Number.isInteger(input.catalogConcurrency)
    && input.catalogConcurrency >= 1
    && input.catalogConcurrency <= 10;

  const formValid = Boolean(
    (isDeepLX ? hasDeepLXEndpoint : input.baseUrl)
      && (isAliyun ? input.regionId : (isDeepLX || input.modelName))
      && Number.isInteger(input.timeoutSeconds)
      && input.timeoutSeconds >= 1
      && input.timeoutSeconds <= 120
      && validRpm
      && validRetryCount
      && validBatchSize
      && validBatchCharacters
      && validConcurrency
      && (!isOpenAICompatible || (
        Number.isInteger(input.maxTokens)
        && input.maxTokens >= 512
        && input.maxTokens <= 32768
      ))
      && (isDeepLX ? hasDeepLXEndpoint : hasApiSecret)
      && (!isAliyun || hasAccessKeyId)
      && (input.catalogExecutionMode !== "QWEN_BATCH" || (
        input.batchBaseUrl
        && input.batchModelName
        && hasBatchApiSecret
      )),
  );
  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!formValid || saving) return;
    setSaving(true);
    setError("");
    setMessage("");
    try {
      const next = await updateTranslationSettings({ ...input, enabled });
      applySettings(next);
      setMessage(t("翻译 API 配置已保存并立即生效。"));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : t("翻译 API 配置保存失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  const changeProvider = (next: TranslationProviderKind) => {
    clearResult();
    setProvider(next);
    setApiKey("");
    setAccessKeyId("");
    if (next === "aliyun-alimt") {
      setBaseUrl(ALIYUN_ENDPOINT);
      setModelName(ALIYUN_EDITION);
      setRegionId(ALIYUN_REGION);
      setReasoningEffort("none");
      setMaxTokens("16384");
      return;
    }
    if (next === "deeplx") {
      setBaseUrl("");
      setModelName(DEEPLX_MODEL);
      setRegionId(ALIYUN_REGION);
      setReasoningEffort("none");
      setMaxTokens("16384");
      return;
    }
    if (provider !== "openai-compatible") {
      setBaseUrl("");
      setModelName("");
      setRegionId(ALIYUN_REGION);
      setReasoningEffort("low");
    }
  };

  return (
    <div className={embedded ? "core-configuration-embedded" : "core-workspace"}>
      {!embedded ? (
        <CorePageHeading
          eyebrow={t("平台设置")}
          title={t("翻译 API")}
          description={t("管理翻译服务配置。")}
          actions={(
            <Button
              variant="soft"
              color="gray"
              disabled={loading}
              onClick={() => void loadSettings()}
            >
              <ArrowClockwise />
              {t("刷新配置")}
            </Button>
          )}
        />
      ) : null}

      {loading && !settings ? (
        <CoreLoading label={t("正在读取翻译 API 配置")} />
      ) : null}
      {error && !settings ? (
        <CoreError message={error} onRetry={() => void loadSettings()} />
      ) : null}

      {settings ? (
        <>
          <Card className="core-translation-api-card">
            <div className="core-translation-api-heading">
              <span className="core-translation-api-icon">
                <Translate weight="duotone" />
              </span>
              <div>
                <Text size="1" color="gray" as="div">
                  {t(catalogExecutionMode === "QWEN_BATCH"
                    ? "Qwen Batch 文件翻译"
                    : isAliyun
                    ? "阿里云机器翻译"
                    : (isDeepLX ? "DeepLX 翻译" : "OpenAI 兼容接口"))}
                </Text>
                <Heading size="5">{t("全局翻译服务")}</Heading>
                <Text size="2" color="gray">
                  {t("选择翻译方式并调整运行参数。")}
                </Text>
              </div>
              <div className="core-translation-api-status">
                <Badge color={settings.enabled ? "jade" : "gray"}>
                  {t(settings.enabled ? "已启用" : "服务已停用")}
                </Badge>
              </div>
            </div>

            <form className="core-translation-api-form" onSubmit={(event) => void saveSettings(event)}>
              <label className="core-translation-api-wide">
                <Text size="1" color="gray">{t("商品翻译执行方式")}</Text>
                <Select.Root
                  value={catalogExecutionMode}
                  onValueChange={(value) => {
                    clearResult();
                    setCatalogExecutionMode(value as CatalogTranslationExecutionMode);
                  }}
                >
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="QWEN_BATCH">
                      {t("Qwen Batch 文件翻译")}
                    </Select.Item>
                    <Select.Item value="REALTIME">
                      {t("实时大模型 / 机器翻译")}
                    </Select.Item>
                  </Select.Content>
                </Select.Root>
                <Text size="1" color="gray">
                  {t(catalogExecutionMode === "QWEN_BATCH"
                    ? "全量目录异步提交到百炼 Batch，按文本去重并复用历史译文；新增少量商品时可切回实时翻译。"
                    : "商品任务按当前实时服务商执行；客服与前台即时翻译也继续使用此配置。")}
                </Text>
              </label>

              {catalogExecutionMode === "QWEN_BATCH" ? (
                <div className="core-translation-batch-settings core-translation-api-wide">
                  <div className="core-translation-batch-heading">
                    <div>
                      <Text size="2" weight="bold" as="div">
                        {t("Qwen Batch 配置")}
                      </Text>
                      <Text size="1" color="gray">
                        {t("固定关闭思考模式，任务完成后自动校验 custom_id、写入翻译记忆并发布语言包。")}
                      </Text>
                    </div>
                    <Badge color="jade" variant="soft">
                      {t("Batch 计费 5 折")}
                    </Badge>
                  </div>
                  <div className="core-translation-batch-fields">
                    <label>
                      <Text size="1" color="gray">{t("Batch Base URL")}</Text>
                      <TextField.Root
                        type="url"
                        value={batchBaseUrl}
                        onChange={(event) => {
                          clearResult();
                          setBatchBaseUrl(event.target.value);
                        }}
                        placeholder={QWEN_BATCH_BASE_URL}
                        required
                      />
                    </label>
                    <label>
                      <Text size="1" color="gray">{t("Batch 模型")}</Text>
                      <TextField.Root
                        value={batchModelName}
                        onChange={(event) => {
                          clearResult();
                          setBatchModelName(event.target.value);
                        }}
                        placeholder={QWEN_BATCH_MODEL}
                        required
                      />
                    </label>
                    <label className="core-translation-api-wide">
                      <Text size="1" color="gray">{t("Batch API Key")}</Text>
                      <TextField.Root
                        type="password"
                        autoComplete="new-password"
                        value={batchApiKey}
                        onChange={(event) => {
                          clearResult();
                          setBatchApiKey(event.target.value);
                        }}
                        placeholder={hasBatchApiSecret
                          ? t("已从 Qwen 配置复制 {hint}，留空则保持不变", {
                              hint: settings.batchApiKeyHint ?? settings.apiKeyHint ?? "",
                            })
                          : t("请输入百炼 API Key")}
                        required={!hasBatchApiSecret}
                      />
                    </label>
                  </div>
                </div>
              ) : null}

              <label className="core-translation-api-wide">
                <Text size="1" color="gray">{t("实时翻译服务商")}</Text>
                <Select.Root
                  value={provider}
                  onValueChange={(value) => {
                    changeProvider(value as TranslationProviderKind);
                  }}
                >
                  <Select.Trigger />
                  <Select.Content>
                    <Select.Item value="deeplx">
                      {t("DeepLX 翻译")}
                    </Select.Item>
                    <Select.Item value="aliyun-alimt">
                      {t("阿里云机器翻译（通用版）")}
                    </Select.Item>
                    <Select.Item value="openai-compatible">
                      {t("大模型兼容接口")}
                    </Select.Item>
                  </Select.Content>
                </Select.Root>
                <Text size="1" color="gray">
                  {t(isAliyun
                    ? "适合大批量商品内容翻译。"
                    : (isDeepLX
                      ? "使用 DeepLX 接口进行低成本机器翻译。"
                      : "适合需要上下文理解的翻译内容。"))}
                </Text>
              </label>

              <div className="core-translation-api-switch">
                <span>
                  <Text size="2" weight="bold" as="div">{t("启用翻译服务")}</Text>
                  <Text size="1" color="gray">
                    {t("关闭后，所有翻译任务将暂停。")}
                  </Text>
                </span>
                <Switch
                  checked={enabled}
                  onCheckedChange={(checked) => {
                    clearResult();
                    setEnabled(checked);
                  }}
                />
              </div>

              {isAliyun ? (
                <>
                  <label>
                    <Text size="1" color="gray">{t("地域")}</Text>
                    <TextField.Root
                      value={regionId}
                      onChange={(event) => {
                        clearResult();
                        setRegionId(event.target.value);
                      }}
                      placeholder={ALIYUN_REGION}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("服务 Endpoint")}</Text>
                    <TextField.Root
                      value={baseUrl}
                      onChange={(event) => {
                        clearResult();
                        setBaseUrl(event.target.value);
                      }}
                      placeholder={ALIYUN_ENDPOINT}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("AccessKey ID")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={accessKeyId}
                      onChange={(event) => {
                        clearResult();
                        setAccessKeyId(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.accessKeyIdConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.accessKeyIdHint ?? "",
                            })
                          : t("请输入 AccessKey ID")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.accessKeyIdConfigured
                      )}
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("AccessKey Secret")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        clearResult();
                        setApiKey(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.apiKeyConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.apiKeyHint ?? "",
                            })
                          : t("请输入 AccessKey Secret")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.apiKeyConfigured
                      )}
                    />
                  </label>
                </>
              ) : isDeepLX ? (
                <label className="core-translation-api-wide">
                  <Text size="1" color="gray">
                    {t("DeepLX 完整接口地址")}
                  </Text>
                  <TextField.Root
                    type="password"
                    autoComplete="new-password"
                    value={baseUrl}
                    onChange={(event) => {
                      clearResult();
                      setBaseUrl(event.target.value);
                    }}
                    placeholder={
                      storedCredentialsMatch && settings.apiKeyConfigured
                        ? t("接口地址已加密保存，留空则保持不变")
                        : "https://api.deeplx.org/<token>/translate"
                    }
                    required={!((
                      storedCredentialsMatch && settings.apiKeyConfigured
                    ))}
                  />
                  <Text size="1" color="gray">
                    {t("请填写以 /translate 结尾的完整地址；地址中的 Token 会加密保存。")}
                  </Text>
                </label>
              ) : (
                <>
                  <label className="core-translation-api-wide">
                    <Text size="1" color="gray">{t("Base URL")}</Text>
                    <TextField.Root
                      type="url"
                      value={baseUrl}
                      onChange={(event) => {
                        clearResult();
                        setBaseUrl(event.target.value);
                      }}
                      placeholder="https://api.example.com"
                      required
                    />
                    <Text size="1" color="gray">
                      {t("可以填写服务根地址、/v1，或完整的 /v1/chat/completions 地址。")}
                    </Text>
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("模型")}</Text>
                    <TextField.Root
                      value={modelName}
                      onChange={(event) => {
                        clearResult();
                        setModelName(event.target.value);
                      }}
                      placeholder="DeepSeek-V4-Flash-0731"
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("API Key")}</Text>
                    <TextField.Root
                      type="password"
                      autoComplete="new-password"
                      value={apiKey}
                      onChange={(event) => {
                        clearResult();
                        setApiKey(event.target.value);
                      }}
                      placeholder={
                        storedCredentialsMatch && settings.apiKeyConfigured
                          ? t("已配置 {hint}，留空则保持不变", {
                              hint: settings.apiKeyHint ?? "",
                            })
                          : t("请输入 API Key")
                      }
                      required={enabled && !(
                        storedCredentialsMatch && settings.apiKeyConfigured
                      )}
                    />
                  </label>
                </>
              )}

              <label>
                <Text size="1" color="gray">{t("请求超时（秒）")}</Text>
                <TextField.Root
                  type="number"
                  min="1"
                  max="120"
                  value={timeoutSeconds}
                  onChange={(event) => {
                    clearResult();
                    setTimeoutSeconds(event.target.value);
                  }}
                  required
                />
              </label>

              <label>
                <Text size="1" color="gray">
                  {t("每分钟最大请求数（RPM）")}
                </Text>
                <TextField.Root
                  type="number"
                  min="1"
                  max="10000"
                  value={requestsPerMinute}
                  onChange={(event) => {
                    clearResult();
                    setRequestsPerMinute(event.target.value);
                  }}
                  required
                />
                <Text size="1" color="gray">
                  {t("达到上限后请求会排队等待，已完成的翻译和断点不会丢失。")}
                </Text>
              </label>

              {catalogExecutionMode === "REALTIME" ? (
              <div className="core-translation-batch-settings core-translation-api-wide">
                <div className="core-translation-batch-heading">
                  <div>
                    <Text size="2" weight="bold" as="div">
                      {t("商品批量翻译")}
                    </Text>
                    <Text size="1" color="gray">
                      {t("同时满足 SKU 数量和字符上限时才会放入同一次请求。")}
                    </Text>
                  </div>
                  <Badge color="blue" variant="soft">
                    {t("全量与增量任务")}
                  </Badge>
                </div>
                <div className="core-translation-batch-fields">
                  <label>
                    <Text size="1" color="gray">
                      {t("每批最多 SKU 数")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="1"
                      max="200"
                      value={catalogBatchSize}
                      onChange={(event) => {
                        clearResult();
                        setCatalogBatchSize(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("默认 50，可设置 1–200。")}
                    </Text>
                  </label>
                  <label>
                    <Text size="1" color="gray">
                      {t("单批字符上限")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="1000"
                      max="100000"
                      step="1000"
                      value={catalogBatchCharacters}
                      onChange={(event) => {
                        clearResult();
                        setCatalogBatchCharacters(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("默认 10,000，超出后自动拆分，不会丢失断点。")}
                    </Text>
                  </label>
                  <label>
                    <Text size="1" color="gray">
                      {t("同时请求数")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="1"
                      max="10"
                      value={catalogConcurrency}
                      onChange={(event) => {
                        clearResult();
                        setCatalogConcurrency(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("默认 3；会同时发起多个批次，但仍受 RPM 限制。")}
                    </Text>
                  </label>
                  <label>
                    <Text size="1" color="gray">
                      {t("失败后最多重试次数")}
                    </Text>
                    <TextField.Root
                      type="number"
                      min="0"
                      max="10"
                      value={maxRetryCount}
                      onChange={(event) => {
                        clearResult();
                        setMaxRetryCount(event.target.value);
                      }}
                      required
                    />
                    <Text size="1" color="gray">
                      {t("仅临时错误会自动重试；次数不包含首次请求，建议设置为 2–3。")}
                    </Text>
                  </label>
                </div>
              </div>
              ) : null}

              {isOpenAICompatible ? (
                <>
                  <label>
                    <Text size="1" color="gray">{t("最大输出 Tokens")}</Text>
                    <TextField.Root
                      type="number"
                      min="512"
                      max="32768"
                      step="128"
                      value={maxTokens}
                      onChange={(event) => {
                        clearResult();
                        setMaxTokens(event.target.value);
                      }}
                      required
                    />
                  </label>

                  <label>
                    <Text size="1" color="gray">{t("推理强度")}</Text>
                    <Select.Root
                      value={reasoningEffort}
                      onValueChange={(value) => {
                        clearResult();
                        setReasoningEffort(value as TranslationReasoningEffort);
                      }}
                    >
                      <Select.Trigger />
                      <Select.Content>
                        {reasoningOptions.map((option) => (
                          <Select.Item key={option} value={option}>
                            {t(option)}
                          </Select.Item>
                        ))}
                      </Select.Content>
                    </Select.Root>
                  </label>
                </>
              ) : null}

              <div className="core-translation-api-actions">
                <Button
                  type="submit"
                  size="3"
                  disabled={!formValid || saving}
                >
                  <FloppyDisk />
                  {t(saving ? "保存中…" : "保存并生效")}
                </Button>
              </div>
            </form>

            {message ? <Text size="2" color="green">{message}</Text> : null}
            {error && settings ? <Text size="2" color="red">{error}</Text> : null}
          </Card>

        </>
      ) : null}
    </div>
  );
}
