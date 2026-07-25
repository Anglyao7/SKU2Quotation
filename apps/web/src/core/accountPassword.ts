export interface PasswordChangePayload {
  current_password: string;
  new_password: string;
}

export interface PasswordRuleResult {
  key: "length" | "letter" | "number" | "whitespace" | "identity";
  label: string;
  met: boolean;
}

export interface PasswordChangeValidation {
  currentPassword?: string;
  newPassword?: string;
  confirmation?: string;
}

export type PasswordStrength = "empty" | "weak" | "progressing" | "ready" | "strong";

export function passwordRules(password: string, identityCandidates: string[] = []): PasswordRuleResult[] {
  const normalizedPassword = password.toLocaleLowerCase();
  const normalizedIdentities = identityCandidates
    .map((candidate) => candidate.trim().toLocaleLowerCase())
    .filter(Boolean);

  return [
    { key: "length", label: "长度为 8-128 个字符", met: password.length >= 8 && password.length <= 128 },
    { key: "letter", label: "至少包含一个字母", met: /[A-Za-z]/.test(password) },
    { key: "number", label: "包含数字", met: /\d/.test(password) },
    { key: "whitespace", label: "不包含空白字符", met: Boolean(password) && !/\s/.test(password) },
    {
      key: "identity",
      label: "不能与账号或邮箱相同",
      met: Boolean(password) && !normalizedIdentities.includes(normalizedPassword),
    },
  ];
}

export function passwordStrength(password: string, rules: PasswordRuleResult[]): PasswordStrength {
  if (!password) return "empty";
  const metRules = rules.filter((rule) => rule.met).length;
  if (metRules === rules.length && password.length >= 12) return "strong";
  if (metRules === rules.length) return "ready";
  if (metRules >= 3) return "progressing";
  return "weak";
}

export function validatePasswordChange(input: {
  currentPassword: string;
  newPassword: string;
  confirmation: string;
  identityCandidates?: string[];
}): PasswordChangeValidation {
  const errors: PasswordChangeValidation = {};
  if (!input.currentPassword) errors.currentPassword = "请输入当前密码";

  const rules = passwordRules(input.newPassword, input.identityCandidates);
  if (!input.newPassword) {
    errors.newPassword = "请输入新密码";
  } else if (input.newPassword === input.currentPassword) {
    errors.newPassword = "新密码不能与当前密码相同";
  } else if (rules.some((rule) => !rule.met)) {
    errors.newPassword = "新密码还未满足全部安全要求";
  }

  if (!input.confirmation) {
    errors.confirmation = "请再次输入新密码";
  } else if (input.confirmation !== input.newPassword) {
    errors.confirmation = "两次输入的新密码不一致";
  }
  return errors;
}

export function buildPasswordChangePayload(
  currentPassword: string,
  newPassword: string,
): PasswordChangePayload {
  return {
    current_password: currentPassword,
    new_password: newPassword,
  };
}
