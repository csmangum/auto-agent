import { Link } from 'react-router-dom';
import { useAgentsCatalog } from '../api/queries';

const CREW_COLORS = [
  'border-blue-200 bg-blue-50',
  'border-green-200 bg-green-50',
  'border-orange-200 bg-orange-50',
  'border-purple-200 bg-purple-50',
  'border-red-200 bg-red-50',
  'border-teal-200 bg-teal-50',
];

const CREW_ICONS = ['🔀', '📝', '🔍', '💥', '🚨', '🔧'];

export default function Agents() {
  const { data, isLoading, error } = useAgentsCatalog();
  const crews = data?.crews ?? [];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold text-gray-900">Agents & Crews</h1>
        <div className="animate-pulse space-y-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-48 bg-gray-100 rounded-xl" />
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
        <h1 className="text-2xl font-bold text-gray-900">Agents & Crews</h1>
        <p className="text-sm text-gray-500 mt-1">
          Complete catalog of all workflow crews and their specialized agents
        </p>
      </div>

      <div className="space-y-6">
        {crews.map((crew, ci) => (
          <div
            key={crew.name}
            className={`rounded-xl border p-6 ${CREW_COLORS[ci % CREW_COLORS.length]}`}
          >
            <div className="flex items-start gap-3 mb-4">
              <span className="text-2xl">{CREW_ICONS[ci % CREW_ICONS.length]}</span>
              <div>
                <h2 className="text-lg font-bold text-gray-900">{crew.name}</h2>
                <p className="text-sm text-gray-600 mt-0.5">{crew.description}</p>
                <p className="text-xs text-gray-400 font-mono mt-1">{crew.module}</p>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {crew.agents.map((agent) => (
                <div
                  key={agent.name}
                  className="bg-white/80 rounded-lg border border-white/50 p-4"
                >
                  <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-semibold text-gray-900">{agent.name}</h3>
                    <Link
                      to={`/skills/${agent.skill}`}
                      className="text-xs text-blue-600 hover:text-blue-800"
                    >
                      view skill
                    </Link>
                  </div>
                  <p className="text-xs text-gray-600 mb-3">{agent.description}</p>

                  {agent.tools.length > 0 && (
                    <div>
                      <p className="text-xs text-gray-500 mb-1">Tools:</p>
                      <div className="flex flex-wrap gap-1">
                        {agent.tools.map((tool) => (
                          <span
                            key={tool}
                            className="inline-block bg-gray-100 text-gray-700 text-xs px-2 py-0.5 rounded font-mono"
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
