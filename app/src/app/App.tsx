import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { SessionProvider } from './context/SessionContext';
import { PrivateRoute } from './components/PrivateRoute';
import { LogoutOverlay } from './components/LogoutOverlay';
import LoginPage from './pages/LoginPage';
import AuditPage from './pages/AuditPage';
import SearchPage from './pages/SearchPage';
import AdminPage from './pages/AdminPage';

export default function App() {
  return (
    <Router>
      <AuthProvider>
        <SessionProvider>
          <Routes>
            {/* Public Routes */}
            <Route path="/search" element={<SearchPage />} />
            <Route path="/login" element={<LoginPage />} />

            {/* Protected Routes */}
            <Route
              path="/audit"
              element={
                <PrivateRoute>
                  <AuditPage />
                </PrivateRoute>
              }
            />

            {/* Admin Routes */}
            <Route
              path="/admin"
              element={
                <PrivateRoute>
                  <AdminPage />
                </PrivateRoute>
              }
            />

            {/* Default redirect to search */}
            <Route path="/" element={<Navigate to="/search" replace />} />
            <Route path="*" element={<Navigate to="/search" replace />} />
          </Routes>

          {/* Overlay global para la animación de cierre de sesión */}
          <LogoutOverlay />
        </SessionProvider>
      </AuthProvider>
    </Router>
  );
}
