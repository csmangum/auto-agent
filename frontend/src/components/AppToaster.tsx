import { Toaster } from 'sonner';
import { useTheme } from '../context/ThemeContext';

export default function AppToaster() {
  const { resolvedTheme } = useTheme();
  return <Toaster theme={resolvedTheme} position="top-right" richColors closeButton />;
}
