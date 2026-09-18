"""What-if agent: free text -> a lever built from primitives, with every number labelled.

Routing: specialist keyword match (car, deductible, child, ...) -> LLM tool-use agent -> rules agent -> form.
"""
from .router import WhatIfEngine
from .session import WhatIfQuestion, WhatIfResult

__all__ = ["WhatIfEngine", "WhatIfQuestion", "WhatIfResult"]
