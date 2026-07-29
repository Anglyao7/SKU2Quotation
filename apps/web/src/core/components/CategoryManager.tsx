import { Badge, Button, Select, Text, TextField } from "@radix-ui/themes";
import {
  DotsSixVertical,
  Folder,
  FolderOpen,
  PencilSimple,
  Plus,
  Storefront,
  TreeStructure,
} from "@phosphor-icons/react";
import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { createCategory, reorderCategories, updateCategory } from "../api";
import { useLocale } from "../LocaleContext";
import { automaticTagColor, TAG_COLOR_PALETTE, tagGlassStyle } from "../../lib/tagColors";
import type { ProductCategory } from "../types";

type Draft =
  | { mode: "create"; parentId?: string; name: string; sortOrder: number; displayColor?: string; status: "ACTIVE" }
  | { mode: "edit"; id: string; parentId?: string; name: string; sortOrder: number; displayColor?: string; status: "ACTIVE" | "INACTIVE"; version: number };

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
  allProductsPosition: number;
  onChanged: () => Promise<void>;
  onAllProductsPositionChanged: (position: number) => Promise<void>;
}

const rootParentKey = "__root__";
const allProductsId = "__all_products__";

function categoryParentKey(category: ProductCategory) {
  return category.parentId ?? rootParentKey;
}

function sameOrder(left: ProductCategory[], right: ProductCategory[]) {
  return left.length === right.length && left.every((category, index) => category.id === right[index]?.id);
}

export function CategoryManager({
  categories,
  allProductsPosition,
  onChanged,
  onAllProductsPositionChanged,
}: CategoryManagerProps) {
  const { locale, t } = useLocale();
  const [displayCategories, setDisplayCategories] = useState(categories);
  const [displayAllProductsPosition, setDisplayAllProductsPosition] = useState(
    allProductsPosition,
  );
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
    setDisplayAllProductsPosition(allProductsPosition);
    setDraft((current) => {
      if (current.mode !== "edit") return current;
      const latest = categories.find((category) => category.id === current.id);
      return latest
        ? { ...current, version: latest.version, sortOrder: latest.sortOrder, displayColor: latest.displayColor }
        : current;
    });
  }, [allProductsPosition, categories]);

  const roots = useMemo(
    () => displayCategories
      .filter((item) => !item.parentId)
      .sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, locale)),
    [displayCategories, locale],
  );
  const childrenByParent = useMemo(() => {
    const result = new Map<string, ProductCategory[]>();
    displayCategories.filter((item) => item.parentId).forEach((item) => {
      const rows = result.get(item.parentId!) ?? [];
      rows.push(item);
      result.set(item.parentId!, rows);
    });
    result.forEach((rows) => rows.sort((a, b) => a.sortOrder - b.sortOrder || a.name.localeCompare(b.name, locale)));
    return result;
  }, [displayCategories, locale]);
  const normalizedAllProductsPosition = Math.max(
    0,
    Math.min(displayAllProductsPosition, roots.length),
  );

  const updateDragState = (next: DragState | null) => {
    dragStateRef.current = next;
    setDragState(next);
  };

  const beginRoot = () => {
    setError("");
    setDraft({ mode: "create", name: "", sortOrder: roots.length, displayColor: undefined, status: "ACTIVE" });
  };

  const beginChild = (parentId: string) => {
    setError("");
    setDraft({
      mode: "create",
      parentId,
      name: "",
      sortOrder: childrenByParent.get(parentId)?.length ?? 0,
      displayColor: undefined,
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
      displayColor: category.displayColor,
      status: category.status === "INACTIVE" ? "INACTIVE" : "ACTIVE",
      version: category.version,
    });
  };

  const selectedChildren = draft.mode === "edit" ? childrenByParent.get(draft.id) ?? [] : [];
  const parentLocked = selectedChildren.length > 0;
  const selectedParent = draft.parentId ? roots.find((root) => root.id === draft.parentId) : undefined;
  const colorPreviewName = draft.name.trim() || t("一级分类");
  const activeCategoryColor = draft.displayColor || automaticTagColor(colorPreviewName);

  const save = async () => {
    const name = draft.name.trim();
    if (!name) {
      setError(t("请填写分类名称。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      if (draft.mode === "create") {
        const created = await createCategory({
          name,
          parentId: draft.parentId,
          sortOrder: draft.sortOrder,
          displayColor: draft.parentId ? undefined : draft.displayColor,
        });
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
          displayColor: draft.parentId ? null : draft.displayColor ?? null,
        });
        await onChanged();
        beginEdit(updated);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("分类保存失败。"));
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
      setReorderError(reason instanceof Error ? reason.message : t("分类顺序保存失败，请刷新后重试。"));
      await onChanged().catch(() => undefined);
    } finally {
      reorderingRef.current = false;
      setReordering(false);
    }
  };

  const persistAllProductsPosition = async (nextPosition: number) => {
    const normalized = Math.max(0, Math.min(nextPosition, roots.length));
    if (
      reorderingRef.current
      || normalized === normalizedAllProductsPosition
    ) return;
    const previous = normalizedAllProductsPosition;
    setDisplayAllProductsPosition(normalized);
    reorderingRef.current = true;
    setReordering(true);
    setReorderError("");
    try {
      await onAllProductsPositionChanged(normalized);
    } catch (reason) {
      setDisplayAllProductsPosition(previous);
      setReorderError(
        reason instanceof Error
          ? reason.message
          : t("“全部商品”顺序保存失败，请刷新后重试。"),
      );
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

  const startAllProductsDragging = (
    event: PointerEvent<HTMLButtonElement>,
  ) => {
    if (reorderingRef.current || (event.pointerType === "mouse" && event.button !== 0)) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    updateDragState({
      pointerId: event.pointerId,
      sourceId: allProductsId,
      parentKey: rootParentKey,
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
    if (
      !targetNode
      || targetNode.dataset.categoryParent !== current.parentKey
      || (
        current.sourceId !== allProductsId
        && targetNode.dataset.categoryId === allProductsId
      )
    ) {
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

  const finishAllProductsDragging = (
    event: PointerEvent<HTMLButtonElement>,
  ) => {
    const current = dragStateRef.current;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    updateDragState(null);
    if (
      current?.sourceId !== allProductsId
      || !current.targetId
      || !current.placement
      || current.targetId === allProductsId
    ) return;
    const targetIndex = roots.findIndex((root) => root.id === current.targetId);
    if (targetIndex < 0) return;
    void persistAllProductsPosition(
      targetIndex + (current.placement === "after" ? 1 : 0),
    );
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
      aria-label={t("拖动调整 {name} 顺序", { name: category.name })}
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

  const allProductsDragHandle = (
    <button
      type="button"
      className="core-category-drag-handle"
      aria-label={t("拖动调整全部商品入口顺序")}
      aria-describedby="category-reorder-help"
      disabled={reordering}
      onPointerDown={startAllProductsDragging}
      onPointerMove={moveDragging}
      onPointerUp={finishAllProductsDragging}
      onPointerCancel={cancelDragging}
      onKeyDown={(event) => {
        if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
        event.preventDefault();
        void persistAllProductsPosition(
          normalizedAllProductsPosition + (event.key === "ArrowUp" ? -1 : 1),
        );
      }}
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
  const allProductsDragClass = !dragState
    ? ""
    : dragState.sourceId === allProductsId
      ? " is-dragging"
      : dragState.targetId === allProductsId
        ? dragState.placement === "before"
          ? " is-drop-before"
          : " is-drop-after"
        : "";

  return (
    <div className="core-category-manager-layout">
      <section className="core-category-tree-panel" aria-label={t("分类树")}>
        <div className="core-category-panel-heading">
          <span>
            <TreeStructure />
            <strong>{t("分类结构")}</strong>
            <small id="category-reorder-help">
              {t("{primary} 个一级 · {secondary} 个二级 · 拖动“全部商品”可调整前台入口位置", {
                primary: roots.length,
                secondary: displayCategories.length - roots.length,
              })}
            </small>
          </span>
          <Button size="1" variant="soft" disabled={reordering} onClick={beginRoot}><Plus />{t("一级分类")}</Button>
        </div>
        <div className="core-category-reorder-status" aria-live="polite">
          {reordering ? t("正在保存分类顺序…") : reorderError}
        </div>
        <div className="core-category-tree">
          {Array.from({ length: roots.length + 1 }, (_, slot) => {
            const root = roots[slot];
            const children = root ? childrenByParent.get(root.id) ?? [] : [];
            return (
              <Fragment key={`category-slot-${slot}`}>
                {slot === normalizedAllProductsPosition ? (
                  <div
                    className={`core-category-node root core-category-all-products${allProductsDragClass}`}
                    data-category-id={allProductsId}
                    data-category-parent={rootParentKey}
                  >
                    {allProductsDragHandle}
                    <div className="core-category-node-main">
                      <span className="core-category-color-mark core-category-all-products-mark">
                        <Storefront weight="duotone" />
                      </span>
                      <span>
                        <strong>{t("全部商品")}</strong>
                        <small>{t("前台固定入口 · 当前前方有 {count} 个一级分类", {
                          count: normalizedAllProductsPosition,
                        })}</small>
                      </span>
                    </div>
                    <Badge color="jade" variant="soft">{t("前台入口")}</Badge>
                  </div>
                ) : null}
                {root ? (
                  <div className="core-category-branch">
                    <div
                      className={`core-category-node root${draft.mode === "edit" && draft.id === root.id ? " is-selected" : ""}${dragClass(root)}`}
                      data-category-id={root.id}
                      data-category-parent={rootParentKey}
                    >
                      {dragHandle(root, roots)}
                      <button className="core-category-node-main" type="button" onClick={() => beginEdit(root)}>
                        <span className="core-category-color-mark" style={tagGlassStyle(root.name, root.displayColor)}>
                          <FolderOpen weight="duotone" />
                        </span>
                        <span><strong>{root.name}</strong><small>{children.length ? t("{count} 个二级分类", { count: children.length }) : t("暂无二级分类")}</small></span>
                      </button>
                      {root.status !== "ACTIVE" ? <Badge color="gray">{t("停用")}</Badge> : null}
                      <Button size="1" variant="ghost" color="gray" disabled={reordering} onClick={() => beginEdit(root)} aria-label={t("编辑 {name}", { name: root.name })}><PencilSimple /></Button>
                      <Button size="1" variant="ghost" disabled={reordering} onClick={() => beginChild(root.id)} aria-label={t("在 {name} 下新增二级分类", { name: root.name })}><Plus /></Button>
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
                        {child.status !== "ACTIVE" ? <Badge color="gray">{t("停用")}</Badge> : null}
                        <Button size="1" variant="ghost" color="gray" disabled={reordering} onClick={() => beginEdit(child)} aria-label={t("编辑 {name}", { name: child.name })}><PencilSimple /></Button>
                      </div>
                    ))}
                  </div>
                ) : null}
              </Fragment>
            );
          })}
          {!roots.length ? (
            <div className="core-category-tree-empty">
              <TreeStructure size={28} />
              <strong>{t("还没有分类")}</strong>
              <Text size="2" color="gray">{t("新建一级分类，或导入带有分类的商品模版。")}</Text>
            </div>
          ) : null}
        </div>
      </section>

      <section className="core-category-editor" aria-label={t("分类编辑器")}>
        <div>
          <Text size="1" color="gray">{t(draft.mode === "create" ? "创建分类" : "编辑分类")}</Text>
          <h3>{draft.mode === "create" ? t(draft.parentId ? "新增二级分类" : "新增一级分类") : draft.name}</h3>
        </div>
        <label>
          <Text size="2" weight="medium">{t("分类名称")}</Text>
          <TextField.Root value={draft.name} maxLength={200} placeholder={t("例如：办公用品")} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
        </label>
        <label>
          <Text size="2" weight="medium">{t("上级分类")}</Text>
          <Select.Root
            value={draft.parentId ?? "root"}
            disabled={parentLocked || reordering}
            onValueChange={(value) => setDraft({ ...draft, parentId: value === "root" ? undefined : value })}
          >
            <Select.Trigger aria-label={t("选择上级分类")} />
            <Select.Content>
              <Select.Item value="root">{t("无（一级分类）")}</Select.Item>
              {roots.filter((root) => draft.mode !== "edit" || root.id !== draft.id).map((root) => (
                <Select.Item value={root.id} key={root.id}>{root.name}</Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
          <Text size="1" color="gray">{t(parentLocked ? "该分类包含二级分类，需先移走子分类才能改变层级。" : "选择一级分类后，本分类会成为二级分类。")}</Text>
        </label>
        {draft.parentId ? (
          <div className="core-category-color-inheritance">
            <span
              className="core-category-color-mark"
              style={tagGlassStyle(selectedParent?.name ?? colorPreviewName, selectedParent?.displayColor)}
            >
              <FolderOpen weight="duotone" />
            </span>
            <span>
              <Text size="2" weight="medium">{t("继承一级分类颜色")}</Text>
              <Text size="1" color="gray">{t("二级分类沿用“{name}”的颜色。", { name: selectedParent?.name ?? t("所属一级分类") })}</Text>
            </span>
          </div>
        ) : (
          <div className="core-category-color-field">
            <Text size="2" weight="medium">{t("一级分类颜色")}</Text>
            <div className="core-tag-color-control">
              <span className="core-tag-glass-preview" style={tagGlassStyle(colorPreviewName, draft.displayColor)}>
                <FolderOpen weight="fill" />{colorPreviewName}
              </span>
              <div className="core-tag-color-presets" role="group" aria-label={t("一级分类颜色")}>
                {TAG_COLOR_PALETTE.map((color) => (
                  <button
                    type="button"
                    className={draft.displayColor === color ? "is-active" : ""}
                    style={{ background: color }}
                    aria-label={`${t("一级分类颜色")} ${color}`}
                    aria-pressed={draft.displayColor === color}
                    disabled={saving || reordering}
                    onClick={() => setDraft({ ...draft, displayColor: color })}
                    key={color}
                  />
                ))}
                <label className="core-tag-custom-color" title={t("自定义颜色")}>
                  <input
                    type="color"
                    value={activeCategoryColor}
                    aria-label={t("自定义颜色")}
                    disabled={saving || reordering}
                    onChange={(event) => setDraft({ ...draft, displayColor: event.target.value.toUpperCase() })}
                  />
                  <span>{t("自定义")}</span>
                </label>
              </div>
              <Button
                size="1"
                variant="ghost"
                color="gray"
                disabled={!draft.displayColor || saving || reordering}
                onClick={() => setDraft({ ...draft, displayColor: undefined })}
              >
                {t("自动配色")}
              </Button>
            </div>
            <Text size="1" color="gray">{t("前台商品角标会沿用这个颜色；自动配色会根据分类名称保持稳定。")}</Text>
          </div>
        )}
        <div className="core-category-editor-row">
          <label>
            <Text size="2" weight="medium">{t("排序")}</Text>
            <TextField.Root type="number" min="0" value={String(draft.sortOrder)} onChange={(event) => setDraft({ ...draft, sortOrder: Math.max(0, Number(event.target.value) || 0) })} />
          </label>
          {draft.mode === "edit" ? (
            <label>
              <Text size="2" weight="medium">{t("状态")}</Text>
              <Select.Root value={draft.status} disabled={reordering} onValueChange={(value) => setDraft({ ...draft, status: value as "ACTIVE" | "INACTIVE" })}>
                <Select.Trigger aria-label={t("分类状态")} />
                <Select.Content><Select.Item value="ACTIVE">{t("启用")}</Select.Item><Select.Item value="INACTIVE">{t("停用")}</Select.Item></Select.Content>
              </Select.Root>
            </label>
          ) : null}
        </div>
        {error ? <Text size="2" color="red">{error}</Text> : null}
        <div className="core-category-editor-actions">
          <Button variant="soft" color="gray" disabled={reordering} onClick={draft.parentId ? () => beginChild(draft.parentId!) : beginRoot}>{t("重置")}</Button>
          <Button loading={saving} disabled={reordering} onClick={() => void save()}>{t(draft.mode === "create" ? "创建分类" : "保存修改")}</Button>
        </div>
      </section>
    </div>
  );
}
