"""
flux-openclaw LLM API 비용 계산 모듈

모델별 가격표 기반으로 API 호출 비용(USD)을 계산합니다.
새 pip 패키지 없음 (stdlib only).

사용법:
    from openclaw.cost_tracker import calculate_cost, list_supported_models

    result = calculate_cost("claude-sonnet-4-20250514", 10000, 5000)
    print(f"총 비용: ${result.total_cost_usd:.6f}")
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# 로깅 설정
try:
    from logging_config import get_logger
    logger = get_logger("cost_tracker")
except ImportError:
    import logging
    logger = logging.getLogger("cost_tracker")


# 가격표: USD per 1M tokens
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-20250514": {"input": 0.25, "output": 1.25},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    # OpenAI
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    # Google
    "gemini-2.5-flash": {"input": 0.15, "output": 0.6},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
}


@dataclass
class CostResult:
    """비용 계산 결과"""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


def get_model_pricing(model: str) -> Optional[dict[str, float]]:
    """모델의 가격 정보 반환. 없으면 None."""
    # 정확한 매칭
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]

    # 부분 매칭 (model_key가 입력에 포함되거나, 입력이 model_key에 포함)
    model_lower = model.lower()
    for model_key, pricing in MODEL_PRICING.items():
        key_lower = model_key.lower()
        if key_lower in model_lower or model_lower in key_lower:
            logger.debug("부분 매칭: '%s' -> '%s'", model, model_key)
            return pricing

    return None


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> CostResult:
    """모델과 토큰 수로 USD 비용 계산.

    정확한 모델명 매칭 → 부분 매칭 → 실패 시 0.0 반환.

    Args:
        model: 모델명
        input_tokens: 입력 토큰 수
        output_tokens: 출력 토큰 수

    Returns:
        CostResult 인스턴스
    """
    pricing = get_model_pricing(model)

    if pricing is None:
        logger.warning("미등록 모델: '%s' - 비용 0.0으로 처리", model)
        return CostResult(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    input_cost = input_tokens * pricing["input"] / 1_000_000
    output_cost = output_tokens * pricing["output"] / 1_000_000

    return CostResult(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
    )


def list_supported_models() -> list[str]:
    """가격표에 등록된 모델 목록 반환."""
    return sorted(MODEL_PRICING.keys())
