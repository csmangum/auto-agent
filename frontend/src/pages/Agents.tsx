import { Link } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import EmptyState from '../components/EmptyState';
import { useAgentsCatalog } from '../api/queries';
import { CREW_CYCLE_ICONS, WarningIcon } from '../components/icons';

const CREW_CARD_CLASSES = [
  'border border-blue-500/30 bg-blue-500/10 border-l-4 border-l-blue-500/60',
  'border border-green-500/30 bg-green-500/10 border-l-4 border-l-green-500/60',
  'border border-orange-500/30 bg-orange-500/10 border-l-4 border-l-orange-500/60',
  'border border-purple-500/30 bg-purple-500/10 border-l-4 border-l-purple-500/60',
  'border border-red-500/30 bg-red-500/10 border-l-4 border-l-red-500/60',
  'border border-teal-500/30 bg-teal-500/10 border-l-4 border-l-teal-500/60',
];

export default function Agents() {
  const { data, isLoading, error } = useAgentsCatalog();
  const crews = data?.crews ?? [];

  if (isLoading) {
    return (
      <div className="space-y-8 animate-fade-in">
        <PageHeader title="Agents & Crews" subtitle="Complete catalog of all workflow crews and their specialized agents" />
        {[1, 2, 3].map((sectionIndex) => (
          <div key={sectionIndex} className="pb-8 last:pb-0">
            <div className="flex items-center gap-2 pb-3 border-b border-gray-700/50 mb-4">
              <div className="h-4 w-4 rounded bg-gray-700/50 skeleton-shimmer" />
              <div className="h-4 w-40 rounded bg-gray-700/50 skeleton-shimmer" />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-32 rounded-xl border border-gray-700/50 bg-gray-800/50 skeleton-shimmer" />
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
        <PageHeader title="Agents & Crews" />
        <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 flex items-start gap-3">
          <WarningIcon className="w-5 h-5 shrink-0 text-red-400" aria-hidden />
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

      {crews.map((crew, ci) => {
        const CrewIcon = CREW_CYCLE_ICONS[ci % CREW_CYCLE_ICONS.length];
        const cardClass = CREW_CARD_CLASSES[ci % CREW_CARD_CLASSES.length];
        return (
          <section key={crew.name} className="pb-8 last:pb-0">
            <h2 className="text-base font-semibold text-gray-200 pb-3 border-b border-gray-700/50 flex items-center gap-2">
              <span className="text-gray-500" aria-hidden>➤</span>
              <CrewIcon className="w-5 h-5 shrink-0 text-gray-400" aria-hidden />
              {crew.name}
            </h2>

            <div className={`rounded-xl border p-6 mt-4 ${cardClass}`}>
              <p className="text-sm text-gray-400 mb-1">{crew.description}</p>
              <p className="text-xs text-gray-600 font-mono">{crew.module}</p>

              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
                {crew.agents.map((agent) => (
                  <div
                    key={agent.name}
                    className="group bg-gray-900/40 rounded-xl border border-gray-700/30 p-4 hover:shadow-lg hover:shadow-black/20 hover:border-gray-600/50 transition-all"
                  >
                    <div className="flex items-start justify-between gap-2 mb-2">
                      <h3 className="font-semibold text-gray-200 text-base">{agent.name}</h3>
                      <Link
                        to={`/skills/${agent.skill}`}
                        className="text-xs text-blue-400 hover:text-blue-300 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-900 rounded"
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
          </section>
        );
      })}
    </div>
  );
}
