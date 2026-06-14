"""Loads the organisation routing table (config/org.yaml)."""
from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Optional

import yaml

from shared.contracts.schema import DecisionType, TargetPerson

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "org.yaml"

# spend-authority order, lowest -> highest
PERSON_ORDER = [TargetPerson.buyer, TargetPerson.procurement_lead, TargetPerson.manager]


@functools.lru_cache(maxsize=1)
def load_orgs() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def org(org_id: str) -> dict:
    orgs = load_orgs()
    return orgs.get(org_id) or next(iter(orgs.values()))


def people(org_id: str) -> dict:
    return org(org_id)["people"]


def label(org_id: str, person: TargetPerson) -> str:
    p = people(org_id).get(person.value)
    return (p or {}).get("label", person.value)


def phone(org_id: str, person: TargetPerson) -> Optional[str]:
    # env override keeps personal numbers out of git: SIVRA_PHONE_<ROLE> or SIVRA_DEMO_PHONE
    env = os.getenv(f"SIVRA_PHONE_{person.value.upper()}") or os.getenv("SIVRA_DEMO_PHONE")
    if env:
        return env
    p = people(org_id).get(person.value)
    return (p or {}).get("phone")


def decision_owner(org_id: str, decision_type: DecisionType) -> TargetPerson:
    dt = getattr(decision_type, "value", decision_type)
    return TargetPerson(org(org_id)["decision_owner"].get(dt, "buyer"))


def person_for_budget(org_id: str, amount: float) -> TargetPerson:
    """Smallest-authority person who can approve `amount`."""
    pe = people(org_id)
    for person in PERSON_ORDER:
        if person.value in pe and amount <= float(pe[person.value]["budget"]):
            return person
    return TargetPerson.manager
