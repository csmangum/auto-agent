# Agentic Claim Representative Dashboard

React + Vite dashboard for the Agentic Claim Representative POC. Provides a UI for claims management, documentation, skills viewing, system configuration, and role-based simulation.

## Features

- **Claims** - List claims, view claim detail, status, and audit history
- **Documentation** - Browse architecture, crews, tools, and other docs
- **Skills** - View agent skill definitions and prompts
- **System Config** - Inspect configuration and environment
- **Simulation Mode** - Role-based testing (adjuster, supervisor, admin)

## Development

```bash
# Start backend first (in project root)
claim-agent serve --reload

# Start frontend (proxies /api to backend)
cd frontend && npm run dev
```

Visit http://localhost:5173. The Vite dev server proxies `/api` to the backend.

## Build

```bash
npm run build
```

The backend serves `frontend/dist` when present for production deployments.

See the main [README](../README.md#observability-ui-dashboard) for full setup and security options.
