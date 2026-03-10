import { Link } from 'react-router-dom';
import { useSkills } from '../api/queries';

const GROUP_COLORS: Record<string, string> = {
  'Core Routing': 'border-blue-200 bg-blue-50',
  'New Claim Workflow': 'border-green-200 bg-green-50',
  'Duplicate Detection': 'border-orange-200 bg-orange-50',
  'Fraud Detection': 'border-red-200 bg-red-50',
  'Total Loss': 'border-purple-200 bg-purple-50',
  'Partial Loss': 'border-teal-200 bg-teal-50',
  'Escalation': 'border-amber-200 bg-amber-50',
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
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Agent Skills</h1>
        <div className="animate-pulse space-y-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-40 bg-gray-100 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <p className="text-red-800">{error instanceof Error ? error.message : 'Unknown error'}</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Agent Skills</h1>
        <p className="text-sm text-gray-500 mt-1">
          Browse agent skill definitions grouped by workflow. Each skill defines the role, goal, and backstory for an AI agent.
        </p>
      </div>

      {Object.entries(groups).map(([groupName, skills]) => (
        <div key={groupName}>
          <h2 className="text-lg font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <span>{GROUP_ICONS[groupName] ?? '📄'}</span>
            {groupName}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {skills.map((skill) => (
              <Link
                key={skill.name}
                to={`/skills/${skill.name}`}
                className={`block border rounded-xl p-5 hover:shadow-md transition-shadow ${
                  GROUP_COLORS[groupName] ?? 'border-gray-200 bg-white'
                }`}
              >
                <h3 className="font-semibold text-gray-900 text-sm">{skill.role}</h3>
                <p className="text-xs text-gray-500 mt-0.5 font-mono">{skill.name}.md</p>
                <p className="text-sm text-gray-600 mt-2 line-clamp-3">
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
