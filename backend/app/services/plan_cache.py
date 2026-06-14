from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from ..schemas import DrawingPlan, PlanRequest
from .guardrails import compact_scene


@dataclass(slots=True)
class CacheEntry:
    plan: DrawingPlan
    created_at: float


class PlanCache:
    """Thread-safe TTL/LRU cache for validated DrawingPlan objects."""

    def __init__(self, max_entries: int = 128, ttl_seconds: int = 900):
        self.max_entries = max(1, max_entries)
        self.ttl_seconds = max(1, ttl_seconds)
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key_for(request: PlanRequest, max_scene_objects: int) -> str:
        payload = {
            "text": " ".join(request.text.strip().split()),
            "canvas": request.canvas.model_dump(mode="json"),
            "scene": compact_scene(request.scene, max_scene_objects),
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> DrawingPlan | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            if now - entry.created_at > self.ttl_seconds:
                self._entries.pop(key, None)
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry.plan.model_copy(deep=True)

    def put(self, key: str, plan: DrawingPlan) -> None:
        with self._lock:
            self._entries[key] = CacheEntry(plan=plan.model_copy(deep=True), created_at=time.monotonic())
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self.hits = 0
            self.misses = 0

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"entries": len(self._entries), "hits": self.hits, "misses": self.misses}
