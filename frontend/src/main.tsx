import React from 'react'
import ReactDOM from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { App } from './App'
import './index.css'
import { Assistant } from './pages/Assistant'
import { Batches } from './pages/Batches'
import { Channels } from './pages/Channels'
import { Clips } from './pages/Clips'
import { ErrorBoundary, RouteError } from './components/ErrorBoundary'
import { Ingest } from './pages/Ingest'
import { JobProgress } from './pages/JobProgress'
import { Providers } from './pages/Providers'
import { Recovery } from './pages/Recovery'
import { Review } from './pages/Review'
import { Routing } from './pages/Routing'
import { Settings } from './pages/Settings'
import { Trends } from './pages/Trends'
import { Workflows } from './pages/Workflows'

const router = createBrowserRouter([
  {
    path: '/',
    element: <App />,
    // A screen that crashes while rendering is caught here — React Router
    // handles route errors before an outer React boundary ever sees them.
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Ingest /> },
      { path: 'clips', element: <Clips /> },
      { path: 'assistant', element: <Assistant /> },
      { path: 'recovery', element: <Recovery /> },
      { path: 'trends', element: <Trends /> },
      { path: 'workflows', element: <Workflows /> },
      { path: 'providers', element: <Providers /> },
      { path: 'channels', element: <Channels /> },
      { path: 'routing', element: <Routing /> },
      { path: 'batches', element: <Batches /> },
      { path: 'jobs/:jobId', element: <JobProgress /> },
      { path: 'jobs/:jobId/clips', element: <Review /> },
      { path: 'settings', element: <Settings /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
    </ErrorBoundary>
  </React.StrictMode>,
)
