import { useParams } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import MarkdownRenderer from '../components/MarkdownRenderer';
import { useSkill } from '../api/queries';

export default function SkillDetail() {
  const { name } = useParams<{ name: string }>();
  const { data: skill, isLoading, error } = useSkill(name ?? undefined);

  if (isLoading) {
    return (
      <div className="space-y-4 animate-fade-in">
        <div className="h-8 bg-gray-700/50 rounded w-48 skeleton-shimmer" />
        <div className="h-4 bg-gray-700/30 rounded w-full skeleton-shimmer" />
        <div className="h-4 bg-gray-700/30 rounded w-5/6 skeleton-shimmer" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4 animate-fade-in">
        <PageHeader title="Skill" backTo="/skills" backLabel="Skills" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (!skill) return null;

  return (
    <div className="space-y-6 animate-fade-in">
      <PageHeader
        title={skill.role}
        backTo="/skills"
        backLabel="Skills"
        actions={
          <span className="text-sm text-gray-500 font-mono">{skill.name}.md</span>
        }
      />

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {skill.goal && (
          <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-5">
            <h3 className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <span>🎯</span> Goal
            </h3>
            <p className="text-sm text-blue-200/80">{skill.goal}</p>
          </div>
        )}
        {skill.backstory && (
          <div className="bg-purple-500/10 border border-purple-500/20 rounded-xl p-5">
            <h3 className="text-xs font-semibold text-purple-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <span>📖</span> Backstory
            </h3>
            <p className="text-sm text-purple-200/80">{skill.backstory}</p>
          </div>
        )}
      </div>

      <div className="bg-gray-800/50 rounded-xl border border-gray-700/50 p-8">
        <MarkdownRenderer content={skill.content} />
      </div>
    </div>
  );
}
