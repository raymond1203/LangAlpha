/**
 * Hierarchical query key factory for React Query.
 *
 * Each level builds on its parent to enable prefix-based invalidation:
 *   invalidateQueries({ queryKey: queryKeys.user.all })
 *     → invalidates me, preferences, apiKeys
 *   invalidateQueries({ queryKey: queryKeys.workspaces.lists() })
 *     → invalidates all workspace list queries (any page/sort)
 */
export const queryKeys = {
  user: {
    all:         ['user'],
    me:          () => [...queryKeys.user.all, 'me'],
    preferences: () => [...queryKeys.user.all, 'preferences'],
    apiKeys:     () => [...queryKeys.user.all, 'api-keys'],
  },
  models: {
    all: ['models'],
  },
  oauth: {
    all:    ['oauth'],
    codex:  () => [...queryKeys.oauth.all, 'codex'],
    claude: () => [...queryKeys.oauth.all, 'claude'],
  },
  workspaces: {
    all:    ['workspaces'],
    lists:  () => [...queryKeys.workspaces.all, 'list'],
    list:   (params) => [...queryKeys.workspaces.lists(), params],
    detail: (id) => [...queryKeys.workspaces.all, 'detail', id],
    flash:  () => [...queryKeys.workspaces.all, 'flash'],
  },
  threads: {
    all:         ['threads'],
    byWorkspace: (wsId) => [...queryKeys.threads.all, 'workspace', wsId],
    detail:      (threadId) => [...queryKeys.threads.all, 'detail', threadId],
  },
  workspaceFiles: {
    all:  ['workspaceFiles'],
    byWs: (wsId, opts) => [...queryKeys.workspaceFiles.all, wsId, opts],
  },
};
