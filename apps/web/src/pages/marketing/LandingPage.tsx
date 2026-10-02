import {
  ArrowRight,
  ArrowDown,
  Buildings,
  Check,
  CheckCircle,
  CubeFocus,
  FilePdf,
  FileXls,
  List,
  MagnifyingGlass,
  Package,
  ShieldCheck,
  Tag,
  UploadSimple,
  X,
  Coffee,
  Handbag,
  Lamp,
  GlobeHemisphereWest,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { BRAND_FULL_NAME } from "../../brand";
import { Brand } from "../../components/Brand";
import { ThemeToggle } from "../../components/ThemeToggle";
import { CloudShader } from "../../components/ui/CloudShader";
import { useThemeMode } from "../../context/ThemeContext";
import publicStyles from "../PublicPage.module.css";
import styles from "./LandingPage.module.css";

const workflow = [
  {
    icon: UploadSimple,
    title: "归整商品资料",
    description:
      "将 SKU、规格、图片、价格与标签放进同一份商品底稿，让团队围绕一致的信息开展工作。",
    tag: "Excel 商品模板",
  },
  {
    icon: MagnifyingGlass,
    title: "找到合适的商品",
    description:
      "从名称、类目和标签检索到 AI 匹配，把客户需求与企业自己的商品库联系起来。",
    tag: "检索与询盘匹配",
  },
  {
    icon: FilePdf,
    title: "交付清晰的报价",
    description:
      "选定商品、数量与价格，经人工确认后生成报价，导出 PDF 或 Excel 继续交付。",
    tag: "人工确认 · 版本化报价",
  },
];

const pricingPlans = [
  {
    id: "standard",
    code: "ATC / 01",
    name: "基础档",
    englishName: "Standard",
    billing: "年度订阅",
    price: "¥2,980",
    audience: "适合需要快速建立数字化产品图册的团队",
    recommended: false,
    features: [
      "AI 产品库向量化搜索",
      "在线询价：人工手动回复",
      "最多 2 个子账号",
      "多语言图册",
      "AI 智能图册（H5）",
    ],
  },
  {
    id: "silver",
    code: "ATC / 02",
    name: "专业版",
    englishName: "Professional",
    billing: "年度订阅",
    price: "¥4,980",
    audience: "适合需要 AI 询价与供应链协同的成长型团队",
    recommended: true,
    features: [
      "AI 产品库向量化搜索",
      "在线询价：AI 自动回复（训练企业资料、SKU 与政策知识）",
      "AI 智能图册（H5）",
      "多语言图册",
      "最多 4 个子账号",
      "AI 外贸单证工作台",
      "供应链管理",
      "AI 智能数据分析与报告",
      "优先技术支持",
    ],
  },
  {
    id: "elite",
    code: "ATC / 03",
    name: "企业版",
    englishName: "Enterprise",
    billing: "年度订阅",
    price: "¥9,800",
    audience: "适合需要完整外贸智能化能力的规模化团队",
    recommended: false,
    features: [
      "AI 产品库向量化搜索",
      "在线询价：AI 自动回复（训练企业资料、SKU 与政策知识）",
      "AI 智能图册（H5）",
      "多语言图册",
      "最多 10 个子账号",
      "AI 外贸单证工作台",
      "最优先技术支持",
      "智能进销存库存管理系统",
      "AI 智能数据分析与报告",
      "AI 智能拓客",
    ],
  },
] as const;

const configuredStorefrontSlug = String(
  import.meta.env.VITE_PRIMARY_STOREFRONT_SLUG || "demo",
)
  .normalize("NFKC")
  .trim()
  .toLocaleLowerCase();
const primaryStorefrontSlug =
  configuredStorefrontSlug &&
  [...configuredStorefrontSlug].length <= 80 &&
  !/[/?#]/.test(configuredStorefrontSlug)
    ? configuredStorefrontSlug
    : "demo";
const primaryStorefrontPath = `/${primaryStorefrontSlug}`;

function ProductWorkflow() {
  return (
    <div className={styles.visual} data-hero-visual>
      <div className={styles.visualLabel}>
        <span>FROM CATALOG TO QUOTATION</span>
        <span>示例工作流 / 非真实业务数据</span>
      </div>
      <div className={styles.workspace}>
        <div className={styles.workspaceTop}>
          <CubeFocus size={19} />
          <strong>AI Trade Cloud</strong>
          <span>商品与报价工作台</span>
        </div>
        <div className={styles.workspaceBody}>
          <div data-flow-step>
            <div className={styles.stepLabel}>
              <Package size={16} />
              <span>01</span> 商品资料库
            </div>
            <div className={styles.productList}>
              {[
                { icon: Handbag, name: "轻量通勤包", sku: "SKU-DEMO-01" },
                { icon: Lamp, name: "桌面阅读灯", sku: "SKU-DEMO-02" },
                { icon: Coffee, name: "不锈钢随行杯", sku: "SKU-DEMO-03" },
              ].map(({ icon: Icon, name, sku }) => (
                <div className={styles.product} key={sku}>
                  <div className={styles.productArt}>
                    <Icon weight="duotone" />
                  </div>
                  <strong>{name}</strong>
                  <small>{sku}</small>
                </div>
              ))}
            </div>
          </div>
          <div className={styles.connector} aria-hidden="true">
            <ArrowDown size={14} /> 需求连接商品
          </div>
          <div className={styles.searchPanel} data-flow-step>
            <div className={styles.stepLabel}>
              <MagnifyingGlass size={16} />
              <span>02</span> 智能匹配
            </div>
            <div className={styles.searchQuery}>
              <MagnifyingGlass size={15} /> 寻找适合商务礼赠的不锈钢随行杯
            </div>
            <div className={styles.searchResult}>
              <span>商品资料 → 检索结果 → 人工选择</span>
              <strong>
                <CheckCircle size={13} /> 已选定商品
              </strong>
            </div>
          </div>
          <div className={styles.connector} aria-hidden="true">
            <ArrowDown size={14} /> 确认数量与价格
          </div>
        </div>
        <div className={styles.quote} data-flow-step>
          <FilePdf size={26} weight="duotone" />
          <div>
            <strong>03 / 生成报价单</strong>
            <small>人工确认后，导出并交付客户</small>
          </div>
          <div className={styles.quoteBadge}>
            <span>PDF</span>
            <span>EXCEL</span>
          </div>
        </div>
      </div>
      <div className={styles.visualCaption}>
        <ShieldCheck size={14} /> 企业自己的资料，连起每一步业务。
      </div>
    </div>
  );
}

export function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [cloudsPaused, setCloudsPaused] = useState(false);
  const { mode } = useThemeMode();
  const pageRef = useRef<HTMLDivElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${BRAND_FULL_NAME} | 从商品资料到客户报价`;
    return () => {
      document.title = previousTitle;
    };
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMenuOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    const closeOnDesktop = () => {
      if (window.innerWidth > 900) setMenuOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    window.addEventListener("resize", closeOnDesktop);
    return () => {
      window.removeEventListener("keydown", closeOnEscape);
      window.removeEventListener("resize", closeOnDesktop);
    };
  }, [menuOpen]);

  useEffect(() => {
    let disposed = false;
    let cleanup: (() => void) | undefined;
    // Content is visible by default; unavailable animation code never blocks it.
    void Promise.all([import("gsap"), import("gsap/ScrollTrigger")])
      .then(([{ gsap }, { ScrollTrigger }]) => {
        if (disposed || !pageRef.current) return;
        gsap.registerPlugin(ScrollTrigger);
        const media = gsap.matchMedia();
        cleanup = () => media.revert();
        media.add("(prefers-reduced-motion: no-preference)", () => {
          const context = gsap.context(() => {
            gsap
              .timeline({ defaults: { duration: 0.7, ease: "power2.out" } })
              .from("[data-hero-copy] > *", {
                y: 18,
                opacity: 0,
                stagger: 0.07,
              })
              .from("[data-hero-visual]", { y: 24, opacity: 0 }, 0.18)
              .from(
                "[data-flow-step]",
                { y: 10, opacity: 0, stagger: 0.16 },
                0.5,
              );
            pageRef.current
              ?.querySelectorAll("[data-reveal]")
              .forEach((element) => {
                gsap.from(element, {
                  y: 22,
                  opacity: 0,
                  duration: 0.65,
                  ease: "power2.out",
                  immediateRender: false,
                  scrollTrigger: {
                    trigger: element,
                    start: "top 92%",
                    once: true,
                  },
                });
              });
          }, pageRef);
          return () => context.revert();
        });
      })
      .catch(() => cleanup?.());
    return () => {
      disposed = true;
      cleanup?.();
    };
  }, []);

  const closeMenu = () => setMenuOpen(false);
  return (
    <div className={publicStyles.page} ref={pageRef}>
      <a className={styles.skipLink} href="#main-content">
        跳到正文
      </a>
      <header className={styles.header}>
        <div className={`${styles.shell} ${styles.headerInner}`}>
          <Brand subtitle="AI TRADE CLOUD" />
          <nav className={styles.desktopNav} aria-label="官网主导航">
            <a href="#product">产品</a>
            <a href="#workflow">工作流程</a>
            <a href="#capabilities">核心能力</a>
            <a href="#pricing">服务方案</a>
            <a href="#merchants">商家入口</a>
          </nav>
          <div className={styles.headerActions}>
            <ThemeToggle />
            <Link className={styles.headerLogin} to="/login">
              登录工作台 <ArrowRight size={12} />
            </Link>
            <button
              ref={menuButtonRef}
              className={styles.menuButton}
              type="button"
              aria-label={menuOpen ? "关闭导航" : "打开导航"}
              aria-expanded={menuOpen}
              aria-controls="mobile-marketing-nav"
              onClick={() => setMenuOpen(!menuOpen)}
            >
              {menuOpen ? <X size={20} /> : <List size={20} />}
            </button>
          </div>
          <nav
            id="mobile-marketing-nav"
            className={`${styles.mobileNav} ${menuOpen ? styles.mobileNavOpen : ""}`}
            aria-label="移动端官网导航"
          >
            <a href="#product" onClick={closeMenu}>
              产品
            </a>
            <a href="#workflow" onClick={closeMenu}>
              工作流程
            </a>
            <a href="#capabilities" onClick={closeMenu}>
              核心能力
            </a>
            <a href="#pricing" onClick={closeMenu}>
              服务方案
            </a>
            <a href="#merchants" onClick={closeMenu}>
              商家入口
            </a>
            <Link to="/login" onClick={closeMenu}>
              登录工作台
            </Link>
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1}>
        <section
          className={styles.hero}
          id="product"
          aria-labelledby="hero-title"
        >
          <div className={styles.cloudBackground} aria-hidden="true">
            <CloudShader
              speed={0.18}
              count={4}
              paused={cloudsPaused}
              cloudColor={mode === "dark" ? "#345c6b" : "#c4dbe2"}
              skyTopColor={mode === "dark" ? "#080f1a" : "#f5f8fa"}
              skyBottomColor={mode === "dark" ? "#122b3b" : "#e9f2f3"}
            />
          </div>
          <div className={`${styles.shell} ${styles.heroGrid}`}>
            <div className={styles.heroCopy} data-hero-copy>
              <div className={styles.eyebrow}>
                <i aria-hidden="true" /> 面向外贸团队的商品与报价平台
              </div>
              <h1 id="hero-title">
                让商品资料，
                <br />
                成为下一份
                <br />
                <span>好报价。</span>
              </h1>
              <p className={styles.heroLead}>
                归整商品、匹配需求、确认报价。智贸云将分散的资料连成清晰的业务流程，让团队把时间用在客户身上。
              </p>
              <div className={styles.heroActions}>
                <Link className={publicStyles.primary} to="/login">
                  进入工作台 <ArrowRight size={17} />
                </Link>
                <a className={publicStyles.secondary} href="#workflow">
                  了解工作流程 <ArrowDown size={16} />
                </a>
              </div>
              <div className={styles.heroDetails}>
                <p className={styles.heroNote}>
                  商品库 / AI 检索 / 询盘匹配 / 报价交付
                </p>
                <button
                  className={styles.cloudControl}
                  type="button"
                  aria-pressed={cloudsPaused}
                  onClick={() => setCloudsPaused((value) => !value)}
                >
                  {cloudsPaused ? "继续云效" : "暂停云效"}
                </button>
              </div>
            </div>
            <ProductWorkflow />
          </div>
          <div className={`${styles.shell} ${styles.facts}`}>
            <div>
              <Buildings size={20} /> 企业资料与账号按租户管理
            </div>
            <div>
              <GlobeHemisphereWest size={20} /> 多语言商品前台
            </div>
            <div>
              <FileXls size={20} /> PDF 与 Excel 报价导出
            </div>
          </div>
        </section>
        <section
          className={styles.section}
          id="workflow"
          aria-labelledby="workflow-title"
        >
          <div className={styles.shell}>
            <div className={styles.workflowIntro} data-reveal>
              <div className={styles.workflowCopy}>
                <span className={publicStyles.kicker}>
                  01 / A CONNECTED WORKFLOW
                </span>
                <h2 id="workflow-title">
                  多件商品，
                  <br />
                  汇成一份客户报价。
                </h2>
                <p>
                  将选定的商品、数量与价格汇入同一份报价，经人工确认后交付客户。让检索、选择和报价围绕一致的商品资料展开。
                </p>
              </div>
              <figure className={styles.workflowArt}>
                <img
                  src="/assets/marketing/workflow-products-to-quotation.webp"
                  width={1536}
                  height={1024}
                  loading="lazy"
                  decoding="async"
                  alt="多种商品通过连线汇聚到同一份报价单的流程示意图"
                />
                <figcaption>
                  多件商品 → 一份报价 <span>流程示意 · 非真实报价</span>
                </figcaption>
              </figure>
            </div>
            <div className={styles.workflowGrid}>
              {workflow.map(
                ({ icon: Icon, title, description, tag }, index) => (
                  <article
                    className={styles.workflowItem}
                    data-reveal
                    key={title}
                  >
                    <div className={styles.workflowMeta}>
                      <span>STEP / 0{index + 1}</span>
                      <Icon size={25} weight="duotone" />
                    </div>
                    <h3>{title}</h3>
                    <p>{description}</p>
                    <span className={styles.workflowTag}>
                      <Check size={13} />
                      {tag}
                    </span>
                  </article>
                ),
              )}
            </div>
          </div>
        </section>
        <section
          className={styles.section}
          id="capabilities"
          aria-labelledby="capabilities-title"
        >
          <div className={styles.shell}>
            <div className={styles.sectionHeading} data-reveal>
              <div>
                <span className={publicStyles.kicker}>
                  02 / BUILT FOR YOUR BUSINESS
                </span>
                <h2 id="capabilities-title">资料有序，业务才有章法。</h2>
              </div>
              <p>让商品展示、需求匹配与团队协作建立在企业自己的资料之上。</p>
            </div>
            <div className={styles.capabilities}>
              <div className={styles.capabilityIntro} data-reveal>
                <CubeFocus size={40} weight="duotone" />
                <h3>
                  商品信息，
                  <br />
                  始终是业务的起点。
                </h3>
                <p>
                  SKU、规格、图片、价格与标签集中维护。从内部工作台到对外商品前台，让信息沿着清楚的路径流转。
                </p>
                <Link to={primaryStorefrontPath}>
                  查看商品前台 <ArrowRight size={17} />
                </Link>
              </div>
              <div className={styles.featureRows} data-reveal>
                {[
                  {
                    icon: Tag,
                    title: "结构化商品库",
                    text: "使用固定 Excel 模板维护商品，按类目、标签和规格组织资料。",
                  },
                  {
                    icon: MagnifyingGlass,
                    title: "检索与询盘匹配",
                    text: "结合商品资料寻找合适的候选商品，由业务人员确认最终选择。",
                  },
                  {
                    icon: GlobeHemisphereWest,
                    title: "多语言商品展示",
                    text: "让客户通过商家专属商品前台查看产品，并继续询价。",
                  },
                  {
                    icon: FilePdf,
                    title: "可交付的版本化报价",
                    text: "确认数量与价格后生成报价，支持 PDF 和 Excel 导出。",
                  },
                ].map(({ icon: Icon, title, text }) => (
                  <article className={styles.featureRow} key={title}>
                    <Icon size={23} weight="duotone" />
                    <div>
                      <h3>{title}</h3>
                      <p>{text}</p>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </div>
        </section>
        <section
          className={styles.section}
          id="pricing"
          aria-labelledby="pricing-title"
        >
          <div className={styles.shell}>
            <div className={styles.sectionHeading} data-reveal>
              <div>
                <span className={publicStyles.kicker}>
                  03 / PLANS FOR YOUR NEXT STEP
                </span>
                <h2 id="pricing-title">选择适合团队的服务方案。</h2>
              </div>
              <p>
                从建立数字商品库开始，按团队所需选择智能检索、协作与业务模块。
              </p>
            </div>
            <div className={styles.pricingGrid}>
              {pricingPlans.map((plan) => (
                <article
                  className={`${styles.pricingCard} ${plan.recommended ? styles.recommended : ""}`}
                  data-reveal
                  key={plan.id}
                  aria-labelledby={`pricing-${plan.id}`}
                >
                  <div className={styles.pricingMeta}>
                    <span>{plan.code}</span>
                    {plan.recommended ? (
                      <strong>推荐方案</strong>
                    ) : (
                      <span>年度订阅</span>
                    )}
                  </div>
                  <h3 id={`pricing-${plan.id}`}>{plan.name}</h3>
                  <span className={styles.pricingEnglish}>
                    {plan.englishName}
                  </span>
                  <div className={styles.pricingAmount}>
                    <strong>{plan.price}</strong>
                    <span>/ 年</span>
                  </div>
                  <p className={styles.pricingAudience}>{plan.audience}</p>
                  <ul className={styles.pricingFeatures}>
                    {plan.features.map((feature) => (
                      <li key={feature}>
                        <Check size={14} />
                        {feature}
                      </li>
                    ))}
                  </ul>
                  <Link
                    className={
                      plan.recommended
                        ? publicStyles.primary
                        : publicStyles.secondary
                    }
                    to="/login"
                    aria-label={`${plan.name}：进入工作台`}
                  >
                    进入工作台 <ArrowRight size={16} />
                  </Link>
                </article>
              ))}
            </div>
            <p className={styles.pricingDisclaimer}>
              价格为年度服务费 · 具体交付范围以服务协议为准 ·
              登录入口不代表购买或升级套餐
            </p>
          </div>
        </section>
        <section
          className={styles.section}
          id="merchants"
          aria-labelledby="merchant-title"
        >
          <div className={`${styles.shell} ${styles.merchant}`} data-reveal>
            <div>
              <span className={publicStyles.kicker}>
                04 / YOUR OWN STOREFRONT
              </span>
              <h2 id="merchant-title">
                让客户找到
                <br />
                你的商品世界。
              </h2>
              <p>
                品牌官网与商家商品前台各司其职。每家商家拥有自己的访问路径，连接商品展示与客户询价。
              </p>
              <Link
                className={publicStyles.secondary}
                to={primaryStorefrontPath}
              >
                查看商品前台 <ArrowRight size={16} />
              </Link>
            </div>
            <div className={styles.routePanel}>
              <span>MERCHANT STOREFRONT / 路径示意</span>
              <div className={styles.routeExample}>
                <span>yourdomain.com/</span>
                <strong>merchant</strong>
              </div>
              <p>专属商家路径 · 多语言展示 · 独立工作台</p>
            </div>
          </div>
        </section>
        <section className={styles.cta} data-reveal>
          <div className={styles.shell}>
            <span className={publicStyles.kicker}>
              LESS SEARCHING. MORE BUSINESS.
            </span>
            <h2>
              从整理商品开始，
              <br />
              把下一步交给清晰的流程。
            </h2>
            <p>让团队在同一份资料上完成选择、确认与交付。</p>
            <Link className={publicStyles.primary} to="/login">
              进入智贸云工作台 <ArrowRight size={17} />
            </Link>
          </div>
        </section>
      </main>
      <footer className={styles.footer}>
        <div className={`${styles.shell} ${styles.footerInner}`}>
          <Brand subtitle="AI TRADE CLOUD" />
          <nav aria-label="页脚导航">
            <a href="#product">产品</a>
            <a href="#workflow">流程</a>
            <a href="#pricing">服务方案</a>
            <Link to={primaryStorefrontPath}>商品前台</Link>
            <Link to="/login">登录</Link>
            <Link to="/privacy">隐私政策</Link>
            <a href="/licenses/Noto-CJK-OFL.txt">字体许可</a>
          </nav>
          <small>
            © {new Date().getFullYear()} {BRAND_FULL_NAME}
          </small>
        </div>
      </footer>
    </div>
  );
}
