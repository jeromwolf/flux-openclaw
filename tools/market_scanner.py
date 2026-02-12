import json
import time
from typing import Dict, List, Any, Optional
import requests

SCHEMA = {
    "name": "market_scanner",
    "description": "Polymarket 예측 시장 스캐너. 활성 마켓을 스캔하고 가격/확률/거래량 데이터를 조회합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["scan", "detail", "categories"],
                "description": "scan: 마켓 스캔, detail: 특정 마켓 상세, categories: 카테고리 목록"
            },
            "category": {
                "type": "string",
                "description": "카테고리 필터 (crypto, sports, politics 등)"
            },
            "min_volume": {
                "type": "number",
                "description": "최소 24시간 거래량 (USD)"
            },
            "min_liquidity": {
                "type": "number",
                "description": "최소 유동성 (USD)"
            },
            "limit": {
                "type": "integer",
                "description": "결과 수 (기본 20, 최대 100)"
            },
            "market_slug": {
                "type": "string",
                "description": "마켓 slug (detail 액션용)"
            }
        },
        "required": ["action"]
    }
}

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
CLOB_API_BASE = "https://clob.polymarket.com"
REQUEST_TIMEOUT = 30


def get_live_price(token_id: str) -> Optional[float]:
    """CLOB API에서 실시간 가격 조회"""
    try:
        time.sleep(0.1)  # Rate limit protection
        url = f"{CLOB_API_BASE}/price?token_id={token_id}&side=BUY"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            data = response.json()
            return float(data.get("price", 0))
        return None
    except Exception:
        return None


def parse_market_data(market: Dict[str, Any]) -> Dict[str, Any]:
    """마켓 데이터 파싱 및 정규화"""
    try:
        # JSON 문자열 필드 파싱
        outcomes = json.loads(market.get("outcomes", "[]"))
        outcome_prices = json.loads(market.get("outcomePrices", "[]"))
        clob_token_ids = json.loads(market.get("clobTokenIds", "[]"))

        # 가격 데이터
        yes_price = float(outcome_prices[0]) if len(outcome_prices) > 0 else 0
        no_price = float(outcome_prices[1]) if len(outcome_prices) > 1 else 0

        # 실시간 가격 조회 (선택적)
        if clob_token_ids:
            live_yes = get_live_price(clob_token_ids[0])
            live_no = get_live_price(clob_token_ids[1]) if len(clob_token_ids) > 1 else None
            if live_yes is not None:
                yes_price = live_yes
            if live_no is not None:
                no_price = live_no

        # 확률 계산 (가격 = 확률)
        yes_prob = yes_price * 100
        no_prob = no_price * 100

        return {
            "question": market.get("question", ""),
            "slug": market.get("slug", ""),
            "outcomes": outcomes,
            "yes_price": yes_price,
            "no_price": no_price,
            "yes_probability": yes_prob,
            "no_probability": no_prob,
            "volume_24h": float(market.get("volume24hr", 0)),
            "liquidity": float(market.get("liquidity", 0)),
            "category": market.get("groupItemTitle", ""),
            "end_date": market.get("endDate", ""),
            "clob_token_ids": clob_token_ids
        }
    except Exception as e:
        return {
            "question": market.get("question", ""),
            "error": f"파싱 실패: {str(e)}"
        }


def scan_markets(
    category: Optional[str] = None,
    min_volume: Optional[float] = None,
    min_liquidity: Optional[float] = None,
    limit: int = 20
) -> str:
    """활성 마켓 스캔"""
    try:
        # API 요청
        url = f"{GAMMA_API_BASE}/markets"
        params = {
            "closed": "false",
            "limit": min(limit, 100)
        }

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        markets = response.json()

        # 필터링
        filtered = []
        for market in markets:
            parsed = parse_market_data(market)

            if "error" in parsed:
                continue

            # 카테고리 필터
            if category and category.lower() not in parsed["category"].lower():
                continue

            # 거래량 필터
            if min_volume and parsed["volume_24h"] < min_volume:
                continue

            # 유동성 필터
            if min_liquidity and parsed["liquidity"] < min_liquidity:
                continue

            filtered.append(parsed)

        # 거래량 기준 정렬
        filtered.sort(key=lambda x: x["volume_24h"], reverse=True)

        # 결과 포맷팅
        output = [f"📊 Polymarket 활성 마켓 ({len(filtered)}개)\n"]

        for i, market in enumerate(filtered[:limit], 1):
            output.append(f"\n{i}. {market['question']}")
            output.append(f"   YES: ${market['yes_price']:.3f} ({market['yes_probability']:.1f}%)")
            output.append(f"   NO:  ${market['no_price']:.3f} ({market['no_probability']:.1f}%)")
            output.append(f"   📈 24h 거래량: ${market['volume_24h']:,.0f}")
            output.append(f"   💧 유동성: ${market['liquidity']:,.0f}")
            output.append(f"   🏷️  카테고리: {market['category']}")
            output.append(f"   🔗 Slug: {market['slug']}")

        return "\n".join(output)

    except requests.RequestException as e:
        return f"❌ API 요청 실패: {str(e)}"
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


def get_market_detail(market_slug: str) -> str:
    """특정 마켓 상세 정보"""
    try:
        url = f"{GAMMA_API_BASE}/markets/{market_slug}"
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        market = response.json()
        parsed = parse_market_data(market)

        if "error" in parsed:
            return f"❌ {parsed['error']}"

        # 상세 정보 포맷팅
        output = [
            f"📊 {parsed['question']}\n",
            f"🔹 YES 옵션",
            f"   가격: ${parsed['yes_price']:.4f}",
            f"   예측 확률: {parsed['yes_probability']:.2f}%",
            f"   Token ID: {parsed['clob_token_ids'][0] if parsed['clob_token_ids'] else 'N/A'}",
            f"\n🔹 NO 옵션",
            f"   가격: ${parsed['no_price']:.4f}",
            f"   예측 확률: {parsed['no_probability']:.2f}%",
            f"   Token ID: {parsed['clob_token_ids'][1] if len(parsed['clob_token_ids']) > 1 else 'N/A'}",
            f"\n📈 거래 정보",
            f"   24시간 거래량: ${parsed['volume_24h']:,.2f}",
            f"   유동성: ${parsed['liquidity']:,.2f}",
            f"   카테고리: {parsed['category']}",
            f"   종료 날짜: {parsed['end_date']}",
            f"\n🔗 Slug: {parsed['slug']}"
        ]

        return "\n".join(output)

    except requests.RequestException as e:
        return f"❌ API 요청 실패: {str(e)}"
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


def list_categories() -> str:
    """카테고리 목록 조회"""
    try:
        url = f"{GAMMA_API_BASE}/markets"
        params = {"closed": "false", "limit": 100}

        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()

        markets = response.json()

        # 카테고리 수집
        categories = {}
        for market in markets:
            category = market.get("groupItemTitle", "기타")
            categories[category] = categories.get(category, 0) + 1

        # 정렬
        sorted_categories = sorted(categories.items(), key=lambda x: x[1], reverse=True)

        # 포맷팅
        output = ["📂 Polymarket 카테고리\n"]
        for cat, count in sorted_categories:
            output.append(f"   {cat}: {count}개 마켓")

        return "\n".join(output)

    except requests.RequestException as e:
        return f"❌ API 요청 실패: {str(e)}"
    except Exception as e:
        return f"❌ 오류 발생: {str(e)}"


def main(
    action: str,
    category: Optional[str] = None,
    min_volume: Optional[float] = None,
    min_liquidity: Optional[float] = None,
    limit: int = 20,
    market_slug: Optional[str] = None
) -> str:
    """
    Polymarket 마켓 스캐너 메인 함수

    Args:
        action: 액션 타입 (scan, detail, categories)
        category: 카테고리 필터
        min_volume: 최소 24시간 거래량
        min_liquidity: 최소 유동성
        limit: 결과 수 (기본 20, 최대 100)
        market_slug: 마켓 slug (detail 액션용)
    """
    if action == "scan":
        return scan_markets(category, min_volume, min_liquidity, limit)
    elif action == "detail":
        if not market_slug:
            return "❌ detail 액션에는 market_slug가 필요합니다."
        return get_market_detail(market_slug)
    elif action == "categories":
        return list_categories()
    else:
        return f"❌ 알 수 없는 액션: {action}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 1:
        # 스키마 출력
        print(json.dumps(SCHEMA, indent=2, ensure_ascii=False))
    else:
        # CLI 테스트 모드
        if sys.argv[1] == "scan":
            print(scan_markets(limit=5))
        elif sys.argv[1] == "categories":
            print(list_categories())
        elif sys.argv[1] == "detail" and len(sys.argv) > 2:
            print(get_market_detail(sys.argv[2]))
        else:
            print("Usage: python market_scanner.py [scan|categories|detail <slug>]")
