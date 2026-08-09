import {
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Select,
  Switch,
  Tabs,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  Brain,
  Check,
  CheckCircle,
  Database,
  FileArrowUp,
  FileText,
  GlobeHemisphereWest,
  MagnifyingGlass,
  PaperPlaneTilt,
  Prohibit,
  Quotes,
  Robot,
  ShieldCheck,
  UserSwitch,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { Link } from "react-router-dom";
import {
  approveSupportAIKnowledgeSource,
  getSupportAIIngestionJob,
  getSupportAISettings,
  listSupportAIKnowledgeSources,
  listSupportAIRuns,
  reindexSupportAIKnowledgeSource,
  revokeSupportAIKnowledgeSource,
  runSupportAITest,
  updateSupportAISettings,
  uploadSupportAIKnowledgeSource,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate, percent } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIIngestionJob,
  SupportAIKnowledgeSource,
  SupportAIRun,
  SupportAISettings,
  SupportCitation,
} from "../types";
import "./SupportAIPage.css";

const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "RUNNING"]);

const STATUS_COLOR: Record<string, "gray" | "blue" | "amber" | "jade" | "red"> = {
  QUEUED: "gray",
  RUNNING: "blue",
  PROCESSING: "blue",
  READY: "amber",
  APPROVED: "jade",
  SUCCEEDED: "jade",
  NEEDS_REVIEW: "amber",
  HANDOFF: "amber",
  REVOKED: "gray",
  CANCELLED: "gray",
  SKIPPED: "gray",
  FAILED: "red",
};

function EvidenceList({ evidence }: { evidence: SupportCitation[] }) {
  const { t } = useLocale();
  if (!evidence.length) {
    return <Text size="1" color="gray">{t("本次没有可用证据。")}</Text>;
  }
  return (
    <div className="support-ai-evidence-list">
      {evidence.map((item) => (
        <article key={`${item.sourceType}:${item.sourceEntityId}:${item.citationNumber}`}>
          <span>[{item.citationNumber}]</span>
          <div>
            <strong>{item.sourceTitle}</strong>
            <small>{item.sourceType === "SKU" ? "SKU" : t("企业文件")} · v{item.sourceVersion} · {percent(item.score)}</small>
            <p>{item.excerpt}</p>
          </div>
        </article>
      ))}
    </div>
  );
}

function RunDetail({ run }: { run: SupportAIRun }) {
  const { t } = useLocale();
  return (
    <Card className="support-ai-run-detail">
      <div className="support-ai-panel-heading">
        <div>
          <Text size="1" color="gray">{t("运行追踪")} · {run.triggerType}</Text>
          <Heading size="4">{run.question}</Heading>
        </div>
        <Badge color={STATUS_COLOR[run.status] || "gray"}>{t(run.status)}</Badge>
      </div>
      <div className="support-ai-run-facts">
        <span><small>{t("识别语言")}</small><strong>{run.detectedLanguage || "—"}</strong></span>
        <span><small>{t("置信度")}</small><strong>{run.confidence === undefined ? "—" : percent(run.confidence)}</strong></span>
        <span><small>{t("证据数")}</small><strong>{run.retrievalCount}</strong></span>
        <span><small>{t("模型")}</small><strong>{run.modelDisplayName || "—"}</strong></span>
      </div>
      {run.normalizedQuery && run.normalizedQuery !== run.question ? (
        <div className="support-ai-normalized-query">
          <Text size="1" color="gray">{t("仅供检索的归一化查询")}</Text>
          <p>{run.normalizedQuery}</p>
        </div>
      ) : null}
      {run.answer ? (
        <section className="support-ai-answer">
          <Text size="1" color="gray">{t("最终回答")}</Text>
          <p dir="auto">{run.answer}</p>
        </section>
      ) : null}
      {run.handoffReason ? <Text size="2" color="orange"><UserSwitch /> {t("转人工：")}{run.handoffReason}</Text> : null}
      {run.errorMessage ? <Text size="2" color="red">{run.errorMessage}</Text> : null}
      <section>
        <Text size="1" color="gray">{t("引用证据")}</Text>
        <EvidenceList evidence={run.evidence} />
      </section>
    </Card>
  );
}

export function SupportAIPage() {
  const { hasPermission } = useCoreAuth();
  const { locale, t } = useLocale();
  const canManage = hasPermission("support.ai.manage");
  const canInspect = hasPermission("support.ai.inspect");
  const canTest = hasPermission("support.ai.test");
  const canManageKnowledge = hasPermission("knowledge.manage");
  const canApproveKnowledge = hasPermission("knowledge.approve");

  const [settings, setSettings] = useState<SupportAISettings>();
  const [sources, setSources] = useState<SupportAIKnowledgeSource[]>([]);
  const [runs, setRuns] = useState<SupportAIRun[]>([]);
  const [activeJobs, setActiveJobs] = useState<Record<string, SupportAIIngestionJob>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");

  const [enabled, setEnabled] = useState(false);
  const [skuEnabled, setSkuEnabled] = useState(true);
  const [fileEnabled, setFileEnabled] = useState(true);
  const [multilingualEnabled, setMultilingualEnabled] = useState(true);
  const [retrievalScore, setRetrievalScore] = useState("0.12");
  const [answerConfidence, setAnswerConfidence] = useState("0.65");
  const [maxSources, setMaxSources] = useState("5");
  const [dailyLimit, setDailyLimit] = useState("500");
  const [systemPrompt, setSystemPrompt] = useState("");

  const [uploadFile, setUploadFile] = useState<File>();
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadDescription, setUploadDescription] = useState("");
  const [uploadClassification, setUploadClassification] = useState<"PUBLIC" | "CUSTOMER_APPROVED">("CUSTOMER_APPROVED");
  const [uploadLanguage, setUploadLanguage] = useState("und");

  const [testQuestion, setTestQuestion] = useState("");
  const [testLocale, setTestLocale] = useState("zh-CN");
  const [testRun, setTestRun] = useState<SupportAIRun>();

  const applySettings = useCallback((next: SupportAISettings) => {
    setSettings(next);
    setEnabled(next.enabled);
    setSkuEnabled(next.skuKnowledgeEnabled);
    setFileEnabled(next.fileKnowledgeEnabled);
    setMultilingualEnabled(next.multilingualEnabled);
    setRetrievalScore(String(next.minRetrievalScore));
    setAnswerConfidence(String(next.minAnswerConfidence));
    setMaxSources(String(next.maxSources));
    setDailyLimit(String(next.dailyAutoReplyLimit));
    setSystemPrompt(next.systemPrompt ?? "");
  }, []);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const [nextSettings, nextSources, nextRuns] = await Promise.all([
        (canManage || canInspect) ? getSupportAISettings() : Promise.resolve(undefined),
        (canManageKnowledge || canInspect) ? listSupportAIKnowledgeSources() : Promise.resolve([]),
        canInspect ? listSupportAIRuns({ pageSize: 30 }) : Promise.resolve({ items: [], total: 0, page: 1, pageSize: 30, pages: 1 }),
      ]);
      if (nextSettings) applySettings(nextSettings);
      setSources(nextSources);
      setRuns(nextRuns.items);
      setError("");
    } catch (reason) {
      if (!quiet) setError(reason instanceof Error ? reason.message : t("智能客服数据读取失败"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [applySettings, canInspect, canManage, canManageKnowledge, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const activeJobIds = useMemo(
    () => Object.values(activeJobs).filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).map((job) => job.id),
    [activeJobs],
  );

  useEffect(() => {
    if (!activeJobIds.length) return;
    let stopped = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const jobs = await Promise.all(activeJobIds.map(getSupportAIIngestionJob));
        if (stopped) return;
        setActiveJobs((current) => {
          const next = { ...current };
          jobs.forEach((job) => { next[job.sourceId] = job; });
          return next;
        });
        if (jobs.some((job) => !ACTIVE_JOB_STATUSES.has(job.status))) await load(true);
      } catch {
        // The primary reload path will expose durable ingestion failures.
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 1600);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [activeJobIds.join("|"), load]);

  const settingsValid = Boolean(
    Number(retrievalScore) >= 0 && Number(retrievalScore) <= 1
    && Number(answerConfidence) >= 0 && Number(answerConfidence) <= 1
    && Number.isInteger(Number(maxSources)) && Number(maxSources) >= 1 && Number(maxSources) <= 12
    && Number.isInteger(Number(dailyLimit)) && Number(dailyLimit) >= 1,
  );

  const saveSettings = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canManage || !settingsValid || busy) return;
    setBusy("settings");
    setError("");
    setMessage("");
    try {
      applySettings(await updateSupportAISettings({
        enabled,
        skuKnowledgeEnabled: skuEnabled,
        fileKnowledgeEnabled: fileEnabled,
        multilingualEnabled,
        minRetrievalScore: Number(retrievalScore),
        minAnswerConfidence: Number(answerConfidence),
        maxSources: Number(maxSources),
        dailyAutoReplyLimit: Number(dailyLimit),
        systemPrompt: systemPrompt.trim() || undefined,
        handoffMessages: settings?.handoffMessages || {},
      }));
      setMessage(t("智能客服运行策略已保存。新消息将使用最新提示词版本。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("运行策略保存失败"));
    } finally {
      setBusy("");
    }
  };

  const uploadKnowledge = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!uploadFile || !canManageKnowledge || busy) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      const result = await uploadSupportAIKnowledgeSource({
        file: uploadFile,
        title: uploadTitle.trim() || uploadFile.name.replace(/\.[^.]+$/, ""),
        description: uploadDescription.trim() || undefined,
        classification: uploadClassification,
        language: uploadLanguage.trim() || "und",
      });
      setSources((current) => [result.source, ...current.filter((item) => item.id !== result.source.id)]);
      setActiveJobs((current) => ({ ...current, [result.source.id]: result.job }));
      setUploadFile(undefined);
      setUploadTitle("");
      setUploadDescription("");
      const input = document.getElementById("support-ai-file-input") as HTMLInputElement | null;
      if (input) input.value = "";
      setMessage(t("文件已安全上传，正在解析、分块和向量化；完成后需要人工批准。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识文件上传失败"));
    } finally {
      setBusy("");
    }
  };

  const sourceAction = async (source: SupportAIKnowledgeSource, action: "approve" | "reindex" | "revoke") => {
    if (busy) return;
    setBusy(`${action}:${source.id}`);
    setError("");
    setMessage("");
    try {
      if (action === "approve") {
        const next = await approveSupportAIKnowledgeSource(source.id);
        setSources((current) => current.map((item) => item.id === next.id ? next : item));
        setMessage(t("知识文件已批准，后续回答可以引用这份来源。"));
      } else if (action === "reindex") {
        const job = await reindexSupportAIKnowledgeSource(source.id);
        setActiveJobs((current) => ({ ...current, [source.id]: job }));
        setSources((current) => current.map((item) => item.id === source.id
          ? { ...item, status: item.status === "APPROVED" ? "APPROVED" : "PROCESSING" }
          : item));
        setMessage(t("已重新提交解析与向量化任务。"));
      } else {
        const next = await revokeSupportAIKnowledgeSource(source.id);
        setSources((current) => current.map((item) => item.id === next.id ? next : item));
        setMessage(t("知识来源已撤销，新的回答不会再检索它。"));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识来源操作失败"));
    } finally {
      setBusy("");
    }
  };

  const executeTest = async () => {
    if (!canTest || !testQuestion.trim() || busy) return;
    setBusy("test");
    setError("");
    setTestRun(undefined);
    try {
      const next = await runSupportAITest(testQuestion.trim(), testLocale);
      setTestRun(next);
      setRuns((current) => [next, ...current.filter((item) => item.id !== next.id)].slice(0, 30));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能客服试跑失败"));
    } finally {
      setBusy("");
    }
  };

  const approvedSources = sources.filter((source) => source.status === "APPROVED").length;
  return (
    <div className="core-workspace support-ai-page">
      <CorePageHeading
        eyebrow={t("客户沟通")}
        title={t("AI 智能客服")}
        description={t("用客户安全的 SKU 数据和已批准企业文件回答问题，逐条保存引用，并在证据不足时转交人工。")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray"><Link to="/console/support"><UserSwitch />{t("打开客服会话")}</Link></Button>
            <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}><ArrowClockwise />{t("刷新")}</Button>
          </>
        )}
      />

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {message ? <Card className="support-ai-success"><CheckCircle weight="fill" /><Text size="2">{message}</Text></Card> : null}
      {loading ? <CoreLoading label={t("正在读取智能客服配置与运行记录")} /> : null}

      {!loading ? (
        <>
          <section className="support-ai-overview">
            <Card><Robot weight="duotone" /><div><Text size="1" color="gray">{t("当前店铺")}</Text><strong>{t(settings?.enabled ? "启用" : "关闭")}</strong><small>{t(settings?.enabled ? "客户消息可触发智能回复" : "客服会话由人工处理")}</small></div></Card>
            <Card><Brain weight="duotone" /><div><Text size="1" color="gray">{t("服务模型")}</Text><strong>{settings?.modelDisplayName || t("智能客服")}</strong><small>{t("模型接入由平台统一维护")}</small></div></Card>
            <Card><Database weight="duotone" /><div><Text size="1" color="gray">{t("SKU 知识")}</Text><strong>{settings?.indexedSkuProducts ?? 0}</strong><small>{t("仅客户安全字段")}</small></div></Card>
            <Card><FileText weight="duotone" /><div><Text size="1" color="gray">{t("已批准文件")}</Text><strong>{settings?.approvedFileSources ?? approvedSources}</strong><small>{t("可被回答引用")}</small></div></Card>
          </section>

          <Tabs.Root defaultValue={canManage ? "policy" : canManageKnowledge ? "knowledge" : "runs"}>
            <Tabs.List className="support-ai-tabs">
              {canManage ? <Tabs.Trigger value="policy"><ShieldCheck />{t("运行策略")}</Tabs.Trigger> : null}
              {(canManageKnowledge || canInspect) ? <Tabs.Trigger value="knowledge"><Database />{t("知识库")}</Tabs.Trigger> : null}
              {canTest ? <Tabs.Trigger value="test"><MagnifyingGlass />{t("问答试跑")}</Tabs.Trigger> : null}
              {canInspect ? <Tabs.Trigger value="runs"><Quotes />{t("运行与溯源")}</Tabs.Trigger> : null}
            </Tabs.List>

            {canManage ? (
              <Tabs.Content value="policy" className="support-ai-tab-panel">
                <Card className="support-ai-policy-card">
                  <div className="support-ai-panel-heading">
                    <div><Text size="1" color="gray">{t("当前店铺配置")}</Text><Heading size="5">{t("智能客服与安全门槛")}</Heading></div>
                    <Badge color={enabled ? "jade" : "gray"}>{t(enabled ? "启用" : "关闭")}</Badge>
                  </div>
                  <form className="support-ai-policy-form" onSubmit={(event) => void saveSettings(event)}>
                    <label className="support-ai-switch support-ai-wide"><span><strong>{t("启用智能客服")}</strong><small>{t("关闭时不会创建或发送 AI 回答；知识库、提示词、阈值和历史记录都会保留。")}</small></span><Switch checked={enabled} onCheckedChange={setEnabled} /></label>
                    <label className="support-ai-switch"><span><strong>{t("SKU 商品知识")}</strong><small>{t("只检索公开商品资料、公开报价与 MOQ；供应商名称、供应商 SKU、供应商评分不会参与向量化或回答。")}</small></span><Switch checked={skuEnabled} onCheckedChange={setSkuEnabled} /></label>
                    <label className="support-ai-switch"><span><strong>{t("企业文件知识")}</strong><small>{t("只检索已完成解析且经人工批准的文件版本。")}</small></span><Switch checked={fileEnabled} onCheckedChange={setFileEnabled} /></label>
                    <label className="support-ai-switch support-ai-wide"><span><strong>{t("多语言回答")}</strong><small>{t("保留客户原文并识别本次消息实际语言；必要时仅把查询翻译为内部检索语言，最终回答仍使用客户语言，SKU/型号等标识保持原样。")}</small></span><Switch checked={multilingualEnabled} onCheckedChange={setMultilingualEnabled} /></label>
                    <label><Text size="1" color="gray">{t("最低检索分数")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={retrievalScore} onChange={(event) => setRetrievalScore(event.target.value)} /></label>
                    <label><Text size="1" color="gray">{t("最低回答置信度")}</Text><TextField.Root type="number" min="0" max="1" step="0.01" value={answerConfidence} onChange={(event) => setAnswerConfidence(event.target.value)} /></label>
                    <label><Text size="1" color="gray">{t("单次最大来源数")}</Text><TextField.Root type="number" min="1" max="12" value={maxSources} onChange={(event) => setMaxSources(event.target.value)} /></label>
                    <label><Text size="1" color="gray">{t("每日自动回复上限")}</Text><TextField.Root type="number" min="1" max="100000" value={dailyLimit} onChange={(event) => setDailyLimit(event.target.value)} /></label>
                    <label className="support-ai-wide"><Text size="1" color="gray">{t("企业补充提示词（可选）")}</Text><TextArea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} maxLength={12000} placeholder={t("例如品牌语气、售前范围；不能用来绕过客户安全边界。")}/></label>
                    <div className="support-ai-actions support-ai-wide"><Button type="submit" disabled={!settingsValid || busy === "settings"}>{busy === "settings" ? t("保存中…") : t("保存店铺配置")}</Button><Text size="1" color="gray">{t("配置只影响当前店铺；文件知识库和 SKU 数据不会跨店铺读取。任何人工客服回复都会立即接管该会话。")}</Text></div>
                  </form>
                </Card>
              </Tabs.Content>
            ) : null}

            {(canManageKnowledge || canInspect) ? (
              <Tabs.Content value="knowledge" className="support-ai-tab-panel">
                {canManageKnowledge ? (
                  <Card className="support-ai-upload-card">
                    <div className="support-ai-panel-heading"><div><Text size="1" color="gray">{t("文件知识摄取")}</Text><Heading size="5">{t("上传企业资料")}</Heading></div><Badge color="blue">{t("安全存储 + 智能索引")}</Badge></div>
                    <form className="support-ai-upload-form" onSubmit={(event) => void uploadKnowledge(event)}>
                      <label className="support-ai-wide support-ai-file-field"><FileArrowUp /><span><strong>{uploadFile?.name || t("选择 PDF、DOCX、TXT 或 Markdown")}</strong><small>{t("最大 25 MB；文件会先进行安全扫描，再加密存储并异步解析。")}</small></span><input id="support-ai-file-input" type="file" accept=".pdf,.docx,.txt,.md" onChange={(event) => setUploadFile(event.target.files?.[0])} required /></label>
                      <label><Text size="1" color="gray">{t("知识标题")}</Text><TextField.Root value={uploadTitle} onChange={(event) => setUploadTitle(event.target.value)} placeholder={uploadFile?.name.replace(/\.[^.]+$/, "") || t("例如：品牌介绍 2026")} /></label>
                      <label><Text size="1" color="gray">{t("文件语言")}</Text><TextField.Root value={uploadLanguage} onChange={(event) => setUploadLanguage(event.target.value)} placeholder="und / zh-CN / en" /></label>
                      <label><Text size="1" color="gray">{t("客户可用分类")}</Text><Select.Root value={uploadClassification} onValueChange={(value) => setUploadClassification(value as "PUBLIC" | "CUSTOMER_APPROVED")}><Select.Trigger /><Select.Content><Select.Item value="CUSTOMER_APPROVED">{t("客户回答可用（需批准）")}</Select.Item><Select.Item value="PUBLIC">{t("公开资料（需批准）")}</Select.Item></Select.Content></Select.Root></label>
                      <label><Text size="1" color="gray">{t("说明（可选）")}</Text><TextField.Root value={uploadDescription} onChange={(event) => setUploadDescription(event.target.value)} /></label>
                      <div className="support-ai-actions support-ai-wide"><Button type="submit" disabled={!uploadFile || busy === "upload"}><FileArrowUp />{busy === "upload" ? t("上传中…") : t("上传并开始处理")}</Button><Text size="1" color="gray">{t("处理完成不会自动发布，必须由有审批权限的成员批准。")}</Text></div>
                    </form>
                  </Card>
                ) : null}

                <Card className="support-ai-source-card">
                  <div className="support-ai-panel-heading"><div><Text size="1" color="gray">{t("版本化来源")}</Text><Heading size="5">{t("企业文件知识")}</Heading></div><Badge color="gray">{sources.length}</Badge></div>
                  {!sources.length ? <CoreEmpty title={t("还没有企业文件知识")} description={t("上传品牌介绍、产品手册或服务政策，处理完成并批准后即可参与回答。")}/> : null}
                  <div className="support-ai-source-list">
                    {sources.map((source) => {
                      const job = activeJobs[source.id];
                      const processing = source.status === "PROCESSING" || Boolean(job && ACTIVE_JOB_STATUSES.has(job.status));
                      return (
                        <article key={source.id}>
                          <span className="support-ai-source-icon"><FileText weight="duotone" /></span>
                          <div className="support-ai-source-copy">
                            <div><strong>{source.title}</strong><Badge color={STATUS_COLOR[source.status] || "gray"}>{t(source.status)}</Badge></div>
                            <small>{source.originalFilename} · {(source.byteSize / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB · {source.chunkCount} {t("分块")} · v{source.version}</small>
                            {source.description ? <p>{source.description}</p> : null}
                            {processing ? <Progress value={job?.progress ?? 10} /> : null}
                            {source.failureMessage ? <small className="is-error">{source.failureMessage}</small> : null}
                          </div>
                          <div className="support-ai-source-actions">
                            {canApproveKnowledge && source.status === "READY" ? <Button size="1" onClick={() => void sourceAction(source, "approve")} disabled={Boolean(busy)}><Check />{t("批准")}</Button> : null}
                            {canManageKnowledge && !processing ? <Button size="1" variant="soft" color="gray" onClick={() => void sourceAction(source, "reindex")} disabled={Boolean(busy)}><ArrowClockwise />{t("重新处理")}</Button> : null}
                            {canManageKnowledge && source.status !== "REVOKED" && !processing ? <Button size="1" variant="ghost" color="red" onClick={() => void sourceAction(source, "revoke")} disabled={Boolean(busy)}><Prohibit />{t("撤销")}</Button> : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </Card>
              </Tabs.Content>
            ) : null}

            {canTest ? (
              <Tabs.Content value="test" className="support-ai-tab-panel">
                <div className="support-ai-test-grid">
                  <Card className="support-ai-test-card">
                    <div className="support-ai-panel-heading"><div><Text size="1" color="gray">{t("真实编排链路")}</Text><Heading size="5">{t("问答试跑")}</Heading></div><Brain weight="duotone" /></div>
                    <label><Text size="1" color="gray">{t("客户消息")}</Text><TextArea value={testQuestion} onChange={(event) => setTestQuestion(event.target.value)} maxLength={4000} placeholder={t("可以直接输入中文、English、Español、العربية 等客户原文。")}/></label>
                    <label><Text size="1" color="gray">{t("页面语言提示")}</Text><Select.Root value={testLocale} onValueChange={setTestLocale}><Select.Trigger /><Select.Content><Select.Item value="zh-CN">简体中文</Select.Item><Select.Item value="en-US">English</Select.Item><Select.Item value="es">Español</Select.Item><Select.Item value="pt">Português</Select.Item><Select.Item value="ar">العربية</Select.Item><Select.Item value="ja">日本語</Select.Item><Select.Item value="ko">한국어</Select.Item></Select.Content></Select.Root><small>{t("模型仍会根据本次消息确认实际语言，不会只依赖页面语言。")}</small></label>
                    <Button size="3" onClick={() => void executeTest()} disabled={!testQuestion.trim() || busy === "test"}><PaperPlaneTilt weight="fill" />{busy === "test" ? t("检索与生成中…") : t("运行一次完整问答")}</Button>
                  </Card>
                  {testRun ? <RunDetail run={testRun} /> : <Card className="support-ai-test-placeholder"><GlobeHemisphereWest weight="duotone" /><Heading size="4">{t("回答将保留客户语言")}</Heading><Text size="2" color="gray">{t("右侧会展示最终回答、识别语言、内部检索查询、置信度与逐条引用；证据不足时展示转人工原因。")}</Text></Card>}
                </div>
              </Tabs.Content>
            ) : null}

            {canInspect ? (
              <Tabs.Content value="runs" className="support-ai-tab-panel">
                <Card className="support-ai-runs-card">
                  <div className="support-ai-panel-heading"><div><Text size="1" color="gray">{t("审计与溯源")}</Text><Heading size="5">{t("最近运行")}</Heading></div><Badge color="gray">{runs.length}</Badge></div>
                  {!runs.length ? <CoreEmpty title={t("还没有智能客服运行记录")} description={t("店铺启用智能客服后收到客户消息，或在问答试跑中执行一次，就会形成不可混淆的 Run 与 Evidence 记录。")}/> : null}
                  <div className="support-ai-run-list">
                    {runs.map((run) => (
                      <details key={run.id}>
                        <summary>
                          <span><Robot weight="duotone" /></span>
                          <div><strong>{run.question}</strong><small>{coreDate(run.createdAt)} · {run.detectedLanguage || run.visitorLocale} · {run.triggerType}</small></div>
                          <Badge color={STATUS_COLOR[run.status] || "gray"}>{t(run.status)}</Badge>
                        </summary>
                        <div className="support-ai-run-expanded"><RunDetail run={run} /></div>
                      </details>
                    ))}
                  </div>
                </Card>
              </Tabs.Content>
            ) : null}
          </Tabs.Root>
        </>
      ) : null}
    </div>
  );
}
