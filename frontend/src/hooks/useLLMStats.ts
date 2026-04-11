import { useQuery } from '@tanstack/react-query'
import { fetchLLMStats } from '@/api/dashboard'

export function useLLMStats() {
  return useQuery({
    queryKey: ['llm', 'stats'],
    queryFn: fetchLLMStats,
    staleTime: 60_000, // Model info doesn't change often
  })
}
