import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import MarkdownRenderer from '../components/MarkdownRenderer';
import { getSkill } from '../api/client';

export default function SkillDetail() {
  const { name } = useParams();
  const [skill, setSkill] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    getSkill(name)
      .then((data) => setSkill(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [name]);

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 bg-gray-200 rounded w-48" />
        <div className="h-4 bg-gray-100 rounded w-full" />
        <div className="h-4 bg-gray-100 rounded w-5/6" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <Link to="/skills" className="text-blue-600 hover:text-blue-800 text-sm">&larr; Back to Skills</Link>
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4 flex-wrap">
        <Link to="/skills" className="text-blue-600 hover:text-blue-800 text-sm">&larr; Skills</Link>
        <h1 className="text-2xl font-bold text-gray-900">{skill.role}</h1>
        <span className="text-sm text-gray-400 font-mono">{skill.name}.md</span>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {skill.goal && (
          <div className="bg-blue-50 border border-blue-200 rounded-xl p-5">
            <h3 className="text-xs font-semibold text-blue-600 uppercase tracking-wider mb-2">Goal</h3>
            <p className="text-sm text-blue-900">{skill.goal}</p>
          </div>
        )}
        {skill.backstory && (
          <div className="bg-purple-50 border border-purple-200 rounded-xl p-5">
            <h3 className="text-xs font-semibold text-purple-600 uppercase tracking-wider mb-2">Backstory</h3>
            <p className="text-sm text-purple-900">{skill.backstory}</p>
          </div>
        )}
      </div>

      {/* Full content */}
      <div className="bg-white rounded-xl border border-gray-200 p-8">
        <MarkdownRenderer content={skill.content} />
      </div>
    </div>
  );
}
