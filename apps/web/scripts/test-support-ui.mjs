import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const trackerSource = await fs.readFile(
  new URL("../src/core/supportNotificationState.ts", import.meta.url),
  "utf8",
);
const compiled = ts.transpileModule(trackerSource, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
}).outputText;
const moduleUrl = `data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`;
const { humanRequestKey, mergeHumanRequestSnapshot } = await import(moduleUrl);

const request = (conversationId, requestedAt) => ({
  conversationId,
  requestedAt,
});
const initial = [
  request("conversation-b", "2026-08-12T12:02:00.000Z"),
  request("conversation-a", "2026-08-12T12:01:00.000Z"),
];
const seeded = mergeHumanRequestSnapshot(null, initial, false);
assert.deepEqual(seeded.arrivals, []);
assert.equal(seeded.tracker.knownKeys.has(humanRequestKey(initial[0])), true);

const concurrentArrival = request(
  "conversation-c",
  "2026-08-12T12:03:00.000Z",
);
const refreshedAfterLocalChange = mergeHumanRequestSnapshot(
  seeded.tracker,
  [concurrentArrival, initial[0]],
  true,
);
assert.deepEqual(refreshedAfterLocalChange.arrivals, [concurrentArrival]);

const repeated = mergeHumanRequestSnapshot(
  refreshedAfterLocalChange.tracker,
  [concurrentArrival, initial[0]],
  true,
);
assert.deepEqual(repeated.arrivals, []);

const previouslyUnseenOldRequest = request(
  "conversation-outside-old-page",
  "2026-08-12T11:59:00.000Z",
);
const oldRequestReenteredPage = mergeHumanRequestSnapshot(
  repeated.tracker,
  [concurrentArrival, previouslyUnseenOldRequest],
  true,
);
assert.deepEqual(oldRequestReenteredPage.arrivals, []);
assert.equal(
  oldRequestReenteredPage.tracker.knownKeys.has(
    humanRequestKey(previouslyUnseenOldRequest),
  ),
  true,
);

const supportPageSource = await fs.readFile(
  new URL("../src/core/pages/SupportCenterPage.tsx", import.meta.url),
  "utf8",
);
[
  "selectedIdRef.current !== conversationId",
  "detailRequestSequenceRef.current !== requestSequence",
  "detail.id !== selectedIdRef.current",
  "selectConversation(item.id)",
  "replyBusy || detailLoading",
].forEach((contract) => {
  assert.ok(
    supportPageSource.includes(contract),
    `Missing conversation race guard: ${contract}`,
  );
});

const notificationSource = await fs.readFile(
  new URL("../src/core/components/SupportNotificationBell.tsx", import.meta.url),
  "utf8",
);
assert.ok(
  notificationSource.includes("const refreshAfterChange = () => void refresh(true)"),
  "Local support changes must still detect concurrent new human requests",
);
assert.ok(
  notificationSource.includes("setLoadError("),
  "Notification API failures must be visible instead of looking like zero requests",
);

const localeSource = await fs.readFile(
  new URL("../src/core/LocaleContext.tsx", import.meta.url),
  "utf8",
);
[
  "人工接管",
  "AI 回答中",
  "AI 可接待",
  "恢复 AI",
  "恢复 AI 接待失败",
  "AI 客服",
  "企业文件",
  "查看 {count} 条引用来源",
  "人工客服提醒加载失败",
].forEach((key) => {
  assert.ok(localeSource.includes(`"${key}":`), `Missing English locale key: ${key}`);
});

console.log("Support conversation and notification race tests passed");
