import { Badge, Button, Select, Text, TextField } from "@radix-ui/themes";
import {
  DotsSixVertical,
  Folder,
  FolderOpen,
  PencilSimple,
  Plus,
  TreeStructure,
} from "@phosphor-icons/react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { createCategory, reorderCategories, updateCategory } from "../api";
import type { ProductCategory } from "../types";

type Draft =
  | { mode: "create"; parentId?: string; name: string; sortOrder: number; status: "ACTIVE" }
  | { mode: "edit"; id: string; parentId?: string; name: string; sortOrder: number; status: "ACTIVE" | "INACTIVE"; version: number };

type DropPlacement = "before" | "after";

interface DragState {
  pointerId: number;
  sourceId: string;
  parentKey: string;
  targetId?: string;
  placement?: DropPlacement;
}

interface CategoryManagerProps {
  categories: ProductCategory[];
  onChanged: () => Promise<void>;
}

const rootParentKey = "__root__";

function categoryParentKey(category: ProductCategory) {
  return category.parentId ?? rootParentKey;
}

function sameOrder(left: ProductCategory[], right: ProductCategory[]) {
  return left.length === right.length && left.every((category, index) => category.id === right[index]?.id);
}

export function CategoryManager({
  categories,
  onChanged,
}: CategoryManagerProps) {
  const [displayCategories, setDisplayCategories] = useState(categories);
  const [draft, setDraft] = useState<Draft>({ mode: "create", name: "", sortOrder: 0, status: "ACTIVE" });
  const [saving, setSaving] = useState(false);
  const [reordering, setReordering] = useState(false);
  const [error, setError] = useState("");
  const [reorderError, setReorderError] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const dragStateRef = useRef<DragState | null>(null);
  const reorderingRef = useRef(false);

  useEffect(() => {
    setDisplayCategories(categories);
    setDraft((current) => {
      if (current.mode !== "edit") return current;
      const latest = categories.find((category) => category.id === current.id);
      return latest
        ? { ...current, version: latest.version, sortOrder: latest.sortOrder }
        : current;
    });
  }, [categories]);

  const roots = useMemo(
    () => displayCategories
      .filter((item) => !item.parentId)
      .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, "zh-CN")),
    [displayCategories],
  );
  const childrenByParent = useMemo(() => {
    const result = new Map<string, ProductCategory[]>();
    displayCategories.filter((item) => item.parentId).forEach((item) => {
      const rows = result.get(item.parentId!) ?? [];
      rows.push(item);
      result.set(item.parentId!, rows);
    });
    result.forEach((rows) => rows.sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, "zh-CN")));
    return result;
  }, [displayCategories]);

  const updateDragState = (next: DragState | null) => {
    dragStateRef.current = next;
    setDragState(next);
  };

  const beginRoot = () => {
    setError("");
    setDraft({ mode: "create", name: "", sortOrder: roots.length, status: "ACTIVE" });
  };

  const beginChild = (parentId: string) => {
    setError("");
    setDraft({
      mode: "create",
      parentId,
      name: "",
      sortOrder: childrenByParent.get(parentId)?.length ?? 0,
      status: "ACTIVE",
    });
  };

  const beginEdit = (category: ProductCategory) => {
    setError("");
    setDraft({
      mode: "edit",
      id: category.id,
      parentId: category.parentId,
      name: category.name,
      sortOrder: category.sortOrder,
      status: category.status === "INACTIVE" ? "INACTIVE" : "ACTIVE",
      version: category.version,
    });
  };

  const selectedChildren = draft.mode === "edit" ? childrenByParent.get(draft.id) ?? [] : [];
  const parentLocked = selectedChildren.length > 0;

  const save = async () => {
    const name = draft.name.trim();
    if (!name) {
      setError("请填写分类名称。");
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (draft.mode === "create") {
        const created = await createCategory({ name, parentId: draft.parentId, sortOrder: draft.sortOrder });
        await onChanged();
        beginEdit(created);
      } else {
        const updated = await updateCategory({
          id: draft.id,
          expectedVersion: draft.version,
          name,
          parentId: draft.parentId,
          sortOrder: draft.sortOrder,
          status: draft.status,
        });
        await onChanged();
        beginEdit(updated);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "分类保存失败。");
    } finally {
      setSaving(false);
    }
  };

  const persistReorder = async (
    siblings: ProductCategory[],
    sourceId: string,
    targetId: string,
    placement: DropPlacement,
  ) => {
    if (reorderingRef.current || sourceId === targetId) return;
    const source = siblings.find((category) => category.id === sourceId);
    if (!source) return;
    const reordered = siblings.filter((category) => category.id !== sourceId);
    const targetIndex = reordered.findIndex((category) => category.id === targetId);
    if (targetIndex < 0) return;
    reordered.splice(targetIndex + (placement === "after" ? 1 : 0), 0, source);
    if (sameOrder(siblings, reordered)) return;

    const normalized = reordered.map((category, index) => ({ ...category, sortOrder: index }));
    const optimisticById = new Map(normalized.map((category) => [category.id, category]));
    setDisplayCategories((current) => current.map((category) => optimisticById.get(category.id) ?? category));
    setDraft((current) => {
      if (current.mode !== "edit") return current;
      const next = optimisticById.get(current.id);
      return next ? { ...current, sortOrder: next.sortOrder } : current;
    });
    reorderingRef.current = true;
    setReordering(true);
    setReorderError("");

    try {
      const saved = await reorderCategories(normalized);
      const savedById = new Map(saved.map((category) => [category.id, category]));
      setDisplayCategories((current) => current.map((category) => savedById.get(category.id) ?? category));
      await onChanged();
    } catch (reason) {
      setDisplayCategories(categories);
      setReorderError(reason instanceof Error ? reason.message : "分类顺序保存失败，请刷新后重试。");
      await onChanged().catch(() => undefined);
    } finally {
      reorderingRef.current = false;
      setReordering(false);
    }
  };

  const startDragging = (
    event: PointerEvent<HTMLButtonElement>,
    category: ProductCategory,
  ) => {
    if (reorderingRef.current || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    updateDragState({
      pointerId: event.pointerId,
      sourceId: category.id,
      parentKey: categoryParentKey(category),
    });
  };

  const moveDragging = (event: PointerEvent<HTMLButtonElement>) => {
    const current = dragStateRef.current;
    if (!current || current.pointerId !== event.pointerId) return;
    event.preventDefault();
    const tree = event.currentTarget.closest<HTMLElement>(".core-category-tree");
    if (tree) {
      const bounds = tree.getBoundingClientRect();
      if (event.clientY < bounds.top + 44) tree.scrollBy({ top: -18 });
      else if (event.clientY > bounds.bottom - 44) tree.scrollBy({ top: 18 });
    }
    const targetNode = document
      .elementFromPoint(event.clientX, event.clientY)
      ?.closest<HTMLElement>(".core-category-node[data-category-id]");
    if (!targetNode || targetNode.dataset.categoryParent !== current.parentKey) {
      updateDragState({ ...current, targetId: undefined, placement: undefined });
      return;
    }
    const bounds = targetNode.getBoundingClientRect();
    updateDragState({
      ...current,
      targetId: targetNode.dataset.categoryId,
      placement: event.clientY < bounds.top + bounds.height / 2 ? "before" : "after",
    });
  };

  const finishDragging = (
    event: PointerEvent<HTMLButtonElement>,
    siblings: ProductCategory[],
  ) => {
    const current = dragStateRef.current;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    updateDragState(null);
    if (!current?.targetId || !current.placement) return;
    void persistReorder(siblings, current.sourceId, current.targetId, current.placement);
  };

  const cancelDragging = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    updateDragState(null);
  };

  const handleOrderKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    category: ProductCategory,
    siblings: ProductCategory[],
  ) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    const currentIndex = siblings.findIndex((item) => item.id === category.id);
    const targetIndex = currentIndex + (event.key === "ArrowUp" ? -1 : 1);
    const target = siblings[targetIndex];
    if (!target) return;
    void persistReorder(
      siblings,
      category.id,
      target.id,
      event.key === "ArrowUp" ? "before" : "after",
    );
  };

  const dragHandle = (category: ProductCategory, siblings: ProductCategory[]) => (
    <button
      type="button"
      className="core-category-drag-handle"
      aria-label={`拖动调整${category.name}顺序`}
      aria-describedby="category-reorder-help"
      disabled={reordering}
      onPointerDown={(event) => startDragging(event, category)}
      onPointerMove={moveDragging}
      onPointerUp={(event) => finishDragging(event, siblings)}
      onPointerCancel={cancelDragging}
      onKeyDown={(event) => handleOrderKey(event, category, siblings)}
    >
      <DotsSixVertical weight="bold" />
    </button>
  );

  const dragClass = (category: ProductCategory) => {
    if (!dragState) return "";
    if (dragState.sourceId === category.id) return " is-dragging";
    if (dragState.targetId !== category.id) return "";
    return dragState.placement === "before" ? " is-drop-before" : " is-drop-after";
  };

  return (
    <div className="core-category-manager-layout">
      <section className="core-category-tree-panel" aria-label="分类树">
        <div className="core-category-panel-heading">
          <span>
            <TreeStructure />
            <strong>分类结构</strong>
            <small id="category-reorder-help">
              {roots.length} 个一级 · {displayCategories.length - roots.length} 个二级 · 拖动手柄调整同级顺序
            </small>
          </span>
          <Button size="1" variant="soft" disabled={reordering} onClick={beginRoot}><Plus />一级分类</Button>
        </div>
        <div className="core-category-reorder-status" aria-live="polite">
          {reordering ? "正在保存分类顺序…" : reorderError}
        </div>
        <div className="core-category-tree">
          {roots.length ? roots.map((root) => {
            const children = childrenByParent.get(root.id) ?? [];
            return (
              <div className="core-category-branch" key={root.id}>
                <div
                  className={`core-category-node root${draft.mode === "edit" && draft.id === root.id ? " is-selected" : ""}${dragClass(root)}`}
                  data-category-id={root.id}
                  data-category-parent={rootParentKey}
                >
                  {dragHandle(root, roots)}
                  <button className="core-category-node-main" type="button" onClick={() => beginEdit(root)}>
                    <FolderOpen weight="duotone" />
                    <span><strong>{root.name}</strong><small>{children.length ? `${children.length} 个二级分类` : "暂无二级分类"}</small></span>
                  </button>
                  {root.status !== "ACTIVE" ? <Badge color="gray">停用</Badge> : null}
                  <Button size="1" variant="ghost" color="gray" disabled={reordering} onClick={() => beginEdit(root)} aria-label={`编辑${root.name}`}><PencilSimple /></Button>
                  <Button size="1" variant="ghost" disabled={reordering} onClick={() => beginChild(root.id)} aria-label={`在${root.name}下新增二级分类`}><Plus /></Button>
                </div>
                {children.map((child) => (
                  <div
                    className={`core-category-node child${draft.mode === "edit" && draft.id === child.id ? " is-selected" : ""}${dragClass(child)}`}
                    data-category-id={child.id}
                    data-category-parent={root.id}
                    key={child.id}
                  >
                    {dragHandle(child, children)}
                    <button className="core-category-node-main" type="button" onClick={() => beginEdit(child)}>
                      <Folder weight="duotone" />
                      <span><strong>{child.name}</strong><small>{root.name} / {child.name}</small></span>
                    </button>
                    {child.status !== "ACTIVE" ? <Badge color="gray">停用</Badge> : null}
                    <Button size="1" variant="ghost" color="gray" disabled={reordering} onClick={() => beginEdit(child)} aria-label={`编辑${child.name}`}><PencilSimple /></Button>
                  </div>
                ))}
              </div>
            );
          }) : (
            <div className="core-category-tree-empty">
              <TreeStructure size={28} />
              <strong>还没有分类</strong>
              <Text size="2" color="gray">新建一级分类，或导入带有分类的商品模版。</Text>
            </div>
          )}
        </div>
      </section>

      <section className="core-category-editor" aria-label="分类编辑器">
        <div>
          <Text size="1" color="gray">{draft.mode === "create" ? "创建分类" : "编辑分类"}</Text>
          <h3>{draft.mode === "create" ? (draft.parentId ? "新增二级分类" : "新增一级分类") : draft.name}</h3>
        </div>
        <label>
          <Text size="2" weight="medium">分类名称</Text>
          <TextField.Root value={draft.name} maxLength={200} placeholder="例如：办公用品" onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>
          <Text size="2" weight="medium">上级分类</Text>
          <Select.Root
            value={draft.parentId ?? "root"}
            disabled={parentLocked || reordering}
            onValueChange={(value) => setDraft({ ...draft, parentId: value === "root" ? undefined : value })}
          >
            <Select.Trigger aria-label="选择上级分类" />
            <Select.Content>
              <Select.Item value="root">无（一级分类）</Select.Item>
              {roots.filter((root) => draft.mode !== "edit" || root.id !== draft.id).map((root) => (
                <Select.Item value={root.id} key={root.id}>{root.name}</Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
          <Text size="1" color="gray">{parentLocked ? "该分类包含二级分类，需先移走子分类才能改变层级。" : "选择一级分类后，本分类会成为二级分类。"}</Text>
        </label>
        <div className="core-category-editor-row">
          <label>
            <Text size="2" weight="medium">排序</Text>
            <TextField.Root type="number" min="0" value={String(draft.sortOrder)} onChange={(event) => setDraft({ ...draft, sortOrder: Math.max(0, Number(event.target.value) || 0) })} />
          </label>
          {draft.mode === "edit" ? (
            <label>
              <Text size="2" weight="medium">状态</Text>
              <Select.Root value={draft.status} disabled={reordering} onValueChange={(value) => setDraft({ ...draft, status: value as "ACTIVE" | "INACTIVE" })}>
                <Select.Trigger aria-label="分类状态" />
                <Select.Content><Select.Item value="ACTIVE">启用</Select.Item><Select.Item value="INACTIVE">停用</Select.Item></Select.Content>
              </Select.Root>
            </label>
          ) : null}
        </div>
        {error ? <Text size="2" color="red">{error}</Text> : null}
        <div className="core-category-editor-actions">
          <Button variant="soft" color="gray" disabled={reordering} onClick={draft.parentId ? () => beginChild(draft.parentId!) : beginRoot}>重置</Button>
          <Button loading={saving} disabled={reordering} onClick={() => void save()}>{draft.mode === "create" ? "创建分类" : "保存修改"}</Button>
        </div>
      </section>
    </div>
  );
}
