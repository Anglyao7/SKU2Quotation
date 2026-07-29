type LoginErrorLike = {
  status?: unknown;
  details?: unknown;
  message?: unknown;
};

function errorCode(details: unknown): string | undefined {
  if (!details || typeof details !== "object") return undefined;
  const payload = details as Record<string, unknown>;
  const detail = payload.detail;
  if (detail && typeof detail === "object") {
    const code = (detail as Record<string, unknown>).code;
    if (typeof code === "string") return code;
  }
  return typeof payload.code === "string" ? payload.code : undefined;
}

export function authLoginMessageKey(reason: unknown): string {
  if (!reason || typeof reason !== "object") {
    return "登录失败，请稍后重试。";
  }

  const error = reason as LoginErrorLike;
  const status = typeof error.status === "number" ? error.status : undefined;
  const code = errorCode(error.details);

  if (code === "AUTH_INVALID_CREDENTIALS" || status === 400 || status === 401) {
    return "账号或密码错误，请检查开通时的账号和最近一次设置的密码。";
  }
  if (code === "RATE_LIMITED" || status === 429) {
    return "登录尝试过于频繁，请稍后再试。";
  }
  if (
    code === "RATE_LIMIT_UNAVAILABLE"
    || code === "AUTH_PROVIDER_UNAVAILABLE"
    || status === 502
    || status === 503
    || status === 504
  ) {
    return "认证服务暂时不可用，请稍后再试。";
  }
  if (status === 0) {
    return "无法连接登录服务，请检查网络后重试。";
  }
  if (status === 422) {
    return "登录信息格式不正确，请检查后重试。";
  }
  if (
    error.message === "请输入账号、邮箱或手机号。"
    || error.message === "请输入密码。"
  ) {
    return error.message;
  }
  return "登录失败，请稍后重试。";
}
