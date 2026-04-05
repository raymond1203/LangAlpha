import { describe, it, expect } from 'vitest';
import { buildRateLimitError } from '../rateLimitError';

describe('buildRateLimitError', () => {
  it('returns message + link for credit_limit when accountUrl is set', () => {
    const result = buildRateLimitError(
      { type: 'credit_limit', used_credits: 80, credit_limit: 100 },
      'https://ginlix.ai/account',
    );
    expect(result.message).toBe('Daily credit limit reached (80/100 credits). Resets at midnight UTC.');
    expect(result.link).toEqual({
      url: 'https://ginlix.ai/account/usage',
      label: 'View Usage',
    });
  });

  it('returns message without link for credit_limit when accountUrl is not set', () => {
    const result = buildRateLimitError(
      { type: 'credit_limit', used_credits: 80, credit_limit: 100 },
    );
    expect(result.message).toBe('Daily credit limit reached (80/100 credits). Resets at midnight UTC.');
    expect(result.link).toBeUndefined();
  });

  it('returns message without link for credit_limit when accountUrl is null', () => {
    const result = buildRateLimitError(
      { type: 'credit_limit', used_credits: 50, credit_limit: 50 },
      null,
    );
    expect(result.message).toContain('Daily credit limit reached');
    expect(result.link).toBeUndefined();
  });

  it('returns workspace_limit message with no link', () => {
    const result = buildRateLimitError(
      { type: 'workspace_limit', current: 3, limit: 3 },
      'https://ginlix.ai/account',
    );
    expect(result.message).toBe('Active workspace limit reached (3/3). Stop or delete an existing workspace to free up a slot.');
    expect(result.link).toBeUndefined();
  });

  it('returns burst_limit message', () => {
    const result = buildRateLimitError(
      { type: 'burst_limit' },
      'https://ginlix.ai/account',
    );
    expect(result.message).toBe('Too many concurrent requests. Please wait a moment.');
    expect(result.link).toBeUndefined();
  });

  it('returns message + link for negative_balance when accountUrl is set', () => {
    const result = buildRateLimitError(
      { type: 'negative_balance', message: 'Outstanding credit balance. Please add credits to continue.' },
      'https://ginlix.ai/account',
    );
    expect(result.message).toBe('Outstanding credit balance. Please add credits to continue.');
    expect(result.link).toEqual({
      url: 'https://ginlix.ai/account/usage',
      label: 'View Usage',
    });
  });

  it('falls back to info.message for unknown types', () => {
    const result = buildRateLimitError(
      { type: 'unknown', message: 'Custom rate limit message' },
    );
    expect(result.message).toBe('Custom rate limit message');
    expect(result.link).toBeUndefined();
  });

  it('falls back to generic message when no type or message', () => {
    const result = buildRateLimitError({});
    expect(result.message).toBe('Rate limit exceeded. Please try again later.');
    expect(result.link).toBeUndefined();
  });
});
