from crewai import Agent, Crew, Process, Task
from crewai.agents.agent_builder.base_agent import BaseAgent
from crewai.project import CrewBase, agent, crew, task

from .model_config import llm_for
from .schemas import QAReport
from .tools.sandbox_tools import Sandbox


# Bounds on the hierarchical loop. The manager re-reasons on every delegation, so an
# unbounded manager is an unbounded bill. These are the cost ceiling, and they are the
# reason hierarchical is safe to demo.
MANAGER_MAX_ITER = 30
WORKER_MAX_ITER = 20
CREW_MAX_RPM = 30


@CrewBase
class EngineeringTeam():
    """A hierarchical engineering crew: the lead manages, the specialists build.

    The Engineering Lead is the ``manager_agent``. It owns task assignment and decides
    when the goal is met, rather than the order being hardcoded by the process.

    Two constraints below are enforced by CrewAI itself, verified against the installed
    1.15.10 source rather than the docs:

    * The manager must not appear in ``agents`` (``Crew.check_manager_llm`` raises
      ``manager_agent_in_agents``). That is why :meth:`engineering_lead` is a plain
      method and not an ``@agent``.
    * The manager must not have tools — ``Crew._create_manager_agent`` raises outright.
      So the lead gives up the Context7 MCP it had when it was a normal agent; the
      frontend engineer keeps its own, which is where the Gradio 6 lookups were needed.
    """

    agents: list[BaseAgent]
    tasks: list[Task]

    def __init__(self, sandbox: Sandbox | None = None) -> None:
        # The sandbox is per-run, so it is injected rather than imported. Every agent in
        # this crew shares one instance, which is how they see each other's files.
        self.sandbox = sandbox if sandbox is not None else Sandbox()

    # Models come from config/models.yaml, not from agents.yaml, so that the cost
    # panel and the LLM assignment always read the same source.

    def engineering_lead(self) -> Agent:
        """The manager. Deliberately NOT an ``@agent`` — see the class docstring."""
        return Agent(
            config=self.agents_config['engineering_lead'],
            verbose=True,
            llm=llm_for('engineering_lead'),
            allow_delegation=True,
            max_iter=MANAGER_MAX_ITER,
        )

    # Specialists never delegate. Without this the manager can delegate to an engineer
    # that delegates back, and the crew spends real money going in circles.

    @agent
    def backend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['backend_engineer'],
            verbose=True,
            llm=llm_for('backend_engineer'),
            tools=self.sandbox.tools(),
            allow_delegation=False,
            max_iter=WORKER_MAX_ITER,
        )

    @agent
    def frontend_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['frontend_engineer'],
            verbose=True,
            llm=llm_for('frontend_engineer'),
            tools=self.sandbox.tools(),
            mcps=["https://mcp.context7.com/mcp"],
            allow_delegation=False,
            max_iter=WORKER_MAX_ITER,
        )

    @agent
    def test_engineer(self) -> Agent:
        return Agent(
            config=self.agents_config['test_engineer'],
            verbose=True,
            llm=llm_for('test_engineer'),
            tools=self.sandbox.tools(),
            allow_delegation=False,
            max_iter=WORKER_MAX_ITER,
        )

    @agent
    def qa_inspector(self) -> Agent:
        """Independent verification. Has sandbox tools so it can run the tests itself."""
        return Agent(
            config=self.agents_config['qa_inspector'],
            verbose=True,
            llm=llm_for('qa_inspector'),
            tools=self.sandbox.tools(),
            allow_delegation=False,
            max_iter=WORKER_MAX_ITER,
        )

    @task
    def design_task(self) -> Task:
        return Task(
            config=self.tasks_config['design_task']
        )

    @task
    def code_task(self) -> Task:
        return Task(
            config=self.tasks_config['code_task'],
        )

    @task
    def frontend_task(self) -> Task:
        return Task(
            config=self.tasks_config['frontend_task'],
        )

    @task
    def test_task(self) -> Task:
        return Task(
            config=self.tasks_config['test_task'],
        )

    @task
    def qa_task(self) -> Task:
        """Emits a QAReport so the Phase 4 router branches on a boolean, not on prose."""
        return Task(
            config=self.tasks_config['qa_task'],
            output_pydantic=QAReport,
        )

    @crew
    def crew(self) -> Crew:
        """Creates the EngineeringTeam crew."""
        return Crew(
            agents=self.agents,  # manager excluded: CrewAI rejects it being in here
            tasks=self.tasks,
            process=Process.hierarchical,
            manager_agent=self.engineering_lead(),
            max_rpm=CREW_MAX_RPM,
            verbose=True,
            tracing=True,
        )
