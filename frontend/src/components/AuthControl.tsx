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
        <span className="text-xs text-gray-500 truncate max-w-24" title="API key set">
          Key: ***
        </span>
        <button
          type="button"
          onClick={logout}
          className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100"
        >
          Logout
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
          placeholder="API key or JWT"
          className="text-xs border border-gray-300 rounded px-2 py-1 w-32 focus:outline-none focus:ring-1 focus:ring-blue-500"
          autoFocus
        />
        <button
          type="submit"
          className="text-xs bg-blue-600 text-white px-2 py-1 rounded hover:bg-blue-700"
        >
          Login
        </button>
        <button
          type="button"
          onClick={() => { setShowForm(false); setInput(''); }}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          Cancel
        </button>
      </form>
    );
  }

  return (
    <button
      type="button"
      onClick={() => setShowForm(true)}
      className="text-xs text-gray-500 hover:text-gray-700 px-2 py-1 rounded hover:bg-gray-100"
    >
      Set API key
    </button>
  );
}
