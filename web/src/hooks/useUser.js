import { useQuery } from '@tanstack/react-query';
import { queryKeys } from '../lib/queryKeys';
import { getCurrentUser } from '../pages/Dashboard/utils/api';

/**
 * Shared hook for current user profile data.
 * Replaces manual useEffect+useState fetching of /api/v1/users/me.
 * All consumers share a single cached entry — updates propagate automatically.
 */
export function useUser() {
  const { data, ...rest } = useQuery({
    queryKey: queryKeys.user.me(),
    queryFn: async () => {
      const res = await getCurrentUser();
      return res.user ?? res;
    },
    staleTime: 5 * 60_000,
    retry: false,
  });
  return { user: data ?? null, ...rest };
}
