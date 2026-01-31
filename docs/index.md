# Agentic Claim Representative Documentation

Welcome to the documentation for the Agentic Claim Representative POC - an AI-powered auto insurance claims processing system built with CrewAI.

## Overview

This system uses multi-agent AI architecture to automate auto insurance claim processing. A router agent classifies incoming claims and delegates them to specialized workflow crews that handle different claim types.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│    Claim JSON ──▶ Router ──▶ Escalation Check ──▶ Workflow Crew ──▶ Output  │
│                                                                              │
│    Claim Types: new | duplicate | total_loss | fraud | partial_loss         │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Documentation

### Getting Started

- **[Getting Started](getting-started.md)** - Installation, setup, and quick start guide

### Core Concepts

- **[Architecture](architecture.md)** - System architecture, components, and design decisions
- **[Crews](crews.md)** - Detailed documentation of each workflow crew
- **[Claim Types](claim-types.md)** - The five claim types and their processing workflows
- **[Agent Flow](agent-flow.md)** - Execution flow from input to output

### Reference

- **[Tools](tools.md)** - Complete reference for all available tools
- **[Database](database.md)** - Database schema, repository operations, and status constants
- **[Configuration](configuration.md)** - Environment variables and configuration options
- **[MCP Server](mcp-server.md)** - Optional MCP server for external tool access

## Quick Reference

### CLI Commands

```bash
claim-agent process <claim.json>   # Process a new claim
claim-agent status <claim_id>      # Get claim status
claim-agent history <claim_id>     # Get claim audit log
claim-agent reprocess <claim_id>   # Re-run workflow
```

### Claim Types

| Type | Description | Final Status |
|------|-------------|--------------|
| `new` | First-time claim | `open` |
| `duplicate` | Duplicate of existing | `duplicate` |
| `total_loss` | Vehicle destroyed | `closed` |
| `fraud` | Suspected fraud | `fraud_suspected` |
| `partial_loss` | Repairable damage | `partial_loss` |

### Workflow Crews

| Crew | Agents | Purpose |
|------|--------|---------|
| Router | 1 | Classify claims |
| New Claim | 3 | Validate, verify, assign |
| Duplicate | 3 | Search, compare, resolve |
| Total Loss | 4 | Assess, value, payout, settle |
| Fraud | 3 | Pattern, cross-ref, assess |
| Partial Loss | 5 | Assess, estimate, shop, parts, authorize |

## Project Structure

```
auto-agent/
├── src/claim_agent/
│   ├── main.py           # CLI entry point
│   ├── config/           # LLM and YAML configs
│   ├── agents/           # Agent factory functions
│   ├── crews/            # Crew definitions
│   ├── tools/            # CrewAI tools
│   ├── db/               # Database layer
│   ├── models/           # Pydantic models
│   └── mcp_server/       # MCP server
├── data/                 # Mock data and database
├── tests/                # Test suite
├── docs/                 # This documentation
└── scripts/              # Utility scripts
```

## Key Features

- **Multi-Agent Architecture**: Specialized agents for each task
- **Router-Based Classification**: Intelligent claim routing
- **Human-in-the-Loop (HITL)**: Escalation for high-risk claims
- **Persistent State**: SQLite with full audit trail
- **Extensible Tools**: Easy to add new capabilities
- **MCP Integration**: Optional external tool access

## Technology Stack

- **CrewAI** - Multi-agent orchestration
- **LiteLLM** - LLM abstraction (OpenRouter/OpenAI)
- **Pydantic** - Data validation
- **SQLite** - Persistent storage
- **FastMCP** - MCP server (optional)

## License

MIT License
