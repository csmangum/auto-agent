import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import EmptyState from '../components/EmptyState';
import { useAgentsCatalog } from '../api/queries';

const CREW_COLORS = [
  'border-blue-500/20 bg-blue-500/5',
  'border-green-500/20 bg-green-500/5',
  'border-orange-500/20 bg-orange-500/5',
  'border-purple-500/20 bg-purple-500/5',
  'border-red-500/20 bg-red-500/5',
  'border-teal-500/20 bg-teal-500/5',
];

const CREW_ICONS = ['🔀', '📝', '🔍', '💥', '🚨', '🔧'];

export default function Agents() {
  const { data, isLoading, error } = useAgentsCatalog();
  const crews = data?.crews ?? [];

  if (isLoading) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agents & Crews" subtitle="Complete catalog of all workflow crews and their specialized agents" />
        <div className="space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-48 bg-gray-800/50 rounded-xl border border-gray-700/50 skeleton-shimmer" />
          ))}
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agents & Crews" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <span className="text-lg">⚠️</span>
          <p className="text-sm text-red-400">{error instanceof Error ? error.message : 'Unknown error'}</p>
        </div>
      </div>
    );
  }

  if (crews.length === 0) {
    return (
      <div className="space-y-6 animate-fade-in">
        <PageHeader title="Agents & Crews" />
        <EmptyState icon="🤖" title="No crews found" description="No workflow crews have been defined yet." />
      </div>
    );
  }

  return (
    <div className="space-y-8 animate-fade-in">
      <PageHeader
        title="Agents & Crews"
        subtitle="Complete catalog of all workflow crews and their specialized agents"
      />

      <div className="space-y-6">
        {crews.map((crew, ci) => (
          <div
            key={crew.name}
            className={`rounded-xl border p-6 ${CREW_COLORS[ci % CREW_COLORS.length]}`}
          >
            <div className="flex items-start gap-3 mb-4">
              <span className="text-2xl">{CREW_ICONS[ci % CREW_ICONS.length]}</span>
              <div>
                <h2 className="text-lg font-bold text-gray-100">{crew.name}</h2>
                <p className="text-sm text-gray-400 mt-0.5">{crew.description}</p>
                <p className="text-xs text-gray-600 font-mono mt-1">{crew.module}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {crew.agents.map((agent) => (
                <div
                  key={agent.name}
                  className="bg-gray-900/40 rounded-lg border border-gray-700/30 p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-gray-200">{agent.name}</h3>
                    <Link
                      to={`/skills/${agent.skill}`}
                      className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
                    >
                      view skill →
                    </Link>
                  </div>
                  <p className="text-xs text-gray-400 mb-3">{agent.description}</p>

                  {agent.tools.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-500 mb-1.5">Tools:</p>
                      <div className="flex flex-wrap gap-1">
                        {agent.tools.map((tool) => (
                          <span
                            key={tool}
                            className="inline-block bg-gray-800 text-gray-400 text-xs px-2 py-0.5 rounded font-mono ring-1 ring-gray-700/50"
                          >
                            {tool}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
