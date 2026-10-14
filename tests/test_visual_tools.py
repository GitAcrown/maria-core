"""Images dessinées par des services gratuits, tirages, fuseaux et tracés : sans réseau réel."""

import base64
import json
import urllib.parse
import zlib
from typing import Any

import pytest

from maria_core.capabilities import CapabilityRegistry, Context
from maria_core.capabilities.builtin.formula import compile_formula
from maria_core.capabilities.builtin.plots import plot_capability
from maria_core.capabilities.builtin.visuals import (
    chart_config,
    diagram_url,
    render_visual,
    visual_capabilities,
)
from maria_core.capabilities.http import HttpResponse
from maria_core.llm.schema import openai_tool
from tests.http_fake import FakeHttp


def _context() -> Context:
    return Context(
        user_id=7,
        guild_id=5,
        channel_id=3,
        message_id=1,
        is_owner=False,
        is_moderator=False,
        text="",
    )


def _png(_method: str, _url: str, _headers: Any, _body: Any) -> HttpResponse:
    return HttpResponse(200, b"\x89PNG", {"Content-Type": "image/png"})


def _registry(http: FakeHttp) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    for capability in (*visual_capabilities(http), plot_capability(http)):
        registry.register(capability)
    return registry


async def _run(registry: CapabilityRegistry, name: str, **arguments: Any):
    return await registry.get(name).run(_context(), arguments)


def test_every_new_tool_has_a_valid_strict_schema() -> None:
    http = FakeHttp(_png)
    for capability in (*visual_capabilities(http), plot_capability(http)):
        schema = openai_tool(capability)["function"]["parameters"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


async def test_a_chart_is_created_then_shown_with_its_title() -> None:
    sent: list[dict[str, Any]] = []

    def handler(method: str, url: str, headers: Any, body: Any) -> HttpResponse:
        sent.append(json.loads(body))
        reply = {"success": True, "url": "https://quickchart.io/chart/render/zf-1"}
        return HttpResponse(200, json.dumps(reply).encode(), {})

    registry = _registry(FakeHttp(handler))
    result = await _run(
        registry,
        "render_chart",
        type="pie",
        title="Scores",
        labels=["Léa", "Paul"],
        datasets=[{"label": "Points", "data": [12, 8]}],
    )
    assert result.ok and result.widget == "render_visual"
    assert result.data["url"] == "https://quickchart.io/chart/render/zf-1"
    config = sent[0]["chart"]
    assert config["type"] == "pie" and config["options"]["title"]["text"] == "Scores"
    assert len(config["data"]["datasets"][0]["backgroundColor"]) == 2
    card = render_visual(result.data).cards[0]
    assert [block.kind for block in card.blocks] == ["text", "separator", "gallery", "footer"]
    assert card.blocks[0].text == "## 📊 Scores"
    assert card.blocks[3].text == "QuickChart · image générée"


def test_a_chart_with_the_wrong_number_of_values_is_explained() -> None:
    with pytest.raises(ValueError, match="2 valeurs pour 3 étiquettes"):
        chart_config(
            {
                "type": "bar",
                "labels": ["a", "b", "c"],
                "datasets": [{"label": "x", "data": [1, 2]}],
            }
        )
    with pytest.raises(ValueError, match="nombres"):
        chart_config({"type": "bar", "labels": ["a"], "datasets": [{"label": "x", "data": ["1"]}]})


async def test_a_diagram_is_checked_and_a_refusal_goes_back_to_the_model() -> None:
    def handler(method: str, url: str, headers: Any, body: Any) -> HttpResponse:
        if "A--->>>" in base64.urlsafe_b64decode(url.split("/img/")[1].split("?")[0]).decode():
            return HttpResponse(400, b"Parse error on line 1", {"Content-Type": "text/plain"})
        return HttpResponse(200, b"\x89PNG", {"Content-Type": "image/png"})

    registry = _registry(FakeHttp(handler))
    fine = await _run(registry, "render_diagram", kind="mermaid", code="graph TD; A-->B")
    assert fine.ok and fine.data["url"].startswith("https://mermaid.ink/img/")
    broken = await _run(registry, "render_diagram", kind="mermaid", code="graph TD; A--->>>")
    assert not broken.ok and "Parse error on line 1" in broken.error


def test_diagram_addresses_are_built_for_each_service_and_capped() -> None:
    url = diagram_url("graphviz", "digraph G { a -> b }")
    packed = url.removeprefix("https://kroki.io/graphviz/png/")
    assert zlib.decompress(base64.urlsafe_b64decode(packed)).decode() == "digraph G { a -> b }"
    assert diagram_url("plantuml", "@startuml\nA -> B\n@enduml").startswith("https://kroki.io/")
    with pytest.raises(ValueError, match="trop gros"):
        diagram_url("mermaid", "graph TD; " + "; ".join(f"N{i}-->N{i + 1}" for i in range(400)))
    with pytest.raises(ValueError, match="inconnu"):
        diagram_url("d2", "a -> b")


async def test_qr_math_and_avatar_urls_are_verified() -> None:
    http = FakeHttp(_png)
    registry = _registry(http)
    qr = await _run(registry, "render_qr", text="https://exemple.fr/a b")
    assert qr.ok and "quickchart.io/qr?text=https%3A%2F%2Fexemple.fr%2Fa+b" in qr.data["url"]
    math_ = await _run(registry, "render_math", latex="\\frac{a}{b}")
    assert math_.ok
    assert urllib.parse.unquote(math_.data["url"]).endswith("\\dpi{220}\\bg{white} \\frac{a}{b}")
    avatar = await _run(registry, "render_avatar", seed="Léa", style="pixel-art")
    assert avatar.ok and "/9.x/pixel-art/png?seed=L%C3%A9a" in avatar.data["url"]
    bad = await _run(registry, "render_avatar", seed="x", style="inconnu")
    assert not bad.ok
    assert (await _run(registry, "render_qr", text="x" * 600)).ok is False


async def test_an_unreachable_service_is_reported_not_shown() -> None:
    def refuse(method: str, url: str, headers: Any, body: Any) -> HttpResponse:
        return HttpResponse(503, b"", {})

    result = await _run(_registry(FakeHttp(refuse)), "render_qr", text="salut")
    assert not result.ok and "503" in result.error


def test_formulas_are_computed_without_eval_and_dangerous_ones_are_refused() -> None:
    assert compile_formula("2*x^2 - 3")(3) == pytest.approx(15)
    assert compile_formula("sin(pi/2) + sqrt(x)")(4) == pytest.approx(3)
    assert compile_formula("abs(x)²")(-3) == pytest.approx(9)
    for hostile in (
        "__import__('os').system('id')",
        "x.__class__",
        "[1 for i in range(9)]",
        "open('f')",
        "lambda: 1",
        "x if x else 1",
        "'texte'",
        "sin(x, 2)",
        "f(x)",
        "y + 1",
        "x" * 200,
        "",
    ):
        with pytest.raises(ValueError):
            compile_formula(hostile)
    with pytest.raises(OverflowError):
        compile_formula("9^999")(1)


async def test_a_function_plot_skips_undefined_points_and_refuses_empty_ones() -> None:
    sent: list[dict[str, Any]] = []

    def handler(method: str, url: str, headers: Any, body: Any) -> HttpResponse:
        sent.append(json.loads(body))
        reply = {"success": True, "url": "https://quickchart.io/chart/render/zf-9"}
        return HttpResponse(200, json.dumps(reply).encode(), {})

    registry = _registry(FakeHttp(handler))
    result = await _run(
        registry, "plot_function", expressions=["1/x", "x^2"], xmin=-2, xmax=2, title="Test"
    )
    assert result.ok and result.data["kind"] == "plot"
    first, second = sent[0]["chart"]["data"]["datasets"]
    assert len(first["data"]) == 90 and second["data"][0] == pytest.approx(4)
    assert second["label"] == "f(x) = x^2"
    nothing = await _run(registry, "plot_function", expressions=["log(x)"], xmin=-5, xmax=-1)
    assert not nothing.ok and "nulle part" in nothing.error
    reversed_ = await _run(registry, "plot_function", expressions=["x"], xmin=3, xmax=1)
    assert not reversed_.ok
