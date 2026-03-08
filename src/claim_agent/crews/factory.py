"""Base crew factory to eliminate boilerplate across crew modules."""

from dataclasses import dataclass
from typing import Callable

from crewai import Agent, Crew, Task

from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_crew_verbose


@dataclass
class AgentConfig:
    """Configuration for creating an agent in a crew."""

    factory: Callable[..., Agent]  # (llm, **kwargs) -> Agent


@dataclass
class TaskConfig:
    """Configuration for creating a task in a crew."""

    description: str
    expected_output: str
    agent_index: int
    context_task_indices: list[int] | None = None
    output_pydantic: type | None = None

    def to_task(self, agents: list[Agent], tasks: list[Task]) -> Task:
        context = [tasks[i] for i in (self.context_task_indices or [])]
        return Task(
            description=self.description,
            expected_output=self.expected_output,
            agent=agents[self.agent_index],
            context=context,
            output_pydantic=self.output_pydantic,
        )


def create_crew(
    agents_config: list[AgentConfig],
    tasks_config: list[TaskConfig],
    llm=None,
    agent_kwargs: dict | None = None,
) -> Crew:
    llm = llm or get_llm()
    agent_kwargs = agent_kwargs or {}
    agents = [cfg.factory(llm, **agent_kwargs) for cfg in agents_config]
    tasks = []
    for cfg in tasks_config:
        tasks.append(cfg.to_task(agents, tasks))
    return Crew(agents=agents, tasks=tasks, verbose=get_crew_verbose())
