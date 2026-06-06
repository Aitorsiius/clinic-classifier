import { useState } from 'react';
import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { PasswordInput } from '../components/ui/password-input';
import { Alert, AlertDescription } from '../components/ui/alert';
import { AlertCircle, User, Lock, LogIn } from 'lucide-react';

export default function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const navigate = useNavigate();
  const { login } = useAuth();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    // Validar campos
    if (!username || !password) {
      setError('Por favor completa todos los campos');
      setIsLoading(false);
      return;
    }

    // Validar que el username tenga al menos 3 caracteres
    if (username.length < 3) {
      setError('El nombre de usuario debe tener al menos 3 caracteres');
      setIsLoading(false);
      return;
    }

    try {
      await login(username, password);
      navigate('/search');
    } catch (err) {
      let errorMessage = 'Error de login desconocido';
      
      if (err instanceof Error) {
        errorMessage = err.message;
      } else if (typeof err === 'string') {
        errorMessage = err;
      } else if (err && typeof err === 'object') {
        errorMessage = JSON.stringify(err);
      }
      
      setError(errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-100 p-4">
      {/* Manchas de color difuminadas para dar profundidad al fondo */}
      <div className="pointer-events-none absolute -left-24 -top-24 h-96 w-96 rounded-full bg-blue-400/20 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-16 h-96 w-96 rounded-full bg-indigo-400/20 blur-3xl" />
      <div className="pointer-events-none absolute right-1/4 top-1/3 h-72 w-72 rounded-full bg-cyan-300/20 blur-3xl" />

      <motion.div
        initial={{ opacity: 0, y: 24, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
        className="relative w-full max-w-md"
      >
        {/* Tarjeta con efecto cristal */}
        <div className="overflow-hidden rounded-3xl border border-white/60 bg-white/80 shadow-2xl shadow-blue-900/10 backdrop-blur-xl">
          {/* Cabecera con la mascota y el branding */}
          <div className="flex flex-col items-center gap-3 bg-gradient-to-b from-white/70 to-transparent px-8 pb-2 pt-9 text-center">
            <motion.img
              src="/chinchilla_close.png"
              alt="Clasificador CIE-10 ES"
              className="h-24 w-24 rounded-2xl object-contain drop-shadow-md"
              initial={{ rotate: -8, scale: 0.8 }}
              animate={{ rotate: 0, scale: 1 }}
              transition={{ delay: 0.15, type: 'spring', stiffness: 140, damping: 12 }}
            />
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-800">
                Clasificador <span className="text-blue-600">CIE-10 ES</span>
              </h1>
              <p className="mt-1 text-sm text-slate-500">
                Clasificación automática de diagnósticos médicos
              </p>
            </div>
          </div>

          {/* Formulario */}
          <div className="px-8 pb-8 pt-4">
            {error && (
              <Alert variant="destructive" className="mb-5">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <form onSubmit={handleSubmit} className="space-y-5">
              <div className="space-y-2">
                <label htmlFor="username" className="block text-sm font-medium text-slate-700">
                  Nombre de Usuario
                </label>
                <div className="relative">
                  <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                  <Input
                    id="username"
                    type="text"
                    placeholder="Introduce tu usuario"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    disabled={isLoading}
                    className="h-11 pl-10"
                  />
                </div>
              </div>

              <div className="space-y-2">
                <label htmlFor="password" className="block text-sm font-medium text-slate-700">
                  Contraseña
                </label>
                <PasswordInput
                  id="password"
                  placeholder="Introduce tu contraseña"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                  className="h-11"
                  leftIcon={<Lock className="h-4 w-4" />}
                />
              </div>

              <Button
                type="submit"
                variant="brand"
                disabled={isLoading}
                className="h-11 w-full text-base"
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    Accediendo...
                  </span>
                ) : (
                  <>
                    <LogIn className="mr-1 h-4 w-4" />
                    Iniciar Sesión
                  </>
                )}
              </Button>
            </form>
          </div>
        </div>

        {/* Pie sutil */}
        <p className="mt-6 text-center text-xs text-slate-400">
          Acceso restringido · Clasificador CIE-10 ES
        </p>
      </motion.div>
    </div>
  );
}
