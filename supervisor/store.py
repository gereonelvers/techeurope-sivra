"""In-memory store of pending decisions and their resolutions.

Deliberately simple (a dict behind a lock) — swap for sqlite/redis if we need
persistence across restarts. The buyer agent polls GET /resolution/{id} as a
fallback to the callback, so this is the source of truth during a run."""
from __future__ import annotations

import threading
from typing import Dict, List, Optional

from shared.contracts.schema import DecisionRequest, HumanResolution, RoutingDecision


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.requests: Dict[str, DecisionRequest] = {}
        self.decisions: Dict[str, RoutingDecision] = {}
        self.resolutions: Dict[str, HumanResolution] = {}

    def add(self, req: DecisionRequest, decision: RoutingDecision) -> None:
        with self._lock:
            self.requests[req.request_id] = req
            self.decisions[req.request_id] = decision

    def resolve(self, resolution: HumanResolution) -> None:
        with self._lock:
            self.resolutions[resolution.request_id] = resolution

    def get_resolution(self, request_id: str) -> Optional[HumanResolution]:
        return self.resolutions.get(request_id)

    def pending(self) -> List[RoutingDecision]:
        with self._lock:
            return [
                self.decisions[r]
                for r in self.decisions
                if r not in self.resolutions and self.decisions[r].should_delegate
            ]


STORE = Store()
