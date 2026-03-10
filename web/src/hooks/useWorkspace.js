import { useQuery, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../lib/queryKeys';
import { getWorkspace } from '../pages/ChatAgent/utils/api';

/**
 * Shared hook for a single workspace's details.
 * Derives initialData from cached workspace lists to avoid redundant fetches.
 */
export function useWorkspace(workspaceId) {
  const queryClient = useQueryClient();

  return useQuery({
    queryKey: queryKeys.workspaces.detail(workspaceId),
    queryFn: () => getWorkspace(workspaceId),
    enabled: !!workspaceId,
    staleTime: 5 * 60_000,
    initialData: () => {
      // Try to derive from any cached workspace list
      const queries = queryClient.getQueriesData({ queryKey: queryKeys.workspaces.lists() });
      for (const [, data] of queries) {
        const ws = data?.workspaces?.find((w) => w.workspace_id === workspaceId);
        if (ws) return ws;
      }
      return undefined;
    },
  });
}
