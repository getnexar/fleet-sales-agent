import { BrowserRouter, Routes, Route } from 'react-router-dom'
import ChatWidget from './components/ChatWidget'
import AdminPage from './pages/AdminPage'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/admin/*" element={<AdminPage />} />
        <Route path="*" element={<ChatWidget />} />
      </Routes>
    </BrowserRouter>
  )
}
