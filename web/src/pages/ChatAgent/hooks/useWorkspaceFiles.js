import { useCallback } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../../../lib/queryKeys';
import { listWorkspaceFiles } from '../utils/api';

/**
 * Shared hook for workspace file listing.
 * Uses React Query for automatic caching, retry, and deduplication.
 *
 * @param {string} workspaceId
 * @param {{ includeSystem?: boolean }} options
 * @returns {{ files: string[], loading: boolean, error: string|null, refresh: () => void }}
 */
export function useWorkspaceFiles(workspaceId, { includeSystem = false } = {}) {
  const queryClient = useQueryClient();
  const opts = { includeSystem };

  const { data, isLoading, error } = useQuery({
    queryKey: queryKeys.workspaceFiles.byWs(workspaceId, opts),
    queryFn: () => listWorkspaceFiles(workspaceId, '.', { autoStart: false, includeSystem }),
    enabled: !!workspaceId,
    retry: (count, err) => count < 3 && [500, 503].includes(err?.response?.status),
    retryDelay: (attempt) => (attempt + 1) * 1000, // 1s, 2s, 3s
    staleTime: 30_000,
  });

  const refresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: queryKeys.workspaceFiles.byWs(workspaceId, { includeSystem }) });
  }, [queryClient, workspaceId, includeSystem]);

  return {
    files: data?.files || [],
    loading: isLoading,
    error: error ? (error.response?.status === 503 ? 'Sandbox not available' : 'Failed to load files') : null,
    refresh,
  };
}
