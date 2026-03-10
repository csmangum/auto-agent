import { useState } from 'react';
import { useAuth } from '../context/AuthContext';

export default function AuthControl() {
  const { isAuthenticated, login, logout } = useAuth();
  const [input, setInput] = useState('');
  const [showForm, setShowForm] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (input.trim()) {
      login(input.trim());
      setInput('');
      setShowForm(false);
    }
  };

  if (isAuthenticated) {
    return (
      <div className="flex items-center gap-2">
        <span className="inline-flex items-center gap-1.5 text-xs text-gray-500 truncate max-w-24" title="API key set">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
          Key set
        </span>
        <button
          type="button"
          onClick={logout}
          className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-800 transition-colors"
        >
          Clear key
        </button>
      </div>
    );
  }

  if (showForm) {
    return (
      <form onSubmit={handleSubmit} className="flex items-center gap-2">
        <input
          type="password"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="API key"
          className="text-xs border border-gray-700 bg-gray-800 text-gray-300 rounded px-2 py-1 w-28 focus:outline-none focus:ring-1 focus:ring-blue-500/40 placeholder:text-gray-600"
          autoFocus
        />
        <button
          type="submit"
          className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-500 transition-colors"
        >
          Set
        </button>
        <button
          type="button"
          onClick={() => { setShowForm(false); setInput(''); }}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          ✕
        </button>
      </form>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setShowForm(true)}
      className="text-xs text-gray-500 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-800 transition-colors"
    >
      🔑 Set API key
    </button>
  );
}
