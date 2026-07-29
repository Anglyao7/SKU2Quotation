export type UiLocale = "zh-CN" | "en-US";
export type BusinessMode = "DOMESTIC" | "EXPORT";

export interface AuthUser {
  id: string;
  displayName: string;
  email?: string;
  isPlatformAdmin: boolean;
  locale: UiLocale;
}

export interface AuthWorkspaceContext {
  tenantId?: string;
  membershipId?: string;
  tenantName?: string;
  tenantSlug?: string;
  businessMode?: BusinessMode;
  defaultCurrency?: string;
  defaultWorkspace?: string;
  accountScope?: "STAFF" | "CUSTOMER_SUBACCOUNT";
}

export interface MembershipSummary {
  id: string;
  tenantId: string;
  tenantName: string;
  tenantSlug: string;
  status: string;
}

export interface AuthTokenData {
  accessToken: string;
  expiresIn: number;
  csrfToken: string;
  sessionId: string;
  requiresTenantSelection: boolean;
  user: AuthUser;
  context: AuthWorkspaceContext;
}

export interface CurrentUser {
    user: AuthUser;
    context: AuthWorkspaceContext;
    memberships: MembershipSummary[];
}

export interface MerchantSettings {
  name: string;
  slug: string;
  storefrontPath: string;
  businessMode: BusinessMode;
  defaultCurrency: string;
}

export interface PermissionSet {
  membershipId: string;
  permissionVersion: number;
  permissions: string[];
}

export interface TenantPermission {
  code: string;
  module: string;
  action: string;
  description?: string;
}

export interface TenantRole {
  id: string;
  code: string;
  name: string;
  description?: string;
  isSystem: boolean;
  status: string;
  permissionCodes: string[];
  memberCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface TenantMemberRole {
  id: string;
  code: string;
  name: string;
  isSystem: boolean;
}

export interface TenantMember {
  id: string;
  userId: string;
  displayName: string;
  email?: string;
  jobTitle?: string;
  status: string;
  permissionVersion: number;
  roles: TenantMemberRole[];
  joinedAt?: string;
  createdAt: string;
}

export interface CustomerSubaccount {
  id: string;
  userId: string;
  displayName: string;
  loginIdentifier: string;
  email?: string;
  status: "active" | "suspended" | string;
  createdAt: string;
  lastLoginAt?: string;
  loginCount30d: number;
  orderCount: number;
  lastOrderAt?: string;
}

export interface CustomerSubaccountOrder {
  id: string;
  quoteNumber: string;
  status: string;
  submittedByMembershipId: string;
  submittedByName: string;
  customerName: string;
  customerCompany?: string;
  currency: string;
  totalAmount: number;
  createdAt: string;
  validUntil: string;
}

export interface CustomerSubaccountDashboard {
  accounts: CustomerSubaccount[];
  activeCount: number;
  suspendedCount: number;
  orderCount: number;
}

export interface CustomerSubaccountOrderPage {
  items: CustomerSubaccountOrder[];
  total: number;
  page: number;
  pageSize: number;
}

export interface CustomerPortalOverview {
  displayName: string;
  tenantName: string;
  tenantSlug: string;
  accountStatus: string;
  orderCount: number;
  lastOrderAt?: string;
}

export interface CustomerPortalOrder {
  id: string;
  quoteNumber: string;
  status: string;
  customerName: string;
  customerCompany?: string;
  currency: string;
  totalAmount: number;
  createdAt: string;
  validUntil: string;
}

export type ImportJobStatus = "scanning" | "parsing" | "needs_review" | "published" | "failed";

export interface ImportIssue {
  rowNumber?: number;
  column: string;
  code: string;
  message: string;
  value?: string;
  suggestion?: string;
}

export interface ImportResultDetails {
  outcome?: string;
  imported?: number;
  created?: number;
  updated?: number;
  unchanged?: number;
  skipped?: number;
  issues: ImportIssue[];
  issueTotal: number;
  issuesTruncated: number;
  importProgress?: number;
  importStage?: string;
  processedRows?: number;
  totalRows?: number;
}

export interface ImportJob {
  id: string;
  filename: string;
  supplier: string;
  sourceType: string;
  detectedType: string;
  status: ImportJobStatus;
  progress: number;
  products: number;
  warnings: number;
  warningMessages: string[];
  createdAt: string;
  parser?: string;
  extensionMatches?: boolean;
  errorMessage?: string;
  resultDetails: ImportResultDetails;
}

export interface FileDetection {
  filename: string;
  detected_type: string;
  extension_matches: boolean;
  parser: string;
  warning?: string | null;
}

export interface ReviewField {
  key: string;
  label: string;
  source: string;
  normalized: string;
  confidence: number;
}

export interface ReviewItem {
  id: string;
  jobId?: string;
  taskId?: string;
  candidateGroupKey?: string;
  appliedProductId?: string;
  status?: "pending" | "approved" | "rejected";
  name: string;
  model: string;
  category?: string;
  supplier: string;
  source: string;
  location: string;
  imageStatus: "SOURCE" | "APPROVED";
  fields: ReviewField[];
}

export interface DashboardMetric {
  key: string;
  label: string;
  value: number;
  unit?: string;
  status: string;
  destination: string;
}

export interface DashboardSnapshot {
  generatedAt: string;
  dataScope: "TENANT" | "SELF";
  metrics: DashboardMetric[];
  recentImports: Array<{
    id: string;
    filename: string;
    supplierName: string;
    sourceType: string;
    status: string;
    progress: number;
    productsCount: number;
    warningsCount: number;
    createdAt: string;
  }>;
  dataHealth?: {
    score: number;
    activeProducts: number;
    approvedImageCoverage: number;
    supplierSourceCoverage: number;
    validPriceCoverage: number;
  };
}

export interface ProductOffer {
  supplierProductId: string;
  supplierId: string;
  supplierName: string;
  supplierSku?: string;
  skuId?: string;
  leadTimeDays?: number;
  unitPrice?: number;
  currency?: string;
  priceValidity: "VALID" | "EXPIRING" | "EXPIRED" | "UNKNOWN";
  validTo?: string;
}

export interface CoreProduct {
  id: string;
  productCode?: string;
  name: string;
  model: string;
  status: string;
  category: string;
  categoryId?: string;
  supplier: string;
  price?: number;
  currency?: string;
  updated: string;
  imageStatus: "SOURCE" | "APPROVED" | "NONE";
  tags: string[];
  skuCount: number;
  supplierCount: number;
  currentVersion: number;
  capabilities: string[];
}

export interface ProductSku {
  id: string;
  productId: string;
  skuCode: string;
  name?: string;
  optionValues: Record<string, string | number | boolean>;
  barcode?: string;
  weight?: number;
  weightUnit?: string;
  status: "DRAFT" | "ACTIVE" | "INACTIVE" | "ARCHIVED";
  version: number;
  updatedAt: string;
}

export interface SkuListItem {
  id: string;
  skuCode: string;
  name: string;
  productId: string;
  productCode?: string;
  productName: string;
  category?: {
    id: string;
    code: string;
    name: string;
  };
  tags: string[];
  supplierSummary: {
    count: number;
    primarySupplierId?: string;
    primarySupplierName?: string;
    names: string[];
  };
  publicPrice?: number;
  publicCurrency?: string;
  publicOfferStatus?: "DRAFT" | "PUBLISHED" | "SUSPENDED";
  status: ProductSku["status"];
  version: number;
  updatedAt: string;
  imageStatus: "SOURCE" | "APPROVED" | "NONE";
}

export interface SkuListPage {
  items: SkuListItem[];
  page: number;
  pageSize: number;
  total: number;
  pages: number;
}

export interface PublicCatalogOffer {
  id: string;
  skuId: string;
  unitPrice: number;
  currency: string;
  tags: string[];
  displayTag?: string;
  tagColor?: string;
  publicationStatus: "DRAFT" | "PUBLISHED" | "SUSPENDED";
  publishedAt?: string;
  validFrom?: string;
  validTo?: string;
  createdAt: string;
  updatedAt: string;
}

export interface ProductAttribute {
  id: string;
  definitionId?: string;
  key: string;
  value: unknown;
  unitCode?: string;
  reviewStatus: string;
}

export interface ProductActivity {
  id: string;
  entityType: string;
  entityId: string;
  action: string;
  before: Record<string, unknown>;
  after: Record<string, unknown>;
  actorMembershipId: string;
  occurredAt: string;
}

export interface ProductDetail extends CoreProduct {
  description?: string;
  defaultUnit?: string;
  attributes: ProductAttribute[];
  skus: ProductSku[];
  sources: ProductOffer[];
  activity: ProductActivity[];
}

export interface ProductCategory {
  id: string;
  parentId?: string;
  code: string;
  name: string;
  path?: string;
  displayColor?: string;
  status: string;
  sortOrder: number;
  version: number;
}

export interface CategoryLayout {
  allProductsPosition: number;
  rootCategoryCount: number;
}

export interface CpuUsage {
  utilizationPercent?: number;
  logicalCores: number;
  quotaCores?: number;
  load1m?: number;
  load5m?: number;
  load15m?: number;
}

export interface MemoryUsage {
  usedBytes?: number;
  totalBytes?: number;
  availableBytes?: number;
  utilizationPercent?: number;
  containerUsedBytes?: number;
  containerLimitBytes?: number;
}

export interface DiskUsage {
  mountPath: string;
  usedBytes: number;
  totalBytes: number;
  availableBytes: number;
  utilizationPercent: number;
}

export interface SystemMonitoringSnapshot {
  sampledAt: string;
  scope: string;
  uptimeSeconds?: number;
  cpu: CpuUsage;
  memory: MemoryUsage;
  disk: DiskUsage;
}

export interface AttributeDefinition {
  id: string;
  categoryId?: string;
  attributeKey: string;
  displayName: string;
  dataType: "TEXT" | "NUMBER" | "BOOLEAN" | "ENUM";
  unitCode?: string;
  enumValues?: string[];
  isRequired: boolean;
  isVariant: boolean;
  isFilterable: boolean;
  isMatchable: boolean;
  status: string;
  version: number;
}

export interface SupplierPrice {
  id: string;
  productId: string;
  supplierProductId: string;
  supplierId: string;
  supplierName: string;
  skuId?: string;
  minQuantity: number;
  maxQuantity?: number;
  unitPrice: number;
  currency: string;
  unitCode: string;
  incoterm?: string;
  taxStatus?: string;
  validFrom: string;
  validTo?: string;
  status: string;
  priceValidity: ProductOffer["priceValidity"];
  confirmedAt?: string;
  createdAt: string;
}

export interface SupplierScore {
  overallScore?: number;
  qualityScore?: number;
  priceScore?: number;
  deliveryScore?: number;
  responseScore?: number;
  riskScore?: number;
  sampleSize: number;
  methodVersion: string;
  calculatedAt: string;
}

export interface SupplierProfile {
  id: string;
  supplierCode: string;
  name: string;
  category: string;
  categorySummary?: string;
  countryCode?: string;
  website?: string;
  status: string;
  riskLevel: string;
  health: string;
  version: number;
  activeProducts: number;
  activeSkus: number;
  pendingReviews: number;
  validPrices: number;
  expiredPrices: number;
  latestImportAt?: string;
  updatedAt: string;
  latestScore?: SupplierScore;
}

export interface SupplierProfileDetail extends SupplierProfile {
  sources: Array<{
    supplierProductId: string;
    productId: string;
    productCode: string;
    productName: string;
    skuId?: string;
    supplierSku?: string;
    leadTimeDays?: number;
    status: string;
    unitPrice?: number;
    currency?: string;
    priceValidTo?: string;
    priceValidity: string;
  }>;
  recentImports: Array<{
    id: string;
    filename: string;
    status: string;
    productsCount: number;
    warningsCount: number;
    createdAt: string;
  }>;
}

export interface HybridSearchEvidence {
  documentId: string;
  chunkId: string;
  chunkType: string;
  contentHash: string;
  excerpt: string;
}

export interface HybridSearchResult {
  productId: string;
  productCode?: string;
  name: string;
  sourceVersion: number;
  score: number;
  scoreBreakdown: { keyword: number; semantic: number; attribute: number; supplier: number };
  supplierSignalStatus: string;
  evidence: HybridSearchEvidence[];
  rankingVersion: string;
  degradedChannels: string[];
  product?: ProductDetail;
}

export interface HybridSearchResponse {
  query: string;
  rankingVersion: string;
  model: { provider: string; name: string; version: string; dimensions: number };
  degradedChannels: string[];
  results: HybridSearchResult[];
}

export interface KnowledgeIndexStatus {
  totalProducts: number;
  indexedProducts: number;
  pendingProducts: number;
  modelProvider: string;
  modelName: string;
  modelVersion: string;
  dimensions: number;
  mode?: "INCREMENTAL" | "FULL_REBUILD";
  processedProducts?: number;
  embeddings?: number;
}

export type KnowledgeIndexJobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface KnowledgeIndexJob {
  id: string;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: KnowledgeIndexJobStatus;
  totalProducts: number;
  processedProducts: number;
  failedProducts: number;
  embeddings: number;
  progressPercent: number;
  currentProductId?: string;
  currentProductName?: string;
  modelProvider: string;
  modelName: string;
  modelVersion: string;
  dimensions: number;
  errorMessage?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

export interface EmbeddingSettings {
  source: "database" | "environment" | "deterministic";
  provider: string;
  baseUrl?: string;
  modelName: string;
  modelVersion: string;
  dimensions: number;
  timeoutSeconds: number;
  apiKeyConfigured: boolean;
  apiKeyHint?: string;
  updatedAt?: string;
}

export interface InquiryItem {
  id: string;
  lineNumber: number;
  rawRequirement: string;
  normalizedRequirement: Record<string, unknown>;
  quantity?: number;
  unitCode?: string;
  imageSearchId?: string;
  status: string;
  version: number;
}

export interface InquiryRecord {
  id: string;
  inquiryNumber: string;
  customerId?: string;
  temporaryCustomerName?: string;
  currency: string;
  language: string;
  status: string;
  version: number;
  items: InquiryItem[];
}

export interface InquiryMatch {
  id: string;
  inquiryItemId: string;
  productId: string;
  skuId?: string;
  supplierProductId?: string;
  productVersion: number;
  rank: number;
  totalScore: number;
  scoreBreakdown: Record<string, unknown>;
  reasons: string[];
  gaps: string[];
  evidence: Array<Record<string, unknown>>;
  rankingVersion: string;
  status: string;
}

export interface QuotationRecord {
  id: string;
  quotationNumber: string;
  inquiryId: string;
  customerId: string;
  currency: string;
  status: string;
  currentVersion: number;
  totalAmount: number;
  expiresAt?: string;
  approvalStatus: string;
  versionHash: string;
  createdAt: string;
  updatedAt: string;
  versions: Array<{
    versionNumber: number;
    totalAmount: number;
    currency: string;
    ruleVersion: string;
    contentHash: string;
    approvalStatus: string;
    createdAt: string;
  }>;
  items: Array<{
    id: string;
    inquiryItemId: string;
    productId: string;
    productSnapshot: Record<string, unknown>;
    sourceSnapshot: Record<string, unknown>;
    quantity: number;
    unitCode: string;
    unitCost?: number;
    targetMarginRate?: number;
    unitPrice: number;
    lineTotal: number;
    warnings: string[];
  }>;
}

export interface QuotationSummary {
  id: string;
  quotationNumber: string;
  customerName: string;
  currency: string;
  status: string;
  currentVersion: number;
  totalAmount: number;
  updatedAt: string;
}

export interface PublicQuoteDraftItem {
  id: string;
  skuId: string;
  position: number;
  quantity: number;
  skuCode: string;
  name: string;
  description?: string;
  category?: string;
  tags: string[];
  imageUrl?: string;
  unitCode: string;
  currency: string;
  unitPrice: number;
  lineTotal: number;
  productVersion: number;
  skuVersion: number;
}

export interface PublicQuoteDraft {
  id: string;
  tenantId: string;
  quoteNumber: string;
  status: string;
  customerName: string;
  customerCompany?: string;
  customerEmail?: string;
  customerPhone?: string;
  notes?: string;
  currency: string;
  subtotal: number;
  total: number;
  validUntil: string;
  createdAt: string;
  contentHash: string;
  disclaimer: string;
  disclaimerVersion: string;
  items: PublicQuoteDraftItem[];
}

export interface PublicQuoteDraftSummary {
  id: string;
  quoteNumber: string;
  status: string;
  customerName: string;
  customerCompany?: string;
  currency: string;
  total: number;
  validUntil: string;
  createdAt: string;
}

export interface Warehouse {
  id: string;
  code: string;
  name: string;
  address?: string;
  currency: string;
  status: "ACTIVE" | "INACTIVE";
  isDefault: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface InventoryStockItem {
  balanceId?: string;
  warehouseId: string;
  warehouseName: string;
  currency: string;
  skuId: string;
  skuCode: string;
  skuName: string;
  productId: string;
  productName: string;
  supplierId?: string;
  supplierName?: string;
  onHandQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
  averageCost: number;
  inventoryValue: number;
  reorderPoint: number;
  lowStock: boolean;
  version: number;
  updatedAt?: string;
}

export interface InventoryStockPage {
  items: InventoryStockItem[];
  page: number;
  pageSize: number;
  total: number;
  pages: number;
}

export interface InventoryOverview {
  warehouseId: string;
  warehouseName: string;
  currency: string;
  totalSkus: number;
  stockedSkus: number;
  onHandQuantity: number;
  reservedQuantity: number;
  availableQuantity: number;
  inventoryValue: number;
  lowStockCount: number;
  openPurchaseOrders: number;
  openSalesOrders: number;
  lowStockItems: InventoryStockItem[];
}

export interface InventoryMovement {
  id: string;
  documentId: string;
  documentNumber: string;
  documentType: string;
  sourceNumber?: string;
  warehouseId: string;
  warehouseName: string;
  currency: string;
  skuId: string;
  skuCode: string;
  skuName: string;
  movementType: string;
  onHandDelta: number;
  reservedDelta: number;
  onHandAfter: number;
  reservedAfter: number;
  unitCost: number;
  totalCost: number;
  averageCostAfter: number;
  notes?: string;
  occurredAt: string;
}

export interface InventoryMovementPage {
  items: InventoryMovement[];
  page: number;
  pageSize: number;
  total: number;
  pages: number;
}

export interface InventoryDocument {
  id: string;
  documentNumber: string;
  documentType: string;
  warehouseId: string;
  counterpartyWarehouseId?: string;
  sourceType?: string;
  sourceId?: string;
  sourceNumber?: string;
  notes?: string;
  occurredAt: string;
  items: Array<{
    id: string;
    skuId: string;
    skuCode: string;
    skuName: string;
    quantity: number;
    unitCost?: number;
  }>;
}

export interface PurchaseOrderItem {
  id: string;
  skuId: string;
  skuCode: string;
  skuName: string;
  quantity: number;
  receivedQuantity: number;
  remainingQuantity: number;
  unitCost: number;
  lineTotal: number;
  notes?: string;
}

export interface PurchaseOrderSummary {
  id: string;
  orderNumber: string;
  supplierName: string;
  warehouseId: string;
  warehouseName: string;
  currency: string;
  status: string;
  totalAmount: number;
  expectedAt?: string;
  version: number;
  updatedAt: string;
}

export interface PurchaseOrder extends PurchaseOrderSummary {
  notes?: string;
  confirmedAt?: string;
  completedAt?: string;
  createdAt: string;
  items: PurchaseOrderItem[];
}

export interface SalesOrderItem {
  id: string;
  skuId: string;
  skuCode: string;
  skuName: string;
  quantity: number;
  reservedQuantity: number;
  shippedQuantity: number;
  remainingQuantity: number;
  unitPrice: number;
  lineTotal: number;
  costAmount: number;
  notes?: string;
}

export interface SalesOrderSummary {
  id: string;
  orderNumber: string;
  customerName: string;
  warehouseId: string;
  warehouseName: string;
  currency: string;
  status: string;
  totalAmount: number;
  version: number;
  updatedAt: string;
}

export interface SalesOrder extends SalesOrderSummary {
  customerId?: string;
  sourceQuotationId?: string;
  notes?: string;
  confirmedAt?: string;
  completedAt?: string;
  createdAt: string;
  items: SalesOrderItem[];
}
