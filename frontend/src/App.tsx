import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'

import { CATEGORIES, type Category } from './api'
import { AppShell } from './app/AppShell'
import { ArtificialAnalysisPage } from './features/artificial-analysis/ArtificialAnalysisPage'
import { CategoriesPage } from './features/categories/CategoriesPage'
import { DataQualityPage } from './features/data-quality/DataQualityPage'
import { DiscussionDetailPage } from './features/discussions/DiscussionDetailPage'
import { DiscussionMapPage } from './features/discussions/DiscussionMapPage'
import { DiscussionsPage } from './features/discussions/DiscussionsPage'
import { HomePage } from './features/home/HomePage'
import { InterimCheckInPage } from './features/interim/InterimCheckInPage'
import { ModelDetailPage } from './features/models/ModelDetailPage'
import { OverviewPage } from './features/overview/OverviewPage'
import { PerformanceVsCostPage } from './features/visualizations/PerformanceVsCostPage'
import { CostPerTaskPage } from './features/visualizations/CostPerTaskPage'
import { TaskFitPage } from './features/visualizations/TaskFitPage'
import { ModelCardPage } from './features/visualizations/ModelCardPage'
import './App.css'

function CategoryPathRedirect() {
  const { category } = useParams()
  const location = useLocation()
  const search = new URLSearchParams(location.search)
  if (category && CATEGORIES.includes(category as Category)) {
    search.set('category', category)
  }
  return <Navigate replace to={{ pathname: '/categories', search: search.toString() }} />
}

function NotFoundPage() {
  return (
    <main className="page page--state">
      <p className="error-code">404</p>
      <h1>Page not found</h1>
      <p>The requested view does not exist.</p>
    </main>
  )
}

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<HomePage />} />
        <Route path="interim-check-in" element={<InterimCheckInPage />} />
        <Route
          path="visualizations/performance-vs-cost"
          element={<PerformanceVsCostPage />}
        />
        <Route
          path="visualizations/cost-per-task"
          element={<CostPerTaskPage />}
        />
        <Route path="visualizations/task-fit" element={<TaskFitPage />} />
        <Route path="visualizations/model-card" element={<ModelCardPage />} />
        <Route path="models" element={<OverviewPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="categories/:category" element={<CategoryPathRedirect />} />
        <Route path="artificial-analysis" element={<ArtificialAnalysisPage />} />
        <Route path="models/:key" element={<ModelDetailPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="discussions" element={<DiscussionsPage />} />
        {/*
          Before `discussions/:hnId`, and that ordering is load-bearing rather
          than cosmetic: React Router ranks a static segment above a dynamic one
          so this resolves either way, but the day that ranking changes, `map`
          would silently become a thread id and the page would 404. A test pins
          the behaviour.
        */}
        <Route path="discussions/map" element={<DiscussionMapPage />} />
        <Route path="discussions/:hnId" element={<DiscussionDetailPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
