from datetime import date

from langchain_core.messages import AIMessage

from form_agent.forecast.model import Forecast
from form_agent.forecast.plan import Plan, Recommendation, Unplaced
from form_agent.report.narrative import facts_from, template_narrative, write_narrative

AS_OF, TARGET = date(2026, 11, 1), date(2026, 12, 1)


def rec(tier, containers, vs=-10.0):
    return Recommendation(tier, "CLSAI", "CNSHA", "r", "MOCK FJORD", "1E", date(2026, 12, 3), containers, 2400.0, "USD", vs)


def forecast(origin="CLSAI", p50=180):
    return Forecast(origin, "CNSHA", TARGET, 120, p50, 240, 150.0, 1.1, 3, 12.0, 20.0, 0.8, 24)


def make_facts():
    plan = Plan([rec("buy", 137), rec("prepare", 40), rec("watch", 25, vs=-4.0)], [Unplaced("buy", "CLSAI", "CNSHA", 9, "x")])
    return facts_from(plan, [forecast(), forecast("CLVAP", p50=90)], AS_OF, TARGET, skipped=["PECLL-CNSHA"])


class Capture:
    def __init__(self, text="Resumen del modelo"):
        self.prompts, self.text = [], text

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return AIMessage(content=self.text)


class Boom:
    def invoke(self, prompt):
        raise RuntimeError("api caida")


def test_facts_count_containers_per_tier():
    facts = make_facts()
    assert {t: facts["tiers"][t]["containers"] for t in ("buy", "prepare", "watch")} == {"buy": 137, "prepare": 40, "watch": 25}
    assert facts["unplaced_containers"] == 9 and facts["skipped"] == ["PECLL-CNSHA"]
    assert facts["top_routes"][0]["route"] == "CLSAI-CNSHA"


def test_template_mentions_tier_totals_and_target_month():
    text = template_narrative(make_facts())
    assert "137" in text and "40" in text and "25" in text and "12/2026" in text


def test_template_handles_an_empty_plan():
    text = template_narrative(facts_from(Plan([], []), [], AS_OF, TARGET))
    assert "12/2026" in text


def test_write_narrative_uses_model_text_when_available():
    assert write_narrative(make_facts(), model=Capture("Resumen del modelo")) == "Resumen del modelo"


def test_write_narrative_prompt_contains_the_numbers():
    model = Capture()
    write_narrative(make_facts(), model=model)
    assert "137" in model.prompts[0]


def test_write_narrative_falls_back_when_model_raises():
    assert "137" in write_narrative(make_facts(), model=Boom())


def test_write_narrative_falls_back_when_model_returns_empty():
    assert "137" in write_narrative(make_facts(), model=Capture(""))


def test_write_narrative_without_model_uses_template():
    assert write_narrative(make_facts()) == template_narrative(make_facts())


def test_prompt_asks_for_spanish_tier_names_not_internal_keys():
    model = Capture()
    write_narrative(make_facts(), model=model)
    assert "«comprar»" in model.prompts[0] and "«preparar»" in model.prompts[0] and "«vigilar»" in model.prompts[0]


def test_write_narrative_strips_markdown_formatting():
    text = write_narrative(make_facts(), model=Capture("# Resumen\nConviene **comprar** ya y __preparar__ `P50`."))
    assert text == "Resumen\nConviene comprar ya y preparar P50."


def test_template_phrases_the_price_difference_in_words_not_as_a_signed_number():
    text = template_narrative(make_facts())
    assert "por debajo del precio promedio" in text and "-" not in text.split("precio promedio")[0][-12:]
