import { Badge, Button, Card, Heading, Progress, Text, TextArea } from "@radix-ui/themes";
import { ArrowRight, CaretDown, CaretUp, MagnifyingGlass, ShieldCheck, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { searchProducts } from "../api";
import { CoreEmpty, CoreError, CoreLoading, CorePageHeading, percent } from "../CoreUi";
import type { HybridSearchResponse } from "../types";

const examples = [
  "适合巴西市场的小型防水狗玩具",
  "食品级硅胶水瓶，目标价低于 20 元",
  "适合欧洲市场的环保旅行收纳包",
];

const scoreLabels: Record<string, string> = { keyword: "关键词", semantic: "语义", attribute: "属性", supplier: "供应商" };

export function AiSearchPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [response, setResponse] = useState<HybridSearchResponse>();
  const [expanded, setExpanded] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const runSearch = async (requested = query) => {
    const normalized = requested.trim();
    if (!normalized) return;
    setQuery(normalized);
    setParams({ q: normalized }, { replace: true });
    setLoading(true);
    setError("");
    try { setResponse(await searchProducts(normalized, 10)); }
    catch (reason) { setResponse(undefined); setError(reason instanceof Error ? reason.message : "AI Search 暂不可用"); }
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
      <CorePageHeading eyebrow="AI 产品搜索" title="说出需求，获得可追溯的匹配" description="在当前租户已批准的产品知识中组合关键词、语义、属性与供应商信号。" />
      <Card className="core-search-hero">
        <form onSubmit={submit} className="core-ai-query">
          <Sparkle size={26} />
          <TextArea value={query} onChange={(event) => setQuery(event.target.value)} rows={2} placeholder="例如：适合巴西市场的小型防水狗玩具，目标价低于 3 美元…" aria-label="描述产品需求" />
          <Button size="3" disabled={!query.trim() || loading}>{loading ? "搜索中" : <><MagnifyingGlass />开始搜索</>}</Button>
        </form>
        {!response && !loading ? <div className="core-example-list">{examples.map((example) => <Button key={example} variant="soft" color="gray" onClick={() => void runSearch(example)}>{example}<ArrowRight /></Button>)}</div> : null}
      </Card>
      {loading ? <CoreLoading label="正在综合产品知识与供应商信号" /> : null}
      {error ? <CoreError message={error} onRetry={() => void runSearch()} /> : null}
      {response && !loading ? (
        <section className="core-search-results">
          <div className="core-result-summary">
            <div><Heading size="5">找到 {response.results.length} 个匹配</Heading><Text size="2" color="gray">“{response.query}”</Text></div>
            <div className="core-provenance">
              <Badge color="jade"><ShieldCheck />仅搜索当前工作区</Badge>
              <Badge color="gray">关键词 + 语义匹配</Badge>
            </div>
          </div>
          {response.degradedChannels.length ? <Card className="core-warning"><WarningCircle /><Text size="2">部分智能匹配能力暂不可用，已自动使用可用信号继续搜索。</Text></Card> : null}
          {constraints.length ? <div className="core-chip-row"><Text size="1" color="gray">已识别需求</Text>{constraints.map((item) => <Badge key={item} color="gray">{item}</Badge>)}</div> : null}
          <div className="core-result-list">
            {response.results.map((result, index) => {
              const open = expanded === result.productId;
              return (
                <Card className="core-search-card" key={result.productId}>
                  <div className="core-result-rank">{String(index + 1).padStart(2, "0")}</div>
                  <div className="core-result-body">
                    <div className="core-result-title"><div><Text size="1" color="gray">{result.productCode ?? "产品"} · 来源版本 v{result.sourceVersion}</Text><Heading size="4">{result.name}</Heading></div><strong>{percent(result.score)}</strong></div>
                    <div className="core-score-grid">{Object.entries(result.scoreBreakdown).map(([key, value]) => <div key={key}><span><Text size="1" color="gray">{scoreLabels[key] ?? key}</Text><Text size="1" weight="bold">{percent(value)}</Text></span><Progress value={value * 100} /></div>)}</div>
                    <div className="core-fact-row"><span>供应商：{result.product?.supplier || "暂无证据"}</span><span>参考价：{result.product?.price === undefined ? "—" : `${result.product.currency ?? ""} ${result.product.price.toFixed(2)}`}</span><span>交期：{result.product?.sources[0]?.leadTimeDays ? `${result.product.sources[0].leadTimeDays} 天` : "—"}</span></div>
                    <div className="core-row-actions"><Button variant="ghost" color="gray" onClick={() => setExpanded(open ? undefined : result.productId)}>{open ? <CaretUp /> : <CaretDown />}匹配依据</Button><Button asChild variant="soft"><Link to={`/console/products?product=${encodeURIComponent(result.productId)}`}>查看产品</Link></Button><Button asChild><Link to={`/console/inquiries?product=${encodeURIComponent(result.productId)}&q=${encodeURIComponent(response.query)}`}>加入询盘<ArrowRight /></Link></Button></div>
                    {open ? <div className="core-evidence-list">{result.evidence.map((item) => <blockquote key={item.chunkId}><Text size="1" color="gray">{item.chunkType} · {item.contentHash.slice(0, 10)}</Text><p>{item.excerpt}</p></blockquote>)}{!result.evidence.length ? <Text size="2" color="gray">该结果暂未返回证据摘录。</Text> : null}</div> : null}
                  </div>
                </Card>
              );
            })}
            {!response.results.length ? <CoreEmpty title="没有可靠匹配" description="系统不会伪造高分结果。请减少限制条件或补充产品主数据。" action={<Button asChild><Link to="/console/products">打开产品中心</Link></Button>} /> : null}
          </div>
        </section>
      ) : null}
    </div>
  );
}
