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
    """Create a Crew instance from agent and task configurations.

    This function instantiates agents using the provided ``agents_config`` and
    constructs tasks from ``tasks_config``, wiring each task to the appropriate
    agent and optional context tasks. If no LLM is provided, the default LLM
    from :func:`claim_agent.config.llm.get_llm` is used. Additional keyword
    arguments in ``agent_kwargs`` are passed to each agent factory.

    Args:
        agents_config: Ordered list of :class:`AgentConfig` objects used to
            create the agents for the crew.
        tasks_config: Ordered list of :class:`TaskConfig` objects describing
            the tasks to be executed by the crew.
        llm: Optional LLM instance to use when creating agents. If ``None``,
            the default LLM returned by :func:`get_llm` is used.
        agent_kwargs: Optional mapping of keyword arguments forwarded to each
            agent factory in ``agents_config``.

    Returns:
        Crew: A :class:`Crew` instance with the configured agents and tasks.

    Raises:
        ValueError: If any task references an agent index outside the range of
            ``agents_config``, or if a task's ``context_task_indices`` contains
            a negative index or an index that does not refer to an earlier task.
    """
    llm = llm or get_llm()
    agent_kwargs = agent_kwargs or {}

    n_agents = len(agents_config)
    for i, cfg in enumerate(tasks_config):
        if cfg.agent_index < 0 or cfg.agent_index >= n_agents:
            raise ValueError(
                f"Task {i}: agent_index {cfg.agent_index} out of range [0, {n_agents})"
            )
        for j in cfg.context_task_indices or []:
            if j < 0 or j >= i:
                raise ValueError(
                    f"Task {i}: invalid context_task_indices {cfg.context_task_indices}; "
                    f"context must reference earlier tasks (indices in [0, {i}))"
                )

    agents = [cfg.factory(llm, **agent_kwargs) for cfg in agents_config]
    tasks = []
    for cfg in tasks_config:
        tasks.append(cfg.to_task(agents, tasks))
    return Crew(agents=agents, tasks=tasks, verbose=get_crew_verbose())
