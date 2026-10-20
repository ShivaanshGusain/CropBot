"""Query templates (step 14): kg.query.answer(driver, template, FarmContext) -> a structured answer.

  uv run python -m kg.query drying_target --context tests/query/fixtures/q15_grain_drying.json [--database cropbot-test]

Templates: drying_target (Q15, Q16), storage (Q17), harvest_readiness (Q12, Q14), threshold (Q8).
See kg.query.answer for applicability, three-valued conditions, ranking, visibility and safety.
"""

from .answer import answer
from .context import FarmContext
from .templates import TEMPLATES

__all__ = ["answer", "FarmContext", "TEMPLATES"]
