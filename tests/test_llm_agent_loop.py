"""The LLM agent loop with a scripted fake model: tool calls, pause on ask_user, resume, lever, final text."""
from mygoal.agent.llm_agent import LLMAgent
from mygoal.agent.session import Session
from mygoal.llm import LLMTurn, ToolCall


class ScriptedConversation:
    def __init__(self, turns):
        self.turns = list(turns)
        self.results = []

    def add_user(self, text):
        pass

    def add_tool_results(self, results):
        self.results.append(results)

    def step(self):
        return self.turns.pop(0)


class ScriptedLLM:
    name, model = "scripted", "fake"

    def __init__(self, turns):
        self.conv = ScriptedConversation(turns)

    def conversation(self, system, tools):
        assert "propose_lever" in {t.name for t in tools}
        return self.conv

    def complete(self, system, prompt, max_tokens=4000):
        return ""


def test_llm_agent_pause_and_resume(svc):
    lever_args = {"title": "Sell the Warhammer army", "group": "structural", "effort": "medium", "parts": [
        {"primitive": "asset_dispose", "params": {
            "asset": "Warhammer army", "months_to_sell": 3,
            "sale_value": {"value": 1500, "low": 1000, "high": 1800, "source": "user", "label": "Sale value"},
            "running_costs_monthly": {"value": 60, "source": "transactions", "label": "Games Workshop per month", "unit": "CHF/month"}}}]}
    llm = ScriptedLLM([
        LLMTurn(text="", tool_calls=[ToolCall("c1", "search_transactions", {"query": "warhammer"})], stop_reason="tool_use"),
        LLMTurn(text="", tool_calls=[ToolCall("c2", "ask_user", {"question": "What could it sell for?", "kind": "number", "unit": "CHF"})],
                stop_reason="tool_use"),
        LLMTurn(text="", tool_calls=[ToolCall("c3", "propose_lever", lever_args)], stop_reason="tool_use"),
        LLMTurn(text="Selling it frees about CHF 85 a month for your apartment.", stop_reason="end_turn"),
    ])
    agent = LLMAgent(svc, llm)
    s = Session(client_id="lena", goal_id="home", text="What if I sell my Warhammer army?", lang="en")
    r = agent.start(s)
    assert r.status == "question" and r.question.text == "What could it sell for?"
    search_result = llm.conv.results[0][0]
    assert "games workshop" in search_result[1].lower()
    r = agent.answer(s, "1500")
    assert r.status == "lever" and r.lever_id in svc.state("lena").custom_levers
    assert r.message.startswith("Selling it frees")
    assert r.evaluation and r.evaluation["monthly_equivalent"] > 0
    assert llm.conv.results[1][0][0] == "c2"          # the answer went back as the ask_user tool result
