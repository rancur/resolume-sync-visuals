import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import ErrorBoundary from './components/ErrorBoundary'
import './index.css'
import App from './App'

const root = document.getElementById('root')

if (!root) {
  document.body.innerHTML = '<div style="color:red;padding:20px;font-family:monospace">Fatal: #root element not found</div>'
} else {
  try {
    createRoot(root).render(
      <StrictMode>
        <ErrorBoundary>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </ErrorBoundary>
      </StrictMode>,
    )
  } catch (e) {
    root.innerHTML = '<div style="color:red;padding:20px;font-family:monospace">React failed to mount: ' +
      (e instanceof Error ? e.message : String(e)) + '</div>'
    console.error('React mount error:', e)
  }
}
