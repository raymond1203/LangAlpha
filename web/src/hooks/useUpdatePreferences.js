import { useMutation, useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '../lib/queryKeys';
import { updatePreferences } from '../pages/Dashboard/utils/api';

/**
 * Mutation hook for updating user preferences.
 * Uses setQueryData on success for instant propagation to all usePreferences() consumers.
 */
export function useUpdatePreferences() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: updatePreferences,
    onSuccess: (updatedPrefs) => {
      queryClient.setQueryData(queryKeys.user.preferences(), updatedPrefs);
    },
    onError: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.user.preferences() });
    },
  });
}
