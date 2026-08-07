# LinkedIn post — draft

Ed Donner has an Agentic AI course on Udemy. One of the projects in it is a small,
deliberately limited version of something like Claude Code: a CrewAI crew of four agents
that takes plain-English requirements and writes working Python. It is kept simple on
purpose.

I followed the course, then got curious and started extending it. It turned into a proper
R&D project.

What I added:

- A QA Inspector agent that reads the code and runs the tests itself, instead of trusting
  the agent that wrote them
- A Flow around the crew, so the decision to run another round is plain Python and not an
  agent deciding whether to keep spending money
- A human review step before anything ships
- A Gradio UI with a live cost panel and activity log
- E2B microVMs instead of local Docker, so it can be deployed
- Different models, picked on benchmarks and price

On the models. I went through benchmarks comparing quality against cost, then tried a few.
Everything runs through OpenRouter:

- DeepSeek V4 Pro for the lead and the QA Inspector ($0.435 / $0.870 per M tokens). 80.6%
  on SWE-bench Verified, the best open-weights score I found.
- DeepSeek V4 Flash for the backend and test agents ($0.09 / $0.18). They work against a
  feedback loop, so their mistakes are cheap and easy to see.
- MiniMax M3 for the frontend ($0.30 / $1.20). 80.5% on SWE-bench, basically tied with V4
  Pro, at a fraction of the price of the top frontend model.

A run went from around $4 to around $0.20.

I had started with an expensive model for the frontend. Then I measured, and that one
agent was 68% of the cost of the whole run. Two thirds of it was input tokens, not output.
Swapping it changed the price a lot and the output not at all.

The QA Inspector was the best addition. On one build it noticed the data was only being
kept in memory, which the requirements had explicitly ruled out. The design document had
quietly reworded the requirement to match what was built. The next iteration fixed it.

The part I was most excited about turned out to be a bad idea. I replaced the fixed
pipeline with a hierarchical process, where a manager agent decides who does what. It cost
2.4x more and made 102 LLM calls instead of 37, for the same result. The steps here are
known in advance: design, backend, frontend, tests. The manager was paying to work out a
plan that already existed. I left it behind an env var so anyone can run the comparison.

One more thing that did not work: letting a model read the human's feedback and decide
what it meant. I wrote "reject invalid input in the backend, not just the UI" and it
shipped the build. It is two buttons now.

Demo, opens on a finished build so there is nothing to wait for:
https://huggingface.co/spaces/Neuromediator/engineering-team

Code:
https://github.com/Neuromediator/engineering-team
