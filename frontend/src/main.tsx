// Standalone dev harness — not included in the library build
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RagModule } from './RagModule'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RagModule
      baseUrl={(import.meta as any).env?.VITE_API_BASE_URL || ''}
      datasource="qsint_docs"
      height="100vh"
    />
  </StrictMode>,
)
