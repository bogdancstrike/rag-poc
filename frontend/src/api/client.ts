import axios from 'axios'

// Base URL comes from Vite env or defaults to same-origin (proxied by vite dev server)
// QF framework prefixes all endpoints with /<namespace>/ — ours is /rag/
const BASE_URL = ((import.meta as any).env?.VITE_API_BASE_URL || '') + '/rag'

export const apiClient = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
  timeout: 30_000,
})

apiClient.interceptors.response.use(
  (r) => r,
  (err) => {
    const msg = err.response?.data?.error || err.message || 'Request failed'
    return Promise.reject(new Error(msg))
  },
)

/** Raw base URL for SSE fetch streams (axios cannot stream SSE) */
export const API_BASE = BASE_URL
