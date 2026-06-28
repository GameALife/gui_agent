"""Action Planner：将 Step 转成当前屏幕上可执行的 Action。

StepParser 负责从任务描述中提取候选动作；WidgetUnderstander 负责在控件树中
补全目标控件。这个模块把二者串起来，避免规则解析结果被执行层忽略。
"""

from typing import TYPE_CHECKING

from .models import Action, ActionType

if TYPE_CHECKING:
    from .screen_state import ScreenState
    from .widget_understander import WidgetUnderstander
    from .models import Step


class ActionPlanner:
    """基于规则动作和屏幕状态规划下一步可执行操作。"""

    _NO_TARGET_ACTIONS = {
        ActionType.PRESS_BACK,
        ActionType.PRESS_HOME,
        ActionType.WAIT,
        ActionType.SWIPE,
        ActionType.SCROLL,
        ActionType.KEY_EVENT,
    }

    def __init__(self, understander: "WidgetUnderstander"):
        self.understander = understander

    def resolve(
        self,
        step: "Step",
        screen_state: "ScreenState",
        current_app_name: str = "",
        hinted_action: Action | None = None,
    ) -> Action:
        """返回一个可执行 Action。

        Args:
            step: 当前原子步骤
            screen_state: 当前屏幕状态
            current_app_name: 当前前台 App 名
            hinted_action: StepParser 给出的规则动作。为空时完全交给 LLM/规则匹配。
        """
        if hinted_action is None:
            return self.understander.find_action(
                step_intent=step.intent,
                raw_text=step.raw_text,
                screen_state=screen_state,
                current_app_name=current_app_name,
            )

        if self._can_execute_directly(hinted_action):
            return hinted_action

        resolved = self.understander.find_action(
            step_intent=self._build_hint_intent(step, hinted_action),
            raw_text=step.raw_text,
            screen_state=screen_state,
            current_app_name=current_app_name,
        )
        return self._merge_hint(hinted_action, resolved)

    def _can_execute_directly(self, action: Action) -> bool:
        if action.action_type in self._NO_TARGET_ACTIONS:
            return True

        if action.action_type == ActionType.SET_TEXT and not action.input_text:
            return False

        target = action.target
        if target is None or target.is_empty():
            return False

        return bool(
            target.resource_id
            or target.content_desc
            or target.bounds
            or (target.text and target.class_name)
        )

    @staticmethod
    def _build_hint_intent(step: "Step", action: Action) -> str:
        pieces = [step.intent or step.raw_text, f"期望动作：{action.action_type.value}"]
        if action.input_text:
            pieces.append(f"输入内容：{action.input_text}")
        if action.target and not action.target.is_empty():
            pieces.append(f"候选目标：{action.target.summary()}")
        return "；".join(pieces)

    @staticmethod
    def _merge_hint(hinted: Action, resolved: Action) -> Action:
        """用规则动作补齐 LLM 结果中的缺省字段。"""
        if hinted.action_type != ActionType.CLICK and resolved.action_type != ActionType.KEY_EVENT:
            resolved.action_type = hinted.action_type

        if hinted.input_text and not resolved.input_text:
            resolved.input_text = hinted.input_text
        if hinted.swipe_direction and not resolved.swipe_direction:
            resolved.swipe_direction = hinted.swipe_direction
        if hinted.wait_time and not resolved.wait_time:
            resolved.wait_time = hinted.wait_time
        if hinted.key_code and not resolved.key_code:
            resolved.key_code = hinted.key_code
        if hinted.target and (resolved.target is None or resolved.target.is_empty()):
            resolved.target = hinted.target
        if hinted.reasoning and not resolved.reasoning:
            resolved.reasoning = hinted.reasoning

        return resolved
