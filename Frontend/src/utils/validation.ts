export function validateUsername(value: string): string | null {
  const username = value.trim();
  if (!username) return 'Enter your username.';
  if (username.length > 64) return 'Usernames are at most 64 characters.';
  return null;
}

export function validateRequired(value: string, label: string): string | null {
  return value.trim() ? null : `Enter your ${label.toLowerCase()}.`;
}

export const PASSWORD_RULES: { id: string; label: string; test: (value: string) => boolean }[] = [
  { id: 'length', label: 'At least 12 characters', test: (value) => value.length >= 12 },
  { id: 'case', label: 'Upper and lower case letters', test: (value) => /[a-z]/.test(value) && /[A-Z]/.test(value) },
  { id: 'number', label: 'At least one number', test: (value) => /\d/.test(value) },
  { id: 'symbol', label: 'At least one symbol', test: (value) => /[^A-Za-z0-9]/.test(value) },
];

export function validateNewPassword(value: string): string | null {
  if (!value) return 'Enter a new password.';
  const failed = PASSWORD_RULES.find((rule) => !rule.test(value));
  return failed ? `Password needs: ${failed.label.toLowerCase()}.` : null;
}

export interface LoginFormErrors {
  username?: string;
  password?: string;
}

export function validateLoginForm(username: string, password: string): LoginFormErrors {
  const errors: LoginFormErrors = {};
  const usernameError = validateUsername(username);
  if (usernameError) errors.username = usernameError;
  if (!password) errors.password = 'Enter your password.';
  return errors;
}

export function hasErrors(errors: object): boolean {
  return Object.values(errors).some(Boolean);
}
