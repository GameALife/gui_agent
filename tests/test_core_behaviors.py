from agent_reasoner.llm_client import LLMClient
from execution_agent.action_executor import ActionExecutor
from execution_agent.action_planner import ActionPlanner
from execution_agent.evaluator import Evaluator
from execution_agent.models import Action, ActionType, Step, WidgetTarget
from execution_agent.screen_state import ScreenState
from execution_agent.step_parser import StepParser
from execution_agent.test_mock_device import MockDevice
from execution_agent.widget_understander import WidgetUnderstander


class FakeUnderstander:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def find_action(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_llm_json_extracts_from_fenced_text():
    text = '说明文字\n```json\n{"ok": true, "value": 1}\n```\n结尾'
    assert LLMClient._extract_json(text) == {"ok": True, "value": 1}


def test_step_parser_deduplicates_overlapping_click_rules():
    steps = StepParser().parse("点击搜索按钮")
    assert len(steps) == 1
    assert len(steps[0].actions) == 1
    assert steps[0].actions[0].action_type == ActionType.CLICK


def test_action_planner_uses_direct_rule_action_without_llm():
    hinted = Action(action_type=ActionType.WAIT, wait_time=1)
    fake = FakeUnderstander(Action(action_type=ActionType.CLICK))
    planner = ActionPlanner(fake)

    action = planner.resolve(
        step=Step(raw_text="等待1秒", intent="等待1秒"),
        screen_state=ScreenState(),
        hinted_action=hinted,
    )

    assert action.action_type == ActionType.WAIT
    assert fake.calls == []


def test_action_planner_allows_scroll_without_target():
    hinted = Action(action_type=ActionType.SCROLL)
    fake = FakeUnderstander(Action(action_type=ActionType.CLICK))
    planner = ActionPlanner(fake)

    action = planner.resolve(
        step=Step(raw_text="向上滚动", intent="向上滚动"),
        screen_state=ScreenState(),
        hinted_action=hinted,
    )

    assert action.action_type == ActionType.SCROLL
    assert fake.calls == []


def test_action_planner_merges_rule_input_text_into_llm_target():
    hinted = Action(action_type=ActionType.SET_TEXT, input_text="夜曲")
    resolved = Action(
        action_type=ActionType.SET_TEXT,
        target=WidgetTarget(resource_id="com.example:id/search_input"),
    )
    planner = ActionPlanner(FakeUnderstander(resolved))

    action = planner.resolve(
        step=Step(raw_text="输入夜曲", intent="在搜索框输入夜曲"),
        screen_state=ScreenState(),
        hinted_action=hinted,
    )

    assert action.action_type == ActionType.SET_TEXT
    assert action.input_text == "夜曲"
    assert action.target.resource_id == "com.example:id/search_input"


def test_action_planner_does_not_execute_class_only_target_directly():
    hinted = Action(
        action_type=ActionType.CLICK,
        target=WidgetTarget(class_name="android.widget.TextView"),
    )
    resolved = Action(
        action_type=ActionType.CLICK,
        target=WidgetTarget(resource_id="com.example:id/button"),
    )
    fake = FakeUnderstander(resolved)
    planner = ActionPlanner(fake)

    action = planner.resolve(
        step=Step(raw_text="点击按钮", intent="点击按钮"),
        screen_state=ScreenState(),
        hinted_action=hinted,
    )

    assert len(fake.calls) == 1
    assert action.target.resource_id == "com.example:id/button"


def test_widget_understander_parses_common_bounds_formats():
    assert WidgetUnderstander._parse_bounds("[1, 2, 3, 4]") == [1, 2, 3, 4]
    assert WidgetUnderstander._parse_bounds("[1,2][3,4]") == [1, 2, 3, 4]
    assert WidgetUnderstander._parse_bounds("bad") is None


def test_widget_understander_tolerates_bad_numeric_fields():
    assert WidgetUnderstander._parse_float("bad", default=1.5) == 1.5
    assert WidgetUnderstander._parse_int("bad", default=66) == 66


def test_action_executor_does_not_build_empty_selector_for_bounds_only():
    executor = ActionExecutor(MockDevice())
    target = WidgetTarget(bounds=[1, 2, 3, 4])

    assert executor._build_selector(target) is None


def test_action_executor_accepts_chinese_swipe_direction():
    device = MockDevice()
    executor = ActionExecutor(device)
    result = executor.execute(Action(action_type=ActionType.SWIPE, swipe_direction="下"))

    assert result.success
    assert device.operations[-1] == {"op": "swipe_ext", "kwargs": {"direction": "down"}}


def test_evaluator_passes_when_screen_changes():
    evaluator = Evaluator()
    before = ScreenState(hierarchy_xml="<a />", current_package="pkg", current_activity="A")
    after = ScreenState(hierarchy_xml="<b />", current_package="pkg", current_activity="A")

    result = evaluator.evaluate(
        action=Action(action_type=ActionType.CLICK),
        step_intent="点击按钮",
        before=before,
        after=after,
    )

    assert result.success
    assert result.changed


def test_evaluator_passes_set_text_when_text_appears():
    evaluator = Evaluator()
    before = ScreenState(hierarchy_xml='<node text="" />', current_package="pkg")
    after = ScreenState(hierarchy_xml='<node text="夜曲" />', current_package="pkg")

    result = evaluator.evaluate(
        action=Action(action_type=ActionType.SET_TEXT, input_text="夜曲"),
        step_intent="输入夜曲",
        before=before,
        after=after,
    )

    assert result.success
