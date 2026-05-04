import { useQuery } from '@tanstack/react-query'
import { fetchLLMStats, fetchLLMLive, fetchEmbeddingsLive } from '@/api/dashboard'

export function useLLMStats() {
  return useQuery({
    queryKey: ['llm', 'stats'],
    queryFn: fetchLLMStats,
    staleTime: 60_000, // Model info doesn't change often
  })
}

/**
 * Live runtime metrics from the inference server (Prometheus scrape).
 * Polls every 3s — cheap on vLLM (single GET), gives a real-time feel.
 */
export function useLLMLive() {
  return useQuery({
    queryKey: ['llm', 'live'],
    queryFn: fetchLLMLive,
    refetchInterval: 3_000,
    staleTime: 1_000,
  })
}

export function useEmbeddingsLive() {
  return useQuery({
    queryKey: ['embeddings', 'live'],
    queryFn: fetchEmbeddingsLive,
    refetchInterval: 3_000,
    staleTime: 1_000,
  })
}
