import {
  ArrowRight,
  Buildings,
  CheckCircle,
  FilePdf,
  FileXls,
  List,
  MagnifyingGlass,
  Package,
  ShieldCheck,
  ShoppingCartSimple,
  Tag,
  UploadSimple,
  X,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Brand } from "../../components/Brand";
import styles from "./LandingPage.module.css";

function Reveal({ children, className = "" }: { children: ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -48px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={`${styles.reveal} ${visible ? styles.revealVisible : ""} ${className}`}>
      {children}
    </div>
  );
}

const workflow = [
  {
    icon: UploadSimple,
    title: "让商品归于一处",
    description: "一张表格，便能把 SKU、规格、图片、价格与标签带回同一份商品底稿。",
  },
  {
    icon: MagnifyingGlass,
    title: "让所需循迹而来",
    description: "名称、类目与标签彼此照应，缩短从模糊需求到合适商品的距离。",
  },
  {
    icon: ShoppingCartSimple,
    title: "让选择落在纸上",
    description: "选中的商品与数量自然进入报价，生成 PDF 或 Excel，继续抵达客户。",
  },
];

const configuredStorefrontSlug = String(
  import.meta.env.VITE_PRIMARY_STOREFRONT_SLUG || "demo",
).trim().toLowerCase();
const primaryStorefrontSlug = /^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$/.test(
  configuredStorefrontSlug,
) ? configuredStorefrontSlug : "demo";
const primaryStorefrontPath = `/${primaryStorefrontSlug}`;

export function LandingPage() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [headerElevated, setHeaderElevated] = useState(false);
  const heroRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = "澄湾选品 | 万千货品，自成脉络";
    return () => {
      document.title = previousTitle;
    };
  }, []);

  useEffect(() => {
    const hero = heroRef.current;
    if (!hero) return;

    let observer: IntersectionObserver | undefined;

    const observeHeroBoundary = () => {
      observer?.disconnect();
      const headerHeight = window.innerWidth <= 760 ? 72 : 80;

      observer = new IntersectionObserver(
        ([entry]) => setHeaderElevated(!entry.isIntersecting),
        { threshold: 0, rootMargin: `-${headerHeight}px 0px 0px 0px` },
      );
      observer.observe(hero);
    };

    observeHeroBoundary();
    window.addEventListener("resize", observeHeroBoundary);

    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", observeHeroBoundary);
    };
  }, []);

  const closeMenu = () => setMenuOpen(false);

  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#main-content">跳到正文</a>

      <header className={`${styles.header} ${headerElevated || menuOpen ? styles.headerGlass : ""}`}>
        <div className={`${styles.shell} ${styles.headerInner}`}>
          <Brand subtitle="万千货品，自成脉络" />
          <nav className={styles.desktopNav} aria-label="官网主导航">
            <a href="#product">产品</a>
            <a href="#workflow">流程</a>
            <a href="#capabilities">能力</a>
            <a href="#merchants">商家入口</a>
          </nav>
          <div className={styles.headerActions}>
            <Link className={styles.headerLogin} to="/login">登录工作台</Link>
            <button
              className={styles.menuButton}
              type="button"
              aria-label={menuOpen ? "关闭导航" : "打开导航"}
              aria-expanded={menuOpen}
              aria-controls="mobile-marketing-nav"
              onClick={() => setMenuOpen((current) => !current)}
            >
              {menuOpen ? <X size={22} /> : <List size={22} />}
            </button>
          </div>

          <nav
            id="mobile-marketing-nav"
            className={`${styles.mobileNav} ${menuOpen ? styles.mobileNavOpen : ""}`}
            aria-label="移动端官网导航"
          >
            <a href="#product" onClick={closeMenu}>产品</a>
            <a href="#workflow" onClick={closeMenu}>流程</a>
            <a href="#capabilities" onClick={closeMenu}>能力</a>
            <a href="#merchants" onClick={closeMenu}>商家入口</a>
            <Link to="/login" onClick={closeMenu}>登录工作台</Link>
          </nav>
        </div>
      </header>

      <main id="main-content">
        <section ref={heroRef} className={styles.hero}>
          <img
            className={styles.heroBackdrop}
            src="/assets/marketing/hero-product-universe-spacious.jpg"
            alt="多品类商品汇聚到数字选品工作台的场景"
            width="1672"
            height="941"
            fetchPriority="high"
          />
          <div className={`${styles.shell} ${styles.heroInner}`}>
            <div className={styles.heroCopy}>
              <span className={styles.eyebrow}>商品资料与报价工作台</span>
              <h1>
                <span className={styles.heroTitleLine}>让每一件商品，</span>
                <span className={styles.heroTitleLine}>都有<em>抵达</em><span className={styles.keepTogether}>客户</span>的路。</span>
              </h1>
              <p className={styles.heroLead}>
                收拢散落的 SKU 资料，串起查找、选择与报价，让每一次客户回应更从容。
              </p>
              <div className={styles.heroActions}>
                <Link className={styles.primaryButton} to={primaryStorefrontPath}>
                  查看商品前台 <ArrowRight size={18} weight="bold" />
                </Link>
                <Link className={styles.secondaryButton} to="/login">登录工作台</Link>
              </div>
            </div>
          </div>
        </section>

        <section className={styles.proofSection} id="product">
          <div className={styles.shell}>
            <Reveal className={styles.sectionHeading}>
              <h2>每一件好物，都值得一条清晰的来路。</h2>
              <p>客户看见的是完整的 SKU，商家维护的是同一份商品底稿。一份资料只需整理一次，便能贯穿展示、选择与报价。</p>
            </Reveal>

            <Reveal>
              <figure className={styles.productProof}>
                <figcaption>
                  <span>澄湾商品前台</span>
                  <strong>{window.location.host}/{primaryStorefrontSlug}</strong>
                </figcaption>
                <img
                  src="/assets/marketing/storefront-preview.png"
                  alt="澄湾选品 Demo 商品前台，包含 SKU 搜索、标签筛选和商品卡片"
                  width="863"
                  height="875"
                  loading="lazy"
                />
              </figure>
            </Reveal>
          </div>
        </section>

        <section className={`${styles.shell} ${styles.painSection}`}>
          <Reveal className={styles.painVisual}>
            <figure>
              <img
                src="/assets/marketing/supplier-sample-room.jpg"
                alt="两位采购人员在整齐的样品室中核对商品与标签"
                width="1536"
                height="1024"
                loading="lazy"
              />
              <figcaption className={styles.imageCaption}>样品有归处，信息有来路。</figcaption>
            </figure>
          </Reveal>

          <Reveal className={styles.painCopy}>
            <h2>好商品，不该失落在表格之间。</h2>
            <p>当规格、图片、价格与供应商各自散落，每一次寻找都在重复昨天。澄湾把它们重新编入同一条脉络。</p>
            <dl className={styles.painList}>
              <div>
                <dt>资料有归处</dt>
                <dd>让 SKU、价格、规格、图片与供应商信息彼此照应。</dd>
              </div>
              <div>
                <dt>需求有回应</dt>
                <dd>让关键词、类目与标签成为可靠线索。</dd>
              </div>
              <div>
                <dt>报价有来路</dt>
                <dd>让每次加购自然抵达报价，不再重复搬运明细。</dd>
              </div>
            </dl>
          </Reveal>
        </section>

        <section className={styles.workflowSection} id="workflow">
          <div className={styles.shell}>
            <Reveal className={styles.workflowHeading}>
              <h2>从一张表格，到一份可以送达的报价。</h2>
              <p>没有突兀的跳转，也不必反复复制。商品沿着同一条脉络，被整理、被找到，也自然进入报价。</p>
            </Reveal>
            <Reveal>
              <ol className={styles.workflowList}>
                {workflow.map(({ icon: Icon, title, description }) => (
                  <li key={title}>
                    <div className={styles.workflowMarker}><Icon size={23} weight="duotone" /></div>
                    <h3>{title}</h3>
                    <p>{description}</p>
                  </li>
                ))}
              </ol>
            </Reveal>
          </div>
        </section>

        <section className={`${styles.shell} ${styles.capabilitiesSection}`} id="capabilities">
          <Reveal className={styles.sectionHeadingCompact}>
            <span className={styles.sectionKicker}>把复杂留在系统里</span>
            <h2>把清晰，留给每一次选择。</h2>
            <p>真正顺手的系统，不增加新的负担，只让每一份资料在需要时恰好出现。</p>
          </Reveal>

          <Reveal className={styles.capabilityGrid}>
            <article className={`${styles.capabilityCard} ${styles.capPrimary}`}>
              <Package size={30} weight="duotone" aria-hidden="true" />
              <span className={styles.capGiant} aria-hidden="true">SKU</span>
              <div>
                <h3>每件商品，都能独立被看见</h3>
                <p>每个 SKU 都能独立被看见，规格、价格与起订量不必藏在复杂的产品层级里。</p>
              </div>
            </article>
            <article className={`${styles.capabilityCard} ${styles.capSearch}`}>
              <Tag size={30} weight="duotone" aria-hidden="true" />
              <div>
                <h3>让标签成为寻找的线索</h3>
                <p>名称、编码、类目与标签彼此照应，也为更自然的相似商品检索留下余地。</p>
              </div>
            </article>
            <article className={`${styles.capabilityCard} ${styles.capQuote}`}>
              <ShoppingCartSimple size={30} weight="duotone" aria-hidden="true" />
              <div>
                <h3>选定之后，报价自然成形</h3>
                <p>选中的 SKU 与数量，顺势进入客户报价。</p>
              </div>
            </article>
            <article className={`${styles.capabilityCard} ${styles.capTenant}`}>
              <ShieldCheck size={30} weight="duotone" aria-hidden="true" />
              <div>
                <h3>各自经营，彼此有界</h3>
                <p>平台看见全局，商家只看见自己的商品、报价与前台。</p>
              </div>
            </article>
            <article className={`${styles.capabilityCard} ${styles.capExport}`}>
              <div className={styles.exportIcons} aria-hidden="true"><FilePdf size={27} /><FileXls size={27} /></div>
              <div>
                <h3>一纸报价，随需抵达</h3>
                <p>PDF 便于交付，Excel 便于继续整理。</p>
              </div>
            </article>
          </Reveal>
        </section>

        <section className={styles.merchantSection} id="merchants">
          <div className={`${styles.shell} ${styles.merchantGrid}`}>
            <Reveal className={styles.merchantCopy}>
              <h2>每一家商家，都有自己的一扇窗。</h2>
              <p>官网承载品牌，商家沿着一条简洁路径抵达自己的商品前台。商品、报价与账号各自归属，边界清楚。</p>
              <ul>
                <li><CheckCircle size={20} weight="fill" />一条专属路径，承接自己的商品世界</li>
                <li><CheckCircle size={20} weight="fill" />商品、报价与账号各归其位</li>
                <li><CheckCircle size={20} weight="fill" />旧有链接也被妥善照看</li>
              </ul>
            </Reveal>

            <Reveal className={styles.routeCard}>
              <div className={styles.routeCardTop}>
                <Buildings size={28} weight="duotone" />
                <span>商家的专属门牌</span>
              </div>
              <div className={styles.routeExample}>
                <span>yourdomain.com/</span><strong>merchant</strong>
              </div>
              <div className={styles.routeLegend}>
                <span>根域官网</span>
                <span>专属商家路径</span>
                <span>独立工作台</span>
              </div>
            </Reveal>
          </div>
        </section>

        <section className={`${styles.shell} ${styles.ctaSection}`}>
          <Reveal className={styles.ctaCard}>
            <div>
              <h2>先让第一批商品，走完抵达客户的路。</h2>
              <p>从一家商家、一张表格开始，完成一次真实的展示、选择与报价。</p>
            </div>
            <Link className={styles.primaryButton} to={primaryStorefrontPath}>
              查看商品前台 <ArrowRight size={18} weight="bold" />
            </Link>
          </Reveal>
        </section>
      </main>

      <footer className={styles.footer}>
        <div className={`${styles.shell} ${styles.footerInner}`}>
          <Brand subtitle="万千货品，自成脉络" />
          <nav aria-label="页脚导航">
            <a href="#product">产品</a>
            <a href="#workflow">流程</a>
            <Link to={primaryStorefrontPath}>查看商品前台</Link>
            <Link to="/login">登录工作台</Link>
            <Link to="/privacy">隐私政策</Link>
            <a href="/licenses/Noto-CJK-OFL.txt">字体许可</a>
          </nav>
          <small>© {new Date().getFullYear()} 澄湾选品</small>
        </div>
      </footer>
    </div>
  );
}
