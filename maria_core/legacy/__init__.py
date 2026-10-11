"""Import en lecture seule depuis une copie de MARIA_R.

Sans `--write`, seul le rapport est produit. Avec `--write`, les lignes
convertibles sont copiées. La source n'est jamais modifiée.
"""

from maria_core.legacy.apply import apply
from maria_core.legacy.model import ApplyResult, ImportPlan
from maria_core.legacy.report import render
from maria_core.legacy.scan import scan

__all__ = ["ApplyResult", "ImportPlan", "apply", "render", "scan"]
