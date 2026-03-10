import { useState, useCallback, useMemo } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useWorkspaces } from '../../../hooks/useWorkspaces';
import { queryKeys } from '../../../lib/queryKeys';
import { getWorkspaces, getWorkspaceThreads } from '../utils/api';

/**
 * useNavigationData — fetches workspace + thread data for the navigation panel.
 *
 * Display order: 2 most recent unpinned → pinned → remaining unpinned (up to 5).
 * "Load more" fetches the next page and appends.
 *
 * @param {string} currentWorkspaceId
 * @returns {{ workspaces, workspaceThreads, loading, hasMore, loadAll, expandWorkspace }}
 */
const NAV_WS_PARAMS = { limit: 20, sortBy: 'custom' };

export function useNavigationData(currentWorkspaceId) {
  const queryClient = useQueryClient();

  // Workspace list via React Query
  const { data: wsData, isLoading } = useWorkspaces(NAV_WS_PARAMS);
  const allFetched = wsData?.workspaces || [];
  const totalCount = wsData?.total || 0;

  const [workspaceThreads, setWorkspaceThreads] = useState({});
  const [visibleCount, setVisibleCount] = useState(9); // 2 recent + pinned + 5 rest initially

  // Build ordered workspace list: 2 most recent → remaining pinned → rest
  const workspaces = useMemo(() => {
    if (!allFetched.length) return [];

    // First 2 most recent (pinned or not — API returns by recency)
    const recentTwo = allFetched.slice(0, 2);
    const recentIds = new Set(recentTwo.map((ws) => ws.workspace_id));

    // Remaining pinned that aren't already in recent two
    const remainingPinned = allFetched.filter((ws) => ws.is_pinned && !recentIds.has(ws.workspace_id));
    const pinnedIds = new Set(remainingPinned.map((ws) => ws.workspace_id));

    // Rest: everything not in recent two or remaining pinned
    const rest = allFetched.filter((ws) => !recentIds.has(ws.workspace_id) && !pinnedIds.has(ws.workspace_id));

    const ordered = [...recentTwo, ...remainingPinned, ...rest];
    const sliced = ordered.slice(0, visibleCount);
    // Always include the current workspace even if it fell outside the visible slice
    if (currentWorkspaceId && !sliced.some((ws) => ws.workspace_id === currentWorkspaceId)) {
      const currentWs = allFetched.find((ws) => ws.workspace_id === currentWorkspaceId);
      if (currentWs) sliced.unshift(currentWs);
    }
    return sliced;
  }, [allFetched, visibleCount, currentWorkspaceId]);

  const hasMore = useMemo(() => {
    // More to show from already fetched
    if (visibleCount < allFetched.length) return true;
    // More to fetch from server
    if (allFetched.length < totalCount) return true;
    return false;
  }, [visibleCount, allFetched.length, totalCount]);

  // Subscribe to current workspace's threads via useQuery — auto-updates when cache is invalidated
  const { data: currentWsThreadData, isLoading: currentWsThreadsLoading } = useQuery({
    queryKey: queryKeys.threads.byWorkspace(currentWorkspaceId),
    queryFn: () => getWorkspaceThreads(currentWorkspaceId, 10, 0),
    enabled: !!currentWorkspaceId,
    staleTime: 30_000,
  });

  // Merge current workspace's thread data directly (avoids useEffect sync lag)
  const mergedThreads = useMemo(() => ({
    ...workspaceThreads,
    ...(currentWorkspaceId && currentWsThreadData !== undefined ? {
      [currentWorkspaceId]: {
        threads: currentWsThreadData?.threads || [],
        loading: currentWsThreadsLoading,
      },
    } : currentWorkspaceId ? {
      [currentWorkspaceId]: {
        threads: workspaceThreads[currentWorkspaceId]?.threads || [],
        loading: true,
      },
    } : {}),
  }), [workspaceThreads, currentWorkspaceId, currentWsThreadData, currentWsThreadsLoading]);

  // Lazy-load threads for a workspace on expand
  const expandWorkspace = useCallback((wsId) => {
    const cached = queryClient.getQueryData(queryKeys.threads.byWorkspace(wsId));
    if (cached) {
      setWorkspaceThreads(prev => ({
        ...prev,
        [wsId]: { threads: cached.threads || [], loading: false },
      }));
      return;
    }

    setWorkspaceThreads(prev => ({
      ...prev,
      [wsId]: { threads: prev[wsId]?.threads || [], loading: true },
    }));

    queryClient.fetchQuery({
      queryKey: queryKeys.threads.byWorkspace(wsId),
      queryFn: () => getWorkspaceThreads(wsId, 10, 0),
      staleTime: 30_000,
    }).then(data => {
      setWorkspaceThreads(prev => ({
        ...prev,
        [wsId]: { threads: data.threads || [], loading: false },
      }));
    }).catch(() => {
      setWorkspaceThreads(prev => ({
        ...prev,
        [wsId]: { threads: [], loading: false },
      }));
    });
  }, [queryClient]);

  const loadAll = useCallback(async () => {
    setVisibleCount(Infinity);

    if (allFetched.length < totalCount) {
      try {
        // Fetch remaining and let query cache handle it
        const data = await getWorkspaces(100, allFetched.length, 'custom');
        // Merge into current query data
        queryClient.setQueryData(queryKeys.workspaces.list({ ...NAV_WS_PARAMS, offset: 0 }), (old) => {
          if (!old) return data;
          const existingIds = new Set(old.workspaces.map(w => w.workspace_id));
          const unique = (data.workspaces || []).filter(w => !existingIds.has(w.workspace_id));
          return { ...old, workspaces: [...old.workspaces, ...unique], total: data.total || old.total };
        });
      } catch (e) {
        console.warn('[useNavigationData] Failed to load all workspaces:', e);
      }
    }
  }, [allFetched.length, totalCount, queryClient]);

  return { workspaces, workspaceThreads: mergedThreads, loading: isLoading, hasMore, loadAll, expandWorkspace };
}
