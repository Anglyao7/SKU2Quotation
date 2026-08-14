import type { StorefrontLocale, TenantSubscriptionTier } from "../types";

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
  subscriptionTier?: TenantSubscriptionTier;
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
  memberships?: MembershipSummary[];
  permissionVersion?: number;
  permissions?: string[];
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
  logoUrl?: string;
  shareCardSubtitle?: string;
  businessMode: BusinessMode;
  defaultCurrency: string;
  storefrontLocales: StorefrontLocale[];
  hotProductsEnabled: boolean;
}

export interface PermissionSet {
  membershipId: string;
  permissionVersion: number;
  permissions: string[];
}

export type CustomerSubaccountCapability = "catalog" | "submit_orders" | "view_orders";

export interface CustomerSubaccount {
  id: string;
  userId: string;
  displayName: string;
  loginIdentifier: string;
  email?: string;
  status: "active" | "suspended" | string;
  identityCode: "SUBACCOUNT";
  capabilities: CustomerSubaccountCapability[];
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

export interface CatalogImportBatchCategory {
  id: string;
  name: string;
  skuCount: number;
}

export interface CatalogImportBatch {
  id: string;
  status: "ACTIVE" | "PARTIALLY_REVOKED" | "REVOKED";
  expectedFileCount: number;
  fileCount: number;
  remainingSkuCount: number;
  createdAt: string;
  jobs: ImportJob[];
  categories: CatalogImportBatchCategory[];
}

export interface CatalogImportRollbackResult {
  batchId: string;
  status: CatalogImportBatch["status"];
  deletedSkuCount: number;
  archivedProductCount: number;
  removedImageCount: number;
  deletedStorageImageCount: number;
  preservedExternalImageCount: number;
  retainedSharedImageCount: number;
  storageDeleteFailures: number;
  remainingSkuCount: number;
}

export interface FileDetection {
  filename: string;
  detected_type: string;
  extension_matches: boolean;
  parser: string;
  warning?: string | null;
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

export type SupplyChainStatus = "ACTIVE" | "INACTIVE" | "BLOCKED" | "ARCHIVED";

export interface SupplyChainPartner {
  id: string;
  code: string;
  name: string;
  contactName?: string;
  phone?: string;
  email?: string;
  whatsapp?: string;
  wechat?: string;
  countryRegion?: string;
  address?: string;
  website?: string;
  businessScope?: string;
  notes?: string;
  status: SupplyChainStatus;
  version: number;
  activeProducts: number;
  activeSkus: number;
  updatedAt: string;
}

export interface SupplyChainPage {
  items: SupplyChainPartner[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
}

export interface SupplyChainPartnerInput {
  name: string;
  contactName?: string;
  phone?: string;
  email?: string;
  whatsapp?: string;
  wechat?: string;
  countryRegion?: string;
  address?: string;
  website?: string;
  businessScope?: string;
  notes?: string;
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
  primaryImageUrl?: string;
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
  sourceSkuCode?: string;
  name?: string;
  optionValues: Record<string, string | number | boolean>;
  barcode?: string;
  defaultMoq?: number;
  moqUnit?: string;
  weight?: number;
  weightUnit?: string;
  status: "DRAFT" | "ACTIVE" | "INACTIVE" | "ARCHIVED";
  version: number;
  updatedAt: string;
}

export interface ManualProductCreateInput {
  name: string;
  productCode?: string;
  description?: string;
  categoryId?: string;
  defaultUnit: string;
  imageUrl?: string;
  skuCode?: string;
  skuName?: string;
  barcode?: string;
  defaultMoq?: number;
  moqUnit?: string;
  packingQuantity?: number;
  weight?: number;
  weightUnit?: string;
  unitPrice: number;
  currency: string;
  tags: string[];
  publishToStorefront: boolean;
}

export interface SkuListItem {
  id: string;
  skuCode: string;
  sourceSkuCode?: string;
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
  defaultMoq?: number;
  moqUnit?: string;
  packingQuantity?: string;
  publicPrice?: number;
  publicCurrency?: string;
  publicOfferStatus?: "DRAFT" | "PUBLISHED" | "SUSPENDED";
  status: ProductSku["status"];
  version: number;
  updatedAt: string;
  sourceType: "PRODUCT_TEMPLATE" | "LEGACY_IMPORT" | "MANUAL";
  sourceFilename?: string;
  sourceImportedAt?: string;
  imageStatus: "SOURCE" | "APPROVED" | "NONE";
  thumbnailUrl?: string;
  isPinned: boolean;
}

export interface SkuListPage {
  items: SkuListItem[];
  page: number;
  pageSize: number;
  total: number;
  pages: number;
}

export interface ProductListPage {
  items: CoreProduct[];
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
  coverSource: "NONE" | "UPLOAD" | "PRODUCT";
  coverProductId?: string;
  coverProductName?: string;
  coverImageUrl?: string;
  uploadedCoverImageUrl?: string;
  coverProductImageUrl?: string;
  status: string;
  sortOrder: number;
  version: number;
}

export type CatalogShareTargetType = "PRODUCTS" | "CATEGORY";
export type CatalogShareLogoPosition = "NONE" | "TOP_LEFT" | "TOP_RIGHT";

export interface CatalogShare {
  id: string;
  token: string;
  targetType: CatalogShareTargetType;
  title: string;
  itemCount: number;
  categoryId?: string;
  categoryName?: string;
  categoryPath?: string;
  sharePath: string;
  storeName: string;
  storeSubtitle?: string;
  storeLogoUrl?: string;
  logoPosition: CatalogShareLogoPosition;
  createdAt: string;
}

export interface CategoryLayout {
  allProductsPosition: number;
  rootCategoryCount: number;
  categoryShowcaseEnabled: boolean;
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

export interface StorefrontAnalyticsSnapshot {
  generatedAt: string;
  timezone: string;
  startDate: string;
  endDate: string;
  days: number;
  rawIpRetentionDays: number;
  summary: {
    totalViews: number;
    uniqueVisitors: number;
    viewedProducts: number;
    identifiedCountries: number;
  };
  daily: Array<{ date: string; views: number }>;
  countries: Array<{ countryCode: string; views: number; share: number }>;
  products: Array<{
    productId: string;
    skuId: string;
    skuCode: string;
    name: string;
    views: number;
  }>;
  countryProducts: Array<{ countryCode: string; skuId: string; views: number }>;
}

export interface StorefrontProductRankingItem {
  rank: number;
  productId: string;
  productCode?: string;
  name: string;
  categoryId?: string;
  categoryName?: string;
  views: number;
  isPinned: boolean;
  isPopular: boolean;
}

export interface StorefrontProductRankingPage {
  startDate: string;
  endDate: string;
  days: number;
  page: number;
  pageSize: number;
  total: number;
  items: StorefrontProductRankingItem[];
}

export interface PopularCategoryAssignResult {
  categoryId: string;
  categoryName: string;
  selectedCount: number;
  movedCount: number;
  popularProductCount: number;
}

export type AnnouncementDisplayType = "TICKER" | "MODAL";
export type AnnouncementStatus = "DRAFT" | "PUBLISHED" | "PAUSED";
export type AnnouncementBlockType =
  | "heading"
  | "paragraph"
  | "bullet_list"
  | "image"
  | "video"
  | "link";

export interface AnnouncementContentBlock {
  type: AnnouncementBlockType;
  text?: string;
  url?: string;
  alt?: string;
  caption?: string;
}

export interface AnnouncementRelatedSku {
  id: string;
  productId: string;
  skuCode: string;
  name: string;
  productName: string;
  isPublic: boolean;
}

export interface StorefrontAnnouncement {
  id: string;
  title?: string;
  displayType: AnnouncementDisplayType;
  tickerText?: string;
  contentBlocks: AnnouncementContentBlock[];
  startsAt: string;
  endsAt: string;
  tickerSpeedPxPerSecond: number;
  publicationStatus: AnnouncementStatus;
  relatedSkus: AnnouncementRelatedSku[];
  version: number;
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
}

export interface AnnouncementPayload {
  title?: string;
  displayType: AnnouncementDisplayType;
  tickerText?: string;
  contentBlocks: AnnouncementContentBlock[];
  startsAt: string;
  endsAt?: string;
  durationDays?: number;
  tickerSpeedPxPerSecond: number;
  publicationStatus: AnnouncementStatus;
  relatedSkuIds: string[];
}

export interface SupportActionSettings {
  slot: 2 | 3;
  visible: boolean;
  label?: string;
  externalImageUrl?: string;
  imageUrl?: string;
  hasUploadedImage: boolean;
}

export interface SupportSettings {
  welcomeMessage: string;
  customActions: SupportActionSettings[];
}

export type SupportConversationStatus = "OPEN" | "CLOSED";
export type SupportMessageSender = "VISITOR" | "MERCHANT" | "SYSTEM" | "AI";
export type SupportTranslationStatus = "PENDING" | "READY" | "FAILED" | "UNAVAILABLE" | "NOT_REQUIRED";
export type SupportAutomationState = "AI_ACTIVE" | "HUMAN_TAKEOVER";
export type SupportHumanAssistanceState = "NONE" | "OFFERED" | "REQUESTED" | "RESOLVED";

export interface SupportCitation {
  citationNumber: number;
  sourceType: "SKU" | "FILE";
  sourceEntityId: string;
  sourceTitle: string;
  sourceVersion: number;
  classification: "PUBLIC" | "CUSTOMER_APPROVED";
  locator: Record<string, unknown>;
  excerpt: string;
  score: number;
}

export interface SupportMessage {
  id: string;
  senderType: SupportMessageSender;
  body: string;
  draftBody?: string;
  translatedBody?: string;
  translationSourceLocale?: StorefrontLocale;
  translationTargetLocale?: StorefrontLocale;
  translationStatus: SupportTranslationStatus;
  createdAt: string;
  citations: SupportCitation[];
}

export interface SupportTranslationPreview {
  sourceLocale: StorefrontLocale;
  targetLocale: StorefrontLocale;
  originalMessage: string;
  translatedMessage: string;
}

export interface SupportConversationSummary {
  id: string;
  referenceNumber: string;
  visitorName?: string;
  visitorEmail?: string;
  locale: string;
  status: SupportConversationStatus;
  lastMessagePreview: string;
  lastMessageAt: string;
  unread: boolean;
  automationState: SupportAutomationState;
  aiProcessing: boolean;
  humanAssistanceState: SupportHumanAssistanceState;
  humanAssistanceRequestedAt?: string;
}

export interface SupportConversationDetail extends SupportConversationSummary {
  messages: SupportMessage[];
}

export interface SupportConversationPage {
  items: SupportConversationSummary[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
}

export interface SupportHumanRequest {
  conversationId: string;
  referenceNumber: string;
  visitorName?: string;
  visitorEmail?: string;
  locale: string;
  messagePreview: string;
  requestedAt: string;
}

export interface SupportHumanRequestSummary {
  pendingCount: number;
  items: SupportHumanRequest[];
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

export interface HybridSearchEvidence {
  chunkType: string;
  excerpt: string;
}

export interface HybridSearchResult {
  productId: string;
  productCode?: string;
  name: string;
  sourceVersion: number;
  score: number;
  scoreBreakdown: { keyword: number; semantic: number; attribute: number; tag: number; supplier: number };
  supplierSignalStatus: string;
  evidence: HybridSearchEvidence[];
  product?: ProductDetail;
}

export interface HybridSearchResponse {
  query: string;
  degraded: boolean;
  results: HybridSearchResult[];
}

export interface KnowledgeIndexStatus {
  totalProducts: number;
  indexedProducts: number;
  pendingProducts: number;
  mode?: "INCREMENTAL" | "FULL_REBUILD";
  processedProducts?: number;
  embeddings?: number;
}

export type KnowledgeIndexJobStatus = "QUEUED" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED";

export interface KnowledgeIndexJob {
  id: string;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: KnowledgeIndexJobStatus;
  totalProducts: number;
  processedProducts: number;
  failedProducts: number;
  embeddings: number;
  remainingProducts: number;
  progressPercent: number;
  currentProductId?: string;
  currentProductName?: string;
  errorMessage?: string;
  pauseRequested: boolean;
  pauseRequestedAt?: string;
  pausedAt?: string;
  resumable: boolean;
  checkpointAt?: string;
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
  maxRetryCount: number;
  apiKeyConfigured: boolean;
  apiKeyHint?: string;
  updatedAt?: string;
  modelChanged: boolean;
  clearedProductEmbeddings: number;
  clearedFileEmbeddings: number;
  invalidatedProducts: number;
}

export interface SupportAIProviderSettings {
  id?: string;
  configurationName?: string;
  displayModelName?: string;
  source: "database" | "environment" | "disabled";
  provider: string;
  enabled: boolean;
  baseUrl?: string;
  modelName?: string;
  timeoutSeconds: number;
  maxOutputTokens: number;
  temperature: number;
  apiKeyConfigured: boolean;
  apiKeyHint?: string;
  updatedAt?: string;
}

export interface SupportAIStoreConfiguration {
  tenantId: string;
  tenantName: string;
  organizationId: string;
  enabled: boolean;
  providerProfileId?: string;
  modelDisplayName?: string;
  updatedAt?: string;
}

export interface SupportAIAgentStore {
  tenantId: string;
  tenantName: string;
}

export interface SupportAIAgent {
  id: string;
  agentCode: string;
  name: string;
  description?: string;
  enabled: boolean;
  providerProfileId?: string;
  modelDisplayName?: string;
  apiConfigured: boolean;
  skuKnowledgeEnabled: boolean;
  fileKnowledgeEnabled: boolean;
  multilingualEnabled: boolean;
  minRetrievalScore: number;
  minAnswerConfidence: number;
  maxSources: number;
  dailyAutoReplyLimit: number;
  publicCompanyIntroduction?: string;
  publicServiceScope?: string;
  systemPrompt?: string;
  handoffMessages: Record<string, string>;
  stores: SupportAIAgentStore[];
  knowledgeSourceCount: number;
  approvedKnowledgeSourceCount: number;
  createdAt: string;
  updatedAt: string;
}

export type SupportAITrainingStatus = "DRAFT" | "APPROVED" | "ARCHIVED";
export type SupportAITrainingResponseAction = "ANSWER" | "CLARIFY" | "HANDOFF";
export type SupportAITrainingGroundingMode = "EVIDENCE" | "GENERAL_GUIDANCE" | "APPROVED_COMPANY_PROFILE";

export interface SupportAITrainingCase {
  id: string;
  agentId: string;
  externalId: string;
  sourceTenantId?: string;
  title: string;
  language: string;
  customerMessage: string;
  idealResponse: string;
  responseAction: SupportAITrainingResponseAction;
  groundingMode: SupportAITrainingGroundingMode;
  behaviorNotes?: string;
  requiredEvidenceTypes: string[];
  tags: string[];
  forbiddenPatterns: string[];
  sourceType: "MANUAL" | "PRODUCT_GENERATED" | "CONVERSATION_CORRECTION" | "IMPORT";
  status: SupportAITrainingStatus;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
}

export interface SupportAITrainingRule {
  id: string;
  agentId: string;
  ruleKey: string;
  title: string;
  instruction: string;
  scopes: string[];
  sourceCaseIds: string[];
  priority: number;
  status: SupportAITrainingStatus;
  createdAt: string;
  updatedAt: string;
}

export interface SupportAITrainingVersion {
  id: string;
  agentId: string;
  versionNumber: number;
  status: "PUBLISHED" | "RETIRED";
  packageHash: string;
  compiledPrompt: string;
  caseCount: number;
  ruleCount: number;
  releaseNotes?: string;
  publishedAt: string;
  activatedAt: string;
  retiredAt?: string;
}

export interface SupportAITrainingOverview {
  agentId: string;
  cases: SupportAITrainingCase[];
  rules: SupportAITrainingRule[];
  versions: SupportAITrainingVersion[];
  activeVersionId?: string;
  activeVersionNumber?: number;
  draftCaseCount: number;
  approvedCaseCount: number;
  draftRuleCount: number;
  approvedRuleCount: number;
}

export interface SupportAISettings {
  enabled: boolean;
  skuKnowledgeEnabled: boolean;
  fileKnowledgeEnabled: boolean;
  multilingualEnabled: boolean;
  minRetrievalScore: number;
  minAnswerConfidence: number;
  maxSources: number;
  dailyAutoReplyLimit: number;
  publicCompanyIntroduction?: string;
  publicServiceScope?: string;
  systemPrompt?: string;
  handoffMessages: Record<string, string>;
  promptVersion: number;
  modelDisplayName?: string;
  approvedFileSources: number;
  indexedSkuProducts: number;
  updatedAt?: string;
}

export type SupportAIKnowledgeStatus = "PROCESSING" | "READY" | "APPROVED" | "REVOKED" | "FAILED";

export interface SupportAIKnowledgeSource {
  id: string;
  title: string;
  description?: string;
  classification: "PUBLIC" | "CUSTOMER_APPROVED";
  language: string;
  status: SupportAIKnowledgeStatus;
  originalFilename: string;
  contentType?: string;
  sha256: string;
  byteSize: number;
  chunkCount: number;
  version: number;
  failureCode?: string;
  failureMessage?: string;
  approvedAt?: string;
  createdAt: string;
  updatedAt: string;
}

export interface SupportAIIngestionJob {
  id: string;
  sourceId: string;
  status: "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";
  progress: number;
  parserIdentifier?: string;
  parserVersion?: string;
  chunksWritten: number;
  errorCode?: string;
  errorMessage?: string;
  startedAt?: string;
  completedAt?: string;
  createdAt: string;
}

export interface SupportAIAgentKnowledgeSource {
  tenantId: string;
  tenantName: string;
  source: SupportAIKnowledgeSource;
}

export interface SupportAIAgentKnowledgeUploadItem extends SupportAIAgentKnowledgeSource {
  job: SupportAIIngestionJob;
}

export type SupportAIRunStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "NEEDS_REVIEW" | "HANDOFF" | "FAILED" | "CANCELLED" | "SKIPPED";

export interface SupportAIRun {
  id: string;
  aiTaskId: string;
  conversationId?: string;
  inputMessageId?: string;
  outputMessageId?: string;
  triggerType: "CHAT" | "TEST";
  enabledSnapshot: boolean;
  status: SupportAIRunStatus;
  question: string;
  visitorLocale: string;
  detectedLanguage?: string;
  normalizedQuery?: string;
  answer?: string;
  confidence?: number;
  handoffReason?: string;
  modelDisplayName?: string;
  promptVersion: number;
  trainingVersionId?: string;
  trainingCaseIds: string[];
  retrievalCount: number;
  decisionTrace: Record<string, unknown>;
  errorCode?: string;
  errorMessage?: string;
  evidence: SupportCitation[];
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

export interface SupportAIRunPage {
  items: SupportAIRun[];
  total: number;
  page: number;
  pageSize: number;
  pages: number;
}

export type TranslationReasoningEffort =
  | "none"
  | "minimal"
  | "low"
  | "medium"
  | "high";

export type TranslationProviderKind =
  | "openai-compatible"
  | "aliyun-alimt";

export interface TranslationApiSettings {
  source: "database" | "environment" | "disabled";
  provider: TranslationProviderKind | "deeplx";
  enabled: boolean;
  baseUrl?: string;
  modelName?: string;
  regionId?: string;
  timeoutSeconds: number;
  maxTokens: number;
  requestsPerMinute: number;
  maxRetryCount: number;
  catalogBatchSize: number;
  catalogBatchCharacters: number;
  reasoningEffort: TranslationReasoningEffort;
  apiKeyConfigured: boolean;
  apiKeyHint?: string;
  accessKeyIdConfigured: boolean;
  accessKeyIdHint?: string;
  updatedAt?: string;
}

export interface TranslationApiTestResult {
  provider: string;
  modelName: string;
  latencyMs: number;
  translatedText: string;
}

export type CatalogTranslationJobStage =
  | "QUEUED"
  | "PREPARING"
  | "TRANSLATING"
  | "PACKAGING"
  | "UPLOADING"
  | "PAUSED"
  | "PUBLISHED"
  | "FAILED";

export interface CatalogLanguagePackInfo {
  sourceLocale: StorefrontLocale;
  targetLocale: StorefrontLocale;
  version: number;
  downloadUrl: string;
  contentSha256: string;
  byteSize: number;
  productCount: number;
  skuCount: number;
  categoryCount: number;
  sourceCutoffAt: string;
  publishedAt: string;
  lastFullTranslationAt?: string;
}

export interface CatalogTranslationJob {
  id: string;
  sourceLocale: StorefrontLocale;
  targetLocale: StorefrontLocale;
  mode: "INCREMENTAL" | "FULL_REBUILD";
  status: "QUEUED" | "RUNNING" | "PAUSED" | "SUCCEEDED" | "FAILED";
  stage: CatalogTranslationJobStage;
  totalSkus: number;
  processedSkus: number;
  failedSkus: number;
  remainingSkus: number;
  progressPercent: number;
  currentSkuId?: string;
  currentSkuName?: string;
  failureDetails: Array<{
    skuId?: string;
    skuCode?: string;
    name?: string;
    message: string;
  }>;
  errorMessage?: string;
  packageVersion?: number;
  packagePublished: boolean;
  packageByteSize?: number;
  sourceCutoffAt?: string;
  pauseRequested: boolean;
  pauseRequestedAt?: string;
  pausedAt?: string;
  resumable: boolean;
  checkpointAt?: string;
  createdAt: string;
  startedAt?: string;
  completedAt?: string;
}

export interface CatalogTranslationStatus {
  sourceLocale: StorefrontLocale;
  targetLocale: StorefrontLocale;
  providerConfigured: boolean;
  totalSkus: number;
  translatedSkus: number;
  staleSkus: number;
  pendingSkus: number;
  packageOutdated: boolean;
  packageStorageConfigured: boolean;
  availableLocales: StorefrontLocale[];
  package?: CatalogLanguagePackInfo;
  latestJob?: CatalogTranslationJob;
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
  specification?: string;
  optionValues: Record<string, unknown>;
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
  locale: StorefrontLocale;
  currency: string;
  subtotal: number;
  total: number;
  validUntil: string;
  createdAt: string;
  updatedAt: string;
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
  locale: StorefrontLocale;
  currency: string;
  total: number;
  validUntil: string;
  createdAt: string;
  updatedAt: string;
}

export interface StorefrontOrderCurrencyStatistics {
  currency: string;
  totalAmount: number;
  completedAmount: number;
  orderCount: number;
}

export interface StorefrontOrderPeriodStatistics {
  startAt: string;
  endAt: string;
  orderCount: number;
  completedOrderCount: number;
  cancelledOrderCount: number;
  amounts: StorefrontOrderCurrencyStatistics[];
}

export interface StorefrontOrderStatistics {
  timezone: string;
  currentMonth: StorefrontOrderPeriodStatistics;
  currentYear: StorefrontOrderPeriodStatistics;
}

export type QuoteTemplateField =
  | "serial_number"
  | "sku_code"
  | "product_name"
  | "description"
  | "specification"
  | "category"
  | "tags"
  | "product_image"
  | "quantity"
  | "unit_code"
  | "packing_quantity"
  | "carton_dimensions"
  | "gross_weight"
  | "carton_volume"
  | "unit_price"
  | "line_total"
  | "total_volume"
  | "total_gross_weight"
  | "currency"
  | "quote_number"
  | "quote_date"
  | "customer_name"
  | "customer_company"
  | "customer_email"
  | "customer_phone"
  | "notes";

export interface QuoteExcelColumn {
  key: string;
  index: number;
  header: string;
  samples: string[];
  suggestedField?: QuoteTemplateField;
  mappedField?: QuoteTemplateField;
}

export interface QuoteExcelTemplate {
  id: string;
  name: string;
  originalFilename: string;
  byteSize: number;
  sheetNames: string[];
  sheetName: string;
  headerRow: number;
  dataStartRow: number;
  dataEndRow: number;
  columns: QuoteExcelColumn[];
  columnMappings: Partial<Record<string, QuoteTemplateField>>;
  isDefault: boolean;
  isReady: boolean;
  version: number;
  createdAt: string;
  updatedAt: string;
}

export interface QuoteExcelTemplateUpdate {
  name: string;
  columnMappings: Partial<Record<string, QuoteTemplateField>>;
  isDefault: boolean;
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
