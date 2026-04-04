import { Suspense, lazy, useState, useEffect } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import ErrorBoundary from './components/ErrorBoundary'
import LoadingSpinner from './components/LoadingSpinner'
import { api } from './api/client'

// Lazy-load all page components to reduce initial bundle size
const Dashboard = lazy(() => import('./pages/Dashboard'))
const Library = lazy(() => import('./pages/Library'))
const TrackDetail = lazy(() => import('./pages/TrackDetail'))
const GenerationQueue = lazy(() => import('./pages/GenerationQueue'))
const BudgetDashboard = lazy(() => import('./pages/BudgetDashboard'))
const BrandEditor = lazy(() => import('./pages/BrandEditor'))
const ModelSelection = lazy(() => import('./pages/ModelSelection'))
const Settings = lazy(() => import('./pages/Settings'))
const ResolumeSettings = lazy(() => import('./pages/ResolumeSettings'))
const Genres = lazy(() => import('./pages/Genres'))
const Logs = lazy(() => import('./pages/Logs'))
const SetupWizard = lazy(() => import('./pages/SetupWizard'))
const Presets = lazy(() => import('./pages/Presets'))
const ComparisonViewer = lazy(() => import('./pages/ComparisonViewer'))
const Setlists = lazy(() => import('./pages/Setlists'))
const OscControl = lazy(() => import('./pages/OscControl'))
const TimelineEditor = lazy(() => import('./pages/TimelineEditor'))

function LazyPage({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      <Suspense fallback={<LoadingSpinner />}>
        {children}
      </Suspense>
    </ErrorBoundary>
  )
}

function App() {
  const [setupComplete, setSetupComplete] = useState<boolean | null>(null)

  useEffect(() => {
    api.getSetupStatus()
      .then((status) => setSetupComplete(status.setup_complete))
      .catch(() => setSetupComplete(true)) // If check fails, assume setup done
  }, [])

  // Loading state while checking setup
  if (setupComplete === null) {
    return <LoadingSpinner />
  }

  // Show setup wizard if not configured
  if (!setupComplete) {
    return (
      <ErrorBoundary>
        <Suspense fallback={<LoadingSpinner />}>
          <SetupWizard onComplete={() => setSetupComplete(true)} />
        </Suspense>
      </ErrorBoundary>
    )
  }

  return (
    <ErrorBoundary>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<LazyPage><Dashboard /></LazyPage>} />
          <Route path="library" element={<LazyPage><Library /></LazyPage>} />
          <Route path="library/:trackId" element={<LazyPage><TrackDetail /></LazyPage>} />
          <Route path="genres" element={<LazyPage><Genres /></LazyPage>} />
          <Route path="queue" element={<LazyPage><GenerationQueue /></LazyPage>} />
          <Route path="budget" element={<LazyPage><BudgetDashboard /></LazyPage>} />
          <Route path="brand-editor" element={<LazyPage><BrandEditor /></LazyPage>} />
          <Route path="models" element={<LazyPage><ModelSelection /></LazyPage>} />
          <Route path="settings" element={<LazyPage><Settings /></LazyPage>} />
          <Route path="resolume" element={<LazyPage><ResolumeSettings /></LazyPage>} />
          <Route path="presets" element={<LazyPage><Presets /></LazyPage>} />
          <Route path="compare" element={<LazyPage><ComparisonViewer /></LazyPage>} />
          <Route path="setlists" element={<LazyPage><Setlists /></LazyPage>} />
          <Route path="osc" element={<LazyPage><OscControl /></LazyPage>} />
          <Route path="timeline" element={<LazyPage><TimelineEditor /></LazyPage>} />
          <Route path="logs" element={<LazyPage><Logs /></LazyPage>} />
        </Route>
      </Routes>
    </ErrorBoundary>
  )
}

export default App
