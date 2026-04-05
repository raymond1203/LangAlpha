/**
 * Shared rate-limit error builder.
 *
 * Constructs a structured error from a 429 response's `rateLimitInfo`
 * so both ChatAgent and MarketView produce identical messages and,
 * when the account portal URL is configured, a "View Usage" deep-link.
 */

export interface RateLimitErrorInfo {
  type?: string;
  used_credits?: number;
  credit_limit?: number;
  current?: number;
  limit?: number;
  message?: string;
  [key: string]: unknown;
}

export interface StructuredError {
  message: string;
  link?: { url: string; label: string };
}

export function buildRateLimitError(
  info: RateLimitErrorInfo,
  accountUrl?: string | null,
): StructuredError {
  let message: string;

  if (info.type === 'credit_limit') {
    message = `Daily credit limit reached (${info.used_credits}/${info.credit_limit} credits). Resets at midnight UTC.`;
  } else if (info.type === 'negative_balance') {
    message = (info.message as string) || 'Outstanding credit balance. Please add credits to continue.';
  } else if (info.type === 'workspace_limit') {
    message = `Active workspace limit reached (${info.current}/${info.limit}). Stop or delete an existing workspace to free up a slot.`;
  } else if (info.type === 'burst_limit') {
    message = `Too many concurrent requests. Please wait a moment.`;
  } else {
    message = (info.message as string) || 'Rate limit exceeded. Please try again later.';
  }

  const link =
    accountUrl && (info.type === 'credit_limit' || info.type === 'negative_balance')
      ? { url: `${accountUrl}/usage`, label: 'View Usage' }
      : undefined;

  return { message, link };
}
