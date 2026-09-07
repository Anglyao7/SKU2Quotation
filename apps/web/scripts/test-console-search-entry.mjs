import assert from "node:assert/strict";
import fs from "node:fs/promises";
import ts from "typescript";

const source = await fs.readFile(new URL("../src/pages/console/ConsoleLayout.tsx", import.meta.url), "utf8");
const ast = ts.createSourceFile("ConsoleLayout.tsx", source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const nav = ast.statements.filter(ts.isVariableStatement)
  .flatMap(statement => [...statement.declarationList.declarations])
  .find(declaration => declaration.name.getText(ast) === "navigationGroups");
assert.ok(nav?.initializer);
const navigation = nav.initializer.getText(ast);
assert.ok(!navigation.includes('to: "/console/ai-search"'), "Search is no longer a sidebar or mobile-menu module");
assert.ok(navigation.includes('to: "/console/ai-search/manage"'), "Search settings remain available");

const header = source.slice(source.indexOf('<header className="console-topbar">'), source.indexOf("</header>"));
assert.match(header, /hasPermission\("product\.view"\)\s*\?\s*<NavLink\s+to="\/console\/ai-search"/, "Keep the original product.view permission boundary");
assert.match(header, /<MagnifyingGlass size=\{20\} aria-hidden="true"\s*\/>/);
assert.match(header, /aria-label=\{t\("AI 搜索"\)\}/);
assert.match(header, /title=\{t\("AI 搜索"\)\}/);
assert.match(header, /topbar-search-trigger\$\{isActive/);
assert.match(header, /onFocus=\{\(\) => preloadConsoleRoute\("\/console\/ai-search"\)\}/);

const app = await fs.readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
assert.ok(app.includes('path: "ai-search", element: <PermissionGate anyOf={["product.view"]}><AiSearchPage /></PermissionGate>'), "Preserve search and existing links/bookmarks");
console.log("Console search entry: sidebar removed, topbar icon, permission, locale labels, active state and search route passed");
