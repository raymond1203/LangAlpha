import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHookWithProviders } from '../../test/utils';
import { useWorkspaces } from '../useWorkspaces';
import { waitFor } from '@testing-library/react';

vi.mock('../../pages/ChatAgent/utils/api', () => ({
  getWorkspaces: vi.fn(),
}));

import { getWorkspaces } from '../../pages/ChatAgent/utils/api';

describe('useWorkspaces', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches workspaces with default parameters', async () => {
    const mockData = { workspaces: [{ workspace_id: 'ws-1' }], total: 1 };
    getWorkspaces.mockResolvedValue(mockData);

    const { result } = renderHookWithProviders(() => useWorkspaces());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(mockData);
    expect(getWorkspaces).toHaveBeenCalledWith(20, 0, 'custom');
  });

  it('passes custom limit, offset, and sortBy', async () => {
    getWorkspaces.mockResolvedValue({ workspaces: [], total: 0 });

    const { result } = renderHookWithProviders(
      () => useWorkspaces({ limit: 10, offset: 5, sortBy: 'name' })
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(getWorkspaces).toHaveBeenCalledWith(10, 5, 'name');
  });

  it('does not fetch when enabled is false', () => {
    const { result } = renderHookWithProviders(
      () => useWorkspaces({ enabled: false })
    );

    expect(result.current.isFetching).toBe(false);
    expect(getWorkspaces).not.toHaveBeenCalled();
  });

  it('handles API errors gracefully', async () => {
    getWorkspaces.mockRejectedValue(new Error('Network error'));

    const { result } = renderHookWithProviders(() => useWorkspaces());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error).toBeInstanceOf(Error);
  });

  it('uses the correct query key structure', async () => {
    getWorkspaces.mockResolvedValue({ workspaces: [], total: 0 });

    const { result, queryClient } = renderHookWithProviders(
      () => useWorkspaces({ limit: 5, offset: 0, sortBy: 'custom' })
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // The query key should match queryKeys.workspaces.list(params)
    const cachedData = queryClient.getQueryData([
      'workspaces', 'list', { limit: 5, offset: 0, sortBy: 'custom' },
    ]);
    expect(cachedData).toEqual({ workspaces: [], total: 0 });
  });
});
