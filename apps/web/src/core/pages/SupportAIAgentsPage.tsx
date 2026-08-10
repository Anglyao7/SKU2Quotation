import {
  Badge,
  Button,
  Card,
  Dialog,
  Heading,
  Select,
  Table,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowRight,
  Brain,
  Database,
  Plus,
  Robot,
  SlidersHorizontal,
  Storefront,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  createSupportAIAgent,
  listSupportAIAgents,
  listSupportAIProviderProfiles,
  updateSupportAIAgent,
} from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, coreDate } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { SupportAIAgent, SupportAIProviderSettings } from "../types";
import "./SupportAIAgentManagement.css";

export function SupportAIAgentsPage() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [agents, setAgents] = useState<SupportAIAgent[]>([]);
  const [profiles, setProfiles] = useState<SupportAIProviderSettings[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [bindingAgentId, setBindingAgentId] = useState("");
  const [message, setMessage] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [providerProfileId, setProviderProfileId] = useState("unassigned");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextAgents, nextProfiles] = await Promise.all([
        listSupportAIAgents(),
        listSupportAIProviderProfiles(),
      ]);
      setAgents(nextAgents);
      setProfiles(nextProfiles);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体列表加载失败"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const createAgent = async (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    setError("");
    try {
      const agent = await createSupportAIAgent({
        name: name.trim(),
        description: description.trim() || undefined,
        providerProfileId: providerProfileId === "unassigned" ? undefined : providerProfileId,
      });
      setCreateOpen(false);
      setName("");
      setDescription("");
      setProviderProfileId("unassigned");
      navigate(`/console/agents/${agent.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体创建失败"));
    } finally {
      setCreating(false);
    }
  };

  const assignProfile = async (agent: SupportAIAgent, value: string) => {
    if (bindingAgentId) return;
    const nextProfileId = value === "unassigned" ? null : value;
    setBindingAgentId(agent.id);
    setError("");
    setMessage("");
    try {
      const updated = await updateSupportAIAgent(agent.id, {
        providerProfileId: nextProfileId,
        enabled: nextProfileId ? agent.enabled : false,
      });
      setAgents((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMessage(nextProfileId
        ? t("已为“{name}”分配 {model}。", {
          name: agent.name,
          model: profiles.find((profile) => profile.id === nextProfileId)?.displayModelName || t("模型配置"),
        })
        : t("已取消“{name}”的模型配置并停用智能体。", { name: agent.name }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("智能体模型分配失败"));
    } finally {
      setBindingAgentId("");
    }
  };

  const enabledCount = agents.filter((agent) => agent.enabled).length;
  const boundStoreCount = new Set(agents.flatMap((agent) => agent.stores.map((store) => store.tenantId))).size;
  const knowledgeCount = agents.reduce((total, agent) => total + agent.knowledgeSourceCount, 0);

  return (
    <div className="core-workspace support-agent-page">
      <CorePageHeading
        eyebrow={t("智能体管理")}
        title={t("智能体列表")}
        actions={(
          <>
            <Button variant="soft" color="gray" disabled={loading} onClick={() => void load()}>
              <ArrowClockwise />{t("刷新")}
            </Button>
            <Button asChild variant="soft" color="gray">
              <Link to="/console/system/configuration"><SlidersHorizontal />{t("API 配置中心")}</Link>
            </Button>
            <Button onClick={() => setCreateOpen(true)}><Plus />{t("新增智能体")}</Button>
          </>
        )}
      />

      <section className="support-agent-metrics" aria-label={t("智能体概览")}>
        <Card><Robot weight="duotone" /><span><small>{t("智能体")}</small><strong>{agents.length}</strong></span></Card>
        <Card><Brain weight="duotone" /><span><small>{t("运行中")}</small><strong>{enabledCount}</strong></span></Card>
        <Card><Storefront weight="duotone" /><span><small>{t("已绑定店铺")}</small><strong>{boundStoreCount}</strong></span></Card>
        <Card><Database weight="duotone" /><span><small>{t("知识文件")}</small><strong>{knowledgeCount}</strong></span></Card>
      </section>

      {error ? <CoreError message={error} onRetry={() => void load()} /> : null}
      {message ? <Card className="support-agent-success"><Text size="2">{message}</Text></Card> : null}
      {loading ? <CoreLoading label={t("正在读取智能体")} /> : null}
      {!loading && !agents.length ? (
        <CoreEmpty
          title={t("还没有智能体")}
          description={t("创建智能体后，再配置模型、绑定店铺和上传知识库。")}
          action={<Button onClick={() => setCreateOpen(true)}><Plus />{t("新增智能体")}</Button>}
        />
      ) : null}

      {!loading && agents.length ? (
        <Card className="support-agent-table-card">
          <div className="support-agent-section-heading">
            <div><Text size="1" color="gray">{t("平台智能客服")}</Text><Heading size="5">{t("现有智能体")}</Heading></div>
            <Badge color="gray">{agents.length}</Badge>
          </div>
          <div className="support-agent-table-wrap">
            <Table.Root size="2">
              <Table.Header>
                <Table.Row>
                  <Table.ColumnHeaderCell>{t("智能体")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("智能体 ID")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("状态")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("模型")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("绑定店铺")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("知识库")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell>{t("更新时间")}</Table.ColumnHeaderCell>
                  <Table.ColumnHeaderCell justify="end">{t("操作")}</Table.ColumnHeaderCell>
                </Table.Row>
              </Table.Header>
              <Table.Body>
                {agents.map((agent) => (
                  <Table.Row key={agent.id}>
                    <Table.RowHeaderCell>
                      <div className="support-agent-name-cell">
                        <span><Robot weight="duotone" /></span>
                        <div><strong>{agent.name}</strong><small>{agent.description || t("暂无说明")}</small></div>
                      </div>
                    </Table.RowHeaderCell>
                    <Table.Cell><code className="support-agent-code">{agent.agentCode}</code></Table.Cell>
                    <Table.Cell><Badge color={agent.enabled ? "jade" : "gray"}>{t(agent.enabled ? "启用" : "停用")}</Badge></Table.Cell>
                    <Table.Cell>
                      <div className="support-agent-model-assignment">
                        <Select.Root
                          value={agent.providerProfileId || "unassigned"}
                          disabled={Boolean(bindingAgentId)}
                          onValueChange={(value) => void assignProfile(agent, value)}
                        >
                          <Select.Trigger aria-label={t("为 {name} 分配模型", { name: agent.name })} />
                          <Select.Content position="popper">
                            <Select.Item value="unassigned">{t("不分配模型")}</Select.Item>
                            {profiles
                              .filter((profile) => profile.id && (profile.enabled || profile.id === agent.providerProfileId))
                              .map((profile) => (
                                <Select.Item value={profile.id || ""} key={profile.id}>
                                  {profile.displayModelName || profile.configurationName || profile.modelName}
                                </Select.Item>
                              ))}
                          </Select.Content>
                        </Select.Root>
                        {!agent.apiConfigured ? <small className="is-warning">{t("API 未完成")}</small> : null}
                      </div>
                    </Table.Cell>
                    <Table.Cell>{agent.stores.length}</Table.Cell>
                    <Table.Cell>{agent.approvedKnowledgeSourceCount} / {agent.knowledgeSourceCount}</Table.Cell>
                    <Table.Cell><Text size="1" color="gray">{coreDate(agent.updatedAt)}</Text></Table.Cell>
                    <Table.Cell justify="end">
                      <Button asChild size="1" variant="soft" color="gray">
                        <Link to={`/console/agents/${agent.id}`}>{t("详情配置")}<ArrowRight /></Link>
                      </Button>
                    </Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table.Root>
          </div>
        </Card>
      ) : null}

      <Dialog.Root open={createOpen} onOpenChange={setCreateOpen}>
        <Dialog.Content className="support-agent-create-dialog" maxWidth="520px">
          <Dialog.Title>{t("新增智能体")}</Dialog.Title>
          <Dialog.Description>{t("创建后会自动生成唯一的 8 位智能体 ID。")}</Dialog.Description>
          <form className="support-agent-dialog-form" onSubmit={(event) => void createAgent(event)}>
            <label><Text size="2" weight="medium">{t("智能体名称")}</Text><TextField.Root value={name} onChange={(event) => setName(event.target.value)} maxLength={160} autoFocus required placeholder={t("例如：售前客服")}/></label>
            <label><Text size="2" weight="medium">{t("说明（选填）")}</Text><TextArea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={4000} placeholder={t("说明这个智能体负责的业务")}/></label>
            <label>
              <Text size="2" weight="medium">{t("模型配置（选填）")}</Text>
              <Select.Root value={providerProfileId} onValueChange={setProviderProfileId}>
                <Select.Trigger />
                <Select.Content position="popper">
                  <Select.Item value="unassigned">{t("创建后再分配")}</Select.Item>
                  {profiles.filter((profile) => profile.enabled && profile.id).map((profile) => (
                    <Select.Item value={profile.id || ""} key={profile.id}>
                      {profile.displayModelName || profile.configurationName || profile.modelName}
                    </Select.Item>
                  ))}
                </Select.Content>
              </Select.Root>
            </label>
            <div className="core-dialog-actions">
              <Dialog.Close><Button type="button" variant="soft" color="gray" disabled={creating}>{t("取消")}</Button></Dialog.Close>
              <Button type="submit" loading={creating} disabled={!name.trim()}>{t("创建智能体")}</Button>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}
