import { Badge, Button, Card, Heading, Progress, Text, TextArea } from "@radix-ui/themes";
import { ArrowRight, CaretDown, CaretUp, MagnifyingGlass, ShieldCheck, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getAISearchRecommendedQuestions, searchProducts } from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, percent } from "../CoreUi";
import { useLocale } from "../LocaleContext";
import type { HybridSearchResponse } from "../types";

const defaultExamples = [
  "适合巴西市场的小型防水狗玩具",
  "食品级硅胶水瓶，目标价低于 20 元",
  "适合欧洲市场的环保旅行收纳包",
];

const scoreLabels: Record<string, string> = { keyword: "关键词", semantic: "语义", attribute: "属性", tag: "标签", supplier: "供应商" };

export function AiSearchPage() {
  const { t } = useLocale();
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [response, setResponse] = useState<HybridSearchResponse>();
  const [expanded, setExpanded] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [examples, setExamples] = useState(defaultExamples);

  useEffect(() => {
    let active = true;
    void getAISearchRecommendedQuestions()
      .then((result) => {
        if (active && result.questions.length === 3) setExamples(result.questions);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, []);

  const runSearch = async (requested = query) => {
    const normalized = requested.trim();
    if (!normalized) return;
    setQuery(normalized);
    setParams({ q: normalized }, { replace: true });
    setLoading(true);
    setError("");
    try { setResponse(await searchProducts(normalized, 10)); }
    catch (reason) { setResponse(undefined); setError(reason instanceof Error ? reason.message : t("AI Search 暂不可用")); }
    finally { setLoading(false); }
  };
  useEffect(() => {
    const initial = params.get("q");
    if (initial) void runSearch(initial);
    // The query string is the initial, shareable search state.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const constraints = useMemo(() => query.split(/[,，]/).map((item) => item.trim()).filter(Boolean).slice(0, 5), [query]);
  const submit = (event: FormEvent) => { event.preventDefault(); void runSearch(); };

  return (
    <div className="core-workspace">
      <CorePageHeading eyebrow={t("AI 产品搜索")} title={t("说出需求，获得可追溯的匹配")} description={t("优先匹配 SKU、商品名、标签与分类，再用语义搜索补充相近商品。")} />
      <Card className="core-search-hero">
        <form onSubmit={submit} className="core-ai-query">
          <Sparkle size={26} />
          <TextArea value={query} onChange={(event) => setQuery(event.target.value)} rows={2} placeholder={t("例如：适合巴西市场的小型防水狗玩具，目标价低于 3 美元…")} aria-label={t("描述产品需求")} />
          <Button size="3" disabled={!query.trim() || loading}>{loading ? t("搜索中") : <><MagnifyingGlass />{t("开始搜索")}</>}</Button>
        </form>
        {!response && !loading ? <div className="core-example-list">{examples.map((example) => <Button key={example} variant="soft" color="gray" onClick={() => void runSearch(t(example))}>{t(example)}<ArrowRight /></Button>)}</div> : null}
      </Card>
      {loading ? <CoreLoading label={t("正在综合产品知识与供应商信号")} /> : null}
      {error ? <CoreError message={error} onRetry={() => void runSearch()} /> : null}
      {response && !loading ? (
        <section className="core-search-results">
          <div className="core-result-summary">
            <div><Heading size="5">{t("找到 {count} 个匹配", { count: response.results.length })}</Heading><Text size="2" color="gray">“{response.query}”</Text></div>
            <div className="core-provenance">
              <Badge color="jade"><ShieldCheck />{t("仅搜索当前工作区")}</Badge>
              <Badge color="gray">{t("文本匹配优先 · 语义补充")}</Badge>
            </div>
          </div>
          {response.degraded ? <Card className="core-warning"><WarningCircle /><Text size="2">{t("部分智能匹配能力暂不可用，已自动使用可用信号继续搜索。")}</Text></Card> : null}
          {constraints.length ? <div className="core-chip-row"><Text size="1" color="gray">{t("已识别需求")}</Text>{constraints.map((item) => <Badge key={item} color="gray">{item}</Badge>)}</div> : null}
          <div className="core-result-list">
            {response.results.map((result, index) => {
              const open = expanded === result.productId;
              return (
                <Card className="core-search-card" key={result.productId}>
                  <div className="core-result-rank">{String(index + 1).padStart(2, "0")}</div>
                  <div className="core-result-body">
                    <div className="core-result-title"><div><Text size="1" color="gray">{result.productCode ?? t("产品")} · {t("来源版本")} v{result.sourceVersion}</Text><Heading size="4">{result.name}</Heading></div><strong>{percent(result.score)}</strong></div>
                    <div className="core-score-grid">{Object.entries(result.scoreBreakdown).map(([key, value]) => <div key={key}><span><Text size="1" color="gray">{t(scoreLabels[key] ?? key)}</Text><Text size="1" weight="bold">{percent(value)}</Text></span><Progress value={value * 100} /></div>)}</div>
                    <div className="core-fact-row"><span>{t("供应商")}：{result.product?.supplier || t("暂无证据")}</span><span>{t("参考价")}：{result.product?.price === undefined ? "—" : `${result.product.currency ?? ""} ${result.product.price.toFixed(2)}`}</span><span>{t("交期")}：{result.product?.sources[0]?.leadTimeDays ? t("{count} 天", { count: result.product.sources[0].leadTimeDays }) : "—"}</span></div>
                    <div className="core-row-actions"><Button variant="ghost" color="gray" onClick={() => setExpanded(open ? undefined : result.productId)}>{open ? <CaretUp /> : <CaretDown />}{t("匹配依据")}</Button><Button asChild variant="soft"><Link to={`/console/products?product=${encodeURIComponent(result.productId)}`}>{t("查看产品")}</Link></Button><Button asChild><Link to={`/console/inquiries?product=${encodeURIComponent(result.productId)}&q=${encodeURIComponent(response.query)}`}>{t("加入询盘")}<ArrowRight /></Link></Button></div>
                    {open ? <div className="core-evidence-list">{result.evidence.map((item, evidenceIndex) => <blockquote key={`${result.productId}:${evidenceIndex}`}><Text size="1" color="gray">{t("匹配依据")}</Text><p>{item.excerpt}</p></blockquote>)}{!result.evidence.length ? <Text size="2" color="gray">{t("该结果暂未返回证据摘录。")}</Text> : null}</div> : null}
                  </div>
                </Card>
              );
            })}
            {!response.results.length ? <CoreEmpty title={t("没有可靠匹配")} description={t("系统不会伪造高分结果。请减少限制条件或补充产品主数据。")} action={<Button asChild><Link to="/console/products">{t("打开产品中心")}</Link></Button>} /> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
