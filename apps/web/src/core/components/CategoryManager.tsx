import { AlertDialog, Badge, Button, Select, Spinner, Text, TextField } from "@radix-ui/themes";
import {
  CheckCircle,
  CaretDown,
  CaretRight,
  DotsSixVertical,
  Folder,
  FolderOpen,
  ImageSquare,
  MagnifyingGlass,
  Plus,
  ShareNetwork,
  Storefront,
  Trash,
  TreeStructure,
  UploadSimple,
  WarningCircle,
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
import {
  createCategory,
  deleteCategory,
  getCategoryDeleteImpact,
  listSkus,
  reorderCategories,
  uploadCategoryCover,
  updateCategory,
  type CategoryDeleteImpact,
} from "../api";
import { useLocale } from "../LocaleContext";
import { automaticTagColor, TAG_COLOR_PALETTE, tagGlassStyle } from "../../lib/tagColors";
import type { ProductCategory, SkuListItem } from "../types";

type CategoryCoverSource = NonNullable<ProductCategory["coverSource"]>;

type Draft =
  | { mode: "create"; parentId?: string; name: string; sortOrder: number; displayColor?: string; status: "ACTIVE" }
  | { mode: "edit"; id: string; parentId?: string; name: string; sortOrder: number; displayColor?: string; status: "ACTIVE" | "INACTIVE"; version: number; coverSource: CategoryCoverSource; coverProductId?: string; coverProductName?: string; coverImageUrl?: string; uploadedCoverImageUrl?: string; coverProductImageUrl?: string };

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
  onShareCategory?: (category: ProductCategory) => void;
}

const rootParentKey = "__root__";
const allProductsId = "__all_products__";
const collapsedRootsStorageKey = "atc.categoryManager.collapsedRoots";

function readCollapsedRoots() {
  if (typeof window === "undefined") return new Set<string>();
  try {
    const value = JSON.parse(
      window.localStorage.getItem(collapsedRootsStorageKey) || "[]",
    );
    return new Set(
      Array.isArray(value)
        ? value.filter((item): item is string => typeof item === "string")
        : [],
    );
  } catch {
    return new Set<string>();
  }
}

function writeCollapsedRoots(value: Set<string>) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(
      collapsedRootsStorageKey,
      JSON.stringify([...value]),
    );
  } catch {
    // Collapsing still works for this render when storage is unavailable.
  }
}

function categoryNameKey(value: string) {
  return value.normalize("NFKC").toLowerCase();
}

function compareCategoryOrder(left: ProductCategory, right: ProductCategory) {
  if (left.sortOrder !== right.sortOrder) return left.sortOrder - right.sortOrder;
  const leftName = categoryNameKey(left.name);
  const rightName = categoryNameKey(right.name);
  if (leftName < rightName) return -1;
  if (leftName > rightName) return 1;
  return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
}

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
  onShareCategory,
}: CategoryManagerProps) {
  const { t } = useLocale();
  const [displayCategories, setDisplayCategories] = useState(categories);
  const [displayAllProductsPosition, setDisplayAllProductsPosition] = useState(
    allProductsPosition,
  );
  const [draft, setDraft] = useState<Draft>({ mode: "create", name: "", sortOrder: 0, status: "ACTIVE" });
  const [saving, setSaving] = useState(false);
  const [reordering, setReordering] = useState(false);
  const [error, setError] = useState("");
  const [reorderError, setReorderError] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<ProductCategory>();
  const [deleteImpact, setDeleteImpact] = useState<CategoryDeleteImpact>();
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const [coverQuery, setCoverQuery] = useState("");
  const [coverCandidates, setCoverCandidates] = useState<SkuListItem[]>([]);
  const [coverCandidatesLoading, setCoverCandidatesLoading] = useState(false);
  const [coverUploadBusy, setCoverUploadBusy] = useState(false);
  const [coverError, setCoverError] = useState("");
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [collapsedRootIds, setCollapsedRootIds] = useState(readCollapsedRoots);
  const dragStateRef = useRef<DragState | null>(null);
  const reorderingRef = useRef(false);
  const deleteRequestIdRef = useRef(0);
  const editorRef = useRef<HTMLElement | null>(null);
  const nameInputRef = useRef<HTMLInputElement | null>(null);
  const coverInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDisplayCategories(categories);
    setDisplayAllProductsPosition(allProductsPosition);
    setDraft((current) => {
      if (current.mode !== "edit") return current;
      const latest = categories.find((category) => category.id === current.id);
      return latest
        ? {
            ...current,
            version: latest.version,
            sortOrder: latest.sortOrder,
            displayColor: latest.displayColor,
            coverSource: latest.coverSource ?? "NONE",
            coverProductId: latest.coverProductId,
            coverProductName: latest.coverProductName,
            coverImageUrl: latest.coverImageUrl,
            uploadedCoverImageUrl: latest.uploadedCoverImageUrl,
            coverProductImageUrl: latest.coverProductImageUrl,
          }
        : current;
    });
  }, [allProductsPosition, categories]);

  const roots = useMemo(
    () => displayCategories
      .filter((item) => !item.parentId)
      .sort(compareCategoryOrder),
    [displayCategories],
  );
  const childrenByParent = useMemo(() => {
    const result = new Map<string, ProductCategory[]>();
    displayCategories.filter((item) => item.parentId).forEach((item) => {
      const rows = result.get(item.parentId!) ?? [];
      rows.push(item);
      result.set(item.parentId!, rows);
    });
    result.forEach((rows) => rows.sort(compareCategoryOrder));
    return result;
  }, [displayCategories]);
  const collapsibleRootIds = useMemo(
    () => roots
      .filter((root) => (childrenByParent.get(root.id)?.length ?? 0) > 0)
      .map((root) => root.id),
    [childrenByParent, roots],
  );
  const allCollapsibleRootsCollapsed = Boolean(
    collapsibleRootIds.length
    && collapsibleRootIds.every((id) => collapsedRootIds.has(id)),
  );
  const normalizedAllProductsPosition = Math.max(
    0,
    Math.min(displayAllProductsPosition, roots.length),
  );

  useEffect(() => {
    writeCollapsedRoots(collapsedRootIds);
  }, [collapsedRootIds]);

  useEffect(() => {
    const currentRootIds = new Set(roots.map((root) => root.id));
    setCollapsedRootIds((current) => {
      const next = new Set(
        [...current].filter((id) => currentRootIds.has(id)),
      );
      return next.size === current.size ? current : next;
    });
  }, [roots]);

  const toggleRoot = (rootId: string) => {
    setCollapsedRootIds((current) => {
      const next = new Set(current);
      if (next.has(rootId)) next.delete(rootId);
      else next.add(rootId);
      return next;
    });
  };

  const toggleAllRoots = () => {
    setCollapsedRootIds(
      allCollapsibleRootsCollapsed
        ? new Set()
        : new Set(collapsibleRootIds),
    );
  };

  const updateDragState = (next: DragState | null) => {
    dragStateRef.current = next;
    setDragState(next);
  };

  const revealEditorOnCompactLayout = () => {
    if (
      typeof window === "undefined"
      || !window.matchMedia("(max-width: 820px)").matches
    ) return;
    window.requestAnimationFrame(() => {
      editorRef.current?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    });
  };

  const focusNameInput = () => {
    if (typeof window === "undefined") return;
    window.requestAnimationFrame(() => nameInputRef.current?.focus());
  };

  const beginRoot = () => {
    setError("");
    setDraft({ mode: "create", name: "", sortOrder: roots.length, displayColor: undefined, status: "ACTIVE" });
    revealEditorOnCompactLayout();
    focusNameInput();
  };

  const beginChild = (parentId: string) => {
    setError("");
    setCollapsedRootIds((current) => {
      if (!current.has(parentId)) return current;
      const next = new Set(current);
      next.delete(parentId);
      return next;
    });
    setDraft({
      mode: "create",
      parentId,
      name: "",
      sortOrder: childrenByParent.get(parentId)?.length ?? 0,
      displayColor: undefined,
      status: "ACTIVE",
    });
    revealEditorOnCompactLayout();
    focusNameInput();
  };

  const beginEdit = (category: ProductCategory) => {
    setError("");
    setCoverError("");
    setCoverQuery("");
    setDraft({
      mode: "edit",
      id: category.id,
      parentId: category.parentId,
      name: category.name,
      sortOrder: category.sortOrder,
      displayColor: category.displayColor,
      status: category.status === "INACTIVE" ? "INACTIVE" : "ACTIVE",
      version: category.version,
      coverSource: category.coverSource ?? "NONE",
      coverProductId: category.coverProductId,
      coverProductName: category.coverProductName,
      coverImageUrl: category.coverImageUrl,
      uploadedCoverImageUrl: category.uploadedCoverImageUrl,
      coverProductImageUrl: category.coverProductImageUrl,
    });
    revealEditorOnCompactLayout();
  };

  const selectedCategory = draft.mode === "edit"
    ? displayCategories.find((category) => category.id === draft.id)
    : undefined;
  const selectedChildren = draft.mode === "edit" ? childrenByParent.get(draft.id) ?? [] : [];
  const parentLocked = selectedChildren.length > 0;
  const selectedParent = draft.parentId ? roots.find((root) => root.id === draft.parentId) : undefined;
  const coverEditor = draft.mode === "edit" && draft.parentId ? draft : undefined;
  const coverPreviewUrl = draft.mode === "edit"
    ? draft.coverSource === "UPLOAD"
      ? draft.uploadedCoverImageUrl ?? draft.coverImageUrl
      : draft.coverSource === "PRODUCT"
        ? draft.coverProductImageUrl ?? draft.coverImageUrl
        : undefined
    : undefined;
  const coverPreviewLabel = draft.mode === "edit"
    ? draft.coverSource === "UPLOAD"
      ? t("自定义样图")
      : draft.coverSource === "PRODUCT"
        ? draft.coverProductName || t("商品主图")
        : t("默认分类图标")
    : "";
  const colorPreviewName = draft.name.trim() || t("一级分类");
  const activeCategoryColor = draft.displayColor || automaticTagColor(colorPreviewName);
  const changeParent = (value: string) => {
    const parentId = value === "root" ? undefined : value;
    if (parentId === draft.parentId) return;
    const sortOrder = parentId
      ? childrenByParent.get(parentId)?.length ?? 0
      : roots.length;
    setDraft({
      ...draft,
      parentId,
      sortOrder,
      displayColor: parentId ? undefined : draft.displayColor,
    });
  };

  useEffect(() => {
    if (!coverEditor || coverEditor.coverSource !== "PRODUCT") {
      setCoverCandidates([]);
      setCoverCandidatesLoading(false);
      return;
    }
    let active = true;
    const timeout = window.setTimeout(() => {
      setCoverCandidatesLoading(true);
      setCoverError("");
      void listSkus({
        q: coverQuery.trim() || undefined,
        categoryId: coverEditor.id,
        statuses: ["ACTIVE"],
        page: 1,
        pageSize: 30,
      }).then((result) => {
        if (!active) return;
        const seen = new Set<string>();
        setCoverCandidates(result.items.filter((item) => {
          if (!item.thumbnailUrl || seen.has(item.productId)) return false;
          seen.add(item.productId);
          return true;
        }));
      }).catch((reason) => {
        if (!active) return;
        setCoverError(reason instanceof Error ? reason.message : t("商品读取失败。"));
      }).finally(() => {
        if (active) setCoverCandidatesLoading(false);
      });
    }, 220);
    return () => {
      active = false;
      window.clearTimeout(timeout);
    };
  }, [coverEditor?.coverSource, coverEditor?.id, coverQuery, t]);

  const chooseCoverSource = (source: CategoryCoverSource) => {
    if (draft.mode !== "edit" || !draft.parentId) return;
    setCoverError("");
    // Clicking upload always opens the picker so replacing a sample image is one step.
    if (source === "UPLOAD") {
      coverInputRef.current?.click();
      return;
    }
    setDraft({
      ...draft,
      coverSource: source,
      coverProductId: source === "PRODUCT" ? draft.coverProductId : undefined,
      coverProductName: source === "PRODUCT" ? draft.coverProductName : undefined,
      coverImageUrl: source === "PRODUCT"
        ? draft.coverProductImageUrl
        : undefined,
    });
  };

  const uploadCover = async (file?: File) => {
    if (!file || draft.mode !== "edit" || !draft.parentId || coverUploadBusy) return;
    if (!file.type.startsWith("image/")) {
      setCoverError(t("请选择 PNG、JPG 或 WebP 图片。"));
      return;
    }
    setCoverUploadBusy(true);
    setCoverError("");
    try {
      const updated = await uploadCategoryCover(draft.id, file);
      await onChanged();
      beginEdit(updated);
    } catch (reason) {
      setCoverError(reason instanceof Error ? reason.message : t("分类图片上传失败。"));
    } finally {
      setCoverUploadBusy(false);
    }
  };

  const save = async () => {
    const name = draft.name.trim();
    if (!name) {
      setError(t("请填写分类名称。"));
      return;
    }
    if (draft.mode === "edit" && draft.coverSource === "PRODUCT" && !draft.coverProductId) {
      setError(t("请选择一个商品作为分类门面。"));
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
          coverSource: draft.parentId ? draft.coverSource : "NONE",
          coverProductId: draft.parentId ? draft.coverProductId : undefined,
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

  const prepareDelete = async (category: ProductCategory) => {
    const requestId = deleteRequestIdRef.current + 1;
    deleteRequestIdRef.current = requestId;
    setDeleteTarget(category);
    setDeleteImpact(undefined);
    setDeleteError("");
    setDeleteLoading(true);
    try {
      const impact = await getCategoryDeleteImpact(category.id);
      if (deleteRequestIdRef.current === requestId) setDeleteImpact(impact);
    } catch (reason) {
      if (deleteRequestIdRef.current === requestId) {
        setDeleteError(reason instanceof Error ? reason.message : t("分类删除影响加载失败。"));
      }
    } finally {
      if (deleteRequestIdRef.current === requestId) setDeleteLoading(false);
    }
  };

  const removeCategory = async () => {
    if (!deleteTarget || !deleteImpact || deleteBusy) return;
    setDeleteBusy(true);
    setDeleteError("");
    try {
      const result = await deleteCategory(deleteTarget.id, deleteTarget.version);
      setDisplayAllProductsPosition(result.allProductsPosition);
      setCollapsedRootIds((current) => {
        if (!current.has(deleteTarget.id)) return current;
        const next = new Set(current);
        next.delete(deleteTarget.id);
        return next;
      });
      setDeleteTarget(undefined);
      deleteRequestIdRef.current += 1;
      setDeleteImpact(undefined);
      setDraft({
        mode: "create",
        name: "",
        sortOrder: Math.max(0, roots.length - (deleteTarget.parentId ? 0 : 1)),
        displayColor: undefined,
        status: "ACTIVE",
      });
      await onChanged();
    } catch (reason) {
      setDeleteError(reason instanceof Error ? reason.message : t("分类删除失败，请刷新后重试。"));
    } finally {
      setDeleteBusy(false);
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
    <div className="core-category-manager-layout is-simplified">
      <section className="core-category-tree-panel" aria-label={t("分类树")}>
        <div className="core-category-panel-heading">
          <span>
            <TreeStructure />
            <strong>{t("分类结构")}</strong>
            <small>
              {t("{primary} 个一级分类 · {secondary} 个二级分类", {
                primary: roots.length,
                secondary: displayCategories.length - roots.length,
              })}
            </small>
            <span id="category-reorder-help" className="visually-hidden">
              {t("拖动手柄调整同级顺序")}
            </span>
          </span>
          <div className="core-category-panel-actions">
            <Button
              size="1"
              variant="ghost"
              color="gray"
              disabled={reordering || !collapsibleRootIds.length}
              onClick={toggleAllRoots}
            >
              {allCollapsibleRootsCollapsed ? <CaretRight /> : <CaretDown />}
              {t(allCollapsibleRootsCollapsed ? "全部展开" : "全部收起")}
            </Button>
            <Button size="1" variant="soft" disabled={reordering} onClick={beginRoot}><Plus />{t("一级分类")}</Button>
          </div>
        </div>
        <div className="core-category-reorder-status" aria-live="polite">
          {reordering ? t("正在保存分类顺序…") : reorderError}
        </div>
        <div className="core-category-tree">
          {Array.from({ length: roots.length + 1 }, (_, slot) => {
            const root = roots[slot];
            const children = root ? childrenByParent.get(root.id) ?? [] : [];
            const collapsed = root ? collapsedRootIds.has(root.id) : false;
            const childrenId = root ? `category-children-${root.id}` : "";
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
                      <span><strong>{t("全部商品")}</strong></span>
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
                      {children.length ? (
                        <button
                          type="button"
                          className="core-category-collapse-toggle"
                          aria-expanded={!collapsed}
                          aria-controls={childrenId}
                          aria-label={t(collapsed ? "展开 {name}" : "收起 {name}", {
                            name: root.name,
                          })}
                          onClick={() => toggleRoot(root.id)}
                        >
                          {collapsed ? <CaretRight weight="bold" /> : <CaretDown weight="bold" />}
                        </button>
                      ) : (
                        <span className="core-category-collapse-placeholder" aria-hidden="true" />
                      )}
                      <button className="core-category-node-main" type="button" onClick={() => beginEdit(root)}>
                        <span className="core-category-color-mark" style={tagGlassStyle(root.name, root.displayColor)}>
                          {collapsed ? <Folder weight="duotone" /> : <FolderOpen weight="duotone" />}
                        </span>
                        <span>
                          <span className="core-category-name-line">
                            <strong>{root.name}</strong>
                            <small className="core-category-product-count">
                              {t("{count} 个商品", { count: root.productCount })}
                            </small>
                          </span>
                          {children.length ? <small>{t("{count} 个二级分类", { count: children.length })}</small> : null}
                        </span>
                      </button>
                      {root.status !== "ACTIVE" ? <Badge color="gray">{t("停用")}</Badge> : null}
                      <Button className="core-category-add-child" size="1" variant="ghost" disabled={reordering} onClick={() => beginChild(root.id)} aria-label={t("在 {name} 下新增二级分类", { name: root.name })}><Plus /></Button>
                    </div>
                    <div id={childrenId} className="core-category-children" hidden={collapsed}>
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
                            <span className="core-category-name-line">
                              <strong>{child.name}</strong>
                              <small className="core-category-product-count">
                                {t("{count} 个商品", { count: child.productCount })}
                              </small>
                            </span>
                          </button>
                          {child.status !== "ACTIVE" ? <Badge color="gray">{t("停用")}</Badge> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </Fragment>
            );
          })}
          {!roots.length ? (
            <div className="core-category-tree-empty">
              <TreeStructure size={28} />
              <strong>{t("还没有分类")}</strong>
              <Button size="1" variant="soft" onClick={beginRoot}><Plus />{t("新增一级分类")}</Button>
            </div>
          ) : null}
        </div>
      </section>

      <section ref={editorRef} className="core-category-editor" aria-label={t("分类编辑器")}>
        <div className="core-category-editor-heading">
          <span
            className="core-category-color-mark"
            style={tagGlassStyle(
              draft.parentId ? selectedParent?.name ?? colorPreviewName : colorPreviewName,
              draft.parentId ? selectedParent?.displayColor : draft.displayColor,
            )}
          >
            {draft.parentId ? <Folder weight="duotone" /> : <FolderOpen weight="duotone" />}
          </span>
          <span>
            <Text size="1" color="gray">{t(draft.parentId ? "二级分类" : "一级分类")}</Text>
            <h3>
              {draft.mode === "create"
                ? t(draft.parentId ? "新增二级分类" : "新增一级分类")
                : draft.name}
            </h3>
          </span>
        </div>
        <label>
          <Text size="2" weight="medium">{t("分类名称")}</Text>
          <TextField.Root
            key={draft.mode === "edit" ? draft.id : `create-${draft.parentId ?? "root"}`}
            ref={nameInputRef}
            value={draft.name}
            maxLength={200}
            placeholder={t("例如：办公用品")}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || event.nativeEvent.isComposing) return;
              event.preventDefault();
              void save();
            }}
          />
        </label>
        {draft.parentId ? (
          <label>
            <Text size="2" weight="medium">{t("所属一级分类")}</Text>
            <Select.Root
              value={draft.parentId}
              disabled={reordering}
              onValueChange={changeParent}
            >
              <Select.Trigger aria-label={t("选择上级分类")} />
              <Select.Content>
                <Select.Item value="root">{t("无（一级分类）")}</Select.Item>
                {roots
                  .filter((root) => draft.mode !== "edit" || root.id !== draft.id)
                  .map((root) => (
                    <Select.Item value={root.id} key={root.id}>{root.name}</Select.Item>
                  ))}
              </Select.Content>
            </Select.Root>
          </label>
        ) : (
          <div className="core-category-color-field">
            <div className="core-category-color-heading">
              <Text size="2" weight="medium">{t("一级分类颜色")}</Text>
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
            <div className="core-tag-color-control">
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
            </div>
          </div>
        )}
        {draft.mode === "edit" && draft.parentId ? (
          <section className="core-category-cover-field">
            <div className="core-category-cover-heading">
              <span>
                <Text size="2" weight="medium">{t("二级分类门面")}</Text>
                <Text size="1" color="gray">{t("这张样图会显示在前台二级分类卡片上")}</Text>
              </span>
              {draft.coverSource !== "NONE" ? (
                <Badge color="jade" variant="soft">{t("已设置")}</Badge>
              ) : null}
            </div>

            <input
              ref={coverInputRef}
              hidden
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.currentTarget.value = "";
                void uploadCover(file);
              }}
            />

            {draft.coverSource !== "NONE" ? (
              <div className="core-category-cover-current">
                {coverPreviewUrl ? (
                  <img src={coverPreviewUrl} alt={t("{name} 的二级分类门面", { name: draft.name })} />
                ) : (
                  <span><ImageSquare weight="duotone" /></span>
                )}
                <div>
                  <small>{t("当前门面")}</small>
                  <strong>{coverPreviewLabel}</strong>
                </div>
                {coverUploadBusy ? <Spinner /> : <CheckCircle weight="fill" />}
              </div>
            ) : (
              <div className="core-category-cover-empty">
                <ImageSquare weight="duotone" />
                <span>{t("还没有门面图片")}</span>
              </div>
            )}

            <div className="core-category-cover-sources" role="group" aria-label={t("分类门面来源")}>
              <button
                type="button"
                className={`core-category-cover-source-button${draft.coverSource === "NONE" ? " is-active" : ""}`}
                onClick={() => chooseCoverSource("NONE")}
              >
                <Folder weight="duotone" />
                <span><strong>{t("默认图标")}</strong></span>
                {draft.coverSource === "NONE" ? <CheckCircle weight="fill" /> : null}
              </button>
              <button
                type="button"
                className={`core-category-cover-source-button${draft.coverSource === "UPLOAD" ? " is-active" : ""}`}
                disabled={coverUploadBusy}
                onClick={() => chooseCoverSource("UPLOAD")}
              >
                <UploadSimple weight="duotone" />
                <span><strong>{t(coverUploadBusy ? "上传中…" : "上传样图")}</strong></span>
                {draft.coverSource === "UPLOAD" ? <CheckCircle weight="fill" /> : null}
              </button>
              <button
                type="button"
                className={`core-category-cover-source-button${draft.coverSource === "PRODUCT" ? " is-active" : ""}`}
                onClick={() => chooseCoverSource("PRODUCT")}
              >
                <ImageSquare weight="duotone" />
                <span><strong>{t("从商品选择")}</strong></span>
                {draft.coverSource === "PRODUCT" ? <CheckCircle weight="fill" /> : null}
              </button>
            </div>

            {draft.coverSource === "PRODUCT" ? (
              <div className="core-category-cover-products">
                <TextField.Root
                  size="2"
                  value={coverQuery}
                  placeholder={t("搜索当前分类内的商品")}
                  onChange={(event) => setCoverQuery(event.target.value)}
                >
                  <TextField.Slot><MagnifyingGlass /></TextField.Slot>
                </TextField.Root>
                <div className="core-category-cover-product-list" aria-busy={coverCandidatesLoading}>
                  {coverCandidates.map((candidate) => (
                    <button
                      type="button"
                      className={draft.coverProductId === candidate.productId ? "is-active" : ""}
                      key={candidate.productId}
                      onClick={() => setDraft({
                        ...draft,
                        coverSource: "PRODUCT",
                        coverProductId: candidate.productId,
                        coverProductName: candidate.productName,
                        coverProductImageUrl: candidate.thumbnailUrl,
                        coverImageUrl: candidate.thumbnailUrl,
                      })}
                    >
                      {candidate.thumbnailUrl ? <img src={candidate.thumbnailUrl} alt="" /> : <span><ImageSquare /></span>}
                      <span><strong>{candidate.productName}</strong><small>{candidate.productCode || candidate.skuCode}</small></span>
                      {draft.coverProductId === candidate.productId ? <CheckCircle weight="fill" /> : null}
                    </button>
                  ))}
                  {coverCandidatesLoading ? <Text size="1" color="gray">{t("正在读取商品…")}</Text> : null}
                  {!coverCandidatesLoading && !coverCandidates.length ? <Text size="1" color="gray">{t("当前分类暂无可选商品")}</Text> : null}
                </div>
              </div>
            ) : null}
            {coverError ? <Text size="1" color="red">{coverError}</Text> : null}
          </section>
        ) : null}
        {draft.mode === "edit" ? (
          <details className="core-category-advanced">
            <summary><span>{t("更多设置")}</span><CaretDown weight="bold" /></summary>
            <div>
              {!draft.parentId ? (
                <label>
                  <Text size="2" weight="medium">{t("上级分类")}</Text>
                  <Select.Root
                    value="root"
                    disabled={parentLocked || reordering}
                    onValueChange={changeParent}
                  >
                    <Select.Trigger aria-label={t("选择上级分类")} />
                    <Select.Content>
                      <Select.Item value="root">{t("无（一级分类）")}</Select.Item>
                      {roots
                        .filter((root) => root.id !== draft.id)
                        .map((root) => (
                          <Select.Item value={root.id} key={root.id}>{root.name}</Select.Item>
                        ))}
                    </Select.Content>
                  </Select.Root>
                  {parentLocked ? (
                    <Text size="1" color="gray">{t("该分类包含二级分类，需先移走子分类才能改变层级。")}</Text>
                  ) : null}
                </label>
              ) : null}
              <label>
                <Text size="2" weight="medium">{t("状态")}</Text>
                <Select.Root
                  value={draft.status}
                  disabled={reordering}
                  onValueChange={(value) => setDraft({ ...draft, status: value as "ACTIVE" | "INACTIVE" })}
                >
                  <Select.Trigger aria-label={t("分类状态")} />
                  <Select.Content>
                    <Select.Item value="ACTIVE">{t("启用")}</Select.Item>
                    <Select.Item value="INACTIVE">{t("停用")}</Select.Item>
                  </Select.Content>
                </Select.Root>
              </label>
            </div>
          </details>
        ) : null}
        {error ? <Text size="2" color="red">{error}</Text> : null}
        <div className="core-category-editor-actions">
          {draft.mode === "edit" && selectedCategory && onShareCategory ? (
            <Button
              variant="soft"
              color="gray"
              disabled={saving || reordering || selectedCategory.status !== "ACTIVE"}
              onClick={() => onShareCategory(selectedCategory)}
            >
              <ShareNetwork />{t("分享分类")}
            </Button>
          ) : null}
          {draft.mode === "edit" && selectedCategory ? (
            <Button
              className="core-category-delete-button"
              variant="soft"
              color="red"
              disabled={saving || reordering}
              onClick={() => void prepareDelete(selectedCategory)}
            >
              <Trash />{t("删除分类")}
            </Button>
          ) : null}
          <Button loading={saving} disabled={reordering} onClick={() => void save()}>{t(draft.mode === "create" ? "创建分类" : "保存修改")}</Button>
        </div>
      </section>

      <AlertDialog.Root
        open={Boolean(deleteTarget)}
        onOpenChange={(open) => {
          if (open || deleteBusy) return;
          deleteRequestIdRef.current += 1;
          setDeleteTarget(undefined);
          setDeleteImpact(undefined);
          setDeleteError("");
        }}
      >
        <AlertDialog.Content maxWidth="500px" className="core-category-delete-dialog">
          <AlertDialog.Title>
            {t("删除“{name}”？", { name: deleteTarget?.name ?? "" })}
          </AlertDialog.Title>
          <AlertDialog.Description>
            {t("分类删除后无法恢复，但不会删除任何商品。")}
          </AlertDialog.Description>

          {deleteLoading ? (
            <div className="core-category-delete-loading" aria-live="polite">
              <Spinner /><Text size="2" color="gray">{t("正在计算删除影响…")}</Text>
            </div>
          ) : null}

          {deleteImpact ? (
            <div className="core-category-delete-impact">
              <div>
                <span>{t("删除分类")}</span>
                <strong>{1 + deleteImpact.childCategoryCount}</strong>
                <small>
                  {deleteImpact.childCategoryCount
                    ? t("包含 {count} 个二级分类", { count: deleteImpact.childCategoryCount })
                    : t("仅当前分类")}
                </small>
              </div>
              <div>
                <span>{t("关联商品")}</span>
                <strong>{deleteImpact.affectedProductCount}</strong>
                <small>{t("商品保留并改为未分类")}</small>
              </div>
              {deleteImpact.attributeDefinitionCount ? (
                <div>
                  <span>{t("分类属性规则")}</span>
                  <strong>{deleteImpact.attributeDefinitionCount}</strong>
                  <small>{t("属性值保留，规则解除关联")}</small>
                </div>
              ) : null}
            </div>
          ) : null}

          {deleteImpact?.childCategoryCount ? (
            <div className="core-category-delete-warning">
              <WarningCircle />
              <Text size="2">
                {t("这是一级分类，确认后会同时删除它下面的全部二级分类。")}
              </Text>
            </div>
          ) : null}

          {deleteError ? (
            <div className="core-category-delete-error" role="alert">
              <WarningCircle /><span>{deleteError}</span>
              {!deleteImpact ? (
                <Button size="1" variant="soft" color="gray" disabled={!deleteTarget || deleteLoading} onClick={() => deleteTarget && void prepareDelete(deleteTarget)}>
                  {t("重试")}
                </Button>
              ) : null}
            </div>
          ) : null}

          <div className="core-dialog-actions">
            <AlertDialog.Cancel>
              <Button variant="soft" color="gray" disabled={deleteBusy}>{t("取消")}</Button>
            </AlertDialog.Cancel>
            <Button color="red" loading={deleteBusy} disabled={!deleteImpact || deleteLoading} onClick={() => void removeCategory()}>
              <Trash />{t(deleteBusy ? "正在删除…" : "确认删除")}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Root>
    </div>
  );
}
