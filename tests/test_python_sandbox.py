"""run_python : utile pour les calculs de dates, et sans issue vers le reste du processus."""

import pytest

from maria_core.capabilities.builtin.sandbox import execute

ESCAPES = [
    "statistics.sys.modules['os'].getcwd()",
    "re.enum",
    "json.codecs",
    "g = (g.gi_frame.f_back.f_back.f_globals['sys'] for i in [0])\nlist(g)",
    "(lambda: 1).__globals__",
    "().__class__.__bases__",
    "__import__('os')",
    "import os",
    "import math, os",
    "from os import path",
    "from math import *",
    "from math import __loader__",
    "open('x')",
    "type(1)",
]


@pytest.mark.parametrize("code", ESCAPES)
def test_no_way_out(code: str) -> None:
    assert "error" in execute(code), code


def test_dates_and_the_libraries_work_without_or_with_imports() -> None:
    assert execute("import math\nmath.sqrt(16)") == {"ok": True, "result": 4.0}
    assert execute("from math import sqrt, pi as p\nsqrt(9) + p")["result"] == pytest.approx(
        6.141592653589793
    )
    days = execute("from datetime import date\n(date(2099, 1, 1) - date.today()).days")
    assert days["ok"] is True and days["result"] > 0
    assert execute("datetime.datetime.strptime('2026-10-31', '%Y-%m-%d').weekday()")["result"] == 5
    span = "(datetime(2026, 10, 31) - datetime(2026, 10, 14)).days"
    assert execute(f"from datetime import datetime, timedelta\n{span}")["result"] == 17
    assert execute("statistics.mean([1, 2, 3])")["result"] == 2
    assert execute("print(json.dumps({'a': 1}))")["stdout"] == '{"a": 1}\n'


def test_the_error_tells_what_exists() -> None:
    hint = execute("import requests")["hint"]
    assert "math" in hint and "datetime" in hint
