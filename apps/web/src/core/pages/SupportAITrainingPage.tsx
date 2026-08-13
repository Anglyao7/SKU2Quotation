import {
  Badge,
  Button,
  Card,
  Dialog,
  Heading,
  Select,
  Tabs,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowCounterClockwise,
  ArrowLeft,
  Brain,
  Check,
  Copy,
  DownloadSimple,
  FileArrowUp,
  FloppyDisk,
  MagicWand,
  Plus,
  Robot,
  Sparkle,
  Trash,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { Link, useParams } from "react-router-dom";
import {
  activateSupportAITrainingVersion,
  copySupportAITraining,
  createSupportAITrainingCase,
  createSupportAITrainingRule,
  deleteSupportAITrainingCase,
  deleteSupportAITrainingRule,
  exportSupportAITraining,
  generateSupportAITrainingCases,
  getSupportAIAgent,
  getSupportAITrainingOverview,
  importSupportAITraining,
  listSupportAIAgents,
  previewSupportAITraining,
  publishSupportAITraining,
  summarizeSupportAITrainingRules,
  updateSupportAITrainingCase,
  updateSupportAITrainingRule,
  type SupportAITrainingCaseInput,
  type SupportAITrainingRuleInput,
} from "../api";
import {
  CoreEmpty,
  CoreError,
  CoreLoading,
  CorePageHeading,
  coreDate,
} from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type {
  SupportAIAgent,
  SupportAITrainingCase,
  SupportAITrainingGroundingMode,
  SupportAITrainingOverview,
  SupportAITrainingPreview,
  SupportAITrainingResponseAction,
  SupportAITrainingRule,
  SupportAITrainingStatus,
} from "../types";
import "./SupportAIAgentManagement.css";

const emptyCase = (): SupportAITrainingCaseInput => ({
  title: "",
  language: "zh-CN",
  customerMessage: "",
  idealResponse: "",
  responseAction: "ANSWER",
  groundingMode: "EVIDENCE",
  behaviorNotes: "",
  requiredEvidenceTypes: ["SKU"],
  tags: [],
  forbiddenPatterns: [],
  sourceType: "MANUAL",
  status: "DRAFT",
  sortOrder: 0,
});

const emptyRule = (): SupportAITrainingRuleInput => ({
  title: "",
  instruction: "",
  scopes: ["QUESTION_ANSWERING"],
  sourceCaseIds: [],
  priority: 100,
  status: "DRAFT",
});

const caseInput = (item: SupportAITrainingCase): SupportAITrainingCaseInput => ({
  externalId: item.externalId,
  sourceTenantId: item.sourceTenantId,
  title: item.title,
  language: item.language,
  customerMessage: item.customerMessage,
  idealResponse: item.idealResponse,
  responseAction: item.responseAction,
  groundingMode: item.groundingMode,
  behaviorNotes: item.behaviorNotes,
  requiredEvidenceTypes: item.requiredEvidenceTypes,
  tags: item.tags,
  forbiddenPatterns: item.forbiddenPatterns,
  sourceType: item.sourceType,
  status: item.status,
  sortOrder: item.sortOrder,
});

const ruleInput = (item: SupportAITrainingRule): SupportAITrainingRuleInput => ({
  ruleKey: item.ruleKey,
  title: item.title,
  instruction: item.instruction,
  scopes: item.scopes,
  sourceCaseIds: item.sourceCaseIds,
  priority: item.priority,
  status: item.status,
});

const splitValues = (value: string) => Array.from(new Set(
  value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean),
));

const statusColor = (status: SupportAITrainingStatus) => (
  status === "APPROVED" ? "jade" : status === "DRAFT" ? "amber" : "gray"
);

export function SupportAITrainingPage() {
  const { agentId = "" } = useParams();
  const { t } = useLocale();
  const importRef = useRef<HTMLInputElement>(null);
  const [agent, setAgent] = useState<SupportAIAgent>();
  const [agents, setAgents] = useState<SupportAIAgent[]>([]);
  const [overview, setOverview] = useState<SupportAITrainingOverview>();
  const [preview, setPreview] = useState<SupportAITrainingPreview>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [caseOpen, setCaseOpen] = useState(false);
  const [caseEditingId, setCaseEditingId] = useState("");
  const [caseDraft, setCaseDraft] = useState<SupportAITrainingCaseInput>(emptyCase);
  const [ruleOpen, setRuleOpen] = useState(false);
  const [ruleEditingId, setRuleEditingId] = useState("");
  const [ruleDraft, setRuleDraft] = useState<SupportAITrainingRuleInput>(emptyRule);
  const [generateOpen, setGenerateOpen] = useState(false);
  const [generateStoreId, setGenerateStoreId] = useState("");
  const [generateCount, setGenerateCount] = useState("12");
  const [generateLanguages, setGenerateLanguages] = useState("zh-CN, en");
  const [releaseOpen, setReleaseOpen] = useState(false);
  const [releaseNotes, setReleaseNotes] = useState("");
  const [copyTargetId, setCopyTargetId] = useState("");

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError("");
    try {
      const [nextAgent, nextOverview, nextAgents] = await Promise.all([
        getSupportAIAgent(agentId),
        getSupportAITrainingOverview(agentId),
        listSupportAIAgents(),
      ]);
      setAgent(nextAgent);
      setOverview(nextOverview);
      setAgents(nextAgents);
      setGenerateStoreId((current) => current || nextAgent.stores[0]?.tenantId || "");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("训练工作台加载失败"));
    } finally {
      setLoading(false);
    }
  }, [agentId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const reloadOverview = async () => {
    const next = await getSupportAITrainingOverview(agentId);
    setOverview(next);
    setPreview(undefined);
  };

  const runAction = async (key: string, action: () => Promise<string | void>, success: string) => {
    if (busy) return;
    setBusy(key);
    setError("");
    setMessage("");
    try {
      const actionMessage = await action();
      setMessage(actionMessage || success);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("训练操作失败"));
    } finally {
      setBusy("");
    }
  };

  const openCase = (item?: SupportAITrainingCase) => {
    setCaseEditingId(item?.id || "");
    setCaseDraft(item ? caseInput(item) : emptyCase());
    setCaseOpen(true);
  };

  const saveCase = async (event: FormEvent) => {
    event.preventDefault();
    if (!caseDraft.title.trim() || !caseDraft.customerMessage.trim() || !caseDraft.idealResponse.trim()) return;
    await runAction("case-save", async () => {
      if (caseEditingId) {
        await updateSupportAITrainingCase(agentId, caseEditingId, caseDraft);
      } else {
        await createSupportAITrainingCase(agentId, caseDraft);
      }
      await reloadOverview();
      setCaseOpen(false);
    }, t("训练案例已保存"));
  };

  const setCaseStatus = (item: SupportAITrainingCase, status: SupportAITrainingStatus) => runAction(
    `case-status-${item.id}`,
    async () => {
      await updateSupportAITrainingCase(agentId, item.id, { ...caseInput(item), status });
      await reloadOverview();
    },
    status === "APPROVED" ? t("案例已批准") : t("案例已退回草稿"),
  );

  const removeCase = (item: SupportAITrainingCase) => runAction(
    `case-delete-${item.id}`,
    async () => {
      await deleteSupportAITrainingCase(agentId, item.id);
      await reloadOverview();
    },
    t("训练案例已删除"),
  );

  const openRule = (item?: SupportAITrainingRule) => {
    setRuleEditingId(item?.id || "");
    setRuleDraft(item ? ruleInput(item) : emptyRule());
    setRuleOpen(true);
  };

  const saveRule = async (event: FormEvent) => {
    event.preventDefault();
    if (!ruleDraft.title.trim() || !ruleDraft.instruction.trim()) return;
    await runAction("rule-save", async () => {
      if (ruleEditingId) {
        await updateSupportAITrainingRule(agentId, ruleEditingId, ruleDraft);
      } else {
        await createSupportAITrainingRule(agentId, ruleDraft);
      }
      await reloadOverview();
      setRuleOpen(false);
    }, t("训练规则已保存"));
  };

  const setRuleStatus = (item: SupportAITrainingRule, status: SupportAITrainingStatus) => runAction(
    `rule-status-${item.id}`,
    async () => {
      await updateSupportAITrainingRule(agentId, item.id, { ...ruleInput(item), status });
      await reloadOverview();
    },
    status === "APPROVED" ? t("规则已批准") : t("规则已退回草稿"),
  );

  const removeRule = (item: SupportAITrainingRule) => runAction(
    `rule-delete-${item.id}`,
    async () => {
      await deleteSupportAITrainingRule(agentId, item.id);
      await reloadOverview();
    },
    t("训练规则已删除"),
  );

  const generateCases = async () => {
    await runAction("generate", async () => {
      const result = await generateSupportAITrainingCases({
        agentId,
        tenantId: generateStoreId || undefined,
        count: Math.max(1, Math.min(40, Number(generateCount) || 12)),
        languages: splitValues(generateLanguages),
      });
      await reloadOverview();
      setGenerateOpen(false);
      return result.generationMode === "MODEL"
        ? t("AI 已根据 {count} 个公开商品生成案例草稿", { count: result.productCount })
        : t("模型不可用，已生成可编辑的安全模板案例");
    }, t("案例草稿已生成"));
  };

  const summarizeRules = () => runAction("summarize", async () => {
    await summarizeSupportAITrainingRules({ agentId, maxRules: 8 });
    await reloadOverview();
  }, t("可复用规则草稿已生成"));

  const loadPreview = () => runAction("preview", async () => {
    setPreview(await previewSupportAITraining(agentId));
  }, t("已编译当前批准内容"));

  const publish = async () => {
    await runAction("publish", async () => {
      await publishSupportAITraining(agentId, releaseNotes.trim() || undefined);
      await reloadOverview();
      setReleaseOpen(false);
      setReleaseNotes("");
    }, t("训练版本已发布并同步到绑定店铺"));
  };

  const activateVersion = (versionId: string) => runAction(`activate-${versionId}`, async () => {
    await activateSupportAITrainingVersion(agentId, versionId);
    await reloadOverview();
  }, t("已切换训练版本"));

  const importFile = async (file?: File) => {
    if (!file) return;
    await runAction("import", async () => {
      const content = JSON.parse(await file.text()) as unknown;
      setOverview(await importSupportAITraining(agentId, content));
      setPreview(undefined);
    }, t("训练包已导入为草稿"));
  };

  const copyToAgent = () => {
    if (!copyTargetId) return Promise.resolve();
    return runAction("copy", async () => {
      await copySupportAITraining({ agentId, targetAgentId: copyTargetId });
    }, t("案例和规则已复制到目标智能体，状态为草稿"));
  };

  const availableAgents = useMemo(
    () => agents.filter((item) => item.id !== agentId),
    [agents, agentId],
  );

  return (
    <div className="core-workspace support-agent-page support-training-page">
      <CorePageHeading
        eyebrow={t("人工训练")}
        title={agent ? `${agent.name} · ${t("训练工作台")}` : t("训练工作台")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray"><Link to={`/console/agents/${agentId}`}><ArrowLeft />{t("返回智能体")}</Link></Button>
            <Button variant="soft" color="gray" disabled={Boolean(busy)} onClick={() => void loadPreview()}><Brain />{t("编译预览")}</Button>
            <Button disabled={!overview?.approvedCaseCount || Boolean(busy)} onClick={() => setReleaseOpen(true)}><UploadSimple />{t("发布训练版本")}</Button>
          </>
        )}
      />

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {message ? <Card className="support-agent-success"><Check weight="bold" /><Text size="2">{message}</Text></Card> : null}
      {loading ? <CoreLoading label={t("正在读取训练工作台")} /> : null}

      {!loading && agent && overview ? (
        <>
          <Card className="support-training-boundary">
            <span><Robot weight="duotone" /></span>
            <div>
              <Heading size="4">{t("训练教行为，知识给事实")}</Heading>
              <Text size="2" color="gray">{t("案例与规则负责教 AI 如何推荐、追问和组织回答；价格、MOQ、规格、库存和商品编号始终从当前 SKU 或已批准文件读取。生成、导入和复制的内容默认都是草稿。")}</Text>
            </div>
            <Badge color={overview.activeVersionId ? "jade" : "gray"}>
              {overview.activeVersionNumber ? `v${overview.activeVersionNumber} ${t("运行中")}` : t("尚未发布")}
            </Badge>
          </Card>

          <section className="support-agent-metrics support-training-metrics">
            <Card><Sparkle weight="duotone" /><span><small>{t("案例草稿")}</small><strong>{overview.draftCaseCount}</strong></span></Card>
            <Card><Check weight="bold" /><span><small>{t("已批准案例")}</small><strong>{overview.approvedCaseCount}</strong></span></Card>
            <Card><Brain weight="duotone" /><span><small>{t("规则草稿")}</small><strong>{overview.draftRuleCount}</strong></span></Card>
            <Card><UploadSimple weight="duotone" /><span><small>{t("历史版本")}</small><strong>{overview.versions.length}</strong></span></Card>
          </section>

          <Card className="support-training-actions">
            <div>
              <Text size="1" color="gray">{t("AI 辅助")}</Text>
              <Heading size="4">{t("从商品生成并归纳")}</Heading>
              <Text size="2" color="gray">{t("先从绑定店铺的公开商品生成问答草稿，再由 AI 从案例中归纳可复用规则。所有内容都需要人工批准。")}</Text>
            </div>
            <div className="support-training-action-buttons">
              <Button variant="soft" disabled={!agent.stores.length || Boolean(busy)} onClick={() => setGenerateOpen(true)}><MagicWand />{t("AI 生成商品案例")}</Button>
              <Button variant="soft" disabled={!overview.cases.length || Boolean(busy)} loading={busy === "summarize"} onClick={() => void summarizeRules()}><Brain />{t("总结可复用规则")}</Button>
              <Button variant="soft" color="gray" disabled={Boolean(busy)} onClick={() => void exportSupportAITraining(agentId, agent.agentCode)}><DownloadSimple />{t("导出训练包")}</Button>
              <input ref={importRef} hidden type="file" accept=".json,application/json" onChange={(event) => { void importFile(event.target.files?.[0]); event.currentTarget.value = ""; }} />
              <Button variant="soft" color="gray" loading={busy === "import"} disabled={Boolean(busy)} onClick={() => importRef.current?.click()}><FileArrowUp />{t("导入训练包")}</Button>
            </div>
            {availableAgents.length ? (
              <div className="support-training-copy-row">
                <Select.Root value={copyTargetId || "none"} onValueChange={(value) => setCopyTargetId(value === "none" ? "" : value)}>
                  <Select.Trigger placeholder={t("复制到其他智能体")} />
                  <Select.Content><Select.Item value="none">{t("选择目标智能体")}</Select.Item>{availableAgents.map((item) => <Select.Item key={item.id} value={item.id}>{item.name} · {item.agentCode}</Select.Item>)}</Select.Content>
                </Select.Root>
                <Button variant="soft" color="gray" disabled={!copyTargetId || Boolean(busy)} loading={busy === "copy"} onClick={() => void copyToAgent()}><Copy />{t("复制案例与规则")}</Button>
              </div>
            ) : null}
          </Card>

          <Tabs.Root defaultValue="cases" className="support-training-tabs">
            <Tabs.List>
              <Tabs.Trigger value="cases">{t("训练案例")} · {overview.cases.length}</Tabs.Trigger>
              <Tabs.Trigger value="rules">{t("复用规则")} · {overview.rules.length}</Tabs.Trigger>
              <Tabs.Trigger value="versions">{t("版本与回滚")} · {overview.versions.length}</Tabs.Trigger>
              <Tabs.Trigger value="preview">{t("编译结果")}</Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="cases">
              <Card className="support-training-list-card">
                <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("人工可增删改")}</Text><Heading size="5">{t("训练案例")}</Heading></div><Button onClick={() => openCase()}><Plus />{t("新增案例")}</Button></div>
                {!overview.cases.length ? <CoreEmpty title={t("还没有训练案例")} description={t("可以手工新增，也可以让 AI 根据公开商品生成一批草稿。")}/> : (
                  <div className="support-training-case-list">
                    {overview.cases.map((item) => (
                      <article key={item.id}>
                        <div className="support-training-item-heading">
                          <div><Heading size="3">{item.title}</Heading><span><Badge color={statusColor(item.status)}>{t(item.status === "APPROVED" ? "已批准" : item.status === "DRAFT" ? "草稿" : "已归档")}</Badge><Badge color="gray">{item.language}</Badge><Badge color="gray">{t(item.responseAction)}</Badge>{item.tags.slice(0, 3).map((tag) => <Badge key={tag} color="gray">{tag}</Badge>)}</span></div>
                          <small>{coreDate(item.updatedAt)}</small>
                        </div>
                        <div className="support-training-qa"><div><small>{t("客户问题")}</small><p>{item.customerMessage}</p></div><div><small>{t("理想回答 / 行为")}</small><p>{item.idealResponse}</p></div></div>
                        {item.behaviorNotes ? <Text size="1" color="gray">{item.behaviorNotes}</Text> : null}
                        <div className="support-training-item-actions">
                          <Button size="1" variant="soft" color="gray" onClick={() => openCase(item)}>{t("编辑")}</Button>
                          {item.status === "APPROVED" ? <Button size="1" variant="soft" color="amber" disabled={Boolean(busy)} onClick={() => void setCaseStatus(item, "DRAFT")}>{t("退回草稿")}</Button> : <Button size="1" variant="soft" color="jade" disabled={Boolean(busy)} onClick={() => void setCaseStatus(item, "APPROVED")}><Check />{t("批准")}</Button>}
                          <Button size="1" variant="ghost" color="red" disabled={Boolean(busy)} onClick={() => void removeCase(item)}><Trash />{t("删除")}</Button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </Card>
            </Tabs.Content>

            <Tabs.Content value="rules">
              <Card className="support-training-list-card">
                <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("从案例中沉淀")}</Text><Heading size="5">{t("可复用规则")}</Heading></div><Button onClick={() => openRule()}><Plus />{t("新增规则")}</Button></div>
                {!overview.rules.length ? <CoreEmpty title={t("还没有复用规则")} description={t("先准备案例，再使用“总结可复用规则”，或由人工直接新增。")}/> : (
                  <div className="support-training-rule-list">
                    {overview.rules.map((item) => (
                      <article key={item.id}>
                        <div><span><Badge color={statusColor(item.status)}>{t(item.status === "APPROVED" ? "已批准" : "草稿")}</Badge><Badge color="gray">P{item.priority}</Badge>{item.scopes.map((scope) => <Badge key={scope} color="gray">{scope}</Badge>)}</span><Heading size="3">{item.title}</Heading><Text size="2">{item.instruction}</Text></div>
                        <div className="support-training-item-actions"><Button size="1" variant="soft" color="gray" onClick={() => openRule(item)}>{t("编辑")}</Button>{item.status === "APPROVED" ? <Button size="1" variant="soft" color="amber" onClick={() => void setRuleStatus(item, "DRAFT")}>{t("退回草稿")}</Button> : <Button size="1" variant="soft" color="jade" onClick={() => void setRuleStatus(item, "APPROVED")}><Check />{t("批准")}</Button>}<Button size="1" variant="ghost" color="red" onClick={() => void removeRule(item)}><Trash />{t("删除")}</Button></div>
                      </article>
                    ))}
                  </div>
                )}
              </Card>
            </Tabs.Content>

            <Tabs.Content value="versions">
              <Card className="support-training-list-card">
                <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("不可变发布记录")}</Text><Heading size="5">{t("版本与回滚")}</Heading></div><Button disabled={!overview.approvedCaseCount || Boolean(busy)} onClick={() => setReleaseOpen(true)}><UploadSimple />{t("发布新版本")}</Button></div>
                {!overview.versions.length ? <CoreEmpty title={t("尚未发布训练版本")} description={t("批准案例后即可发布；发布会同步到此智能体绑定的所有店铺。")}/> : <div className="support-training-version-list">{overview.versions.map((item) => <article key={item.id} className={item.status === "PUBLISHED" ? "is-active" : ""}><div><strong>v{item.versionNumber}</strong><Badge color={item.status === "PUBLISHED" ? "jade" : "gray"}>{t(item.status === "PUBLISHED" ? "运行中" : "历史版本")}</Badge></div><div><Text size="2">{item.releaseNotes || t("无发布说明")}</Text><small>{item.caseCount} {t("个案例")} · {item.ruleCount} {t("条规则")} · {coreDate(item.publishedAt)}</small><code>{item.packageHash.slice(0, 16)}</code></div>{item.status !== "PUBLISHED" ? <Button size="1" variant="soft" loading={busy === `activate-${item.id}`} onClick={() => void activateVersion(item.id)}><ArrowCounterClockwise />{t("回滚到此版本")}</Button> : null}</article>)}</div>}
              </Card>
            </Tabs.Content>

            <Tabs.Content value="preview">
              <Card className="support-training-list-card">
                <div className="support-agent-section-heading"><div><Text size="1" color="gray">{t("只包含批准内容")}</Text><Heading size="5">{t("编译 Prompt")}</Heading></div><Button variant="soft" loading={busy === "preview"} onClick={() => void loadPreview()}><Brain />{t("重新编译")}</Button></div>
                {preview ? <><div className="support-training-preview-meta"><Badge color="jade">{preview.approvedCaseCount} {t("个案例")}</Badge><Badge color="jade">{preview.approvedRuleCount} {t("条规则")}</Badge><code>{preview.packageHash}</code></div><pre>{preview.compiledPrompt}</pre></> : <CoreEmpty title={t("尚未编译预览")} description={t("点击“重新编译”查看下一次发布将写入运行时的行为提示词。")}/>} 
              </Card>
            </Tabs.Content>
          </Tabs.Root>
        </>
      ) : null}

      <Dialog.Root open={caseOpen} onOpenChange={(open) => { if (!busy) setCaseOpen(open); }}>
        <Dialog.Content className="support-training-dialog">
          <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("人工训练")}</Text><Dialog.Title>{t(caseEditingId ? "编辑训练案例" : "新增训练案例")}</Dialog.Title><Dialog.Description>{t("案例描述理想行为；涉及商品事实时，运行时仍会重新读取证据。")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={() => setCaseOpen(false)}><X /></Button></div>
          <form onSubmit={(event) => void saveCase(event)}>
            <div className="support-agent-form-grid">
              <label><Text size="1" color="gray">{t("案例标题")}</Text><TextField.Root required maxLength={240} value={caseDraft.title} onChange={(event) => setCaseDraft({ ...caseDraft, title: event.target.value })}/></label>
              <label><Text size="1" color="gray">{t("语言")}</Text><TextField.Root required maxLength={35} value={caseDraft.language} onChange={(event) => setCaseDraft({ ...caseDraft, language: event.target.value })}/></label>
              <label><Text size="1" color="gray">{t("回答动作")}</Text><Select.Root value={caseDraft.responseAction} onValueChange={(value) => setCaseDraft({ ...caseDraft, responseAction: value as SupportAITrainingResponseAction })}><Select.Trigger/><Select.Content><Select.Item value="ANSWER">ANSWER</Select.Item><Select.Item value="CLARIFY">CLARIFY</Select.Item><Select.Item value="HANDOFF">HANDOFF</Select.Item></Select.Content></Select.Root></label>
              <label><Text size="1" color="gray">{t("事实模式")}</Text><Select.Root value={caseDraft.groundingMode} onValueChange={(value) => setCaseDraft({ ...caseDraft, groundingMode: value as SupportAITrainingGroundingMode })}><Select.Trigger/><Select.Content><Select.Item value="EVIDENCE">EVIDENCE</Select.Item><Select.Item value="GENERAL_GUIDANCE">GENERAL_GUIDANCE</Select.Item><Select.Item value="APPROVED_COMPANY_PROFILE">APPROVED_COMPANY_PROFILE</Select.Item></Select.Content></Select.Root></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("客户问题")}</Text><TextArea required value={caseDraft.customerMessage} onChange={(event) => setCaseDraft({ ...caseDraft, customerMessage: event.target.value })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("理想回答 / 行为")}</Text><TextArea required value={caseDraft.idealResponse} onChange={(event) => setCaseDraft({ ...caseDraft, idealResponse: event.target.value })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("行为备注")}</Text><TextArea value={caseDraft.behaviorNotes || ""} onChange={(event) => setCaseDraft({ ...caseDraft, behaviorNotes: event.target.value })}/></label>
              <label><Text size="1" color="gray">{t("需要的证据类型")}</Text><TextField.Root value={caseDraft.requiredEvidenceTypes.join(", ")} onChange={(event) => setCaseDraft({ ...caseDraft, requiredEvidenceTypes: splitValues(event.target.value) })}/></label>
              <label><Text size="1" color="gray">{t("标签")}</Text><TextField.Root value={caseDraft.tags.join(", ")} onChange={(event) => setCaseDraft({ ...caseDraft, tags: splitValues(event.target.value) })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("禁止行为（逗号分隔）")}</Text><TextField.Root value={caseDraft.forbiddenPatterns.join(", ")} onChange={(event) => setCaseDraft({ ...caseDraft, forbiddenPatterns: splitValues(event.target.value) })}/></label>
            </div>
            <div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={() => setCaseOpen(false)}>{t("取消")}</Button><Button type="submit" loading={busy === "case-save"}><FloppyDisk />{t("保存案例")}</Button></div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={ruleOpen} onOpenChange={(open) => { if (!busy) setRuleOpen(open); }}>
        <Dialog.Content className="support-training-dialog">
          <div className="core-dialog-heading"><div><Text size="1" color="gray">{t("可复用策略")}</Text><Dialog.Title>{t(ruleEditingId ? "编辑训练规则" : "新增训练规则")}</Dialog.Title><Dialog.Description>{t("规则应当可跨商品复用，不能包含具体价格、MOQ、SKU 或商品编码。")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={() => setRuleOpen(false)}><X /></Button></div>
          <form onSubmit={(event) => void saveRule(event)}><div className="support-agent-form-grid"><label><Text size="1" color="gray">{t("规则标题")}</Text><TextField.Root required value={ruleDraft.title} onChange={(event) => setRuleDraft({ ...ruleDraft, title: event.target.value })}/></label><label><Text size="1" color="gray">{t("优先级")}</Text><TextField.Root type="number" min="0" max="1000" value={ruleDraft.priority} onChange={(event) => setRuleDraft({ ...ruleDraft, priority: Number(event.target.value) })}/></label><label className="support-agent-wide"><Text size="1" color="gray">{t("规则指令")}</Text><TextArea required value={ruleDraft.instruction} onChange={(event) => setRuleDraft({ ...ruleDraft, instruction: event.target.value })}/></label><label className="support-agent-wide"><Text size="1" color="gray">{t("适用范围（逗号分隔）")}</Text><TextField.Root value={ruleDraft.scopes.join(", ")} onChange={(event) => setRuleDraft({ ...ruleDraft, scopes: splitValues(event.target.value).map((item) => item.toUpperCase()) })}/></label></div><div className="core-dialog-actions"><Button type="button" variant="soft" color="gray" onClick={() => setRuleOpen(false)}>{t("取消")}</Button><Button type="submit" loading={busy === "rule-save"}><FloppyDisk />{t("保存规则")}</Button></div></form>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={generateOpen} onOpenChange={(open) => { if (!busy) setGenerateOpen(open); }}>
        <Dialog.Content className="support-training-dialog"><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("AI 辅助生成")}</Text><Dialog.Title>{t("根据公开商品生成案例")}</Dialog.Title><Dialog.Description>{t("模型只会收到对客可见的商品字段，生成结果保存为草稿。")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={() => setGenerateOpen(false)}><X /></Button></div><div className="support-agent-form-grid"><label><Text size="1" color="gray">{t("来源店铺")}</Text><Select.Root value={generateStoreId} onValueChange={setGenerateStoreId}><Select.Trigger/><Select.Content>{agent?.stores.map((store) => <Select.Item key={store.tenantId} value={store.tenantId}>{store.tenantName}</Select.Item>)}</Select.Content></Select.Root></label><label><Text size="1" color="gray">{t("生成数量")}</Text><TextField.Root type="number" min="1" max="40" value={generateCount} onChange={(event) => setGenerateCount(event.target.value)}/></label><label className="support-agent-wide"><Text size="1" color="gray">{t("案例语言（逗号分隔）")}</Text><TextField.Root value={generateLanguages} onChange={(event) => setGenerateLanguages(event.target.value)}/></label></div><div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={() => setGenerateOpen(false)}>{t("取消")}</Button><Button loading={busy === "generate"} disabled={!generateStoreId} onClick={() => void generateCases()}><MagicWand />{t("开始生成")}</Button></div></Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={releaseOpen} onOpenChange={(open) => { if (!busy) setReleaseOpen(open); }}>
        <Dialog.Content className="support-training-dialog"><div className="core-dialog-heading"><div><Text size="1" color="gray">{t("版本化发布")}</Text><Dialog.Title>{t("发布训练版本")}</Dialog.Title><Dialog.Description>{t("只会打包已批准案例和规则，并立即同步到绑定店铺；历史版本可随时回滚。")}</Dialog.Description></div><Button variant="ghost" color="gray" onClick={() => setReleaseOpen(false)}><X /></Button></div><label className="support-training-release-notes"><Text size="1" color="gray">{t("发布说明（选填）")}</Text><TextArea value={releaseNotes} onChange={(event) => setReleaseNotes(event.target.value)} placeholder={t("例如：加强场景推荐，减少无必要转人工")}/></label><div className="core-dialog-actions"><Button variant="soft" color="gray" onClick={() => setReleaseOpen(false)}>{t("取消")}</Button><Button loading={busy === "publish"} onClick={() => void publish()}><UploadSimple />{t("确认发布")}</Button></div></Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
