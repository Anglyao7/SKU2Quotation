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
  ArrowLeft,
  Check,
  DownloadSimple,
  FloppyDisk,
  Plus,
  Robot,
  Trash,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import {
  approveAllSupportAITraining,
  createSupportAITrainingCase,
  createSupportAITrainingRule,
  deleteSupportAITrainingCase,
  deleteSupportAITrainingRule,
  exportSupportAITraining,
  getSupportAIAgent,
  getSupportAITrainingOverview,
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
  requiredEvidenceTypes: [],
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

const RESPONSE_ACTION_LABELS: Record<SupportAITrainingResponseAction, string> = {
  ANSWER: "直接回答",
  CLARIFY: "追问澄清",
  HANDOFF: "转人工",
};

const GROUNDING_MODE_LABELS: Record<SupportAITrainingGroundingMode, string> = {
  EVIDENCE: "依据知识证据",
  GENERAL_GUIDANCE: "通用建议",
  APPROVED_COMPANY_PROFILE: "已批准企业资料",
};

const RECOMMENDED_COMBINATIONS: Array<{
  key: string;
  title: string;
  description: string;
  responseAction: SupportAITrainingResponseAction;
  groundingMode: SupportAITrainingGroundingMode;
}> = [
  {
    key: "product-recommendation",
    title: "商品推荐",
    description: "有匹配商品证据时直接推荐，并说明理由和引用来源。",
    responseAction: "ANSWER",
    groundingMode: "EVIDENCE",
  },
  {
    key: "ambiguous-request",
    title: "需求太模糊",
    description: "先给通用方向，再追问一个最关键条件。",
    responseAction: "CLARIFY",
    groundingMode: "GENERAL_GUIDANCE",
  },
  {
    key: "greeting",
    title: "打招呼",
    description: "回复问候，并结合已批准的企业介绍说明服务范围。",
    responseAction: "ANSWER",
    groundingMode: "APPROVED_COMPANY_PROFILE",
  },
  {
    key: "human-refund",
    title: "人工处理退款",
    description: "客户明确要求人工或退款必须人工执行时转交人工。",
    responseAction: "HANDOFF",
    groundingMode: "GENERAL_GUIDANCE",
  },
];

export function SupportAITrainingPage() {
  const { agentId = "" } = useParams();
  const { t } = useLocale();
  const [agent, setAgent] = useState<SupportAIAgent>();
  const [overview, setOverview] = useState<SupportAITrainingOverview>();
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

  const load = useCallback(async () => {
    if (!agentId) return;
    setLoading(true);
    setError("");
    try {
      const [nextAgent, nextOverview] = await Promise.all([
        getSupportAIAgent(agentId),
        getSupportAITrainingOverview(agentId),
      ]);
      setAgent(nextAgent);
      setOverview(nextOverview);
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
    setOverview(await getSupportAITrainingOverview(agentId));
  };

  const runAction = async (
    key: string,
    action: () => Promise<string | void>,
    success: string,
  ) => {
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
      const payload = { ...caseDraft, status: "DRAFT" as const };
      if (caseEditingId) {
        await updateSupportAITrainingCase(agentId, caseEditingId, payload);
      } else {
        await createSupportAITrainingCase(agentId, payload);
      }
      await reloadOverview();
      setCaseOpen(false);
    }, t("训练案例已保存为草稿，请一键审批后生效"));
  };

  const removeCase = (item: SupportAITrainingCase) => runAction(
    `case-delete-${item.id}`,
    async () => {
      await deleteSupportAITrainingCase(agentId, item.id);
      await reloadOverview();
    },
    t("训练案例已删除，请一键审批使变更生效"),
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
      const payload = { ...ruleDraft, status: "DRAFT" as const };
      if (ruleEditingId) {
        await updateSupportAITrainingRule(agentId, ruleEditingId, payload);
      } else {
        await createSupportAITrainingRule(agentId, payload);
      }
      await reloadOverview();
      setRuleOpen(false);
    }, t("复用规则已保存为草稿，请一键审批后生效"));
  };

  const removeRule = (item: SupportAITrainingRule) => runAction(
    `rule-delete-${item.id}`,
    async () => {
      await deleteSupportAITrainingRule(agentId, item.id);
      await reloadOverview();
    },
    t("复用规则已删除，请一键审批使变更生效"),
  );

  const approveAll = () => runAction("approve-all", async () => {
    setOverview(await approveAllSupportAITraining(agentId));
  }, t("全部草稿已审批并生效"));

  const exportTraining = () => runAction("export", async () => {
    await exportSupportAITraining(agentId, agent?.agentCode || agentId);
  }, t("训练数据已导出"));

  return (
    <div className="core-workspace support-agent-page support-training-page">
      <CorePageHeading
        eyebrow={t("知识库管理")}
        title={agent ? `${agent.name} · ${t("AI 训练工作台")}` : t("AI 训练工作台")}
        actions={(
          <>
            <Button asChild variant="soft" color="gray">
              <Link to={`/console/agents/knowledge?agent_id=${agentId}`}><ArrowLeft />{t("返回知识库")}</Link>
            </Button>
            <Button
              variant="soft"
              color="gray"
              disabled={!agent || Boolean(busy)}
              loading={busy === "export"}
              onClick={() => void exportTraining()}
            >
              <DownloadSimple />{t("导出")}
            </Button>
            <Button
              disabled={!overview?.cases.length || Boolean(busy)}
              loading={busy === "approve-all"}
              onClick={() => void approveAll()}
            >
              <Check weight="bold" />{t("一键审批")}
            </Button>
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
              <Heading size="4">{t("案例和规则统一审批")}</Heading>
              <Text size="2" color="gray">
                {t("知识库中导入的训练 JSON 会在这里解析为草稿。人工新增或编辑后，点击“一键审批”即可统一审核并立即生效。")}
              </Text>
            </div>
            <Badge color={overview.activeVersionId ? "jade" : "gray"}>
              {overview.activeVersionNumber ? `v${overview.activeVersionNumber} ${t("运行中")}` : t("尚未生效")}
            </Badge>
          </Card>

          <Tabs.Root defaultValue="cases" className="support-training-tabs">
            <Tabs.List>
              <Tabs.Trigger value="cases">
                {t("案例训练")} · {overview.cases.length}
                {overview.draftCaseCount ? ` (${overview.draftCaseCount} ${t("草稿")})` : ""}
              </Tabs.Trigger>
              <Tabs.Trigger value="rules">
                {t("复用规则")} · {overview.rules.length}
                {overview.draftRuleCount ? ` (${overview.draftRuleCount} ${t("草稿")})` : ""}
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value="cases">
              <Card className="support-training-list-card">
                <div className="support-agent-section-heading">
                  <div><Text size="1" color="gray">{t("导入 JSON 或人工添加")}</Text><Heading size="5">{t("案例训练")}</Heading></div>
                  <Button onClick={() => openCase()}><Plus />{t("新增案例")}</Button>
                </div>
                {!overview.cases.length ? (
                  <CoreEmpty
                    title={t("还没有训练案例")}
                    description={t("请在知识库导入案例 JSON，或在这里手工新增案例。")}
                  />
                ) : (
                  <div className="support-training-case-list">
                    {overview.cases.map((item) => (
                      <article key={item.id}>
                        <div className="support-training-item-heading">
                          <div>
                            <Heading size="3">{item.title}</Heading>
                            <span>
                              <Badge color={statusColor(item.status)}>{t(item.status === "APPROVED" ? "已生效" : item.status === "DRAFT" ? "待审批" : "已归档")}</Badge>
                              <Badge color="gray">{item.language}</Badge>
                              <Badge color="blue">{t(RESPONSE_ACTION_LABELS[item.responseAction])}</Badge>
                              <Badge color="gray">{t(GROUNDING_MODE_LABELS[item.groundingMode])}</Badge>
                            </span>
                          </div>
                          <small>{coreDate(item.updatedAt)}</small>
                        </div>
                        <div className="support-training-qa">
                          <div><small>{t("客户问题")}</small><p>{item.customerMessage}</p></div>
                          <div><small>{t("理想回答")}</small><p>{item.idealResponse}</p></div>
                        </div>
                        <div className="support-training-item-actions">
                          <Button size="1" variant="soft" color="gray" onClick={() => openCase(item)}>{t("编辑")}</Button>
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
                <div className="support-agent-section-heading">
                  <div><Text size="1" color="gray">{t("跨案例复用的处理原则")}</Text><Heading size="5">{t("复用规则")}</Heading></div>
                  <Button onClick={() => openRule()}><Plus />{t("新增规则")}</Button>
                </div>
                {!overview.rules.length ? (
                  <CoreEmpty title={t("还没有复用规则")} description={t("可以从案例中人工整理规则，或在这里直接新增。")}/>
                ) : (
                  <div className="support-training-rule-list">
                    {overview.rules.map((item) => (
                      <article key={item.id}>
                        <div>
                          <span>
                            <Badge color={statusColor(item.status)}>{t(item.status === "APPROVED" ? "已生效" : "待审批")}</Badge>
                            <Badge color="gray">P{item.priority}</Badge>
                            {item.scopes.map((scope) => <Badge key={scope} color="gray">{scope}</Badge>)}
                          </span>
                          <Heading size="3">{item.title}</Heading>
                          <Text size="2">{item.instruction}</Text>
                        </div>
                        <div className="support-training-item-actions">
                          <Button size="1" variant="soft" color="gray" onClick={() => openRule(item)}>{t("编辑")}</Button>
                          <Button size="1" variant="ghost" color="red" disabled={Boolean(busy)} onClick={() => void removeRule(item)}><Trash />{t("删除")}</Button>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </Card>
            </Tabs.Content>
          </Tabs.Root>
        </>
      ) : null}

      <Dialog.Root open={caseOpen} onOpenChange={(open) => { if (!busy) setCaseOpen(open); }}>
        <Dialog.Content className="support-training-dialog">
          <div className="core-dialog-heading">
            <div>
              <Text size="1" color="gray">{t("案例训练")}</Text>
              <Dialog.Title>{t(caseEditingId ? "编辑训练案例" : "新增训练案例")}</Dialog.Title>
              <Dialog.Description>{t("只填写客户会怎么问，以及 AI 应该如何回答。")}</Dialog.Description>
            </div>
            <Button variant="ghost" color="gray" onClick={() => setCaseOpen(false)}><X /></Button>
          </div>
          <form onSubmit={(event) => void saveCase(event)}>
            <div className="support-agent-form-grid">
              <label><Text size="1" color="gray">{t("案例标题")}</Text><TextField.Root required maxLength={240} value={caseDraft.title} onChange={(event) => setCaseDraft({ ...caseDraft, title: event.target.value })}/></label>
              <label><Text size="1" color="gray">{t("语言")}</Text><TextField.Root required maxLength={35} value={caseDraft.language} onChange={(event) => setCaseDraft({ ...caseDraft, language: event.target.value })}/></label>
            </div>
            <div className="support-training-combination-picker">
              <div>
                <Text size="1" color="gray">{t("推荐组合")}</Text>
                <strong>{t("选择这个案例要训练的处理方式")}</strong>
              </div>
              <div className="support-training-combination-grid">
                {RECOMMENDED_COMBINATIONS.map((combination) => {
                  const selected = caseDraft.responseAction === combination.responseAction
                    && caseDraft.groundingMode === combination.groundingMode;
                  return (
                    <button
                      key={combination.key}
                      type="button"
                      className={selected ? "is-selected" : undefined}
                      aria-pressed={selected}
                      onClick={() => setCaseDraft((current) => ({
                        ...current,
                        responseAction: combination.responseAction,
                        groundingMode: combination.groundingMode,
                      }))}
                    >
                      <span><strong>{t(combination.title)}</strong>{selected ? <Check weight="bold" /> : null}</span>
                      <small>{t(RESPONSE_ACTION_LABELS[combination.responseAction])} + {t(GROUNDING_MODE_LABELS[combination.groundingMode])}</small>
                      <p>{t(combination.description)}</p>
                    </button>
                  );
                })}
              </div>
            </div>
            <div className="support-agent-form-grid">
              <label><Text size="1" color="gray">{t("回答动作")}</Text><Select.Root value={caseDraft.responseAction} onValueChange={(value) => setCaseDraft({ ...caseDraft, responseAction: value as SupportAITrainingResponseAction })}><Select.Trigger/><Select.Content><Select.Item value="ANSWER">{t("直接回答")}</Select.Item><Select.Item value="CLARIFY">{t("追问澄清")}</Select.Item><Select.Item value="HANDOFF">{t("转人工")}</Select.Item></Select.Content></Select.Root></label>
              <label><Text size="1" color="gray">{t("回答依据")}</Text><Select.Root value={caseDraft.groundingMode} onValueChange={(value) => setCaseDraft({ ...caseDraft, groundingMode: value as SupportAITrainingGroundingMode })}><Select.Trigger/><Select.Content><Select.Item value="EVIDENCE">{t("依据知识证据")}</Select.Item><Select.Item value="GENERAL_GUIDANCE">{t("通用建议")}</Select.Item><Select.Item value="APPROVED_COMPANY_PROFILE">{t("已批准企业资料")}</Select.Item></Select.Content></Select.Root></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("客户问题")}</Text><TextArea required value={caseDraft.customerMessage} onChange={(event) => setCaseDraft({ ...caseDraft, customerMessage: event.target.value })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("理想回答")}</Text><TextArea required value={caseDraft.idealResponse} onChange={(event) => setCaseDraft({ ...caseDraft, idealResponse: event.target.value })}/></label>
            </div>
            <div className="core-dialog-actions">
              <Button type="button" variant="soft" color="gray" onClick={() => setCaseOpen(false)}>{t("取消")}</Button>
              <Button type="submit" loading={busy === "case-save"}><FloppyDisk />{t("保存为草稿")}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root open={ruleOpen} onOpenChange={(open) => { if (!busy) setRuleOpen(open); }}>
        <Dialog.Content className="support-training-dialog">
          <div className="core-dialog-heading">
            <div><Text size="1" color="gray">{t("复用规则")}</Text><Dialog.Title>{t(ruleEditingId ? "编辑复用规则" : "新增复用规则")}</Dialog.Title><Dialog.Description>{t("规则应当可跨商品复用，不能包含具体价格、MOQ、SKU 或商品编码。")}</Dialog.Description></div>
            <Button variant="ghost" color="gray" onClick={() => setRuleOpen(false)}><X /></Button>
          </div>
          <form onSubmit={(event) => void saveRule(event)}>
            <div className="support-agent-form-grid">
              <label><Text size="1" color="gray">{t("规则标题")}</Text><TextField.Root required value={ruleDraft.title} onChange={(event) => setRuleDraft({ ...ruleDraft, title: event.target.value })}/></label>
              <label><Text size="1" color="gray">{t("优先级")}</Text><TextField.Root type="number" min="0" max="1000" value={ruleDraft.priority} onChange={(event) => setRuleDraft({ ...ruleDraft, priority: Number(event.target.value) })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("规则指令")}</Text><TextArea required value={ruleDraft.instruction} onChange={(event) => setRuleDraft({ ...ruleDraft, instruction: event.target.value })}/></label>
              <label className="support-agent-wide"><Text size="1" color="gray">{t("适用范围（逗号分隔）")}</Text><TextField.Root value={ruleDraft.scopes.join(", ")} onChange={(event) => setRuleDraft({ ...ruleDraft, scopes: splitValues(event.target.value).map((item) => item.toUpperCase()) })}/></label>
            </div>
            <div className="core-dialog-actions">
              <Button type="button" variant="soft" color="gray" onClick={() => setRuleOpen(false)}>{t("取消")}</Button>
              <Button type="submit" loading={busy === "rule-save"}><FloppyDisk />{t("保存为草稿")}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
