"""
Polymarket Fair Value Engine
Claude API를 사용하여 예측 시장의 공정 가치를 추정하고
Kelly Criterion으로 최적 베팅 크기를 계산합니다.
"""

import json
import os
from dataclasses import dataclass
from typing import Optional, Any

# Import from project modules with fallback
try:
    from config import get_config
    cfg = get_config()
except ImportError:
    cfg = None

try:
    from logging_config import get_logger
    logger = get_logger("polymarket_engine")
except ImportError:
    import logging
    logger = logging.getLogger("polymarket_engine")

try:
    from llm_provider import get_provider
    HAS_LLM_PROVIDER = True
except ImportError:
    HAS_LLM_PROVIDER = False


@dataclass
class ProbabilityEstimate:
    """Claude의 확률 추정 결과"""
    probability: float  # 0.0 ~ 1.0
    confidence: str  # "low" | "medium" | "high"
    reasoning: str
    api_cost: float = 0.0  # 추정 API 비용 (달러)


@dataclass
class MispricingOpportunity:
    """시장 미스프라이싱 기회"""
    market_question: str
    market_price: float
    estimated_prob: float
    edge: float  # |estimated_prob - market_price|
    side: str  # "YES" | "NO"
    confidence: str
    reasoning: str


@dataclass
class KellyCriterion:
    """Kelly Criterion 베팅 크기 계산 결과"""
    bet_amount: float
    kelly_fraction: float
    edge: float
    side: str  # "YES" | "NO"
    expected_value: float


class FairValueEngine:
    """Polymarket 공정 가치 추정 엔진

    Claude를 사용하여 예측 시장의 확률을 추정하고
    Kelly Criterion으로 최적 베팅 크기를 계산합니다.
    """

    # API 비용 추정 (입력 토큰당, 출력 토큰당, 달러 단위)
    # Claude Sonnet-4 기준 (2025년 1월)
    INPUT_TOKEN_COST = 3.0 / 1_000_000   # $3/M tokens
    OUTPUT_TOKEN_COST = 15.0 / 1_000_000  # $15/M tokens

    # 평균 토큰 사용량 추정
    AVG_INPUT_TOKENS = 500
    AVG_OUTPUT_TOKENS = 150

    def __init__(self, provider=None, client=None):
        """
        Args:
            provider: llm_provider.BaseLLMProvider 인스턴스
            client: anthropic.Anthropic 클라이언트 (fallback)
        """
        self.provider = provider
        self.client = client

        # 프로바이더/클라이언트 자동 설정
        if not self.provider and not self.client:
            if HAS_LLM_PROVIDER:
                try:
                    self.provider = get_provider()
                    logger.info("LLM provider initialized: %s", self.provider.PROVIDER_NAME)
                except Exception as e:
                    logger.warning("Failed to initialize LLM provider: %s", e)

            # Fallback to direct Anthropic client
            if not self.provider:
                try:
                    import anthropic
                    api_key = os.environ.get("ANTHROPIC_API_KEY")
                    if api_key:
                        self.client = anthropic.Anthropic(api_key=api_key)
                        logger.info("Direct Anthropic client initialized")
                except ImportError:
                    logger.error("Neither llm_provider nor anthropic library available")

    def estimate_probability(
        self,
        market_question: str,
        context: Optional[str] = None
    ) -> ProbabilityEstimate:
        """Claude를 사용하여 시장 질문의 확률을 추정합니다.

        Args:
            market_question: 예측 시장 질문 (예: "Will Bitcoin reach $100k by EOY 2025?")
            context: 추가 컨텍스트 정보 (선택적)

        Returns:
            ProbabilityEstimate: 확률, 신뢰도, 근거 포함
        """
        # 프롬프트 구성
        prompt = self._build_estimation_prompt(market_question, context)

        try:
            # LLM 호출
            response = self._call_llm(prompt)

            # 응답 파싱
            result = self._parse_probability_response(response)

            # API 비용 추정
            result.api_cost = self._estimate_api_cost(response)

            logger.info(
                "Estimated probability for '%s': %.2f%% (confidence: %s, cost: $%.4f)",
                market_question[:50],
                result.probability * 100,
                result.confidence,
                result.api_cost
            )

            return result

        except Exception as e:
            logger.error("Failed to estimate probability: %s", e)
            # 오류 시 중립 확률 반환
            return ProbabilityEstimate(
                probability=0.5,
                confidence="low",
                reasoning=f"Error during estimation: {str(e)}",
                api_cost=0.0
            )

    def find_mispricing(
        self,
        markets: list[dict],
        min_edge: float = 0.08
    ) -> list[MispricingOpportunity]:
        """시장 가격과 Claude 추정치를 비교하여 미스프라이싱을 찾습니다.

        Args:
            markets: 시장 정보 리스트
                [{"question": str, "price": float, "context": str}, ...]
            min_edge: 최소 엣지 (기본값 8%)

        Returns:
            MispricingOpportunity 리스트 (엣지 크기 내림차순 정렬)
        """
        opportunities = []

        for market in markets:
            question = market.get("question", "")
            market_price = market.get("price", 0.5)
            context = market.get("context")

            if not question:
                continue

            # Claude 확률 추정
            estimate = self.estimate_probability(question, context)

            # 엣지 계산
            edge = abs(estimate.probability - market_price)

            # 최소 엣지 필터링
            if edge < min_edge:
                logger.debug("Edge too small for '%s': %.2f%%", question[:50], edge * 100)
                continue

            # 베팅 방향 결정
            if estimate.probability > market_price:
                side = "YES"
            else:
                side = "NO"

            opportunity = MispricingOpportunity(
                market_question=question,
                market_price=market_price,
                estimated_prob=estimate.probability,
                edge=edge,
                side=side,
                confidence=estimate.confidence,
                reasoning=estimate.reasoning
            )

            opportunities.append(opportunity)
            logger.info(
                "Mispricing found: '%s' - Edge: %.2f%%, Side: %s",
                question[:50],
                edge * 100,
                side
            )

        # 엣지 크기로 정렬 (큰 것부터)
        opportunities.sort(key=lambda x: x.edge, reverse=True)

        return opportunities

    def kelly_criterion(
        self,
        bankroll: float,
        market_price: float,
        estimated_prob: float,
        max_fraction: float = 0.06
    ) -> KellyCriterion:
        """Kelly Criterion으로 최적 베팅 크기를 계산합니다.

        Args:
            bankroll: 총 자본금
            market_price: 시장 가격 (YES의 확률)
            estimated_prob: 추정 확률 (YES의 실제 확률)
            max_fraction: 최대 Kelly fraction (기본값 6% - fractional Kelly)

        Returns:
            KellyCriterion: 베팅 금액, Kelly fraction, 엣지 포함
        """
        # 베팅 방향 결정
        if estimated_prob > market_price:
            # BUY YES
            side = "YES"
            p = estimated_prob
            odds = 1 / market_price  # decimal odds
        else:
            # BUY NO (가격 반전)
            side = "NO"
            p = 1 - estimated_prob
            odds = 1 / (1 - market_price)

        # Kelly formula: f = (bp - q) / b
        # b = odds - 1 (net odds)
        # p = win probability
        # q = 1 - p (loss probability)
        b = odds - 1
        q = 1 - p

        # Edge calculation
        edge = b * p - q

        # Kelly fraction
        if b <= 0:
            kelly_fraction = 0.0
        else:
            kelly_fraction = edge / b

        # Cap at max_fraction (fractional Kelly for safety)
        kelly_fraction = max(0.0, min(kelly_fraction, max_fraction))

        # Bet amount
        bet_amount = kelly_fraction * bankroll

        # Expected value
        expected_value = bet_amount * edge

        logger.info(
            "Kelly calculation - Side: %s, Edge: %.2f%%, Kelly: %.2f%%, Bet: $%.2f",
            side,
            edge * 100,
            kelly_fraction * 100,
            bet_amount
        )

        return KellyCriterion(
            bet_amount=bet_amount,
            kelly_fraction=kelly_fraction,
            edge=edge,
            side=side,
            expected_value=expected_value
        )

    def _build_estimation_prompt(
        self,
        market_question: str,
        context: Optional[str] = None
    ) -> str:
        """확률 추정 프롬프트 생성"""
        prompt_parts = [
            "You are a prediction market analyst. Estimate the probability of the following event.",
            "",
            f"Question: {market_question}",
        ]

        if context:
            prompt_parts.extend([
                "",
                f"Context: {context}",
            ])

        prompt_parts.extend([
            "",
            "Output ONLY a JSON object with this exact format:",
            '{"probability": 0.XX, "confidence": "high|medium|low", "reasoning": "brief explanation"}',
            "",
            "Important:",
            "- probability must be between 0.0 and 1.0",
            "- confidence must be one of: high, medium, low",
            "- reasoning should be 1-2 sentences explaining your estimate",
            "- Do not include any text outside the JSON object",
        ])

        return "\n".join(prompt_parts)

    def _call_llm(self, prompt: str) -> Any:
        """LLM 호출 (provider 또는 client 사용)"""
        if self.provider:
            # llm_provider 사용
            messages = [{"role": "user", "content": prompt}]
            response = self.provider.create_message(
                messages=messages,
                max_tokens=500
            )
            return response

        elif self.client:
            # Direct Anthropic client 사용
            response = self.client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            return response

        else:
            raise RuntimeError("No LLM provider or client available")

    def _parse_probability_response(self, response: Any) -> ProbabilityEstimate:
        """LLM 응답에서 확률 추정치 파싱"""
        # response.content에서 텍스트 추출
        if hasattr(response, "content"):
            # llm_provider.LLMResponse 또는 Anthropic Message
            text_parts = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                elif isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            text = "\n".join(text_parts).strip()
        else:
            text = str(response)

        # JSON 파싱 시도
        try:
            # JSON 객체만 추출 (전후 텍스트 무시)
            json_start = text.find("{")
            json_end = text.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                data = json.loads(json_str)
            else:
                raise ValueError("No JSON object found in response")

            # 필드 검증
            probability = float(data.get("probability", 0.5))
            probability = max(0.0, min(1.0, probability))  # Clamp to [0, 1]

            confidence = data.get("confidence", "low")
            if confidence not in ["low", "medium", "high"]:
                confidence = "low"

            reasoning = data.get("reasoning", "No reasoning provided")

            return ProbabilityEstimate(
                probability=probability,
                confidence=confidence,
                reasoning=reasoning
            )

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            logger.warning("Failed to parse probability response: %s. Using default.", e)
            return ProbabilityEstimate(
                probability=0.5,
                confidence="low",
                reasoning=f"Failed to parse response: {text[:100]}"
            )

    def _estimate_api_cost(self, response: Any) -> float:
        """API 호출 비용 추정"""
        if hasattr(response, "usage"):
            # llm_provider.LLMResponse 또는 Anthropic Message
            input_tokens = getattr(response.usage, "input_tokens", self.AVG_INPUT_TOKENS)
            output_tokens = getattr(response.usage, "output_tokens", self.AVG_OUTPUT_TOKENS)
        else:
            # Fallback to average
            input_tokens = self.AVG_INPUT_TOKENS
            output_tokens = self.AVG_OUTPUT_TOKENS

        cost = (
            input_tokens * self.INPUT_TOKEN_COST +
            output_tokens * self.OUTPUT_TOKEN_COST
        )

        return cost


# Convenience functions

def estimate_market_probability(
    market_question: str,
    context: Optional[str] = None
) -> ProbabilityEstimate:
    """단일 시장에 대한 확률 추정 (편의 함수)

    Args:
        market_question: 시장 질문
        context: 추가 컨텍스트

    Returns:
        ProbabilityEstimate
    """
    engine = FairValueEngine()
    return engine.estimate_probability(market_question, context)


def find_arbitrage_opportunities(
    markets: list[dict],
    min_edge: float = 0.08
) -> list[MispricingOpportunity]:
    """미스프라이싱 기회 검색 (편의 함수)

    Args:
        markets: 시장 정보 리스트
        min_edge: 최소 엣지 (기본 8%)

    Returns:
        MispricingOpportunity 리스트
    """
    engine = FairValueEngine()
    return engine.find_mispricing(markets, min_edge)


def calculate_optimal_bet(
    bankroll: float,
    market_price: float,
    estimated_prob: float,
    max_kelly: float = 0.06
) -> KellyCriterion:
    """최적 베팅 크기 계산 (편의 함수)

    Args:
        bankroll: 자본금
        market_price: 시장 가격
        estimated_prob: 추정 확률
        max_kelly: 최대 Kelly fraction

    Returns:
        KellyCriterion
    """
    engine = FairValueEngine()
    return engine.kelly_criterion(bankroll, market_price, estimated_prob, max_kelly)
