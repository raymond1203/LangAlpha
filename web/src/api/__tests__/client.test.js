import { describe, it, expect, vi, beforeEach } from 'vitest';
import { setTokenGetter } from '../client';

describe('setTokenGetter', () => {
  beforeEach(() => {
    setTokenGetter(null);
  });

  it('accepts a function that will be used for auth', () => {
    const getter = vi.fn(() => Promise.resolve('test-token'));
    expect(() => setTokenGetter(getter)).not.toThrow();
  });

  it('accepts null to clear the token getter', () => {
    expect(() => setTokenGetter(null)).not.toThrow();
  });
});

describe('api axios instance', () => {
  it('exports an api object with expected methods', async () => {
    const { api } = await import('../client');
    expect(api).toBeDefined();
    expect(typeof api.get).toBe('function');
    expect(typeof api.post).toBe('function');
    expect(typeof api.put).toBe('function');
    expect(typeof api.delete).toBe('function');
  });

  it('has JSON content-type as default header', async () => {
    const { api } = await import('../client');
    expect(api.defaults.headers.common?.['Content-Type'] || api.defaults.headers['Content-Type']).toBe('application/json');
  });

  it('has interceptors registered', async () => {
    const { api } = await import('../client');
    // Axios interceptors have a handlers array
    expect(api.interceptors.request.handlers.length).toBeGreaterThan(0);
    expect(api.interceptors.response.handlers.length).toBeGreaterThan(0);
  });
});

describe('request interceptor behavior', () => {
  it('attaches Bearer token when token getter is set', async () => {
    const { api } = await import('../client');
    setTokenGetter(() => Promise.resolve('my-token'));

    // Get the request interceptor handler
    const handler = api.interceptors.request.handlers[0];
    const interceptor = handler.fulfilled;

    const config = { headers: {} };
    const result = await interceptor(config);
    expect(result.headers.Authorization).toBe('Bearer my-token');
  });

  it('does not attach Authorization when token getter is null', async () => {
    const { api } = await import('../client');
    setTokenGetter(null);

    const handler = api.interceptors.request.handlers[0];
    const interceptor = handler.fulfilled;

    const config = { headers: {} };
    const result = await interceptor(config);
    expect(result.headers.Authorization).toBeUndefined();
  });

  it('proceeds without auth when token getter throws', async () => {
    const { api } = await import('../client');
    setTokenGetter(() => Promise.reject(new Error('auth error')));

    const handler = api.interceptors.request.handlers[0];
    const interceptor = handler.fulfilled;

    const config = { headers: {} };
    const result = await interceptor(config);
    expect(result.headers.Authorization).toBeUndefined();
  });
});

describe('response interceptor behavior (429 handling)', () => {
  it('enriches 429 errors with rateLimitInfo and retryAfter', async () => {
    const { api } = await import('../client');

    const handler = api.interceptors.response.handlers[0];
    const errorHandler = handler.rejected;

    const error = {
      response: {
        status: 429,
        data: { detail: { message: 'Too many requests', limit: 10 } },
        headers: { 'retry-after': '30' },
      },
    };

    await expect(errorHandler(error)).rejects.toMatchObject({
      status: 429,
      rateLimitInfo: { message: 'Too many requests', limit: 10 },
      retryAfter: 30,
    });
  });

  it('rejects non-429 errors without enrichment', async () => {
    const { api } = await import('../client');

    const handler = api.interceptors.response.handlers[0];
    const errorHandler = handler.rejected;

    const error = {
      response: { status: 500, data: { detail: 'Server error' } },
    };

    await expect(errorHandler(error)).rejects.toBe(error);
    expect(error.rateLimitInfo).toBeUndefined();
  });
});
