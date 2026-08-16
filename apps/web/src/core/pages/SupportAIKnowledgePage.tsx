import {
  Badge,
  Button,
  Card,
  Dialog,
  Heading,
  Progress,
  Select,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowLeft,
  Brain,
  CaretRight,
  Check,
  Database,
  FileArrowUp,
  FileText,
  Plus,
  Prohibit,
  Robot,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  createSupportAIKnowledgeBase,
  getSupportAIIngestionJob,
  importSupportAITraining,
  listSupportAIAgents,
  listSupportAIKnowledgeBaseSources,
  listSupportAIKnowledgeBases,
  reindexSupportAIKnowledgeSource,
  revokeSupportAIKnowledgeSource,
  uploadSupportAIKnowledgeBaseSource,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIAgent,
  SupportAIIngestionJob,
  SupportAIKnowledgeBase,
  SupportAIKnowledgeBaseSource,
} from "../types";
import "./SupportAIAgentManagement.css";

const ACTIVE_JOBS = new Set(["QUEUED", "RUNNING"]);
const STATUS_COLOR: Record<string, "gray" | "blue" | "amber" | "jade" | "red"> = {
  PROCESSING: "blue",
  READY: "jade",
  APPROVED: "jade",
  REVOKED: "gray",
  FAILED: "red",
};
const STATUS_LABEL: Record<string, string> = {
  PROCESSING: "处理中",
  READY: "可用",
  APPROVED: "已批准",
  REVOKED: "已停用",
  FAILED: "处理失败",
};

interface TrackedJob {
  tenantId: string;
  job: SupportAIIngestionJob;
}

export function SupportAIKnowledgePage() {
  const { locale, t } = useLocale();
  const navigate = useNavigate();
  const { knowledgeBaseId: routeKnowledgeBaseId } = useParams();
  const [searchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agent_id") || "";
  const requestedKnowledgeBaseId = routeKnowledgeBaseId || searchParams.get("knowledge_base_id") || "";
  const detailView = Boolean(requestedKnowledgeBaseId);
  const [agents, setAgents] = useState<SupportAIAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [knowledgeBases, setKnowledgeBases] = useState<SupportAIKnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [sources, setSources] = useState<SupportAIKnowledgeBaseSource[]>([]);
  const [jobs, setJobs] = useState<Record<string, TrackedJob>>({});
  const [loading, setLoading] = useState(true);
  const [baseLoading, setBaseLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [file, setFile] = useState<File>();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("und");
  const [classification, setClassification] = useState<"PUBLIC" | "CUSTOMER_APPROVED">("CUSTOMER_APPROVED");
  const [createOpen, setCreateOpen] = useState(false);
  const [newBaseName, setNewBaseName] = useState("");
  const [newBaseDescription, setNewBaseDescription] = useState("");
  const [newBaseTenantId, setNewBaseTenantId] = useState("");

  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const next = await listSupportAIAgents();
      setAgents(next);
      setSelectedAgentId((current) => (
        [requestedAgentId, current, next[0]?.id || ""]
          .find((candidate) => next.some((agent) => agent.id === candidate)) || ""
      ));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, [requestedAgentId, t]);

  useEffect(() => {
    void loadAgents();
  }, [loadAgents]);

  const loadKnowledgeBases = useCallback(async () => {
    if (!selectedAgentId) {
      setKnowledgeBases([]);
      setSelectedKnowledgeBaseId("");
      return;
    }
    setBaseLoading(true);
    try {
      const next = await listSupportAIKnowledgeBases(selectedAgentId);
      setKnowledgeBases(next);
      setSelectedKnowledgeBaseId((current) => (
        [requestedKnowledgeBaseId, current, next[0]?.id || ""]
          .find((candidate) => next.some((base) => base.id === candidate)) || ""
      ));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识库加载失败"));
    } finally {
      setBaseLoading(false);
    }
  }, [requestedKnowledgeBaseId, selectedAgentId, t]);

  useEffect(() => {
    void loadKnowledgeBases();
  }, [loadKnowledgeBases]);

  const loadSources = useCallback(async (quiet = false) => {
    if (!detailView) {
      setSources([]);
      return;
    }
    const base = knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId);
    if (!base) {
      setSources([]);
      return;
    }
    if (!quiet) setLoading(true);
    try {
      setSources(await listSupportAIKnowledgeBaseSources({
        knowledgeBaseId: base.id,
        tenantId: base.tenantId,
      }));
      setError("");
    } catch (reason) {
      if (!quiet) setError(reason instanceof Error ? reason.message : t("知识库文件加载失败"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [detailView, knowledgeBases, selectedKnowledgeBaseId, t]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const active = Object.entries(jobs).filter(([, tracked]) => ACTIVE_JOBS.has(tracked.job.status));
    if (!active.length) return;
    const timer = window.setInterval(() => {
      void Promise.all(active.map(async ([key, tracked]) => {
        try {
          const next = await getSupportAIIngestionJob(tracked.tenantId, tracked.job.id);
          setJobs((current) => ({ ...current, [key]: { ...tracked, job: next } }));
          if (!ACTIVE_JOBS.has(next.status)) await loadSources(true);
        } catch {
          // A later manual refresh still reconciles the durable job state.
        }
      }));
    }, 2500);
    return () => window.clearInterval(timer);
  }, [jobs, loadSources]);

  const selectAgent = (agentId: string) => {
    setSelectedAgentId(agentId);
    setKnowledgeBases([]);
    setSelectedKnowledgeBaseId("");
    setSources([]);
    setJobs({});
    setMessage("");
    navigate(`/console/agents/knowledge?agent_id=${encodeURIComponent(agentId)}`, { replace: true });
  };

  const selectKnowledgeBase = (knowledgeBaseId: string) => {
    setSelectedKnowledgeBaseId(knowledgeBaseId);
    setJobs({});
    setMessage("");
    navigate(`/console/agents/knowledge/${encodeURIComponent(knowledgeBaseId)}?agent_id=${encodeURIComponent(selectedAgentId)}`);
  };

  const createKnowledgeBase = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedAgentId || !newBaseName.trim() || !newBaseTenantId || busy) return;
    setBusy("create-base");
    setError("");
    try {
      const created = await createSupportAIKnowledgeBase({
        agentId: selectedAgentId,
        tenantId: newBaseTenantId,
        name: newBaseName.trim(),
        description: newBaseDescription.trim() || undefined,
      });
      setKnowledgeBases((current) => [created, ...current]);
      setSelectedKnowledgeBaseId(created.id);
      setCreateOpen(false);
      setNewBaseName("");
      setNewBaseDescription("");
      setMessage(t("知识库已创建"));
      navigate(`/console/agents/knowledge/${encodeURIComponent(created.id)}?agent_id=${encodeURIComponent(selectedAgentId)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识库创建失败"));
    } finally {
      setBusy("");
    }
  };

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    const base = knowledgeBases.find((item) => item.id === selectedKnowledgeBaseId);
    if (!base || !file || busy) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      if (file.name.toLowerCase().endsWith(".json")) {
        let jsonPayload: unknown;
        try {
          jsonPayload = JSON.parse(await file.text()) as unknown;
        } catch {
          throw new Error(t("JSON 文件格式无效，请检查编码和语法。"));
        }
        if (
          typeof jsonPayload === "object"
          && jsonPayload !== null
          && "schema_version" in jsonPayload
          && jsonPayload.schema_version === "support-ai-training/v1"
        ) {
          await importSupportAITraining(selectedAgentId, jsonPayload, base.id);
          setFile(undefined);
          setTitle("");
          const input = document.getElementById("support-knowledge-file") as HTMLInputElement | null;
          if (input) input.value = "";
          setMessage(t("案例和规则已导入当前知识库为草稿，请进入 AI 训练工作台一键审批。"));
          return;
        }
      }
      const result = await uploadSupportAIKnowledgeBaseSource({
        knowledgeBaseId: base.id,
        tenantId: base.tenantId,
        file,
        title: title.trim() || file.name.replace(/\.[^.]+$/, ""),
        classification,
        language,
      });
      setSources((current) => [{
        knowledgeBaseId: base.id,
        knowledgeBaseName: base.name,
        source: result.source,
      }, ...current]);
      setJobs((current) => ({
        ...current,
        [result.source.id]: { tenantId: base.tenantId, job: result.job },
      }));
      setKnowledgeBases((current) => current.map((item) => item.id === base.id
        ? { ...item, sourceCount: item.sourceCount + 1 }
        : item));
      setFile(undefined);
      setTitle("");
      const input = document.getElementById("support-knowledge-file") as HTMLInputElement | null;
      if (input) input.value = "";
      setMessage(t("知识文件已提交到当前知识库"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识文件上传失败"));
    } finally {
      setBusy("");
    }
  };

  const sourceAction = async (item: SupportAIKnowledgeBaseSource, action: "reindex" | "revoke") => {
    const base = knowledgeBases.find((candidate) => candidate.id === item.knowledgeBaseId);
    if (!base || busy) return;
    const key = item.source.id;
    setBusy(`${action}:${key}`);
    setError("");
    setMessage("");
    try {
      if (action === "reindex") {
        const job = await reindexSupportAIKnowledgeSource(base.tenantId, item.source.id);
        setJobs((current) => ({ ...current, [key]: { tenantId: base.tenantId, job } }));
        setMessage(t("知识文件已重新提交处理"));
      } else {
        const source = await revokeSupportAIKnowledgeSource(base.tenantId, item.source.id);
        setSources((current) => current.map((row) => row.source.id === source.id ? { ...row, source } : row));
        setMessage(t("知识文件已撤销"));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识文件操作失败"));
    } finally {
      setBusy("");
    }
  };

  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  const selectedBase = knowledgeBases.find((base) => base.id === selectedKnowledgeBaseId);

  return (
    <div className="core-workspace support-agent-page">
      <CorePageHeading
        eyebrow={detailView ? t("知识库详情") : t("智能体管理")}
        title={detailView ? (selectedBase?.name || t("知识库详情")) : t("知识库管理")}
        actions={(
          <>
            {detailView ? <Button variant="soft" color="gray" onClick={() => navigate(`/console/agents/knowledge?agent_id=${encodeURIComponent(selectedAgentId)}`)}><ArrowLeft />{t("返回知识库列表")}</Button> : null}
            {detailView && selectedBase ? <Button asChild><Link to={`/console/agents/${selectedAgentId}/training?knowledge_base_id=${encodeURIComponent(selectedBase.id)}`}><Brain />{t("AI 训练工作台")}</Link></Button> : null}
            <Button variant="soft" color="gray" disabled={loading || !selectedAgentId} onClick={() => void loadKnowledgeBases()}>
              <ArrowClockwise />{t("刷新")}
            </Button>
          </>
        )}
      />

      <Card className="support-agent-knowledge-scope">
        <span><Robot weight="duotone" /></span>
        <div><Text size="1" color="gray">{t("选择智能体")}</Text><Heading size="4">{selectedAgent?.name || t("暂无智能体")}</Heading></div>
        <Select.Root value={selectedAgentId} onValueChange={selectAgent}>
          <Select.Trigger placeholder={t("选择智能体")} />
          <Select.Content>{agents.map((agent) => <Select.Item value={agent.id} key={agent.id}>{agent.name} · {agent.agentCode}</Select.Item>)}</Select.Content>
        </Select.Root>
        {selectedAgent ? <Button asChild size="1" variant="ghost" color="gray"><Link to={`/console/agents/${selectedAgent.id}`}>{t("详情配置")}</Link></Button> : null}
      </Card>

      {error ? <CoreError message={error} onRetry={() => void loadKnowledgeBases()} /> : null}
      {message ? <Card className="support-agent-success"><Check weight="bold" /><Text size="2">{message}</Text></Card> : null}
      {loading && !selectedBase ? <CoreLoading label={t("正在读取知识库")} /> : null}
      {!loading && !agents.length ? <CoreEmpty title={t("还没有智能体")} description={t("请先在智能体列表创建智能体。")} /> : null}

      {!loading && selectedAgent && !detailView ? (
        <Card className="support-agent-source-card support-agent-knowledge-list-card">
          <div className="support-agent-section-heading">
            <div><Text size="1" color="gray">{t("当前智能体的知识库")}</Text><Heading size="5">{t("知识库列表")}</Heading></div>
            <Button size="1" onClick={() => { setNewBaseTenantId(selectedAgent.stores[0]?.tenantId || ""); setCreateOpen(true); }} disabled={!selectedAgent.stores.length}>
              <Plus />{t("新增知识库")}
            </Button>
          </div>
          <Text size="2" color="gray">{t("选择一个知识库进入详情，再上传文件、查看来源或进行 AI 训练。")}</Text>
          {!selectedAgent.stores.length ? (
            <CoreEmpty title={t("尚未绑定店铺")} description={t("先在智能体详情中绑定店铺，再创建知识库。")} action={<Button asChild size="1"><Link to={`/console/agents/${selectedAgent.id}`}><Storefront />{t("绑定店铺")}</Link></Button>} />
          ) : baseLoading ? <CoreLoading label={t("正在读取知识库")} /> : !knowledgeBases.length ? (
            <CoreEmpty title={t("还没有知识库")} description={t("为智能体绑定的店铺创建一个知识库，再进入详情上传文件和训练。")} />
          ) : (
            <div className="support-agent-knowledge-list">
              {knowledgeBases.map((base) => (
                <button type="button" key={base.id} className="support-agent-knowledge-base-row" onClick={() => selectKnowledgeBase(base.id)}>
                  <span><Database weight="duotone" /></span>
                  <div><strong>{base.name}</strong><small>{base.tenantName} · {base.approvedSourceCount}/{base.sourceCount} {t("个已批准文件")} · {base.trainingCaseCount} {t("个训练案例")}</small></div>
                  <Badge color={base.status === "ACTIVE" ? "jade" : "gray"}>{t(base.status === "ACTIVE" ? "启用" : "停用")}</Badge>
                  <CaretRight />
                </button>
              ))}
            </div>
          )}
        </Card>
      ) : null}

      {!loading && selectedAgent && detailView && selectedBase ? (
        <>
          <Card className="support-agent-knowledge-detail-header">
            <span><Database weight="duotone" /></span>
            <div><Text size="1" color="gray">{t("所属智能体")}</Text><strong>{selectedAgent.name}</strong><small>{selectedBase.tenantName} · {selectedBase.description || t("文件和训练内容均独立归属于此知识库")}</small></div>
            <div className="support-agent-knowledge-detail-stats"><span><strong>{selectedBase.sourceCount}</strong><small>{t("知识文件")}</small></span><span><strong>{selectedBase.trainingCaseCount}</strong><small>{t("训练案例")}</small></span><span><strong>{selectedBase.trainingRuleCount}</strong><small>{t("复用规则")}</small></span></div>
          </Card>
          <Card className="support-agent-upload-card">
            <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("当前知识库")}</Text><Heading size="5">{t("上传文件")}</Heading></div><Database weight="duotone" /></div>
            <Text size="2" color="gray">{t("文件上传、解析、向量化和批准都只作用于当前知识库。")}</Text>
            <form className="support-agent-upload-form" onSubmit={(event) => void upload(event)}>
              <label className="support-agent-file-field">
                <FileArrowUp weight="duotone" />
                <span><strong>{file?.name || t("选择 PDF、DOCX、TXT、Markdown 或 JSON")}</strong><small>{t("文件会归属于当前知识库；训练案例 JSON 请在 AI 训练工作台导入")}</small></span>
                <input id="support-knowledge-file" type="file" accept=".pdf,.docx,.txt,.md,.json,application/json" onChange={(event) => setFile(event.target.files?.[0])} required />
              </label>
              <label><Text size="1" color="gray">{t("知识标题")}</Text><TextField.Root value={title} onChange={(event) => setTitle(event.target.value)} placeholder={file?.name.replace(/\.[^.]+$/, "") || t("文件标题")} /></label>
              <label><Text size="1" color="gray">{t("文件语言")}</Text><TextField.Root value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="und / zh-CN / en" /></label>
              <label><Text size="1" color="gray">{t("可用范围")}</Text><Select.Root value={classification} onValueChange={(value) => setClassification(value as typeof classification)}><Select.Trigger /><Select.Content><Select.Item value="CUSTOMER_APPROVED">{t("客户回答可用")}</Select.Item><Select.Item value="PUBLIC">{t("公开资料")}</Select.Item></Select.Content></Select.Root></label>
              <Button type="submit" disabled={!file || Boolean(busy)} loading={busy === "upload"}><FileArrowUp />{t("上传并处理")}</Button>
            </form>
          </Card>

          <Card className="support-agent-source-card">
            <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("当前知识库内容")}</Text><Heading size="5">{t("知识文件")}</Heading></div><Badge color="gray">{sources.length}</Badge></div>
            {!sources.length ? <CoreEmpty title={t("还没有知识文件")} description={t("上传后，文件会在当前知识库中解析和索引。")} /> : null}
            <div className="support-agent-source-list">
              {sources.map((item) => {
                const key = item.source.id;
                const job = jobs[key]?.job;
                const processing = item.source.status === "PROCESSING" || Boolean(job && ACTIVE_JOBS.has(job.status));
                return <article key={key}>
                  <span><FileText weight="duotone" /></span>
                  <div>
                    <div><strong>{item.source.title}</strong><Badge color={STATUS_COLOR[item.source.status] || "gray"}>{t(STATUS_LABEL[item.source.status] || item.source.status)}</Badge></div>
                    <small>{item.source.originalFilename} · {(item.source.byteSize / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB</small>
                    {processing ? <Progress value={job?.progress ?? 10} /> : null}
                    {item.source.failureMessage ? <small className="is-error">{item.source.failureMessage}</small> : null}
                  </div>
                  <div className="support-agent-source-actions">
                    {!processing ? <Button size="1" variant="soft" color="gray" onClick={() => void sourceAction(item, "reindex")} disabled={Boolean(busy)}><ArrowClockwise />{t("重新处理")}</Button> : null}
                    {!processing && item.source.status !== "REVOKED" ? <Button size="1" variant="ghost" color="red" onClick={() => void sourceAction(item, "revoke")} disabled={Boolean(busy)}><Prohibit />{t("撤销")}</Button> : null}
                  </div>
                </article>;
              })}
            </div>
          </Card>
        </>
      ) : null}

      {!loading && selectedAgent && detailView && !selectedBase && !baseLoading ? (
        <CoreEmpty title={t("知识库不存在")} description={t("请返回知识库列表后重新选择。")} action={<Button onClick={() => navigate(`/console/agents/knowledge?agent_id=${encodeURIComponent(selectedAgentId)}`)}><ArrowLeft />{t("返回知识库列表")}</Button>} />
      ) : null}

      <Dialog.Root open={createOpen} onOpenChange={setCreateOpen}>
        <Dialog.Content className="support-agent-create-dialog" maxWidth="520px">
          <Dialog.Title>{t("新增知识库")}</Dialog.Title>
          <Dialog.Description>{t("一个知识库只绑定当前智能体和一个店铺；智能体可以拥有多个知识库。")}</Dialog.Description>
          <form className="support-agent-dialog-form" onSubmit={(event) => void createKnowledgeBase(event)}>
            <label><Text size="2" weight="medium">{t("所属店铺")}</Text><Select.Root value={newBaseTenantId} onValueChange={setNewBaseTenantId}><Select.Trigger placeholder={t("选择店铺")} /><Select.Content>{selectedAgent?.stores.map((store) => <Select.Item value={store.tenantId} key={store.tenantId}>{store.tenantName}</Select.Item>)}</Select.Content></Select.Root></label>
            <label><Text size="2" weight="medium">{t("知识库名称")}</Text><TextField.Root value={newBaseName} onChange={(event) => setNewBaseName(event.target.value)} maxLength={160} autoFocus required placeholder={t("例如：品牌资料库、售前问答库")} /></label>
            <label><Text size="2" weight="medium">{t("说明（选填）")}</Text><TextArea value={newBaseDescription} onChange={(event) => setNewBaseDescription(event.target.value)} maxLength={4000} placeholder={t("说明这个知识库的用途")}/></label>
            <div className="core-dialog-actions"><Dialog.Close><Button type="button" variant="soft" color="gray" disabled={Boolean(busy)}>{t("取消")}</Button></Dialog.Close><Button type="submit" loading={busy === "create-base"} disabled={!newBaseName.trim() || !newBaseTenantId}>{t("创建知识库")}</Button></div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
