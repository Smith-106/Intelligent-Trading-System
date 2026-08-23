/**
 * Shared strategies query (REV-019-RV6).
 *
 * ["strategies"] was observed by four panels with diverging refetchInterval
 * configs — TanStack takes the LAST active observer's interval, so polling
 * depended on navigation order. All consumers now share this hook.
 */

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api-client";

export function useStrategiesQuery() {
  return useQuery({
    queryKey: ["strategies"],
    queryFn: () => api.strategies(),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}
