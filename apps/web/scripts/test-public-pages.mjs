import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const root = fileURLToPath(new URL("../../../", import.meta.url));
const output = path.join(root, ".runtime/ui-review");
const origin = process.env.UI_TEST_URL || "http://127.0.0.1:5178";

// Run through Playwright MCP or directly against a local preview. All API
// requests are intercepted; this check never writes to a real business account.
export async function runPublicPageTests(page) {
  await mkdir(output, { recursive: true });
  await page.unroute("**/api/**");
  const runtimeErrors = [];
  const normalConsoleErrors = [];
  const captureConsole = (message) => {
    if (message.type() === "error") normalConsoleErrors.push(message.text());
  };
  page.on("console", captureConsole);
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  let scenario = "invalid";
  let heldRequest;
  const requests = [];
  const memberships = [
    {
      id: "review-active",
      tenant_id: "review-tenant",
      tenant_name: "仅供测试的外贸团队 · 长名称工作区展示与换行检查",
      tenant_slug: "review",
      status: "active",
    },
    {
      id: "review-disabled",
      tenant_id: "disabled-tenant",
      tenant_name: "停用工作区",
      tenant_slug: "disabled",
      status: "inactive",
    },
  ];
  const token = (selecting = false) => ({
    access_token: "local-review-token",
    expires_in: 3600,
    csrf_token: "local-review-csrf",
    session_id: "local-review-session",
    requires_tenant_selection: selecting,
    user: {
      id: "review-user",
      display_name: "本地测试用户",
      is_platform_admin: false,
      locale: "zh-CN",
    },
    context: selecting
      ? {}
      : {
          tenant_id: "review-tenant",
          membership_id: "review-active",
          tenant_name: "本地测试企业",
          tenant_slug: "review",
          account_scope: "STAFF",
          default_workspace: "staff_console",
        },
    memberships,
    permission_version: 1,
    permissions: [],
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    requests.push({
      path: url.pathname,
      method: request.method(),
      body: request.postData() ? request.postDataJSON() : null,
    });
    const reply = (status, body) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify(body),
      });
    if (url.pathname.endsWith("/auth/refresh")) {
      if (scenario === "restore") {
        await new Promise((resolve) => {
          heldRequest = resolve;
        });
        return reply(401, {
          detail: {
            code: "AUTH_SESSION_EXPIRED",
            message: "Expired test session",
          },
        });
      }
      return reply(401, {
        detail: {
          code: "AUTH_SESSION_EXPIRED",
          message: "Expired test session",
        },
      });
    }
    if (url.pathname.endsWith("/auth/login")) {
      if (scenario === "selecting" || scenario === "empty")
        return reply(200, {
          data: {
            ...token(true),
            memberships: scenario === "empty" ? [] : memberships,
          },
        });
      if (scenario === "success") return reply(200, { data: token() });
      await new Promise((resolve) => setTimeout(resolve, 400));
      const status =
        scenario === "rate" ? 429 : scenario === "unavailable" ? 503 : 401;
      const code =
        scenario === "rate"
          ? "RATE_LIMITED"
          : scenario === "unavailable"
            ? "RATE_LIMIT_UNAVAILABLE"
            : "AUTH_INVALID_CREDENTIALS";
      return reply(status, {
        detail: { code, message: "Mock authentication response" },
      });
    }
    if (url.pathname.endsWith("/auth/memberships"))
      return reply(200, scenario === "empty" ? [] : memberships);
    if (url.pathname.endsWith("/auth/tenant-context")) {
      if (scenario === "tenant-error")
        return reply(503, { detail: { message: "模拟工作区切换失败" } });
      await new Promise((resolve) => {
        heldRequest = resolve;
      });
      return reply(200, { data: token() });
    }
    return reply(200, { data: [] });
  });

  await page.goto(origin);
  await page.evaluate(() => {
    localStorage.clear();
    localStorage.setItem("zhimaoyun.console.locale", "zh-CN");
  });
  await page.reload();
  await page.locator("#hero-title").waitFor();
  assert.equal(
    await page.locator("html").getAttribute("data-theme"),
    "dark",
    "Public pages should default to dark",
  );
  const screenshot = async (name) => {
    await page.screenshot({
      path: path.join(output, `${name}.png`),
      fullPage: true,
    });
  };
  const checkOverflow = async (label) =>
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      ),
      false,
      `${label}: horizontal overflow`,
    );
  const results = [];

  for (const width of [1440, 768, 390]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 1000 });
    for (const theme of ["dark", "light"]) {
      await page.evaluate(
        (value) => localStorage.setItem("zhimaoyun.theme", value),
        theme,
      );
      await page.goto(origin);
      await page.locator("#hero-title").waitFor();
      await page.waitForTimeout(1400);
      await checkOverflow(`Home ${width} ${theme}`);
      assert.equal(await page.locator("#pricing article").count(), 3);
      for (const amount of ["¥2,980", "¥4,980", "¥9,800"])
        assert.ok(
          await page
            .locator("#pricing")
            .getByText(amount, { exact: true })
            .isVisible(),
        );
      for (const id of [
        "product",
        "workflow",
        "capabilities",
        "pricing",
        "merchants",
      ])
        assert.equal(await page.locator(`#${id}`).count(), 1);
      await screenshot(`home-${width}-${theme}`);
      // Real clicks catch decorative layers intercepting the cloud controls.
      await page.getByRole("button", { name: "暂停云效" }).click();
      assert.equal(
        await page
          .getByRole("button", { name: "继续云效" })
          .getAttribute("aria-pressed"),
        "true",
      );
      await page.getByRole("button", { name: "继续云效" }).click();
      await page.goto(`${origin}/login`);
      await page.locator("#login-identifier").waitFor();
      await checkOverflow(`Login ${width} ${theme}`);
      assert.equal(
        await page.locator("#login-identifier").getAttribute("autocomplete"),
        "username",
      );
      assert.equal(
        await page.locator("#login-password").getAttribute("autocomplete"),
        "current-password",
      );
      await screenshot(`login-${width}-${theme}`);
      results.push(
        `${width}px: home + login, ${theme}, no horizontal overflow`,
      );
    }
  }

  await page.goto(origin);
  await page.getByRole("button", { name: "打开导航" }).click();
  assert.ok(
    await page.getByRole("navigation", { name: "移动端官网导航" }).isVisible(),
  );
  await page.keyboard.press("Escape");
  assert.equal(
    await page
      .getByRole("button", { name: "打开导航" })
      .getAttribute("aria-expanded"),
    "false",
  );
  assert.ok(
    await page
      .getByRole("button", { name: "打开导航" })
      .evaluate((el) => el === document.activeElement),
  );
  await page.getByRole("button", { name: "打开导航" }).click();
  await page
    .getByRole("navigation", { name: "移动端官网导航" })
    .getByRole("link", { name: "服务方案" })
    .click();
  assert.ok(page.url().endsWith("#pricing"));
  const pricingBounds = await page.locator("#pricing").boundingBox();
  const headerBounds = await page.locator("header").boundingBox();
  assert.ok(pricingBounds.y >= headerBounds.height, "Sticky header must not cover the pricing anchor");
  assert.equal(
    await page
      .getByRole("button", { name: "打开导航" })
      .getAttribute("aria-expanded"),
    "false",
  );
  await page.locator("#pricing article").first().getByRole("link").click();
  await page.waitForURL("**/login");
  results.push(
    "Mobile menu: open, Escape, focus return, anchor close, pricing login link",
  );

  await page.getByRole("button", { name: "切换深色模式" }).click();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.reload();
  assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
  await page.getByRole("button", { name: "切换语言" }).click();
  await page.waitForFunction(() => document.documentElement.lang === "en-US");
  assert.ok(
    (await page.locator("#login-intro").textContent()).includes("customers"),
  );
  await screenshot("login-390-english");
  await page.reload();
  assert.equal(await page.locator("html").getAttribute("lang"), "en-US");
  await page.getByRole("button", { name: /Change language|切换语言/ }).click();
  await page.waitForFunction(() => document.documentElement.lang === "zh-CN");
  results.push(
    "Theme and language switches persist across reloads; English mobile layout verified",
  );
  assert.deepEqual(
    normalConsoleErrors,
    [],
    "No browser console errors during normal home and login interactions",
  );
  page.off("console", captureConsole);

  const fillLogin = async () => {
    await page.locator("#login-identifier").fill("ui-review-user");
    await page.locator("#login-password").fill("local-mock-password");
  };
  await page.getByRole("button", { name: "登录工作台", exact: true }).click();
  assert.equal(
    await page
      .locator("#login-identifier")
      .evaluate((el) => el.validity.valueMissing),
    true,
  );
  assert.equal(
    requests.filter((r) => r.path.endsWith("/auth/login")).length,
    0,
  );
  await fillLogin();
  await page.getByRole("button", { name: "显示密码" }).click();
  assert.equal(
    await page.locator("#login-password").getAttribute("type"),
    "text",
  );
  await page.getByRole("button", { name: "隐藏密码" }).click();
  assert.equal(
    await page.locator("#login-password").getAttribute("type"),
    "password",
  );
  await page.locator("#login-password").press("Enter");
  await page.getByRole("status").waitFor();
  assert.ok(await page.locator("#login-identifier").isDisabled());
  await page.locator("#login-error").waitFor();
  assert.ok(
    (await page.locator("#login-error").textContent()).includes(
      "账号或密码错误",
    ),
  );
  assert.equal(
    await page.locator("#login-password").getAttribute("aria-describedby"),
    "login-error",
  );
  assert.equal(
    await page.locator("#login-error").getAttribute("role"),
    "alert",
  );
  await screenshot("login-390-invalid");
  for (const [mode, text] of [
    ["rate", "过于频繁"],
    ["unavailable", "暂时不可用"],
  ]) {
    scenario = mode;
    await page.getByRole("button", { name: "登录工作台", exact: true }).click();
    await page.waitForFunction(
      (expected) =>
        document.getElementById("login-error")?.textContent.includes(expected),
      text,
    );
  }
  results.push(
    "Login: empty-field validation, password visibility, Enter submit, busy disabled, inline 401/429/503 errors",
  );

  scenario = "restore";
  await page.evaluate(() =>
    localStorage.setItem("atc.csrfToken", "local-review-csrf"),
  );
  await page.reload();
  await page.getByRole("status").waitFor();
  assert.ok(await page.locator("#login-password").isDisabled());
  while (!heldRequest) await new Promise((resolve) => setTimeout(resolve, 10));
  heldRequest();
  heldRequest = undefined;
  await page.waitForFunction(
    () => !document.getElementById("login-password")?.disabled,
  );
  results.push(
    "Session restoration: inputs disabled until expired session resolves",
  );

  scenario = "empty";
  await fillLogin();
  await page.locator("#login-password").press("Enter");
  await page.getByText("当前账号没有可用的商家空间。").waitFor();
  scenario = "selecting";
  await page.reload();
  await page.waitForFunction(
    () => !document.getElementById("login-password")?.disabled,
  );
  await fillLogin();
  await page.locator("#login-password").press("Enter");
  await page.getByRole("heading", { name: "选择工作区" }).waitFor();
  assert.ok(
    await page.getByRole("button", { name: "停用工作区" }).isDisabled(),
  );
  await checkOverflow("Long workspace name");
  await screenshot("login-390-workspaces");
  scenario = "tenant-error";
  await page.getByRole("button", { name: /仅供测试的外贸团队/ }).click();
  await page.getByText("模拟工作区切换失败").waitFor();
  assert.ok(
    await page.getByRole("heading", { name: "选择工作区" }).isVisible(),
  );
  scenario = "selecting";
  await page.getByRole("button", { name: /仅供测试的外贸团队/ }).click();
  await page.getByRole("status").waitFor();
  assert.ok(
    await page.getByRole("heading", { name: "选择工作区" }).isVisible(),
  );
  assert.ok(
    await page.getByRole("button", { name: /仅供测试的外贸团队/ }).isDisabled(),
  );
  while (!heldRequest) await new Promise((resolve) => setTimeout(resolve, 10));
  heldRequest();
  heldRequest = undefined;
  await page.waitForURL("**/console");
  assert.deepEqual(
    requests.findLast((r) => r.path.endsWith("/auth/tenant-context")).body,
    { membership_id: "review-active" },
  );
  results.push(
    "Workspaces: empty, inactive, long name, switch failure/retry, busy state, selection payload and default /console redirect",
  );

  await page.goto(`${origin}/login`);
  await page.waitForFunction(
    () => !document.getElementById("login-password")?.disabled,
  );
  scenario = "success";
  // Reload makes React Router read the preserved return destination.
  await page.evaluate(() =>
    history.replaceState({ ...history.state, usr: { from: "/privacy" } }, ""),
  );
  await page.reload();
  await page.waitForFunction(
    () => !document.getElementById("login-password")?.disabled,
  );
  await fillLogin();
  await page.locator("#login-password").press("Enter");
  await page.waitForURL("**/privacy");
  results.push("Successful login preserves requested destination");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto(origin);
  await page.locator("#hero-title").waitFor();
  await page.waitForTimeout(500);
  assert.equal(
    await page
      .locator("#hero-title")
      .evaluate((el) => getComputedStyle(el).opacity),
    "1",
  );
  await screenshot("home-390-reduced-motion");
  results.push("Reduced motion: readable content and usable links");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.route("**/*gsap*", (route) => route.abort());
  await page.goto(origin);
  await page.locator("#hero-title").waitFor();
  await page.waitForTimeout(400);
  assert.equal(
    await page
      .locator("#hero-title")
      .evaluate((el) => getComputedStyle(el).opacity),
    "1",
  );
  await page.unroute("**/*gsap*");
  results.push("Animation-load failure: content remains visible");
  assert.deepEqual(runtimeErrors, [], "No uncaught browser runtime errors");
  const report = {
    results,
    runtimeErrors,
    normalConsoleErrors,
    apiRequestsMocked: requests.length,
    screenshots: output,
  };
  await writeFile(
    path.join(output, "report.json"),
    JSON.stringify(report, null, 2),
  );
  await page.evaluate(() => {
    localStorage.clear();
    localStorage.setItem("zhimaoyun.console.locale", "zh-CN");
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(origin);
  return report;
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const require = createRequire(import.meta.url);
  const { chromium } = require(
    path.join(root, ".runtime/browser-tools/node_modules/playwright"),
  );
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  try {
    console.log(
      JSON.stringify(
        await runPublicPageTests(await browser.newPage()),
        null,
        2,
      ),
    );
  } finally {
    await browser.close();
  }
}
