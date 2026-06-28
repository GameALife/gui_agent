"""Evaluator：根据执行前后的屏幕状态判断 GUI 操作是否生效。"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Action, ActionType, ExecutionResult
from .screen_state import ScreenState


@dataclass
class EvaluationResult:
    """一次操作后的验证结果。"""

    success: bool
    changed: bool = False
    reason: str = ""
    next_suggestion: str = ""
    used_llm: bool = False


class Evaluator:
    """操作结果验证器。

    默认先做确定性验证，避免每一步都依赖模型。需要更复杂判断时可打开
    use_llm=True，用 prompts 中的 RESULT_VERIFY_* 做语义验证。
    """

    _NO_CHANGE_REQUIRED = {
        ActionType.PRESS_BACK,
        ActionType.PRESS_HOME,
        ActionType.WAIT,
        ActionType.KEY_EVENT,
        ActionType.SWIPE,
        ActionType.SCROLL,
    }

    def __init__(self, llm=None, use_llm: bool = False):
        self.llm = llm
        self.use_llm = use_llm
        self.max_summary_len = 4000

    def evaluate(
        self,
        action: Action,
        step_intent: str,
        before: ScreenState,
        after: ScreenState,
        execution_result: ExecutionResult | None = None,
        before_app: str = "",
        after_app: str = "",
    ) -> EvaluationResult:
        """验证一个 Action 是否达到预期效果。"""
        if execution_result and not execution_result.success:
            return EvaluationResult(
                success=False,
                changed=False,
                reason=execution_result.error or "操作执行器返回失败",
                next_suggestion="重新匹配控件或上报异常恢复层",
            )

        changed = self._screen_changed(before, after)

        if action.action_type in self._NO_CHANGE_REQUIRED:
            return EvaluationResult(
                success=True,
                changed=changed,
                reason="该操作不强制要求控件树变化",
            )

        if action.action_type == ActionType.SET_TEXT:
            text_present = bool(action.input_text and action.input_text in after.hierarchy_xml)
            if changed or text_present:
                return EvaluationResult(
                    success=True,
                    changed=changed,
                    reason="输入后屏幕状态变化或目标文本已出现在控件树中",
                )

        if changed:
            return EvaluationResult(
                success=True,
                changed=True,
                reason="操作后包名、Activity 或控件树发生变化",
            )

        if self.use_llm and self.llm:
            llm_result = self._evaluate_with_llm(
                action=action,
                step_intent=step_intent,
                before=before,
                after=after,
                before_app=before_app,
                after_app=after_app,
            )
            if llm_result is not None:
                return llm_result

        return EvaluationResult(
            success=False,
            changed=False,
            reason="操作执行后屏幕状态无变化",
            next_suggestion="重新截屏并重新匹配控件，必要时使用坐标降级或上报异常恢复层",
        )

    @staticmethod
    def _screen_changed(before: ScreenState, after: ScreenState) -> bool:
        return (
            before.current_package != after.current_package
            or before.current_activity != after.current_activity
            or before.hierarchy_xml != after.hierarchy_xml
        )

    def _evaluate_with_llm(
        self,
        action: Action,
        step_intent: str,
        before: ScreenState,
        after: ScreenState,
        before_app: str,
        after_app: str,
    ) -> EvaluationResult | None:
        from .prompts import RESULT_VERIFY_SYSTEM, RESULT_VERIFY_USER

        messages = [
            {"role": "system", "content": RESULT_VERIFY_SYSTEM},
            {
                "role": "user",
                "content": RESULT_VERIFY_USER.format(
                    action_summary=action.summary(),
                    step_intent=step_intent,
                    before_app=before_app or before.current_package or "",
                    after_app=after_app or after.current_package or "",
                    before_summary=self._summarize_screen(before),
                    after_summary=self._summarize_screen(after),
                ),
            },
        ]

        try:
            data = self.llm.chat_json(messages, temperature=0.1, max_tokens=1024)
        except Exception as exc:
            return EvaluationResult(
                success=False,
                changed=self._screen_changed(before, after),
                reason=f"LLM 验证失败：{exc}",
                next_suggestion="使用确定性验证结果并进入重试",
                used_llm=True,
            )

        return EvaluationResult(
            success=self._to_bool(data.get("success")),
            changed=self._screen_changed(before, after),
            reason=data.get("reason", ""),
            next_suggestion=data.get("next_suggestion", ""),
            used_llm=True,
        )

    def _summarize_screen(self, screen: ScreenState) -> str:
        xml = screen.hierarchy_xml or ""
        if len(xml) > self.max_summary_len:
            xml = xml[:self.max_summary_len] + "\n<!-- XML summary truncated -->"
        return (
            f"package={screen.current_package or ''}\n"
            f"activity={screen.current_activity or ''}\n"
            f"xml={xml}"
        )

    @staticmethod
    def _to_bool(value) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes", "y", "是", "成功")
        return bool(value)
