import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import EmptyState from '../components/EmptyState';
import { useSkills } from '../api/queries';

const GROUP_COLORS: Record<string, string> = {
  'Core Routing': 'border-blue-500/20 bg-blue-500/5',
  'New Claim Workflow': 'border-green-500/20 bg-green-500/5',
  'Duplicate Detection': 'border-orange-500/20 bg-orange-500/5',
  'Fraud Detection': 'border-red-500/20 bg-red-500/5',
  'Total Loss': 'border-purple-500/20 bg-purple-500/5',
  'Partial Loss': 'border-teal-500/20 bg-teal-500/5',
  'Escalation': 'border-amber-500/20 bg-amber-500/5',
};

const GROUP_ICONS: Record<string, string> = {
  'Core Routing': '🔀',
  'New Claim Workflow': '📝',
  'Duplicate Detection': '🔍',
  'Fraud Detection': '🚨',
  'Total Loss': '💥',
  'Partial Loss': '🔧',
  'Escalation': '⚠️',
};

export default function Skills() {
  const { data, isLoading, error } = useSkills();
  const groups = data?.groups ?? {};

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agent Skills" subtitle="Browse agent skill definitions grouped by workflow" />
        <div className="space-y-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-gray-800/50 rounded-xl border border-gray-700/50 skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agent Skills" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (Object.keys(groups).length === 0) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agent Skills" />
        <EmptyState icon="🧠" title="No skills found" description="No agent skills have been defined yet." />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="Agent Skills"
        subtitle="Browse agent skill definitions grouped by workflow. Each skill defines the role, goal, and backstory for an AI agent."
      />

      {Object.entries(groups).map(([groupName, skills]) => (
        <div key={groupName}>
          <h2 className="text-base font-semibold text-gray-200 mb-3 flex items-center gap-2">
            <span>{GROUP_ICONS[groupName] ?? '📄'}</span>
            {groupName}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {skills.map((skill) => (
              <Link
                key={skill.name}
                to={`/skills/${skill.name}`}
                className={`block border rounded-xl p-5 hover:shadow-lg hover:shadow-black/20 hover:-translate-y-0.5 transition-all ${
                  GROUP_COLORS[groupName] ?? 'border-gray-700/50 bg-gray-800/50'
                }`}
              >
                <h3 className="font-semibold text-gray-200 text-sm">{skill.role}</h3>
                <p className="text-xs text-gray-500 mt-0.5 font-mono">{skill.name}.md</p>
                <p className="text-sm text-gray-400 mt-2 line-clamp-3">
                  {skill.goal ?? 'No goal defined.'}
                </p>
              </Link>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
