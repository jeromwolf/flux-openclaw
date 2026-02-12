"""cost_tracker.py 테스트 스위트"""

import os
import sys

import pytest

# cost_tracker 모듈 import를 위한 경로 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from openclaw.cost_tracker import (
    CostResult,
    MODEL_PRICING,
    calculate_cost,
    get_model_pricing,
    list_supported_models,
)


# =============================================================================
# CostResult 테스트
# =============================================================================


def test_cost_result_defaults():
    """CostResult 기본 필드값 검증"""
    result = CostResult(
        model="test-model",
        input_tokens=100,
        output_tokens=50,
        input_cost_usd=0.01,
        output_cost_usd=0.02,
        total_cost_usd=0.03,
    )
    assert result.model == "test-model"
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.input_cost_usd == 0.01
    assert result.output_cost_usd == 0.02
    assert result.total_cost_usd == 0.03


def test_cost_result_custom_values():
    """CostResult 커스텀 값 검증"""
    result = CostResult(
        model="custom-model",
        input_tokens=5000,
        output_tokens=2500,
        input_cost_usd=0.123456,
        output_cost_usd=0.654321,
        total_cost_usd=0.777777,
    )
    assert result.model == "custom-model"
    assert result.input_tokens == 5000
    assert result.output_tokens == 2500
    assert abs(result.input_cost_usd - 0.123456) < 1e-9
    assert abs(result.output_cost_usd - 0.654321) < 1e-9
    assert abs(result.total_cost_usd - 0.777777) < 1e-9


# =============================================================================
# get_model_pricing 테스트
# =============================================================================


def test_exact_match_anthropic():
    """Anthropic 모델 정확 매칭 검증"""
    pricing = get_model_pricing("claude-sonnet-4-20250514")
    assert pricing is not None
    assert pricing["input"] == 3.0
    assert pricing["output"] == 15.0


def test_exact_match_openai():
    """OpenAI 모델 정확 매칭 검증"""
    pricing = get_model_pricing("gpt-4o")
    assert pricing is not None
    assert pricing["input"] == 2.5
    assert pricing["output"] == 10.0


def test_exact_match_google():
    """Google 모델 정확 매칭 검증"""
    pricing = get_model_pricing("gemini-2.5-flash")
    assert pricing is not None
    assert pricing["input"] == 0.15
    assert pricing["output"] == 0.6


def test_partial_match_contains_key():
    """부분 매칭: 입력 모델명이 키를 포함하는 경우 (gpt-4o-2024-05-13 -> gpt-4o)"""
    pricing = get_model_pricing("gpt-4o-2024-05-13")
    assert pricing is not None
    assert pricing["input"] == 2.5
    assert pricing["output"] == 10.0


def test_partial_match_key_contains_model():
    """부분 매칭: 키가 입력 모델명을 포함하는 경우 (claude-sonnet -> claude-sonnet-4-20250514)"""
    pricing = get_model_pricing("claude-sonnet")
    assert pricing is not None
    assert pricing["input"] == 3.0
    assert pricing["output"] == 15.0


def test_no_match_returns_none():
    """매칭 실패 시 None 반환 검증"""
    pricing = get_model_pricing("unknown-model-xyz")
    assert pricing is None


# =============================================================================
# calculate_cost 테스트
# =============================================================================


def test_calculate_cost_known_model():
    """알려진 모델의 비용 계산 정확도 검증 (10000 input * 3.0/1M = 0.03)"""
    result = calculate_cost("claude-sonnet-4-20250514", 10000, 5000)
    assert result.model == "claude-sonnet-4-20250514"
    assert result.input_tokens == 10000
    assert result.output_tokens == 5000
    # 10000 * 3.0 / 1_000_000 = 0.03
    assert abs(result.input_cost_usd - 0.03) < 1e-9
    # 5000 * 15.0 / 1_000_000 = 0.075
    assert abs(result.output_cost_usd - 0.075) < 1e-9
    # 0.03 + 0.075 = 0.105
    assert abs(result.total_cost_usd - 0.105) < 1e-9


def test_calculate_cost_zero_tokens():
    """토큰 수가 0일 때 비용도 0인지 검증"""
    result = calculate_cost("gpt-4o-mini", 0, 0)
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.input_cost_usd == 0.0
    assert result.output_cost_usd == 0.0
    assert result.total_cost_usd == 0.0


def test_calculate_cost_unknown_model_returns_zero():
    """미등록 모델의 비용이 0.0으로 반환되는지 검증"""
    result = calculate_cost("unknown-model", 1000, 500)
    assert result.model == "unknown-model"
    assert result.input_tokens == 1000
    assert result.output_tokens == 500
    assert result.input_cost_usd == 0.0
    assert result.output_cost_usd == 0.0
    assert result.total_cost_usd == 0.0


def test_calculate_cost_partial_match():
    """부분 매칭으로 비용 계산이 정상 동작하는지 검증"""
    result = calculate_cost("gemini-2.5-pro-exp-0827", 20000, 10000)
    # 부분 매칭: gemini-2.5-pro
    assert result.input_tokens == 20000
    assert result.output_tokens == 10000
    # 20000 * 1.25 / 1_000_000 = 0.025
    assert abs(result.input_cost_usd - 0.025) < 1e-9
    # 10000 * 10.0 / 1_000_000 = 0.1
    assert abs(result.output_cost_usd - 0.1) < 1e-9
    # 0.025 + 0.1 = 0.125
    assert abs(result.total_cost_usd - 0.125) < 1e-9


def test_total_equals_input_plus_output():
    """total_cost가 input_cost + output_cost와 같은지 검증"""
    result = calculate_cost("claude-haiku-4-20250514", 15000, 7500)
    expected_total = result.input_cost_usd + result.output_cost_usd
    assert abs(result.total_cost_usd - expected_total) < 1e-9


# =============================================================================
# list_supported_models 테스트
# =============================================================================


def test_returns_sorted_list():
    """정렬된 모델 리스트를 반환하는지 검증"""
    models = list_supported_models()
    assert models == sorted(models)


def test_returns_all_8_models():
    """8개의 모델이 모두 반환되는지 검증"""
    models = list_supported_models()
    assert len(models) == 8
    # 모든 MODEL_PRICING 키가 포함되었는지 확인
    for model_key in MODEL_PRICING.keys():
        assert model_key in models
