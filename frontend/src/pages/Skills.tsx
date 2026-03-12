import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import EmptyState from '../components/EmptyState';
import { useSkills } from '../api/queries';
import { DocumentIcon, WarningIcon } from '../components/icons';
import { SKILL_GROUP_ICONS } from '../components/icons/icons-maps';

const SETTLEMENT_CARD =
  'border border-indigo-500/30 bg-indigo-500/10 border-l-4 border-l-indigo-500/60 hover:ring-1 hover:ring-indigo-500/30';

const GROUP_CARD_CLASSES: Record<string, string> = {
  'Core Routing': 'border border-blue-500/30 bg-blue-500/10 border-l-4 border-l-blue-500/60 hover:ring-1 hover:ring-blue-500/30',
  'New Claim Workflow': 'border border-green-500/30 bg-green-500/10 border-l-4 border-l-green-500/60 hover:ring-1 hover:ring-green-500/30',
  'Duplicate Detection': 'border border-orange-500/30 bg-orange-500/10 border-l-4 border-l-orange-500/60 hover:ring-1 hover:ring-orange-500/30',
  'Fraud Detection': 'border border-red-500/30 bg-red-500/10 border-l-4 border-l-red-500/60 hover:ring-1 hover:ring-red-500/30',
  'Total Loss': 'border border-purple-500/30 bg-purple-500/10 border-l-4 border-l-purple-500/60 hover:ring-1 hover:ring-purple-500/30',
  'Partial Loss': 'border border-teal-500/30 bg-teal-500/10 border-l-4 border-l-teal-500/60 hover:ring-1 hover:ring-teal-500/30',
  'Settlement Workflow': SETTLEMENT_CARD,
  Subrogation: SETTLEMENT_CARD,
  Escalation: 'border border-amber-500/30 bg-amber-500/10 border-l-4 border-l-amber-500/60 hover:ring-1 hover:ring-amber-500/30',
};

const CARD_DEFAULT = 'border border-gray-700/50 bg-gray-800/50';


export default function Skills() {
  const { data, isLoading, error } = useSkills();
  const groups = data?.groups ?? {};

  if (isLoading) {
    return (
      <div className="space-y-8 animate-fade-in">
        <PageHeader title="Agent Skills" subtitle="Browse agent skill definitions grouped by workflow" />
        {[1, 2, 3].map((sectionIndex) => (
          <div key={sectionIndex} className="pb-8 last:pb-0">
            <div className="flex items-center gap-2 pb-3 border-b border-gray-700/50 mb-4">
              <div className="h-4 w-4 rounded bg-gray-700/50 skeleton-shimmer" />
              <div className="h-4 w-32 rounded bg-gray-700/50 skeleton-shimmer" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-36 rounded-xl border border-gray-700/50 bg-gray-800/50 skeleton-shimmer" />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agent Skills" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <WarningIcon className="w-5 h-5 shrink-0 text-red-400" aria-hidden />
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

      {Object.entries(groups).map(([groupName, skills]) => {
        const GroupIcon = SKILL_GROUP_ICONS[groupName] ?? DocumentIcon;
        return (
        <section key={groupName} className="pb-8 last:pb-0">
          <h2 className="text-base font-semibold text-gray-200 pb-3 border-b border-gray-700/50 flex items-center gap-2">
            <span className="text-gray-500" aria-hidden>➤</span>
            <GroupIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />
            {groupName}
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
            {skills.map((skill) => (
              <Link
                key={skill.name}
                to={`/skills/${skill.name}`}
                className={`group block rounded-xl p-5 hover:shadow-lg hover:shadow-black/20 hover:-translate-y-0.5 transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-900 ${
                  GROUP_CARD_CLASSES[groupName] ?? CARD_DEFAULT
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <h3 className="font-semibold text-gray-200 text-base">{skill.role}</h3>
                  <span className="text-gray-500 opacity-0 group-hover:opacity-100 transition-opacity shrink-0" aria-hidden>→</span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5 font-mono">{skill.name}.md</p>
                <p className="text-sm text-gray-400 mt-2 line-clamp-3">
                  {skill.goal ?? 'No goal defined.'}
                </p>
              </Link>
            ))}
          </div>
        </section>
        );
      })}
    </div>
  );
}
