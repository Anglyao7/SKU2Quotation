import {
  Badge,
  Button,
  Card,
  Heading,
  Progress,
  Select,
  Text,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  Check,
  Database,
  FileArrowUp,
  FileText,
  Prohibit,
  Robot,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  getSupportAIIngestionJob,
  importSupportAITraining,
  listSupportAIAgentKnowledgeSources,
  listSupportAIAgents,
  reindexSupportAIKnowledgeSource,
  revokeSupportAIKnowledgeSource,
  uploadSupportAIAgentKnowledgeSource,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIAgent,
  SupportAIAgentKnowledgeSource,
  SupportAIIngestionJob,
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
  APPROVED: "可用",
  REVOKED: "已停用",
  FAILED: "处理失败",
};

interface TrackedJob {
  tenantId: string;
  job: SupportAIIngestionJob;
}

export function SupportAIKnowledgePage() {
  const { locale, t } = useLocale();
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedAgentId = searchParams.get("agent_id") || "";
  const [agents, setAgents] = useState<SupportAIAgent[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [sources, setSources] = useState<SupportAIAgentKnowledgeSource[]>([]);
  const [jobs, setJobs] = useState<Record<string, TrackedJob>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState("");
  const [file, setFile] = useState<File>();
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("und");
  const [classification, setClassification] = useState<"PUBLIC" | "CUSTOMER_APPROVED">("CUSTOMER_APPROVED");

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

  const loadSources = useCallback(async (quiet = false) => {
    if (!selectedAgentId) {
      setSources([]);
      return;
    }
    if (!quiet) setLoading(true);
    try {
      setSources(await listSupportAIAgentKnowledgeSources(selectedAgentId));
      setError("");
    } catch (reason) {
      if (!quiet) setError(reason instanceof Error ? reason.message : t("知识库加载失败"));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, [selectedAgentId, t]);

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
    setJobs({});
    setMessage("");
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      next.set("agent_id", agentId);
      return next;
    }, { replace: true });
  };

  const upload = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedAgentId || !file || busy) return;
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
          await importSupportAITraining(selectedAgentId, jsonPayload);
          setFile(undefined);
          setTitle("");
          const input = document.getElementById("support-agent-knowledge-file") as HTMLInputElement | null;
          if (input) input.value = "";
          setMessage(t("训练包已导入为草稿，请前往人工训练审核并发布。"));
          return;
        }
      }
      const items = await uploadSupportAIAgentKnowledgeSource({
        agentId: selectedAgentId,
        file,
        title: title.trim() || file.name.replace(/\.[^.]+$/, ""),
        classification,
        language,
      });
      setSources((current) => [
        ...items.map(({ tenantId, tenantName, source }) => ({ tenantId, tenantName, source })),
        ...current,
      ]);
      setJobs((current) => {
        const next = { ...current };
        items.forEach((item) => {
          next[`${item.tenantId}:${item.source.id}`] = { tenantId: item.tenantId, job: item.job };
        });
        return next;
      });
      setFile(undefined);
      setTitle("");
      const input = document.getElementById("support-agent-knowledge-file") as HTMLInputElement | null;
      if (input) input.value = "";
      setMessage(t("知识文件已提交到智能体绑定的店铺"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识文件上传失败"));
    } finally {
      setBusy("");
    }
  };

  const sourceAction = async (
    item: SupportAIAgentKnowledgeSource,
    action: "reindex" | "revoke",
  ) => {
    const key = `${item.tenantId}:${item.source.id}`;
    if (busy) return;
    setBusy(`${action}:${key}`);
    setError("");
    setMessage("");
    try {
      if (action === "reindex") {
        const job = await reindexSupportAIKnowledgeSource(item.tenantId, item.source.id);
        setJobs((current) => ({ ...current, [key]: { tenantId: item.tenantId, job } }));
        setMessage(t("知识文件已重新提交处理"));
      } else {
        const source = await revokeSupportAIKnowledgeSource(item.tenantId, item.source.id);
        setSources((current) => current.map((row) => row.tenantId === item.tenantId && row.source.id === source.id ? { ...row, source } : row));
        setMessage(t("知识文件已撤销"));
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("知识文件操作失败"));
    } finally {
      setBusy("");
    }
  };

  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);
  return (
    <div className="core-workspace support-agent-page">
      <CorePageHeading
        eyebrow={t("智能体管理")}
        title={t("知识库管理")}
        actions={(
          <Button variant="soft" color="gray" disabled={loading || !selectedAgentId} onClick={() => void loadSources()}>
            <ArrowClockwise />{t("刷新")}
          </Button>
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

      {error ? <CoreError message={error} onRetry={() => void loadSources()} /> : null}
      {message ? <Card className="support-agent-success"><Check weight="bold" /><Text size="2">{message}</Text></Card> : null}
      {loading ? <CoreLoading label={t("正在读取知识库")} /> : null}
      {!loading && !agents.length ? <CoreEmpty title={t("还没有智能体")} description={t("请先在智能体列表创建智能体。")}/> : null}

      {!loading && selectedAgent ? (
        <div className="support-agent-knowledge-layout">
          <Card className="support-agent-upload-card">
            <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("文件知识")}</Text><Heading size="5">{t("上传知识库")}</Heading></div><Database weight="duotone" /></div>
            {!selectedAgent.stores.length ? (
              <CoreEmpty
                title={t("尚未绑定店铺")}
                description={t("先在智能体详情中绑定店铺，再上传知识文件。")}
                action={<Button asChild size="1"><Link to={`/console/agents/${selectedAgent.id}`}><Storefront />{t("绑定店铺")}</Link></Button>}
              />
            ) : (
              <form className="support-agent-upload-form" onSubmit={(event) => void upload(event)}>
                <label className="support-agent-file-field">
                  <FileArrowUp weight="duotone" />
                  <span><strong>{file?.name || t("选择 PDF、DOCX、TXT、Markdown 或 JSON")}</strong><small>{t("普通 JSON 将作为知识解析；训练包 JSON 将自动导入人工训练草稿。")}</small><small>{t("将同步到 {count} 个绑定店铺", { count: selectedAgent.stores.length })}</small></span>
                  <input id="support-agent-knowledge-file" type="file" accept=".pdf,.docx,.txt,.md,.json,application/json" onChange={(event) => setFile(event.target.files?.[0])} required />
                </label>
                <label><Text size="1" color="gray">{t("知识标题")}</Text><TextField.Root value={title} onChange={(event) => setTitle(event.target.value)} placeholder={file?.name.replace(/\.[^.]+$/, "") || t("文件标题")} /></label>
                <label><Text size="1" color="gray">{t("文件语言")}</Text><TextField.Root value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="und / zh-CN / en" /></label>
                <label><Text size="1" color="gray">{t("可用范围")}</Text><Select.Root value={classification} onValueChange={(value) => setClassification(value as typeof classification)}><Select.Trigger /><Select.Content><Select.Item value="CUSTOMER_APPROVED">{t("客户回答可用")}</Select.Item><Select.Item value="PUBLIC">{t("公开资料")}</Select.Item></Select.Content></Select.Root></label>
                <Button type="submit" disabled={!file || Boolean(busy)} loading={busy === "upload"}><FileArrowUp />{t("上传并处理")}</Button>
                <Button asChild variant="ghost" color="gray"><Link to={`/console/agents/${selectedAgent.id}/training`}>{t("前往人工训练")}</Link></Button>
              </form>
            )}
          </Card>

          <Card className="support-agent-source-card">
            <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("智能体知识")}</Text><Heading size="5">{t("知识文件")}</Heading></div><Badge color="gray">{t("{count} 个店铺副本", { count: sources.length })}</Badge></div>
            {!sources.length ? <CoreEmpty title={t("还没有知识文件")} description={t("上传后，文件会按绑定店铺完成解析和索引。")}/> : null}
            <div className="support-agent-source-list">
              {sources.map((item) => {
                const key = `${item.tenantId}:${item.source.id}`;
                const job = jobs[key]?.job;
                const processing = item.source.status === "PROCESSING" || Boolean(job && ACTIVE_JOBS.has(job.status));
                return <article key={key}>
                  <span><FileText weight="duotone" /></span>
                  <div>
                    <div><strong>{item.source.title}</strong><Badge color={STATUS_COLOR[item.source.status] || "gray"}>{t(STATUS_LABEL[item.source.status] || item.source.status)}</Badge></div>
                    <small>{item.tenantName} · {item.source.originalFilename} · {(item.source.byteSize / 1024).toLocaleString(locale, { maximumFractionDigits: 1 })} KB</small>
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
        </div>
      ) : null}
    </div>
  );
}
