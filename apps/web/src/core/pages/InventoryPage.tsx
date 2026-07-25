import {
  Badge,
  Button,
  Card,
  Checkbox,
  Dialog,
  Heading,
  Select,
  Tabs,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  ArrowClockwise,
  ArrowsLeftRight,
  CheckCircle,
  Cube,
  MagnifyingGlass,
  Package,
  Plus,
  Receipt,
  ShoppingCartSimple,
  Trash,
  Warehouse as WarehouseIcon,
  Warning,
  X,
} from "@phosphor-icons/react";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import {
  adjustInventory,
  cancelPurchaseOrder,
  cancelSalesOrder,
  confirmPurchaseOrder,
  confirmSalesOrder,
  createPurchaseOrder,
  createSalesOrder,
  createWarehouse,
  getInventoryOverview,
  getPurchaseOrder,
  getSalesOrder,
  listInventoryMovements,
  listInventoryStocks,
  listPurchaseOrders,
  listSalesOrders,
  listSkus,
  listWarehouses,
  receivePurchaseOrder,
  shipSalesOrder,
  transferInventory,
  updateStockPolicy,
} from "../api";
import { useCoreAuth } from "../AuthContext";
import { useLocale } from "../LocaleContext";
import {
  CoreEmpty,
  CoreError,
  CoreLoading,
  CorePageHeading,
  coreDate,
} from "../CoreUi";
import type {
  InventoryMovement,
  InventoryMovementPage,
  InventoryOverview,
  InventoryStockItem,
  InventoryStockPage,
  PurchaseOrder,
  PurchaseOrderSummary,
  SalesOrder,
  SalesOrderSummary,
  SkuListItem,
  Warehouse,
} from "../types";

const emptyStockPage: InventoryStockPage = {
  items: [],
  page: 1,
  pageSize: 20,
  total: 0,
  pages: 0,
};

const emptyMovementPage: InventoryMovementPage = {
  items: [],
  page: 1,
  pageSize: 50,
  total: 0,
  pages: 0,
};

const orderLabels: Record<string, string> = {
  DRAFT: "草稿",
  CONFIRMED: "已确认",
  PARTIALLY_RECEIVED: "部分入库",
  RECEIVED: "已完成入库",
  PARTIALLY_SHIPPED: "部分出库",
  SHIPPED: "已完成出库",
  CANCELLED: "已取消",
};

const movementLabels: Record<string, string> = {
  PURCHASE_RECEIPT: "采购入库",
  SALES_RESERVATION: "销售锁库",
  SALES_SHIPMENT: "销售出库",
  SALES_RELEASE: "释放锁库",
  MANUAL_ADJUSTMENT: "库存调整",
  TRANSFER_OUT: "调拨出库",
  TRANSFER_IN: "调拨入库",
};

function quantity(value: number) {
  return new Intl.NumberFormat(document.documentElement.lang || "zh-CN", {
    maximumFractionDigits: 3,
  }).format(value);
}

function money(currency: string, value: number) {
  return `${currency} ${value.toLocaleString(document.documentElement.lang || "zh-CN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function signed(value: number) {
  if (value === 0) return "—";
  return `${value > 0 ? "+" : ""}${quantity(value)}`;
}

function orderColor(status: string): "jade" | "amber" | "gray" | "red" | "blue" {
  if (status === "RECEIVED" || status === "SHIPPED") return "jade";
  if (status === "CANCELLED") return "gray";
  if (status === "DRAFT") return "blue";
  if (status.startsWith("PARTIALLY")) return "amber";
  return "amber";
}

type WorkspaceDialog =
  | "warehouse"
  | "adjust"
  | "transfer"
  | "purchase"
  | "sale"
  | undefined;

export function InventoryPage() {
  const { hasPermission } = useCoreAuth();
  const { t } = useLocale();
  const canAdjust = hasPermission("inventory.adjust");
  const canPurchase = hasPermission("inventory.purchase");
  const canSell = hasPermission("inventory.sale");
  const canTransfer = hasPermission("inventory.transfer");
  const canManageWarehouses = hasPermission("inventory.warehouse_manage");
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [warehouseId, setWarehouseId] = useState("");
  const [overview, setOverview] = useState<InventoryOverview>();
  const [stocks, setStocks] = useState<InventoryStockPage>(emptyStockPage);
  const [movements, setMovements] =
    useState<InventoryMovementPage>(emptyMovementPage);
  const [purchases, setPurchases] = useState<PurchaseOrderSummary[]>([]);
  const [sales, setSales] = useState<SalesOrderSummary[]>([]);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [lowStockOnly, setLowStockOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialog, setDialog] = useState<WorkspaceDialog>();
  const [adjustmentStock, setAdjustmentStock] =
    useState<InventoryStockItem>();
  const [policyStock, setPolicyStock] = useState<InventoryStockItem>();
  const [purchaseDetail, setPurchaseDetail] = useState<PurchaseOrder>();
  const [salesDetail, setSalesDetail] = useState<SalesOrder>();

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedQuery(query.trim());
      setPage(1);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const loadWarehouses = useCallback(async (preferDefault = false) => {
    const rows = await listWarehouses();
    setWarehouses(rows);
    setWarehouseId((current) => {
      if (!preferDefault && current && rows.some((row) => row.id === current)) {
        return current;
      }
      return rows.find((row) => row.isDefault)?.id ?? rows[0]?.id ?? "";
    });
    return rows;
  }, []);

  const loadWorkspace = useCallback(async () => {
    if (!warehouseId) return;
    setLoading(true);
    setError("");
    try {
      const [
        nextOverview,
        nextStocks,
        nextMovements,
        nextPurchases,
        nextSales,
      ] = await Promise.all([
        getInventoryOverview(warehouseId),
        listInventoryStocks({
          warehouseId,
          q: debouncedQuery || undefined,
          lowStockOnly,
          page,
          pageSize: 20,
        }),
        listInventoryMovements({
          warehouseId,
          page: 1,
          pageSize: 50,
        }),
        listPurchaseOrders(),
        listSalesOrders(),
      ]);
      setOverview(nextOverview);
      setStocks(nextStocks);
      setMovements(nextMovements);
      setPurchases(nextPurchases);
      setSales(nextSales);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("进销存数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [debouncedQuery, lowStockOnly, page, t, warehouseId]);

  useEffect(() => {
    void loadWarehouses().catch((reason) => {
      setLoading(false);
      setError(reason instanceof Error ? reason.message : t("仓库加载失败"));
    });
  }, [loadWarehouses, t]);

  useEffect(() => {
    const reloadForBusinessMode = () => {
      void loadWarehouses(true).catch((reason) => {
        setError(
          reason instanceof Error ? reason.message : t("仓库切换失败"),
        );
      });
    };
    window.addEventListener(
      "atc:merchant-settings-changed",
      reloadForBusinessMode,
    );
    return () =>
      window.removeEventListener(
        "atc:merchant-settings-changed",
        reloadForBusinessMode,
      );
  }, [loadWarehouses, t]);
  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  const activeWarehouse = warehouses.find((row) => row.id === warehouseId);
  const warehousePurchases = useMemo(
    () => purchases.filter((row) => row.warehouseId === warehouseId),
    [purchases, warehouseId],
  );
  const warehouseSales = useMemo(
    () => sales.filter((row) => row.warehouseId === warehouseId),
    [sales, warehouseId],
  );

  const reloadAfterMutation = async () => {
    await Promise.all([loadWarehouses(), loadWorkspace()]);
  };

  const openPurchase = async (orderId: string) => {
    setError("");
    try {
      setPurchaseDetail(await getPurchaseOrder(orderId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("采购单加载失败"));
    }
  };

  const openSale = async (orderId: string) => {
    setError("");
    try {
      setSalesDetail(await getSalesOrder(orderId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("销售单加载失败"));
    }
  };

  return (
    <div className="core-workspace inventory-workspace">
      <CorePageHeading
        eyebrow={t("库存 · 采购 · 销售")}
        title={t("进销存")}
        description={t("以 SKU 和仓库为核算维度；销售确认锁定库存，实际发货才扣减现存量。")}
        actions={
          <>
            {canPurchase ? (
              <Button onClick={() => setDialog("purchase")}>
                <Receipt /> {t("新建采购")}
              </Button>
            ) : null}
            {canSell ? (
              <Button variant="soft" onClick={() => setDialog("sale")}>
                <ShoppingCartSimple /> {t("新建销售")}
              </Button>
            ) : null}
            <Button
              variant="ghost"
              color="gray"
              onClick={() => void loadWorkspace()}
            >
              <ArrowClockwise /> {t("刷新")}
            </Button>
          </>
        }
      />

      <Card className="inventory-context-bar">
        <div className="inventory-warehouse-context">
          <span className="inventory-context-icon">
            <WarehouseIcon />
          </span>
          <div>
            <Text size="1" color="gray">
              {t("当前仓库")}
            </Text>
            <Select.Root
              value={warehouseId}
              onValueChange={(value) => {
                setWarehouseId(value);
                setPage(1);
              }}
            >
              <Select.Trigger
                className="inventory-warehouse-select"
                placeholder={t("选择仓库")}
              />
              <Select.Content>
                {warehouses
                  .filter((row) => row.status === "ACTIVE")
                  .map((row) => (
                    <Select.Item key={row.id} value={row.id}>
                      {row.name} · {row.code}
                    </Select.Item>
                  ))}
              </Select.Content>
            </Select.Root>
          </div>
          {activeWarehouse?.isDefault ? (
            <Badge color="jade">{t("默认仓")}</Badge>
          ) : null}
          {activeWarehouse ? (
            <Badge color="gray">{t("{currency} 核算", { currency: activeWarehouse.currency })}</Badge>
          ) : null}
        </div>
        <div className="inventory-quick-actions">
          {canAdjust ? (
            <Button variant="soft" color="gray" onClick={() => setDialog("adjust")}>
              <Package /> {t("库存调整")}
            </Button>
          ) : null}
          {canTransfer && warehouses.filter((row) => row.status === "ACTIVE").length > 1 ? (
            <Button
              variant="soft"
              color="gray"
              onClick={() => setDialog("transfer")}
            >
              <ArrowsLeftRight /> {t("仓间调拨")}
            </Button>
          ) : null}
          {canManageWarehouses ? (
            <Button
              variant="soft"
              color="gray"
              onClick={() => setDialog("warehouse")}
            >
              <Plus /> {t("新建仓库")}
            </Button>
          ) : null}
        </div>
      </Card>

      {error ? (
        <CoreError message={error} onRetry={() => void loadWorkspace()} />
      ) : null}

      <section className="inventory-metric-grid">
        <Card className="inventory-metric-card primary">
          <span>
            <Text size="1" color="gray">{t("库存金额")}</Text>
            <strong>
              {overview
                ? money(overview.currency, overview.inventoryValue)
                : "—"}
            </strong>
          </span>
          <Cube />
          <Text size="1" color="gray">
            {t("{count} 个 SKU 有库存", { count: overview?.stockedSkus ?? 0 })}
          </Text>
        </Card>
        <Card className="inventory-metric-card">
          <Text size="1" color="gray">{t("可用 / 现存")}</Text>
          <strong>
            {quantity(overview?.availableQuantity ?? 0)}
            <small> / {quantity(overview?.onHandQuantity ?? 0)}</small>
          </strong>
          <Text size="1" color="gray">
            {t("已锁定 {count}", { count: quantity(overview?.reservedQuantity ?? 0) })}
          </Text>
        </Card>
        <Card className="inventory-metric-card">
          <Text size="1" color="gray">{t("待处理采购")}</Text>
          <strong>{overview?.openPurchaseOrders ?? 0}</strong>
          <Text size="1" color="gray">{t("草稿、待收货与部分入库")}</Text>
        </Card>
        <Card className="inventory-metric-card">
          <Text size="1" color="gray">{t("待处理销售")}</Text>
          <strong>{overview?.openSalesOrders ?? 0}</strong>
          <Text size="1" color="gray">{t("草稿、待发货与部分出库")}</Text>
        </Card>
        <Card
          className={`inventory-metric-card ${
            overview?.lowStockCount ? "warning" : ""
          }`}
        >
          <Text size="1" color="gray">{t("库存预警")}</Text>
          <strong>{overview?.lowStockCount ?? 0}</strong>
          <Text size="1" color="gray">{t("低于补货点的 SKU")}</Text>
        </Card>
      </section>

      <Tabs.Root defaultValue="stock">
        <Tabs.List className="inventory-tabs">
          <Tabs.Trigger value="stock">{t("库存台账")}</Tabs.Trigger>
          <Tabs.Trigger value="purchase">
            {t("采购 {count}", { count: warehousePurchases.length })}
          </Tabs.Trigger>
          <Tabs.Trigger value="sale">{t("销售 {count}", { count: warehouseSales.length })}</Tabs.Trigger>
          <Tabs.Trigger value="movement">{t("出入库流水")}</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="stock">
          <Card className="inventory-panel">
            <div className="inventory-toolbar">
              <TextField.Root
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={t("搜索 SKU 编码或商品名称")}
              >
                <TextField.Slot>
                  <MagnifyingGlass />
                </TextField.Slot>
              </TextField.Root>
              <label className="inventory-check-control">
                <Checkbox
                  checked={lowStockOnly}
                  onCheckedChange={(checked) => {
                    setLowStockOnly(checked === true);
                    setPage(1);
                  }}
                />
                <Text size="2">{t("只看库存预警")}</Text>
              </label>
              <Text size="1" color="gray">
                {t("{count} 个 SKU", { count: stocks.total })}
              </Text>
            </div>
            {loading && !stocks.items.length ? (
              <CoreLoading label={t("正在读取库存余额")} />
            ) : (
              <StockTable
                rows={stocks.items}
                canAdjust={canAdjust}
                onAdjust={(row) => {
                  setAdjustmentStock(row);
                  setDialog("adjust");
                }}
                onPolicy={setPolicyStock}
              />
            )}
            {stocks.pages > 1 ? (
              <div className="inventory-pagination">
                <Button
                  variant="soft"
                  color="gray"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  {t("上一页")}
                </Button>
                <Text size="2">
                  {page} / {stocks.pages}
                </Text>
                <Button
                  variant="soft"
                  color="gray"
                  disabled={page >= stocks.pages}
                  onClick={() => setPage((value) => value + 1)}
                >
                  {t("下一页")}
                </Button>
              </div>
            ) : null}
          </Card>
        </Tabs.Content>

        <Tabs.Content value="purchase">
          <OrderList
            kind="purchase"
            rows={warehousePurchases}
            loading={loading}
            onOpen={openPurchase}
            onCreate={canPurchase ? () => setDialog("purchase") : undefined}
          />
        </Tabs.Content>

        <Tabs.Content value="sale">
          <OrderList
            kind="sale"
            rows={warehouseSales}
            loading={loading}
            onOpen={openSale}
            onCreate={canSell ? () => setDialog("sale") : undefined}
          />
        </Tabs.Content>

        <Tabs.Content value="movement">
          <MovementTable rows={movements.items} loading={loading} />
        </Tabs.Content>
      </Tabs.Root>

      <Dialog.Root
        open={dialog === "warehouse"}
        onOpenChange={(open) => setDialog(open ? "warehouse" : undefined)}
      >
        <Dialog.Content className="inventory-form-dialog compact">
          <WarehouseDialog
            defaultCurrency={activeWarehouse?.currency ?? "CNY"}
            onClose={() => setDialog(undefined)}
            onSaved={async (row) => {
              setDialog(undefined);
              await loadWarehouses();
              setWarehouseId(row.id);
            }}
          />
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={dialog === "adjust"}
        onOpenChange={(open) => {
          setDialog(open ? "adjust" : undefined);
          if (!open) setAdjustmentStock(undefined);
        }}
      >
        <Dialog.Content className="inventory-form-dialog">
          <AdjustmentDialog
            warehouse={activeWarehouse}
            initialStock={adjustmentStock}
            onClose={() => {
              setDialog(undefined);
              setAdjustmentStock(undefined);
            }}
            onSaved={async () => {
              setDialog(undefined);
              setAdjustmentStock(undefined);
              await reloadAfterMutation();
            }}
          />
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={dialog === "transfer"}
        onOpenChange={(open) => setDialog(open ? "transfer" : undefined)}
      >
        <Dialog.Content className="inventory-form-dialog">
          <TransferDialog
            source={activeWarehouse}
            warehouses={warehouses}
            onClose={() => setDialog(undefined)}
            onSaved={async () => {
              setDialog(undefined);
              await reloadAfterMutation();
            }}
          />
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={dialog === "purchase"}
        onOpenChange={(open) => setDialog(open ? "purchase" : undefined)}
      >
        <Dialog.Content className="inventory-form-dialog">
          <PurchaseCreateDialog
            warehouse={activeWarehouse}
            onClose={() => setDialog(undefined)}
            onSaved={async (order) => {
              setDialog(undefined);
              setPurchaseDetail(order);
              await reloadAfterMutation();
            }}
          />
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={dialog === "sale"}
        onOpenChange={(open) => setDialog(open ? "sale" : undefined)}
      >
        <Dialog.Content className="inventory-form-dialog">
          <SalesCreateDialog
            warehouse={activeWarehouse}
            onClose={() => setDialog(undefined)}
            onSaved={async (order) => {
              setDialog(undefined);
              setSalesDetail(order);
              await reloadAfterMutation();
            }}
          />
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={Boolean(policyStock)}
        onOpenChange={(open) => {
          if (!open) setPolicyStock(undefined);
        }}
      >
        <Dialog.Content className="inventory-form-dialog compact">
          {policyStock ? (
            <PolicyDialog
              stock={policyStock}
              onClose={() => setPolicyStock(undefined)}
              onSaved={async () => {
                setPolicyStock(undefined);
                await loadWorkspace();
              }}
            />
          ) : null}
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={Boolean(purchaseDetail)}
        onOpenChange={(open) => {
          if (!open) setPurchaseDetail(undefined);
        }}
      >
        <Dialog.Content className="inventory-order-dialog">
          {purchaseDetail ? (
            <PurchaseDetailDialog
              order={purchaseDetail}
              canManage={canPurchase}
              onClose={() => setPurchaseDetail(undefined)}
              onUpdated={async (order) => {
                setPurchaseDetail(order);
                await reloadAfterMutation();
              }}
            />
          ) : null}
        </Dialog.Content>
      </Dialog.Root>

      <Dialog.Root
        open={Boolean(salesDetail)}
        onOpenChange={(open) => {
          if (!open) setSalesDetail(undefined);
        }}
      >
        <Dialog.Content className="inventory-order-dialog">
          {salesDetail ? (
            <SalesDetailDialog
              order={salesDetail}
              canManage={canSell}
              onClose={() => setSalesDetail(undefined)}
              onUpdated={async (order) => {
                setSalesDetail(order);
                await reloadAfterMutation();
              }}
            />
          ) : null}
        </Dialog.Content>
      </Dialog.Root>
    </div>
  );
}

function StockTable({
  rows,
  canAdjust,
  onAdjust,
  onPolicy,
}: {
  rows: InventoryStockItem[];
  canAdjust: boolean;
  onAdjust: (row: InventoryStockItem) => void;
  onPolicy: (row: InventoryStockItem) => void;
}) {
  const { t } = useLocale();
  if (!rows.length) {
    return (
      <CoreEmpty
        title={t("没有匹配的 SKU")}
        description={t("清除筛选条件，或先在 SKU 商品库导入商品。")}
      />
    );
  }
  return (
    <div className="inventory-table-scroll">
      <div className="inventory-stock-table">
        <div className="inventory-table-head">
          <span>{t("SKU 商品")}</span>
          <span>{t("现存")}</span>
          <span>{t("锁定")}</span>
          <span>{t("可用")}</span>
          <span>{t("平均成本")}</span>
          <span>{t("库存金额")}</span>
          <span>{t("补货点")}</span>
          <span />
        </div>
        {rows.map((row) => (
          <div
            className={`inventory-table-row ${row.lowStock ? "low-stock" : ""}`}
            key={row.skuId}
          >
            <span className="inventory-item-name">
              <span className="inventory-row-icon">
                <Cube />
              </span>
              <span>
                <strong>{row.skuName}</strong>
                <small>{row.skuCode}</small>
              </span>
            </span>
            <strong data-mobile-label={t("现存")}>{quantity(row.onHandQuantity)}</strong>
            <span data-mobile-label={t("锁定")}>{quantity(row.reservedQuantity)}</span>
            <strong data-mobile-label={t("可用")} className={row.lowStock ? "negative" : ""}>
              {quantity(row.availableQuantity)}
            </strong>
            <span data-mobile-label={t("平均成本")}>{money(row.currency, row.averageCost)}</span>
            <strong data-mobile-label={t("库存金额")}>{money(row.currency, row.inventoryValue)}</strong>
            <span data-mobile-label={t("补货点")}>
              {row.lowStock ? <Warning weight="fill" /> : null}
              {quantity(row.reorderPoint)}
            </span>
            <span className="inventory-row-actions">
              <Button
                size="1"
                variant="ghost"
                color="gray"
                onClick={() => onPolicy(row)}
              >
                {t("预警")}
              </Button>
              {canAdjust ? (
                <Button
                  size="1"
                  variant="soft"
                  color="gray"
                  onClick={() => onAdjust(row)}
                >
                  {t("调整")}
                </Button>
              ) : null}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrderList({
  kind,
  rows,
  loading,
  onOpen,
  onCreate,
}: {
  kind: "purchase" | "sale";
  rows: Array<PurchaseOrderSummary | SalesOrderSummary>;
  loading: boolean;
  onOpen: (id: string) => Promise<void>;
  onCreate?: () => void;
}) {
  const { t } = useLocale();
  const purchase = kind === "purchase";
  return (
    <Card className="inventory-panel">
      <div className="inventory-panel-heading">
        <div>
          <Text size="1" color="gray">
            {t(purchase ? "采购与收货" : "销售、锁库与发货")}
          </Text>
          <Heading size="4">{t(purchase ? "采购单" : "销售单")}</Heading>
        </div>
        {onCreate ? (
          <Button variant="soft" onClick={onCreate}>
            <Plus /> {t(purchase ? "新建采购" : "新建销售")}
          </Button>
        ) : null}
      </div>
      {loading && !rows.length ? (
        <CoreLoading label={t(purchase ? "正在读取采购单" : "正在读取销售单")} />
      ) : !rows.length ? (
        <CoreEmpty
          title={t(purchase ? "尚无采购单" : "尚无销售单")}
          description={
            purchase
              ? t("创建采购单并确认后，可以分批登记实际收货。")
              : t("创建销售单并确认后会先锁库，发货时才扣减现存量。")
          }
          action={
            onCreate ? (
              <Button onClick={onCreate}>
                <Plus /> {t(purchase ? "创建第一张采购单" : "创建第一张销售单")}
              </Button>
            ) : undefined
          }
        />
      ) : (
        <div className="inventory-order-list">
          {rows.map((row) => {
            const counterparty =
              "supplierName" in row ? row.supplierName : row.customerName;
            return (
              <button
                type="button"
                className="inventory-order-row"
                key={row.id}
                onClick={() => void onOpen(row.id)}
              >
                <span className="inventory-row-icon">
                  {purchase ? <Receipt /> : <ShoppingCartSimple />}
                </span>
                <span className="inventory-order-identity">
                  <strong>{counterparty}</strong>
                  <small>{row.orderNumber}</small>
                </span>
                <span>
                  <small>{t("仓库")}</small>
                  <strong>{row.warehouseName}</strong>
                </span>
                <span>
                  <small>{t("金额")}</small>
                  <strong>{money(row.currency, row.totalAmount)}</strong>
                </span>
                <Badge color={orderColor(row.status)}>
                  {t(orderLabels[row.status] ?? row.status)}
                </Badge>
                <Text size="1" color="gray">
                  {coreDate(row.updatedAt)}
                </Text>
              </button>
            );
          })}
        </div>
      )}
    </Card>
  );
}

function MovementTable({
  rows,
  loading,
}: {
  rows: InventoryMovement[];
  loading: boolean;
}) {
  const { t } = useLocale();
  return (
    <Card className="inventory-panel">
      <div className="inventory-panel-heading">
        <div>
          <Text size="1" color="gray">{t("不可变库存账")}</Text>
          <Heading size="4">{t("出入库流水")}</Heading>
        </div>
        <Badge color="gray">{t("{count} 条近期流水", { count: rows.length })}</Badge>
      </div>
      {loading && !rows.length ? (
        <CoreLoading label={t("正在读取库存流水")} />
      ) : !rows.length ? (
        <CoreEmpty
          title={t("尚无库存流水")}
          description={t("采购收货、销售锁库与出库、库存调整和调拨都会记录在这里。")}
        />
      ) : (
        <div className="inventory-table-scroll">
          <div className="inventory-movement-table">
            <div className="inventory-table-head">
              <span>{t("时间 / 单据")}</span>
              <span>{t("类型")}</span>
              <span>SKU</span>
              <span>{t("现存变化")}</span>
              <span>{t("锁定变化")}</span>
              <span>{t("变化后余额")}</span>
              <span>{t("成本")}</span>
            </div>
            {rows.map((row) => (
              <div className="inventory-table-row" key={row.id}>
                <span>
                  <strong>{coreDate(row.occurredAt)}</strong>
                  <small>{row.sourceNumber ?? row.documentNumber}</small>
                </span>
                <Badge
                  color={
                    row.onHandDelta > 0
                      ? "jade"
                      : row.onHandDelta < 0
                        ? "amber"
                        : "blue"
                  }
                >
                  {t(movementLabels[row.movementType] ?? row.movementType)}
                </Badge>
                <span>
                  <strong>{row.skuName}</strong>
                  <small>{row.skuCode}</small>
                </span>
                <strong
                  className={
                    row.onHandDelta > 0
                      ? "positive"
                      : row.onHandDelta < 0
                        ? "negative"
                        : ""
                  }
                >
                  {signed(row.onHandDelta)}
                </strong>
                <strong>{signed(row.reservedDelta)}</strong>
                <span>
                  <strong>{quantity(row.onHandAfter)}</strong>
                  <small>{t("锁定 {count}", { count: quantity(row.reservedAfter) })}</small>
                </span>
                <span>{money(row.currency, Math.abs(row.totalCost))}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function DialogHeading({
  eyebrow,
  title,
  description,
  onClose,
}: {
  eyebrow: string;
  title: string;
  description: string;
  onClose: () => void;
}) {
  const { t } = useLocale();
  return (
    <div className="core-dialog-heading">
      <div>
        <Text size="1" color="gray">{t(eyebrow)}</Text>
        <Dialog.Title>{t(title)}</Dialog.Title>
        <Dialog.Description>{t(description)}</Dialog.Description>
      </div>
      <Button
        variant="ghost"
        color="gray"
        onClick={onClose}
        aria-label={t("关闭")}
      >
        <X />
      </Button>
    </div>
  );
}

function FormError({ message }: { message: string }) {
  const { t } = useLocale();
  return message ? (
    <div className="inventory-form-error">
      <Warning /> <Text size="2">{t(message)}</Text>
    </div>
  ) : null;
}

function WarehouseDialog({
  defaultCurrency,
  onClose,
  onSaved,
}: {
  defaultCurrency: string;
  onClose: () => void;
  onSaved: (warehouse: Warehouse) => Promise<void>;
}) {
  const { t } = useLocale();
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [currency, setCurrency] = useState(defaultCurrency);
  const [address, setAddress] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      const row = await createWarehouse({ code, name, currency, address });
      await onSaved(row);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("仓库创建失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={t("仓库档案")}
        title={t("新建仓库")}
        description={t("库存、预警与移动平均成本都会按仓库独立核算。")}
        onClose={onClose}
      />
      <div className="inventory-form-grid two">
        <label>
          {t("仓库编码")}
          <TextField.Root
            required
            value={code}
            onChange={(event) => setCode(event.target.value.toUpperCase())}
            placeholder={t("例如 SH01")}
          />
        </label>
        <label>
          {t("仓库名称")}
          <TextField.Root
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={t("例如 上海仓")}
          />
        </label>
        <label>
          {t("核算币种")}
          <TextField.Root
            required
            maxLength={3}
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          {t("地址")}
          <TextField.Root
            value={address}
            onChange={(event) => setAddress(event.target.value)}
            placeholder={t("可选")}
          />
        </label>
      </div>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button type="submit" disabled={saving || !code.trim() || !name.trim()}>
          {t(saving ? "正在创建" : "创建仓库")}
        </Button>
      </div>
    </form>
  );
}

type DraftLine = {
  skuId: string;
  skuCode: string;
  skuName: string;
  quantity: string;
  amount: string;
};

type LineMode = "quantity" | "adjustment" | "cost" | "price";

function SkuLineBuilder({
  mode,
  lines,
  setLines,
}: {
  mode: LineMode;
  lines: DraftLine[];
  setLines: React.Dispatch<React.SetStateAction<DraftLine[]>>;
}) {
  const { t } = useLocale();
  const [search, setSearch] = useState("");
  const [results, setResults] = useState<SkuListItem[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (!search.trim()) {
        setResults([]);
        return;
      }
      setSearching(true);
      void listSkus({
        q: search.trim(),
        statuses: ["ACTIVE"],
        page: 1,
        pageSize: 12,
      })
        .then((page) => setResults(page.items))
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, 220);
    return () => window.clearTimeout(timer);
  }, [search]);

  const add = (sku: SkuListItem) => {
    setLines((current) => {
      if (current.some((row) => row.skuId === sku.id)) return current;
      return [
        ...current,
        {
          skuId: sku.id,
          skuCode: sku.skuCode,
          skuName: sku.name,
          quantity: mode === "adjustment" ? "" : "1",
          amount: "",
        },
      ];
    });
    setSearch("");
    setResults([]);
  };

  const quantityLabel =
    t(mode === "adjustment" ? "增减数量" : mode === "quantity" ? "调拨数量" : "数量");
  const amountLabel =
    mode === "cost"
      ? t("采购单价")
      : mode === "price"
        ? t("销售单价")
        : mode === "adjustment"
          ? t("入库成本（可选）")
          : "";

  return (
    <div className="inventory-line-builder">
      <label>
        {t("添加 SKU")}
        <div className="inventory-sku-search">
          <TextField.Root
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={t("输入 SKU 编码或商品名称")}
          >
            <TextField.Slot>
              <MagnifyingGlass />
            </TextField.Slot>
          </TextField.Root>
          {search.trim() ? (
            <div className="inventory-sku-results">
              {searching ? (
                <Text size="2" color="gray">{t("正在搜索…")}</Text>
              ) : results.length ? (
                results.map((sku) => (
                  <button key={sku.id} type="button" onClick={() => add(sku)}>
                    <span>
                      <strong>{sku.name}</strong>
                      <small>{sku.skuCode}</small>
                    </span>
                    <Plus />
                  </button>
                ))
              ) : (
                <Text size="2" color="gray">{t("没有匹配的在售 SKU")}</Text>
              )}
            </div>
          ) : null}
        </div>
      </label>
      <div className="inventory-draft-lines">
        {lines.map((line) => (
          <div className="inventory-draft-line" key={line.skuId}>
            <span>
              <strong>{line.skuName}</strong>
              <small>{line.skuCode}</small>
            </span>
            <label>
              {quantityLabel}
              <TextField.Root
                required
                type="number"
                step="any"
                value={line.quantity}
                onChange={(event) =>
                  setLines((current) =>
                    current.map((row) =>
                      row.skuId === line.skuId
                        ? { ...row, quantity: event.target.value }
                        : row,
                    ),
                  )
                }
              />
            </label>
            {amountLabel ? (
              <label>
                {amountLabel}
                <TextField.Root
                  required={mode === "cost" || mode === "price"}
                  type="number"
                  min="0"
                  step="any"
                  value={line.amount}
                  onChange={(event) =>
                    setLines((current) =>
                      current.map((row) =>
                        row.skuId === line.skuId
                          ? { ...row, amount: event.target.value }
                          : row,
                      ),
                    )
                  }
                />
              </label>
            ) : null}
            <Button
              type="button"
              variant="ghost"
              color="red"
              aria-label={t("移除 {name}", { name: line.skuName })}
              onClick={() =>
                setLines((current) =>
                  current.filter((row) => row.skuId !== line.skuId),
                )
              }
            >
              <Trash />
            </Button>
          </div>
        ))}
        {!lines.length ? (
          <div className="inventory-line-empty">
            <Package />
            <Text size="2" color="gray">{t("搜索并添加需要处理的 SKU")}</Text>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AdjustmentDialog({
  warehouse,
  initialStock,
  onClose,
  onSaved,
}: {
  warehouse?: Warehouse;
  initialStock?: InventoryStockItem;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<DraftLine[]>(
    initialStock
      ? [
          {
            skuId: initialStock.skuId,
            skuCode: initialStock.skuCode,
            skuName: initialStock.skuName,
            quantity: "",
            amount: "",
          },
        ]
      : [],
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const items = lines.map((line) => ({
      skuId: line.skuId,
      quantityDelta: Number(line.quantity),
      unitCost: line.amount ? Number(line.amount) : undefined,
    }));
    if (!items.length || items.some((item) => !item.quantityDelta)) {
      setError(t("请添加 SKU，并填写非零的增减数量。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await adjustInventory({
        warehouseId: warehouse?.id,
        reason: reason.trim(),
        items,
      });
      await onSaved();
    } catch (reasonValue) {
      setError(
        reasonValue instanceof Error ? reasonValue.message : t("库存调整失败"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={`${warehouse?.name ?? t("当前仓库")} · ${t("直接记账")}`}
        title={t("库存调整")}
        description={t("用于期初建账、盘盈和盘亏。每次调整都会形成不可删除的库存流水。")}
        onClose={onClose}
      />
      <Card className="inventory-form-note warning">
        <Warning />
        <Text size="2">{t("负数代表盘亏或扣减；系统不允许现存量低于锁定量。")}</Text>
      </Card>
      <SkuLineBuilder mode="adjustment" lines={lines} setLines={setLines} />
      <label>
        {t("调整原因")}
        <TextArea
          required
          minLength={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={t("例如：首次盘点录入期初库存")}
        />
      </label>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button
          type="submit"
          disabled={saving || reason.trim().length < 3 || !lines.length}
        >
          {t(saving ? "正在记账" : "确认调整并记账")}
        </Button>
      </div>
    </form>
  );
}

function TransferDialog({
  source,
  warehouses,
  onClose,
  onSaved,
}: {
  source?: Warehouse;
  warehouses: Warehouse[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const destinations = warehouses.filter(
    (row) =>
      row.status === "ACTIVE" &&
      row.id !== source?.id &&
      row.currency === source?.currency,
  );
  const [destinationId, setDestinationId] = useState(destinations[0]?.id ?? "");
  const [reason, setReason] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!source || !destinationId) return;
    const items = lines.map((line) => ({
      skuId: line.skuId,
      quantity: Number(line.quantity),
    }));
    if (!items.length || items.some((item) => item.quantity <= 0)) {
      setError(t("调拨数量必须大于 0。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await transferInventory({
        fromWarehouseId: source.id,
        toWarehouseId: destinationId,
        reason: reason.trim(),
        items,
      });
      await onSaved();
    } catch (reasonValue) {
      setError(reasonValue instanceof Error ? reasonValue.message : t("调拨失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={t("仓间移动")}
        title={t("库存调拨")}
        description={t("调出与调入在同一事务完成，不会出现单边库存。")}
        onClose={onClose}
      />
      <div className="inventory-transfer-route">
        <Card>
          <Text size="1" color="gray">{t("调出仓")}</Text>
          <strong>{source?.name ?? "—"}</strong>
          <small>{source?.code}</small>
        </Card>
        <ArrowsLeftRight />
        <Card>
          <Text size="1" color="gray">{t("调入仓")}</Text>
          <Select.Root value={destinationId} onValueChange={setDestinationId}>
            <Select.Trigger placeholder={t("选择调入仓")} />
            <Select.Content>
              {destinations.map((row) => (
                <Select.Item key={row.id} value={row.id}>
                  {row.name} · {row.code}
                </Select.Item>
              ))}
            </Select.Content>
          </Select.Root>
        </Card>
      </div>
      {!destinations.length ? (
        <Card className="inventory-form-note warning">
          <Warning />
          <Text size="2">{t("请先创建另一个使用 {currency} 核算的有效仓库。", { currency: source?.currency ?? "" })}</Text>
        </Card>
      ) : null}
      <SkuLineBuilder mode="quantity" lines={lines} setLines={setLines} />
      <label>
        {t("调拨原因")}
        <TextArea
          required
          minLength={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder={t("例如：华东仓补货")}
        />
      </label>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button
          type="submit"
          disabled={
            saving ||
            !destinationId ||
            !lines.length ||
            reason.trim().length < 3
          }
        >
          {t(saving ? "正在调拨" : "确认调拨")}
        </Button>
      </div>
    </form>
  );
}

function PurchaseCreateDialog({
  warehouse,
  onClose,
  onSaved,
}: {
  warehouse?: Warehouse;
  onClose: () => void;
  onSaved: (order: PurchaseOrder) => Promise<void>;
}) {
  const { t } = useLocale();
  const [supplierName, setSupplierName] = useState("");
  const [expectedAt, setExpectedAt] = useState("");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const total = lines.reduce(
    (sum, line) => sum + Number(line.quantity || 0) * Number(line.amount || 0),
    0,
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const items = lines.map((line) => ({
      skuId: line.skuId,
      quantity: Number(line.quantity),
      unitCost: Number(line.amount),
    }));
    if (
      !items.length ||
      items.some(
        (item) =>
          item.quantity <= 0 ||
          !Number.isFinite(item.unitCost) ||
          item.unitCost < 0,
      )
    ) {
      setError(t("请填写有效的采购数量和单价。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const order = await createPurchaseOrder({
        supplierName: supplierName.trim(),
        warehouseId: warehouse?.id,
        currency: warehouse?.currency,
        expectedAt: expectedAt ? new Date(expectedAt).toISOString() : undefined,
        notes: notes.trim() || undefined,
        items,
      });
      await onSaved(order);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("采购单创建失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={`${warehouse?.name ?? t("当前仓库")} · ${warehouse?.currency ?? ""}`}
        title={t("新建采购单")}
        description={t("采购单先保存为草稿，确认后才能登记实际收货；支持分批入库。")}
        onClose={onClose}
      />
      <div className="inventory-form-grid two">
        <label>
          {t("供应商名称")}
          <TextField.Root
            required
            value={supplierName}
            onChange={(event) => setSupplierName(event.target.value)}
            placeholder={t("输入本次采购的供应商")}
          />
        </label>
        <label>
          {t("预计到货")}
          <TextField.Root
            type="datetime-local"
            value={expectedAt}
            onChange={(event) => setExpectedAt(event.target.value)}
          />
        </label>
      </div>
      <SkuLineBuilder mode="cost" lines={lines} setLines={setLines} />
      <div className="inventory-order-total">
        <Text size="2" color="gray">{t("采购总额")}</Text>
        <strong>{money(warehouse?.currency ?? "CNY", total)}</strong>
      </div>
      <label>
        {t("采购备注")}
        <TextArea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder={t("交期、包装或其他说明（可选）")}
        />
      </label>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button
          type="submit"
          disabled={saving || !supplierName.trim() || !lines.length}
        >
          {t(saving ? "正在创建" : "保存采购草稿")}
        </Button>
      </div>
    </form>
  );
}

function SalesCreateDialog({
  warehouse,
  onClose,
  onSaved,
}: {
  warehouse?: Warehouse;
  onClose: () => void;
  onSaved: (order: SalesOrder) => Promise<void>;
}) {
  const { t } = useLocale();
  const [customerName, setCustomerName] = useState("");
  const [currency, setCurrency] = useState(warehouse?.currency ?? "CNY");
  const [notes, setNotes] = useState("");
  const [lines, setLines] = useState<DraftLine[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const total = lines.reduce(
    (sum, line) => sum + Number(line.quantity || 0) * Number(line.amount || 0),
    0,
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const items = lines.map((line) => ({
      skuId: line.skuId,
      quantity: Number(line.quantity),
      unitPrice: Number(line.amount),
    }));
    if (
      !items.length ||
      items.some(
        (item) =>
          item.quantity <= 0 ||
          !Number.isFinite(item.unitPrice) ||
          item.unitPrice < 0,
      )
    ) {
      setError(t("请填写有效的销售数量和单价。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      const order = await createSalesOrder({
        customerName: customerName.trim(),
        warehouseId: warehouse?.id,
        currency,
        notes: notes.trim() || undefined,
        items,
      });
      await onSaved(order);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("销售单创建失败"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={`${warehouse?.name ?? t("当前仓库")} · ${t("销售履约")}`}
        title={t("新建销售单")}
        description={t("草稿不会占用库存；确认销售单时才校验可用量并锁库。")}
        onClose={onClose}
      />
      <div className="inventory-form-grid two">
        <label>
          {t("客户名称")}
          <TextField.Root
            required
            value={customerName}
            onChange={(event) => setCustomerName(event.target.value)}
            placeholder={t("输入客户或公司名称")}
          />
        </label>
        <label>
          {t("销售币种")}
          <TextField.Root
            required
            maxLength={3}
            value={currency}
            onChange={(event) => setCurrency(event.target.value.toUpperCase())}
          />
        </label>
      </div>
      <SkuLineBuilder mode="price" lines={lines} setLines={setLines} />
      <div className="inventory-order-total">
        <Text size="2" color="gray">{t("销售总额")}</Text>
        <strong>{money(currency, total)}</strong>
      </div>
      <label>
        {t("销售备注")}
        <TextArea
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder={t("交付、包装或客户要求（可选）")}
        />
      </label>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button
          type="submit"
          disabled={saving || !customerName.trim() || !lines.length}
        >
          {t(saving ? "正在创建" : "保存销售草稿")}
        </Button>
      </div>
    </form>
  );
}

function PolicyDialog({
  stock,
  onClose,
  onSaved,
}: {
  stock: InventoryStockItem;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const { t } = useLocale();
  const [reorderPoint, setReorderPoint] = useState(String(stock.reorderPoint));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await updateStockPolicy(
        stock.warehouseId,
        stock.skuId,
        stock.version,
        Number(reorderPoint),
      );
      await onSaved();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("预警值保存失败"));
    } finally {
      setSaving(false);
    }
  };
  return (
    <form className="inventory-form" onSubmit={(event) => void submit(event)}>
      <DialogHeading
        eyebrow={stock.skuCode}
        title={t("设置补货点")}
        description={t("{name} 当前可用 {count}。", { name: stock.skuName, count: quantity(stock.availableQuantity) })}
        onClose={onClose}
      />
      <label>
        {t("可用库存低于或等于此数值时预警")}
        <TextField.Root
          autoFocus
          required
          type="number"
          min="0"
          step="any"
          value={reorderPoint}
          onChange={(event) => setReorderPoint(event.target.value)}
        />
      </label>
      <FormError message={error} />
      <div className="core-dialog-actions">
        <Button type="button" variant="soft" color="gray" onClick={onClose}>
          {t("取消")}
        </Button>
        <Button type="submit" disabled={saving || Number(reorderPoint) < 0}>
          {t("保存预警")}
        </Button>
      </div>
    </form>
  );
}

function PurchaseDetailDialog({
  order,
  canManage,
  onClose,
  onUpdated,
}: {
  order: PurchaseOrder;
  canManage: boolean;
  onClose: () => void;
  onUpdated: (order: PurchaseOrder) => Promise<void>;
}) {
  const { t } = useLocale();
  const [quantities, setQuantities] = useState<Record<string, string>>(
    Object.fromEntries(
      order.items.map((item) => [
        item.id,
        item.remainingQuantity > 0 ? String(item.remainingQuantity) : "",
      ]),
    ),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setQuantities(
      Object.fromEntries(
        order.items.map((item) => [
          item.id,
          item.remainingQuantity > 0 ? String(item.remainingQuantity) : "",
        ]),
      ),
    );
  }, [order]);

  const run = async (action: () => Promise<PurchaseOrder>) => {
    setSaving(true);
    setError("");
    try {
      await onUpdated(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("采购单操作失败"));
    } finally {
      setSaving(false);
    }
  };

  const receive = () => {
    const items = order.items
      .map((item) => ({
        orderItemId: item.id,
        quantity: Number(quantities[item.id] || 0),
      }))
      .filter((item) => item.quantity > 0);
    if (!items.length) {
      setError(t("请填写本次实际入库数量。"));
      return;
    }
    void run(() => receivePurchaseOrder(order, items));
  };

  return (
    <div className="inventory-order-detail">
      <DialogHeading
        eyebrow={t("采购单")}
        title={order.orderNumber}
        description={`${order.supplierName} · ${order.warehouseName}`}
        onClose={onClose}
      />
      <OrderSummary
        status={order.status}
        currency={order.currency}
        total={order.totalAmount}
        updatedAt={order.updatedAt}
      />
      <div className="inventory-order-lines">
        <div className="inventory-order-line head">
          <span>SKU</span>
          <span>{t("采购数量")}</span>
          <span>{t("已入库")}</span>
          <span>{t("采购单价")}</span>
          <span>{t("本次入库")}</span>
        </div>
        {order.items.map((item) => (
          <div className="inventory-order-line" key={item.id}>
            <span>
              <strong>{item.skuName}</strong>
              <small>{item.skuCode}</small>
            </span>
            <strong>{quantity(item.quantity)}</strong>
            <span>{quantity(item.receivedQuantity)}</span>
            <span>{money(order.currency, item.unitCost)}</span>
            <TextField.Root
              type="number"
              min="0"
              max={item.remainingQuantity}
              step="any"
              disabled={
                !canManage ||
                !["CONFIRMED", "PARTIALLY_RECEIVED"].includes(order.status)
              }
              value={quantities[item.id] ?? ""}
              onChange={(event) =>
                setQuantities((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))
              }
            />
          </div>
        ))}
      </div>
      {order.notes ? (
        <Card className="inventory-form-note">
          <Text size="2">{order.notes}</Text>
        </Card>
      ) : null}
      <FormError message={error} />
      {canManage ? (
        <div className="core-dialog-actions inventory-order-actions">
          {order.status === "DRAFT" ? (
            <Button
              disabled={saving}
              onClick={() => void run(() => confirmPurchaseOrder(order))}
            >
              <CheckCircle /> {t("确认采购单")}
            </Button>
          ) : null}
          {["CONFIRMED", "PARTIALLY_RECEIVED"].includes(order.status) ? (
            <Button disabled={saving} onClick={receive}>
              <Package /> {t("登记本次入库")}
            </Button>
          ) : null}
          {!["RECEIVED", "CANCELLED"].includes(order.status) ? (
            <Button
              variant="soft"
              color="red"
              disabled={saving}
              onClick={() =>
                void run(() => cancelPurchaseOrder(order, t("后台人工取消")))
              }
            >
              {t("取消未收数量")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function SalesDetailDialog({
  order,
  canManage,
  onClose,
  onUpdated,
}: {
  order: SalesOrder;
  canManage: boolean;
  onClose: () => void;
  onUpdated: (order: SalesOrder) => Promise<void>;
}) {
  const { t } = useLocale();
  const [quantities, setQuantities] = useState<Record<string, string>>(
    Object.fromEntries(
      order.items.map((item) => [
        item.id,
        item.reservedQuantity > 0 ? String(item.reservedQuantity) : "",
      ]),
    ),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setQuantities(
      Object.fromEntries(
        order.items.map((item) => [
          item.id,
          item.reservedQuantity > 0 ? String(item.reservedQuantity) : "",
        ]),
      ),
    );
  }, [order]);

  const run = async (action: () => Promise<SalesOrder>) => {
    setSaving(true);
    setError("");
    try {
      await onUpdated(await action());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("销售单操作失败"));
    } finally {
      setSaving(false);
    }
  };

  const ship = () => {
    const items = order.items
      .map((item) => ({
        orderItemId: item.id,
        quantity: Number(quantities[item.id] || 0),
      }))
      .filter((item) => item.quantity > 0);
    if (!items.length) {
      setError(t("请填写本次实际出库数量。"));
      return;
    }
    void run(() => shipSalesOrder(order, items));
  };

  return (
    <div className="inventory-order-detail">
      <DialogHeading
        eyebrow={t("销售单")}
        title={order.orderNumber}
        description={`${order.customerName} · ${order.warehouseName}`}
        onClose={onClose}
      />
      <OrderSummary
        status={order.status}
        currency={order.currency}
        total={order.totalAmount}
        updatedAt={order.updatedAt}
      />
      <div className="inventory-order-lines">
        <div className="inventory-order-line head">
          <span>SKU</span>
          <span>{t("销售数量")}</span>
          <span>{t("已出库 / 锁定")}</span>
          <span>{t("销售单价")}</span>
          <span>{t("本次出库")}</span>
        </div>
        {order.items.map((item) => (
          <div className="inventory-order-line" key={item.id}>
            <span>
              <strong>{item.skuName}</strong>
              <small>{item.skuCode}</small>
            </span>
            <strong>{quantity(item.quantity)}</strong>
            <span>
              {quantity(item.shippedQuantity)} / {quantity(item.reservedQuantity)}
            </span>
            <span>{money(order.currency, item.unitPrice)}</span>
            <TextField.Root
              type="number"
              min="0"
              max={item.reservedQuantity}
              step="any"
              disabled={
                !canManage ||
                !["CONFIRMED", "PARTIALLY_SHIPPED"].includes(order.status)
              }
              value={quantities[item.id] ?? ""}
              onChange={(event) =>
                setQuantities((current) => ({
                  ...current,
                  [item.id]: event.target.value,
                }))
              }
            />
          </div>
        ))}
      </div>
      {order.notes ? (
        <Card className="inventory-form-note">
          <Text size="2">{order.notes}</Text>
        </Card>
      ) : null}
      <FormError message={error} />
      {canManage ? (
        <div className="core-dialog-actions inventory-order-actions">
          {order.status === "DRAFT" ? (
            <Button
              disabled={saving}
              onClick={() => void run(() => confirmSalesOrder(order))}
            >
              <CheckCircle /> {t("确认并锁定库存")}
            </Button>
          ) : null}
          {["CONFIRMED", "PARTIALLY_SHIPPED"].includes(order.status) ? (
            <Button disabled={saving} onClick={ship}>
              <Package /> {t("登记本次出库")}
            </Button>
          ) : null}
          {!["SHIPPED", "CANCELLED"].includes(order.status) ? (
            <Button
              variant="soft"
              color="red"
              disabled={saving}
              onClick={() =>
                void run(() => cancelSalesOrder(order, t("后台人工取消")))
              }
            >
              {t("取消并释放未发库存")}
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function OrderSummary({
  status,
  currency,
  total,
  updatedAt,
}: {
  status: string;
  currency: string;
  total: number;
  updatedAt: string;
}) {
  const { t } = useLocale();
  return (
    <section className="inventory-order-summary">
      <Card>
        <Text size="1" color="gray">{t("状态")}</Text>
        <Badge color={orderColor(status)}>
          {t(orderLabels[status] ?? status)}
        </Badge>
      </Card>
      <Card>
        <Text size="1" color="gray">{t("单据金额")}</Text>
        <strong>{money(currency, total)}</strong>
      </Card>
      <Card>
        <Text size="1" color="gray">{t("最后更新")}</Text>
        <strong>{coreDate(updatedAt)}</strong>
      </Card>
    </section>
  );
}
