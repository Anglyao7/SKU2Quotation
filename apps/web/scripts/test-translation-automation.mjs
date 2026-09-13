import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const read = path => fs.readFile(new URL(path, import.meta.url), "utf8");
const messages = await read("../src/core/automationMessages.ts");
const compiled = ts.transpileModule(messages, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
const { automaticTranslationCopy } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
for (const locale of ["zh-CN", "en-US", "es", "tr", "ar", "ja", "ko", "pt", "fr", "fa", "ru"]) {
  const copy = automaticTranslationCopy(locale);
  for (const key of ["title", "loading", "RUNNING", "WAITING", "PAUSED", "READY", "ATTENTION", "save"]) {
    assert.equal(typeof copy[key], "string", `${locale}/${key}`);
    assert.ok(copy[key].trim());
  }
}
const page = await read("../src/core/pages/LanguagePackagesPage.tsx");
const controls = await read("../src/core/components/AutomaticTranslationControls.tsx");
assert.match(page, /AutomaticTranslationControls/);
assert.match(page, /const translationStartBlocked = !automationLoaded \|\| automationBusy/);
assert.ok((page.match(/translationStartBlocked/g) ?? []).length >= 7, "start, full, resume and retry must all guard against automatic work/loading");
assert.match(page, /next\.active_job_id \|\| \(previousEvent && next\.last_job_id\)/, "idle page must discover worker jobs");
assert.match(page, /next\.packagePublished && latest\.package/, "unpublished completion must not claim storefront publication");
assert.match(page, /selectedJob\.awaitingPublish && selectedJob\.status === "SUCCEEDED"/);
assert.match(controls, /window\.setInterval\(\(\) => void poll\(\), 5000\)/);
assert.match(controls, /callback\.current\(undefined\)/, "failed/loading status must not enable manual starts");
assert.match(controls, /if \(!mounted\.current\) return/);
console.log("Automatic translation controls, all 11 locales and action guards passed.");
