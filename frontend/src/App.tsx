import { Navigate, Route, Routes, useLocation, useParams } from 'react-router-dom'

import { CATEGORIES, type Category } from './api'
import { AppShell } from './app/AppShell'
import { ArtificialAnalysisPage } from './features/artificial-analysis/ArtificialAnalysisPage'
import { CategoriesPage } from './features/categories/CategoriesPage'
import { DataQualityPage } from './features/data-quality/DataQualityPage'
import { ModelDetailPage } from './features/models/ModelDetailPage'
import { OverviewPage } from './features/overview/OverviewPage'
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
        <Route index element={<OverviewPage />} />
        <Route path="categories" element={<CategoriesPage />} />
        <Route path="categories/:category" element={<CategoryPathRedirect />} />
        <Route path="artificial-analysis" element={<ArtificialAnalysisPage />} />
        <Route path="models/:key" element={<ModelDetailPage />} />
        <Route path="data-quality" element={<DataQualityPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}

export default App
