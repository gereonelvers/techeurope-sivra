"""GLiNER2 guardrail + structured extraction, with a dependency-light fallback.

If `gliner2` is installed (`pip install 'gliner2[local]'`) we run a single
forward-pass that does classification (urgency, needs_signoff) + structured
extraction (counter_offer, pickup_time/location, condition) on the CPU in ~50ms.
Otherwise we fall back to fast regex heuristics so the supervisor runs with zero
ML dependencies. The two return the same `Guardrail` shape.

`needs_signoff` is the standout safety property: if the agent's message contains
a binding commitment ("deal", "I'll take it"), we force escalation regardless of
what the router model decides.
"""
from __future__ import annotations

import re
from functools import lru_cache

from shared.contracts.schema import DecisionRequest, Guardrail, UrgencyTier

_MODEL_NAME = "fastino/gliner2-base-v1"

_COMMITMENT_RE = re.compile(
    r"\b(i'?ll take it|it'?s a deal|we have a deal|deal\b|i agree|i'?ll pay|"
    r"i'?ll buy|sold|confirmed|i confirm|see you (?:there|then))",
    re.I,
)
_URGENT_RE = re.compile(
    r"\b(today|tonight|asap|right now|in an? (?:hour|few minutes|min)|"
    r"only until|first come|other buyers?|ends? (?:soon|in)|expir)",
    re.I,
)
_TIME_RE = re.compile(
    r"\b((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*|tomorrow|today|tonight)\b"
    r"(?:[^.\n]{0,12}?\b\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
    re.I,
)
_PRICE_RE = re.compile(r"(?:€|eur\b|euros?)\s?(\d{2,5})|\b(\d{2,5})\s?(?:€|eur\b|euros?)", re.I)
_PLACE_RE = re.compile(r"\b(?:at|in|near|by)\s+([A-ZÄÖÜ][\wäöüß]+(?:\s?(?:platz|str\.?|straße|station|hbf|park|markt))?)", )


@lru_cache(maxsize=1)
def _model():
    try:
        from gliner2 import GLiNER2  # type: ignore

        return GLiNER2.from_pretrained(_MODEL_NAME)
    except Exception:
        return None


def _fallback(text: str) -> Guardrail:
    commitments = [m.group(0) for m in _COMMITMENT_RE.finditer(text)]
    urgent = bool(_URGENT_RE.search(text))
    price_m = _PRICE_RE.search(text)
    counter = float(next((g for g in price_m.groups() if g), 0)) if price_m else None
    time_m = _TIME_RE.search(text)
    place_m = _PLACE_RE.search(text)
    return Guardrail(
        needs_signoff=bool(commitments),
        urgency_prior=UrgencyTier.urgent_push if urgent else UrgencyTier.async_,
        counter_offer=counter,
        pickup_time=time_m.group(0).strip() if time_m else None,
        pickup_location=place_m.group(1) if place_m else None,
        commitments=commitments,
        extractor="fallback",
    )


def _gliner2(model, text: str) -> Guardrail:
    """Best-effort GLiNER2 extraction; any parse error degrades to the fallback."""
    schema = (
        model.create_schema()
        .classification("urgency", ["async", "urgent_push", "voice"])
        .classification("needs_signoff", ["yes", "no"])
        .entities(
            {
                "counter_offer": "a price proposed by buyer or seller, in euros",
                "pickup_time": "a date or time for meeting or handover",
                "pickup_location": "a place for meeting or handover",
                "condition": "the stated condition of the item",
            }
        )
    )
    res = model.extract(text, schema)

    def _cls(key):
        v = res.get(key) if isinstance(res, dict) else None
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, dict):
            v = v.get("label") or v.get("class")
        return v

    def _ent(key):
        v = res.get(key) if isinstance(res, dict) else None
        if isinstance(v, list) and v:
            v = v[0]
        if isinstance(v, dict):
            v = v.get("text") or v.get("value")
        return v

    urgency_raw = (_cls("urgency") or "async")
    try:
        urgency = UrgencyTier(urgency_raw)
    except ValueError:
        urgency = UrgencyTier.async_
    counter_raw = _ent("counter_offer")
    counter = None
    if counter_raw:
        m = re.search(r"\d{2,5}", str(counter_raw))
        counter = float(m.group(0)) if m else None
    return Guardrail(
        needs_signoff=str(_cls("needs_signoff")).lower() in ("yes", "true", "1"),
        urgency_prior=urgency,
        counter_offer=counter,
        pickup_time=_ent("pickup_time"),
        pickup_location=_ent("pickup_location"),
        condition=_ent("condition"),
        extractor="gliner2",
    )


def extract_guardrail(req: DecisionRequest) -> Guardrail:
    text = req.situation_text or ""
    model = _model()
    if model is not None:
        try:
            return _gliner2(model, text)
        except Exception:
            pass
    return _fallback(text)
