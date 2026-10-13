# STEP 15 — LangGraph Orchestration

## Scope

`ManufacturaIQOrchestrator` wires the frozen STEP 11-14 components into a
LangGraph workflow. This step owns graph topology, conditional fan-out, fan-in,
and result assembly only.

The workflow does not introduce checkpointing, persistent stores,
interrupt/resume handling, retry policies, database lifecycle management, RAG
lifecycle management, or direct provider clients.

## Graph Topology

```text
START
  -> route
  -> conditional dispatch
       -> END                                      when clarification is needed
       -> fusion                                   when no agents are selected
       -> Send(document_agent, {"query": query})   when DOCUMENT is selected
       -> Send(maintenance_agent, {"query": query}) when MAINTENANCE is selected
       -> Send(quality_agent, {"query": query})    when QUALITY is selected
       -> Send(production_agent, {"query": query}) when PRODUCTION is selected

agent nodes
  -> fusion
  -> reason
  -> review
  -> END
```

The `route` node calls `DecisionEngine.route()` and returns only the
`routing_decision` state update.

Conditional fan-out is implemented by the function registered with
`add_conditional_edges("route", ...)`. That conditional function is the only
place that returns LangGraph `Send` objects. Ordinary graph nodes always return
state update dictionaries. Returning `Send` objects from a normal node is
invalid for this state graph shape and produced the recovered
`InvalidUpdateError`.

## Routing Outcomes

- `needs_clarification=True` terminates immediately after `route`.
- An empty `selected_agents` list routes directly to `fusion`.
- Selected agents are dispatched through `Send` to their matching agent nodes.
- Unknown agent names are rejected by the orchestrator dispatch boundary.

## Agent Fan-In

Each agent node receives the query and returns:

```python
{"agent_results_by_name": {agent_name.value: result}}
```

`WorkflowState.agent_results_by_name` uses a reducer to merge concurrent agent
updates. The reducer rejects duplicate agent keys, preserving one result per
agent.

`fusion` collects results in canonical order:

1. DOCUMENT
2. MAINTENANCE
3. QUALITY
4. PRODUCTION

Any noncanonical keys are appended after the canonical agents. `fusion` runs
once after all selected agent branches complete.

## Reasoning And Review

After fusion, the workflow calls the injected reasoning engine and then
`DecisionEngine.review()`. Both PASS and HUMAN_REVIEW decisions are terminal
workflow outcomes in STEP 15. There is no interrupt/resume mechanism.

The same injected decision engine instance owns both `route()` and `review()`.
`score_evidence()` is not called by the STEP 15 graph.

## Resource Ownership

The core `ManufacturaIQOrchestrator` receives its decision engine, agents,
fusion service, and reasoner through dependency injection. The optional
production builder creates default Jev, agent, fusion, and Gemini reasoning
components only when dependencies are not supplied.

The orchestration layer does not directly import or own repositories, database
connections, RAG clients, vector stores, HTTP clients, or provider SDK clients.

## Regression Coverage

`tests/orchestration/test_langgraph_workflow.py` covers:

- graph construction and compilation
- conditional `Send` fan-out
- concurrent selected-agent starts
- fan-in before fusion
- clarification termination
- empty-agent fusion
- PASS and HUMAN_REVIEW terminal review paths
- partial agent selection
- agent error propagation
- missing agent implementation errors
- duplicate fan-in protection
- `score_evidence()` exclusion
- same decision engine instance for route and review
- no checkpoint/store/interrupt/retry production boundary
- static import boundary for orchestration files
