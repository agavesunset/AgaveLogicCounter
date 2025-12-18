# cyclic_int_controller.py

from __future__ import annotations

import random
from math import gcd
from typing import Dict


DEBUG = False


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[CyclicIntController] {msg}")


class CyclicIntController:
    _states: Dict[str, Dict[str, int]] = {}

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("value", "cycle")
    FUNCTION = "next_value"
    CATEGORY = "Agave/Logic"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["fixed", "increment", "decrement", "randomize"], {"default": "increment"}),
                "start": ("INT", {"default": 0, "min": -1_000_000, "max": 1_000_000, "step": 1}),
                "end": ("INT", {"default": 6, "min": -1_000_000, "max": 1_000_000, "step": 1}),
                "step": ("INT", {"default": 1, "min": 1, "max": 1_000_000, "step": 1}),
                "group_key": ("STRING", {"default": "", "multiline": False}),
                "reset": ("BOOLEAN", {"default": False}),
                "reset_cycle_only": ("BOOLEAN", {"default": False}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("NaN")

    @staticmethod
    def _state_key(unique_id, group_key: str) -> str:
        gk = (group_key or "").strip()
        if gk:
            return f"GROUP::{gk}"
        return str(unique_id) if unique_id is not None else "GLOBAL"

    @staticmethod
    def _normalize_range(start: int, end: int) -> tuple[int, int, int]:
        if start > end:
            start, end = end, start
        span = end - start + 1
        if span <= 0:
            raise ValueError(f"Invalid range: start={start}, end={end}")
        return start, end, span

    @staticmethod
    def _cycle_len(mode: str, span: int, step: int) -> int:
        if step <= 0:
            raise ValueError(f"Invalid step: {step}")
        if mode in ("increment", "decrement"):
            g = gcd(span, step)
            if g <= 0:
                raise ValueError(f"Invalid gcd(span, step): span={span}, step={step}")
            return span // g
        return span

    def next_value(
        self,
        mode: str,
        start: int,
        end: int,
        step: int,
        group_key: str,
        reset: bool,
        reset_cycle_only: bool,
        unique_id=None,
    ):
        mode = (mode or "fixed").strip().lower()
        if mode not in ("fixed", "increment", "decrement", "randomize"):
            raise ValueError(f"Invalid mode: {mode!r}")

        start, end, span = self._normalize_range(int(start), int(end))
        step = int(step)
        cycle_len = self._cycle_len(mode, span, step)

        key = self._state_key(unique_id, group_key)
        state = self._states.get(key)
        if state is None:
            state = {"idx": 0, "cycle_offset": 0}
            self._states[key] = state

        idx = int(state.get("idx", 0))
        cycle_offset = int(state.get("cycle_offset", 0))

        if reset:
            idx = 0
            cycle_offset = 0

        cycle_raw = idx // cycle_len
        if (not reset) and reset_cycle_only:
            cycle_offset = cycle_raw

        cycle_out = cycle_raw - cycle_offset
        if cycle_out < 0:
            cycle_out = 0

        if mode == "fixed":
            value = start
        elif mode == "increment":
            value = start + ((idx * step) % span)
            idx += 1
        elif mode == "decrement":
            value = end - ((idx * step) % span)
            idx += 1
        else:  # randomize
            value = random.randint(start, end)
            idx += 1

        state["idx"] = idx
        state["cycle_offset"] = cycle_offset

        _debug(f"key={key} value={value} cycle={cycle_out} idx={idx} offset={cycle_offset}")
        return int(value), int(cycle_out)


NODE_CLASS_MAPPINGS = {"CyclicIntController": CyclicIntController}
NODE_DISPLAY_NAME_MAPPINGS = {"CyclicIntController": "CyclicCounter_AS"}
