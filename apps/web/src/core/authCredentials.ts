export interface PasswordLoginPayload {
  grant_type: "password";
  identifier: string;
  password: string;
  device_label: string;
}

export function buildPasswordLoginPayload(
  identifier: string,
  password: string,
): PasswordLoginPayload {
  const normalizedIdentifier = identifier.trim();
  const normalizedPassword = password.trim();
  if (!normalizedIdentifier) {
    throw new Error("请输入账号、邮箱或手机号。");
  }
  if (!normalizedPassword) {
    throw new Error("请输入密码。");
  }
  return {
    grant_type: "password",
    identifier: normalizedIdentifier,
    password: normalizedPassword,
    device_label: "智贸云 Web",
  };
}
