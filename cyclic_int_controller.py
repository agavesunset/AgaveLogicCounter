# cyclic_int_controller.py
import random
from math import gcd

# 打开这个可以在 ComfyUI 控制台里看到详细日志
DEBUG = False


def _debug(msg: str):
    if DEBUG:
        print(f"[CyclicIntController][DEBUG] {msg}")


class CyclicIntController:
    """
    循环整数控制器（带“满 N 进 1”和归零能力）

    mode:
      - fixed      : 固定值，始终输出 start
      - increment  : 从 start 往 end 递增，越界后回到 start
      - decrement  : 从 end 往 start 递减，越界后回到 end
      - randomize  : 在 [start, end] 内随机

    输出：
      value : 当前区间内的值（例如 0~6 或 1~6 循环）
      cycle : 完成了多少“完整循环”（带偏移，可单独归零）

    状态：
      idx          : 自然增长的步数（每次调用后 +1，用于满 N 进 1）
      cycle_offset : 循环次数偏移量，用来实现“只归零循环次”
    """

    # 全局状态，按节点实例 + group_key 分组
    _states = {}

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mode": (["fixed", "increment", "decrement", "randomize"], {
                    "default": "increment",
                }),
                "start": ("INT", {
                    "default": 0,
                    "min": -1_000_000,
                    "max": 1_000_000,
                    "step": 1,
                }),
                "end": ("INT", {
                    "default": 6,
                    "min": -1_000_000,
                    "max": 1_000_000,
                    "step": 1,
                }),
                "step": ("INT", {
                    "default": 1,
                    "min": 1,  # GUI 层面已经禁止 0/负数，但这里还是再防一层
                    "max": 1_000_000,
                    "step": 1,
                }),
                "group_key": ("STRING", {
                    "default": "",
                    "multiline": False,
                }),
                # 全清零：idx 和 cycle 一起归零
                "reset": ("BOOLEAN", {
                    "default": False,
                }),
                # 只归零 cycle：不改变当前 0~6 的位置
                "reset_cycle_only": ("BOOLEAN", {
                    "default": False,
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("value", "cycle")
    FUNCTION = "next_value"
    CATEGORY = "Agave/Logic"

    # 关键：告诉 ComfyUI“我每次都变了”，避免缓存
    @classmethod
    def IS_CHANGED(cls,
                   mode,
                   start,
                   end,
                   step,
                   group_key,
                   reset,
                   reset_cycle_only,
                   unique_id=None):
        # 这个节点依赖内部状态，即使输入没变输出也会变
        # 按官方推荐做法返回 NaN，让它每次都当作已改变
        return float("NaN")

    # ---------------- 工具方法 ----------------

    @classmethod
    def _make_state_key(cls, unique_id, group_key: str) -> str:
        """
        状态 key 逻辑：
        - 如果写了 group_key：所有填同一个 group_key 的节点共享同一个计数器
        - 如果没写 group_key：用 unique_id 区分每个节点实例
        """
        group_key = (group_key or "").strip()
        if group_key:
            # 跨节点共享：只看 group_key，不看 unique_id
            return f"GROUP::{group_key}"

        # 默认：每个节点一个独立计数器
        uid = str(unique_id) if unique_id is not None else "GLOBAL"
        return uid

    @classmethod
    def _sanitize_and_validate(cls, mode, start, end, step):
        """
        清洗 + 校验输入参数。
        - 保证 start <= end
        - 保证 step 为正整数
        - 检查 span、cycle_len 合法性
        """
        # 规范 mode
        if isinstance(mode, str):
            mode = mode.strip().lower()
        else:
            mode = "fixed"

        if mode not in ("fixed", "increment", "decrement", "randomize"):
            raise ValueError(
                f"[CyclicIntController] 非法模式 mode={mode!r}，"
                f"必须是 'fixed' / 'increment' / 'decrement' / 'randomize' 之一。"
            )

        # 规范范围：保证 start <= end
        if start > end:
            start, end = end, start

        # 计算 span
        span = end - start + 1
        if span <= 0:
            raise ValueError(
                f"[CyclicIntController] 非法区间：start={start}, end={end}，"
                f"计算得到 span={span} <= 0，请检查输入。"
            )

        # 规范 step
        try:
            step = int(step)
        except Exception as e:
            raise ValueError(
                f"[CyclicIntController] 步长 step 无法转换为整数：{step!r}，原始错误：{e}"
            ) from e

        if step <= 0:
            raise ValueError(
                f"[CyclicIntController] 非法步长 step={step}，必须为正整数。"
            )

        # 计算理论上的“完整循环长度”
        if mode in ("increment", "decrement"):
            g = gcd(span, step)
            if g <= 0:
                raise ValueError(
                    f"[CyclicIntController] 计算 gcd(span, step) 失败：span={span}, step={step}, gcd={g}。"
                )
            cycle_len = span // g
        else:
            # fixed / randomize 就按 span 来算“满 span 次进 1”
            cycle_len = span

        if cycle_len <= 0:
            raise ValueError(
                f"[CyclicIntController] 非法循环长度：cycle_len={cycle_len}，"
                f"span={span}, step={step}。"
            )

        _debug(
            f"sanitize: mode={mode}, start={start}, end={end}, step={step}, "
            f"span={span}, cycle_len={cycle_len}"
        )

        return mode, start, end, step, span, cycle_len

    # ---------------- 主逻辑 ----------------

    def next_value(self,
                   mode,
                   start,
                   end,
                   step,
                   group_key,
                   reset,
                   reset_cycle_only,
                   unique_id=None):

        try:
            # 1. 清洗 + 校验输入
            mode, start, end, step, span, cycle_len = self._sanitize_and_validate(
                mode, start, end, step
            )

            # 2. 取出状态
            state_key = self._make_state_key(unique_id, group_key)
            state = self._states.get(
                state_key,
                {"idx": 0, "cycle_offset": 0},
            )

            idx = int(state.get("idx", 0))
            cycle_offset = int(state.get("cycle_offset", 0))

            _debug(
                f"before reset: key={state_key}, idx={idx}, "
                f"cycle_offset={cycle_offset}, reset={reset}, "
                f"reset_cycle_only={reset_cycle_only}"
            )

            # 3. 全清零：reset = True 时，直接把 idx、cycle_offset 统统归零
            if reset:
                idx = 0
                cycle_offset = 0

            # 4. 计算“当前真实循环数”（未偏移）
            cycle_raw = idx // cycle_len

            # 5. 只归零循环次：不改变 idx，只调整 cycle_offset
            if (not reset) and reset_cycle_only:
                # 把当前 raw 当成新的 0 点
                cycle_offset = cycle_raw

            # 6. 对外显示的循环次数（带偏移）
            cycle_out = cycle_raw - cycle_offset
            if cycle_out < 0:
                # 正常情况下不会 <0，这里做个防御性保护
                cycle_out = 0

            _debug(
                f"after reset logic: idx={idx}, cycle_raw={cycle_raw}, "
                f"cycle_offset={cycle_offset}, cycle_out={cycle_out}"
            )

            # 7. 计算当前 value，并推进 idx（自然增长）
            if mode == "fixed":
                value = start
                # 如果你希望 fixed 也“随时间变动”，这里可以改成 idx = idx + 1

            elif mode == "increment":
                offset = (idx * step) % span
                value = start + offset
                idx = idx + 1

            elif mode == "decrement":
                offset = (idx * step) % span
                value = end - offset
                idx = idx + 1

            elif mode == "randomize":
                value = random.randint(start, end)
                idx = idx + 1

            else:
                # 理论上不会进入这里，因为前面已经校验过 mode
                raise RuntimeError(
                    f"[CyclicIntController] 未知模式 mode={mode!r}，理论上不应该到这里。"
                )

            # 8. 写回状态
            state["idx"] = idx
            state["cycle_offset"] = cycle_offset
            self._states[state_key] = state

            _debug(
                f"after step: key={state_key}, value={value}, cycle_out={cycle_out}, "
                f"next_idx={idx}"
            )

            return (int(value), int(cycle_out))

        except Exception as e:
            # 统一加一层前缀，方便在控制台中快速定位
            raise RuntimeError(
                f"[CyclicIntController] 运行时异常：{e}"
            ) from e


NODE_CLASS_MAPPINGS = {
    "CyclicIntController": CyclicIntController,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CyclicIntController": "Cyclic Int Controller",
}
