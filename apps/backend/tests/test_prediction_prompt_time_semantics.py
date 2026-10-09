from app.intelligence import (
    ANALYSIS_PROMPT_VERSION,
    JUDGE_PROMPT_VERSION,
    TRANSLATION_PROMPT_VERSION,
)
from app.prediction_contract import PREDICTION_PROMPT_EXTENSION


def test_only_judge_prompt_version_advances_for_the_time_contract_patch():
    assert ANALYSIS_PROMPT_VERSION == "v2-post-semantics-9-context"
    assert TRANSLATION_PROMPT_VERSION == "v2-zh-translation-2-context"
    assert JUDGE_PROMPT_VERSION == "v2-reset-judge-10-time-contract"


def test_judge_time_prompt_distinguishes_points_bounds_ranges_and_dates():
    prompt = PREDICTION_PROMPT_EXTENSION

    assert "开始时刻" in prompt
    assert "at/planned for" in prompt
    assert "prediction_form=point" in prompt
    assert "predicted_end 可以为 null" in prompt
    assert "复制 predicted_start" in prompt
    assert "after/不早于为 start_only" in prompt
    assert "before/by/until/不晚于为 end_only" in prompt
    assert "开始时间范围保留 range" in prompt
    assert "单一日历日期保留 date/day" in prompt


def test_judge_time_prompt_preserves_source_precision_timezone_scope_and_target_separation():
    prompt = PREDICTION_PROMPT_EXTENSION

    assert "原始 ISO 引文明示到秒时保留 second" in prompt
    assert "普通补出的 :00 推高来源精度" in prompt
    assert "合法等价时区格式按同一绝对时刻处理" in prompt
    assert "source_timezone 仍保留原始声明" in prompt
    assert "时区未明示不得猜补" in prompt
    assert "scope 值为 unknown 时必须原样保留" in prompt
    assert "分别依据各自目标证据，不能相互借用" in prompt


def test_official_time_extraction_eligibility_remains_unchanged():
    prompt = PREDICTION_PROMPT_EXTENSION

    assert "official_time_extraction 仅用于可核验官方明确未来计划" in prompt
    assert "evidence_quote 必须逐作者连续原文引句" in prompt
    assert "不能把第三方父帖日期当作官方承诺" in prompt
