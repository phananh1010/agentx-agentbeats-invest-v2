test_agent.py constructs an AgentWorkload, instantiates Agent from agent.py, and calls its run method with a fake updater—this exercises the core invest agent logic (search + verdict assembly).


test_evaluator.py instantiates the evaluator Agent from agent.py, mocking its network/search helpers, and runs Agent.run to validate the evaluator’s scoring/summary pipeline.


To run test_agent.py, 
```
uv run scenarios/invest/tests/test_agent.py
```

To run test_evaluator.py,
```
(agentbeats-tutorial) $ uv run scenarios/invest/tests/test_evaluator.py 
```
