import { describe, it, expect, vi, beforeEach } from 'vitest';
import { getExtendedHoursInfo, searchStocks, fetchMarketStatus } from '../marketUtils';

// Mock the api client
vi.mock('@/api/client', () => ({
  api: {
    get: vi.fn(),
  },
}));

import { api } from '@/api/client';

describe('getExtendedHoursInfo', () => {
  it('returns nulls when marketStatus is null', () => {
    const result = getExtendedHoursInfo(null, { earlyTradingChangePercent: 1.5 });
    expect(result.extPct).toBeNull();
    expect(result.extLabel).toBeNull();
    expect(result.extType).toBeNull();
  });

  it('returns pre-market info during early hours', () => {
    const status = { market: 'open', afterHours: false, earlyHours: true };
    const data = { earlyTradingChangePercent: 2.5, previousClose: 100 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPct).toBe(2.5);
    expect(result.extLabel).toBe('Pre-Market');
    expect(result.extType).toBe('pre');
  });

  it('returns short label "PM" for pre-market when shortLabels is true', () => {
    const status = { market: 'open', afterHours: false, earlyHours: true };
    const data = { earlyTradingChangePercent: 1.0 };
    const result = getExtendedHoursInfo(status, data, { shortLabels: true });

    expect(result.extLabel).toBe('PM');
  });

  it('returns after-hours info when market is closed and latePct is available', () => {
    const status = { market: 'closed', afterHours: false, earlyHours: false };
    const data = { lateTradingChangePercent: -1.2, previousClose: 200 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPct).toBe(-1.2);
    expect(result.extLabel).toBe('After-Hours');
    expect(result.extType).toBe('post');
  });

  it('returns short label "AH" for after-hours when shortLabels is true', () => {
    const status = { market: 'closed', afterHours: false, earlyHours: false };
    const data = { lateTradingChangePercent: 0.5 };
    const result = getExtendedHoursInfo(status, data, { shortLabels: true });

    expect(result.extLabel).toBe('AH');
  });

  it('returns nulls during regular open market hours', () => {
    const status = { market: 'open', afterHours: false, earlyHours: false };
    const data = { earlyTradingChangePercent: 1.0, lateTradingChangePercent: -0.5 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPct).toBeNull();
    expect(result.extLabel).toBeNull();
    expect(result.extType).toBeNull();
  });

  it('computes extPrice and extChange from previousClose and extPct', () => {
    const status = { market: 'closed', afterHours: false, earlyHours: false };
    const data = { lateTradingChangePercent: 5.0, previousClose: 100 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPrice).toBe(105);
    expect(result.extChange).toBe(5);
    expect(result.prevClose).toBe(100);
  });

  it('handles snake_case field names (raw snapshot data)', () => {
    const status = { market: 'open', afterHours: false, earlyHours: true };
    const data = { early_trading_change_percent: 3.0, previous_close: 50 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPct).toBe(3.0);
    expect(result.extLabel).toBe('Pre-Market');
    expect(result.prevClose).toBe(50);
  });

  it('returns null extPrice when previousClose is absent', () => {
    const status = { market: 'closed', afterHours: false, earlyHours: false };
    const data = { lateTradingChangePercent: 2.0 };
    const result = getExtendedHoursInfo(status, data);

    expect(result.extPct).toBe(2.0);
    expect(result.extPrice).toBeNull();
    expect(result.extChange).toBeNull();
  });
});

describe('searchStocks', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns empty result for empty query', async () => {
    const result = await searchStocks('');
    expect(result).toEqual({ query: '', results: [], count: 0 });
    expect(api.get).not.toHaveBeenCalled();
  });

  it('returns empty result for whitespace-only query', async () => {
    const result = await searchStocks('   ');
    expect(result).toEqual({ query: '', results: [], count: 0 });
    expect(api.get).not.toHaveBeenCalled();
  });

  it('calls the API with trimmed query and returns data', async () => {
    const mockData = { query: 'AAPL', results: [{ symbol: 'AAPL' }], count: 1 };
    api.get.mockResolvedValue({ data: mockData });

    const result = await searchStocks(' AAPL ');
    expect(api.get).toHaveBeenCalledWith('/api/v1/market-data/search/stocks', {
      params: expect.any(URLSearchParams),
    });
    expect(result).toEqual(mockData);
  });

  it('clamps limit between 1 and 100', async () => {
    api.get.mockResolvedValue({ data: { query: 'X', results: [], count: 0 } });

    await searchStocks('X', 200);
    const params = api.get.mock.calls[0][1].params;
    expect(params.get('limit')).toBe('100');
  });

  it('returns fallback on API failure', async () => {
    api.get.mockRejectedValue(new Error('Network error'));

    const result = await searchStocks('AAPL');
    expect(result).toEqual({ query: 'AAPL', results: [], count: 0 });
  });
});

describe('fetchMarketStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('returns data from the API', async () => {
    const mockData = { market: 'open', afterHours: false, earlyHours: false };
    api.get.mockResolvedValue({ data: mockData });

    const result = await fetchMarketStatus();
    expect(api.get).toHaveBeenCalledWith('/api/v1/market-data/market-status', { signal: undefined });
    expect(result).toEqual(mockData);
  });

  it('returns empty object on API failure', async () => {
    api.get.mockRejectedValue(new Error('Server error'));

    const result = await fetchMarketStatus();
    expect(result).toEqual({});
  });

  it('re-throws AbortError (CanceledError)', async () => {
    const err = new Error('canceled');
    err.name = 'CanceledError';
    api.get.mockRejectedValue(err);

    await expect(fetchMarketStatus()).rejects.toThrow();
  });
});
