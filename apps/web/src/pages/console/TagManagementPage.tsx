import {
  AlertDialog,
  Badge,
  Button,
  Callout,
  Dialog,
  Heading,
  IconButton,
  Select,
  Table,
  Text,
  TextField,
  TextArea,
} from "@radix-ui/themes";
import {
  Plus,
  Tag as TagIcon,
  Trash,
  NotePencil,
  WarningCircle,
  CheckCircle,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useOutletContext } from "react-router-dom";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/States";
import { useCoreAuth } from "../../core/AuthContext";
import { api } from "../../lib/api";
import type { ProductTag } from "../../types";
import type { ConsoleOutletContext } from "./ConsoleLayout";

interface TagPayload {
  name: string;
  description: string;
  category: string;
}

const emptyPayload: TagPayload = {
  name: "",
  description: "",
  category: "",
};

const TAG_CATEGORIES = [
  { value: "", label: "不分类" },
  { value: "状态", label: "状态标签" },
  { value: "特性", label: "特性标签" },
  { value: "场景", label: "场景标签" },
  { value: "优势", label: "优势标签" },
];

export function TagManagementPage() {
  const { profile } = useCoreAuth();
  const { activeTenantId } = useOutletContext<ConsoleOutletContext>();
  const [tags, setTags] = useState<ProductTag[]>([]);
  const [total, setTotal] = useState(0);
  const [categoryFilter, setCategoryFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState<ProductTag | "new" | null>(null);
  const [deleting, setDeleting] = useState<ProductTag | null>(null);
  const [payload, setPayload] = useState<TagPayload>(emptyPayload);
  const [saving, setSaving] = useState(false);
  const isPlatformAdmin = Boolean(profile?.user.isPlatformAdmin);

  const load = useCallback(async () => {
    if (isPlatformAdmin && !activeTenantId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const data = await api.getProductTags(categoryFilter, 200);
      setTags(data.tags);
      setTotal(data.total);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "标签列表加载失败。");
    } finally {
      setLoading(false);
    }
  }, [activeTenantId, categoryFilter, isPlatformAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  const openCreate = () => {
    setPayload(emptyPayload);
    setEditing("new");
  };

  const openEdit = (tag: ProductTag) => {
    setPayload({
      name: tag.name,
      description: tag.description || "",
      category: tag.category || "",
    });
    setEditing(tag);
  };

  const closeDialog = () => {
    setEditing(null);
    setPayload(emptyPayload);
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!payload.name.trim()) return;

    setSaving(true);
    try {
      if (editing === "new") {
        await api.createProductTag({
          name: payload.name.trim(),
          description: payload.description.trim() || null,
          category: payload.category.trim() || null,
        });
      } else if (editing && typeof editing !== "string") {
        await api.updateProductTag(editing.id, {
          name: payload.name.trim() || undefined,
          description: payload.description.trim() || null,
          category: payload.category.trim() || null,
        });
      }

      closeDialog();
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "操作失败。");
    } finally {
      setSaving(false);
    }
  };

  const deleteTag = async () => {
    if (!deleting) return;

    try {
      await api.deleteProductTag(deleting.id);
      setDeleting(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "标签删除失败。");
      setDeleting(null);
    }
  };

  if (isPlatformAdmin && !activeTenantId) {
    return (
      <div className="console-page">
        <Callout.Root color="gray">
          <Callout.Icon>
            <WarningCircle weight="fill" />
          </Callout.Icon>
          <Callout.Text>请先从侧边栏选择一个租户，再管理标签。</Callout.Text>
        </Callout.Root>
      </div>
    );
  }

  return (
    <div className="console-page">
      <div className="page-heading-row">
        <div>
          <Heading as="h1" size="6">标签管理</Heading>
          <Text color="gray" size="2">
            统一管理产品标签，支持按分类组织，用于 AI 搜索和商品筛选
          </Text>
        </div>
        <Button onClick={openCreate}>
          <Plus weight="bold" />
          新建标签
        </Button>
      </div>

      <div style={{ display: "flex", gap: "12px", marginBottom: "20px" }}>
        <Select.Root value={categoryFilter} onValueChange={setCategoryFilter}>
          <Select.Trigger placeholder="全部分类" style={{ width: "180px" }} />
          <Select.Content>
            {TAG_CATEGORIES.map((cat) => (
              <Select.Item key={cat.value} value={cat.value}>
                {cat.label}
              </Select.Item>
            ))}
          </Select.Content>
        </Select.Root>
        <Badge color="gray" variant="soft">
          共 {total} 个标签
        </Badge>
      </div>

      {error && (
        <Callout.Root color="red" style={{ marginBottom: "16px" }}>
          <Callout.Icon>
            <WarningCircle weight="fill" />
          </Callout.Icon>
          <Callout.Text>{error}</Callout.Text>
        </Callout.Root>
      )}

      {loading ? (
        <TableSkeleton rows={8} />
      ) : error && tags.length === 0 ? (
        <ErrorState message={error} onRetry={load} />
      ) : tags.length === 0 ? (
        <EmptyState
          title="还没有标签"
          description="创建第一个标签，用于标记和分类您的商品。"
          action={<Button onClick={openCreate}><Plus weight="bold" />新建标签</Button>}
        />
      ) : (
        <Table.Root variant="surface">
          <Table.Header>
            <Table.Row>
              <Table.ColumnHeaderCell>标签名称</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>分类</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>说明</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell>使用次数</Table.ColumnHeaderCell>
              <Table.ColumnHeaderCell width="100px">操作</Table.ColumnHeaderCell>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {tags.map((tag) => (
              <Table.Row key={tag.id}>
                <Table.Cell>
                  <Badge color="blue" variant="soft">
                    <TagIcon weight="fill" />
                    {tag.name}
                  </Badge>
                </Table.Cell>
                <Table.Cell>
                  {tag.category ? (
                    <Badge color="gray" variant="soft">{tag.category}</Badge>
                  ) : (
                    <Text color="gray" size="2">—</Text>
                  )}
                </Table.Cell>
                <Table.Cell>
                  <Text size="2" color="gray">
                    {tag.description || "—"}
                  </Text>
                </Table.Cell>
                <Table.Cell>
                  <Badge color={tag.usage_count > 0 ? "jade" : "gray"} variant="soft">
                    {tag.usage_count}
                  </Badge>
                </Table.Cell>
                <Table.Cell>
                  <div style={{ display: "flex", gap: "8px" }}>
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="gray"
                      onClick={() => openEdit(tag)}
                      aria-label="编辑"
                    >
                      <NotePencil weight="fill" />
                    </IconButton>
                    <IconButton
                      size="1"
                      variant="ghost"
                      color="red"
                      onClick={() => setDeleting(tag)}
                      aria-label="删除"
                    >
                      <Trash weight="fill" />
                    </IconButton>
                  </div>
                </Table.Cell>
              </Table.Row>
            ))}
          </Table.Body>
        </Table.Root>
      )}

      <Dialog.Root open={editing !== null} onOpenChange={(open) => !open && closeDialog()}>
        <Dialog.Content maxWidth="480px">
          <Dialog.Title>{editing === "new" ? "新建标签" : "编辑标签"}</Dialog.Title>
          <form onSubmit={handleSubmit}>
            <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
              <label>
                <Text size="2" weight="medium" as="div" mb="1">
                  标签名称 <Text color="red" as="span">*</Text>
                </Text>
                <TextField.Root
                  value={payload.name}
                  onChange={(e) => setPayload({ ...payload, name: e.target.value })}
                  placeholder="例如：Hot / 畅销 / 防水"
                  maxLength={80}
                  required
                />
              </label>

              <label>
                <Text size="2" weight="medium" as="div" mb="1">
                  标签分类
                </Text>
                <Select.Root
                  value={payload.category}
                  onValueChange={(value) => setPayload({ ...payload, category: value })}
                >
                  <Select.Trigger placeholder="选择分类" />
                  <Select.Content>
                    {TAG_CATEGORIES.map((cat) => (
                      <Select.Item key={cat.value} value={cat.value}>
                        {cat.label}
                      </Select.Item>
                    ))}
                  </Select.Content>
                </Select.Root>
              </label>

              <label>
                <Text size="2" weight="medium" as="div" mb="1">
                  标签说明
                </Text>
                <TextArea
                  value={payload.description}
                  onChange={(e) => setPayload({ ...payload, description: e.target.value })}
                  placeholder="简要说明这个标签的用途和适用场景"
                  maxLength={500}
                  rows={3}
                />
              </label>

              <Callout.Root color="blue" size="1">
                <Callout.Icon>
                  <CheckCircle weight="fill" />
                </Callout.Icon>
                <Callout.Text>
                  标签会在 Excel 导入时自动创建，也可以在 RAG 搜索中起到语义匹配作用
                </Callout.Text>
              </Callout.Root>

              <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", marginTop: "8px" }}>
                <Dialog.Close>
                  <Button type="button" variant="soft" color="gray">
                    取消
                  </Button>
                </Dialog.Close>
                <Button type="submit" disabled={saving || !payload.name.trim()}>
                  {saving ? "保存中…" : editing === "new" ? "创建" : "保存"}
                </Button>
              </div>
            </div>
          </form>
        </Dialog.Content>
      </Dialog.Root>

      <AlertDialog.Root open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialog.Content maxWidth="400px">
          <AlertDialog.Title>确认删除</AlertDialog.Title>
          <AlertDialog.Description>
            确定要删除标签 <strong>"{deleting?.name}"</strong> 吗？
            {deleting && deleting.usage_count > 0 && (
              <Text as="div" color="red" size="2" mt="2">
                ⚠️ 此标签已被 {deleting.usage_count} 个商品使用
              </Text>
            )}
          </AlertDialog.Description>
          <div style={{ display: "flex", gap: "12px", justifyContent: "flex-end", marginTop: "16px" }}>
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray">取消</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action>
              <Button color="red" onClick={deleteTag}>删除</Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
