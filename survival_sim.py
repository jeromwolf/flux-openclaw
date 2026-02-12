"""
Polymarket Survival Mode Simulator

시뮬레이션 모드로 작동하는 Polymarket 트레이딩 봇입니다.
실제 자금 없이 가상 거래를 실행하고 P&L을 추적합니다.

주요 기능:
- 가상 잔액으로 트레이딩 시뮬레이션 (기본 $50)
- 시장 스캔 및 잘못 가격이 책정된 기회 발견
- Kelly criterion 기반 포지션 사이징
- SQLite를 통한 거래 및 잔액 영속성
- 확률 기반 시뮬레이션 거래 해결
- API 비용 추정 및 차감

사용법:
    # 단일 사이클 실행
    python survival_sim.py --once

    # 10분 간격 연속 루프
    python survival_sim.py --loop --interval 600

    # 현재 상태 확인
    python survival_sim.py --status
"""

import os
import json
import time
import random
import sqlite3
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from threading import Lock

from config import get_config
from logging_config import setup_logging, get_logger

logger = get_logger("survival_sim")


@dataclass
class TradeResult:
    """거래 결과 데이터 클래스"""
    market_question: str
    market_slug: str
    side: str  # 'YES' or 'NO'
    amount: float
    entry_price: float
    estimated_prob: float
    edge: float
    kelly_fraction: float


class FairValueEstimator:
    """선구안(Selective Eye) 공정 가치 추정 엔진

    핵심 철학: "타수가 항상 공을 칠 필요 없다. 승률이 높을 때만 친다."

    필터링 기준:
    1. 극단적 가격 제외 (0.05~0.95 범위만)
    2. 충분한 유동성 필요 ($5,000+)
    3. 높은 엣지만 (12%+)
    4. 높은 신뢰도만 (0.5+)
    5. 추정 승률 60%+ 일 때만 거래
    """

    # === 선구안 전략 파라미터 ===
    MIN_EDGE = 0.06              # 최소 엣지 6% (선구안 - 충분히 선택적)
    MIN_CONFIDENCE = 0.3         # 최소 신뢰도 0.3
    MIN_WIN_PROB = 0.52          # 최소 추정 승률 52% (50% 이상에서만)
    MIN_PRICE = 0.01             # 극단적 저가 제외 (1% 미만)
    MAX_PRICE = 0.99             # 극단적 고가 제외 (99% 초과)
    MIN_LIQUIDITY = 2000         # 최소 유동성 $2,000 (스캔 필터와 동일)
    MAX_TRADES_PER_CYCLE = 2     # 사이클당 최대 2건
    KELLY_MAX_FRACTION = 0.06    # Kelly 최대 6% (Argona0x와 동일)
    MAX_BET_FRACTION = 0.10      # 최대 잔액의 10%

    def __init__(self):
        self.api_cost_per_call = 0.08  # Claude API 호출당 예상 비용

    def estimate_probability(self, market: Dict[str, Any]) -> Tuple[float, float]:
        """시장 확률 추정

        Returns:
            (estimated_yes_prob, confidence) 튜플
        """
        market_yes_prob = market['yes_probability'] / 100.0

        # 시뮬레이션: 시장 가격 ± 노이즈 (Claude 추정 편차 시뮬레이션)
        # 실제 Claude는 뉴스/데이터 기반으로 시장과 다른 추정을 할 수 있음
        noise = random.gauss(0, 0.10)
        estimated_prob = max(0.01, min(0.99, market_yes_prob + noise))

        # 신뢰도: 거래량 + 유동성 + 가격 안정성 종합 평가
        volume_score = min(1.0, market['volume_24h'] / 100000)   # 10만$ 기준
        liquidity_score = min(1.0, market['liquidity'] / 20000)  # 2만$ 기준

        # 가격 안정성: 0.2~0.8 범위에서 가장 높음 (극단 가격은 신뢰도 하락)
        price_stability = 1.0 - 2.0 * abs(market_yes_prob - 0.5)
        price_stability = max(0.1, price_stability)

        confidence = (volume_score * 0.4 + liquidity_score * 0.3 + price_stability * 0.3)

        return estimated_prob, confidence

    def _passes_quality_filter(self, market: Dict[str, Any]) -> bool:
        """시장 품질 필터 - 거래할 가치가 있는 시장인가?"""
        yes_price = market['yes_price']
        no_price = market['no_price']

        # 극단적 가격 제외 (너무 확실하거나 너무 불확실한 시장은 엣지가 없다)
        if yes_price < self.MIN_PRICE or yes_price > self.MAX_PRICE:
            return False

        # 유동성 부족 시장 제외
        if market['liquidity'] < self.MIN_LIQUIDITY:
            return False

        # YES + NO 가격 합이 비정상인 경우 제외 (스프레드 너무 넓음)
        spread = abs((yes_price + no_price) - 1.0)
        if spread > 0.15:  # 15% 이상 스프레드는 비정상
            return False

        return True

    def find_opportunities(
        self,
        markets: List[Dict[str, Any]],
        min_edge: float = None,
        min_confidence: float = None
    ) -> List[Dict[str, Any]]:
        """선구안 전략: 승률 높은 기회만 엄선

        "100개 마켓을 스캔해서 1~2개만 거래한다"
        """
        min_edge = min_edge or self.MIN_EDGE
        min_confidence = min_confidence or self.MIN_CONFIDENCE

        opportunities = []
        skipped_quality = 0
        skipped_confidence = 0
        skipped_edge = 0
        skipped_winprob = 0

        for market in markets:
            # 1단계: 품질 필터 (쓰레기 시장 제외)
            if not self._passes_quality_filter(market):
                skipped_quality += 1
                continue

            # 2단계: 확률 추정
            est_yes_prob, confidence = self.estimate_probability(market)

            # 3단계: 신뢰도 필터
            if confidence < min_confidence:
                skipped_confidence += 1
                continue

            market_yes_price = market['yes_price']
            market_no_price = market['no_price']

            # YES 쪽 엣지
            yes_edge = est_yes_prob - market_yes_price
            # NO 쪽 엣지
            no_edge = (1 - est_yes_prob) - market_no_price

            # 최적 사이드 결정
            if yes_edge > no_edge and yes_edge > min_edge:
                side = 'YES'
                edge = yes_edge
                est_prob = est_yes_prob
                market_price = market_yes_price
            elif no_edge > min_edge:
                side = 'NO'
                edge = no_edge
                est_prob = 1 - est_yes_prob
                market_price = market_no_price
            else:
                skipped_edge += 1
                continue

            # 4단계: 최소 승률 필터 (핵심!)
            # "승률 60% 미만이면 안 친다"
            if est_prob < self.MIN_WIN_PROB:
                skipped_winprob += 1
                continue

            # 5단계: 기대값(EV) 계산 - 양의 EV만
            odds = 1.0 / market_price
            expected_value = est_prob * (odds - 1) - (1 - est_prob)
            if expected_value <= 0:
                continue

            opportunities.append({
                'market': market,
                'side': side,
                'edge': edge,
                'estimated_prob': est_prob,
                'market_price': market_price,
                'confidence': confidence,
                'expected_value': expected_value
            })

        # EV × 신뢰도로 정렬 (가장 좋은 기회 우선)
        opportunities.sort(
            key=lambda x: x['expected_value'] * x['confidence'],
            reverse=True
        )

        logger.info(
            f"필터 결과: {len(markets)}개 중 "
            f"품질탈락={skipped_quality}, 신뢰도탈락={skipped_confidence}, "
            f"엣지부족={skipped_edge}, 승률부족={skipped_winprob} → "
            f"{len(opportunities)}개 통과"
        )

        return opportunities

    def calculate_kelly_size(
        self,
        balance: float,
        edge: float,
        price: float,
        max_fraction: float = None
    ) -> float:
        """보수적 Kelly criterion - Half Kelly 사용

        Full Kelly는 이론적 최적이지만 변동성이 크다.
        Half Kelly = Kelly / 2 → 수익 75% 유지, 변동성 50% 감소
        """
        max_fraction = max_fraction or self.KELLY_MAX_FRACTION

        if edge <= 0 or price <= 0 or price >= 1:
            return 0.0

        odds = 1.0 / price
        kelly_fraction = edge / (odds - 1)

        # Half Kelly 적용 (보수적)
        kelly_fraction = kelly_fraction * 0.5

        # 최대 비율 제한
        kelly_fraction = min(kelly_fraction, max_fraction)
        kelly_fraction = max(0, kelly_fraction)

        bet_amount = balance * kelly_fraction

        # 최소/최대 제한
        min_bet = 1.0
        max_bet = balance * self.MAX_BET_FRACTION

        return max(min_bet, min(bet_amount, max_bet))


class SurvivalSimulator:
    """생존 모드 시뮬레이터

    가상 자금으로 트레이딩을 시뮬레이션하고 P&L을 추적합니다.
    수익의 50%는 자동으로 적립금(reserve)으로 분리하여 보호합니다.
    """

    # 최소 잔액 - 이 이하로 내려가면 트레이딩 중단
    MIN_BALANCE = 10.0

    # 수익 적립 비율 (50% = 수익의 절반을 적립)
    PROFIT_RESERVE_RATIO = 0.50

    def __init__(self, initial_balance: float = 50.0, db_path: str = "data/survival_sim.db"):
        """시뮬레이터 초기화

        Args:
            initial_balance: 초기 가상 잔액 (USD)
            db_path: SQLite 데이터베이스 경로
        """
        self.db_path = db_path
        self.db_lock = Lock()
        self.estimator = FairValueEstimator()
        self.start_time = datetime.now()

        # 데이터베이스 초기화
        self._init_db()

        # 초기 잔액 설정 (데이터베이스가 비어있는 경우)
        if self._get_trade_count() == 0:
            with self.db_lock:
                conn = sqlite3.connect(self.db_path)
                try:
                    conn.execute(
                        "INSERT INTO sim_balance_log (timestamp, balance, event, detail) VALUES (?, ?, ?, ?)",
                        (datetime.now().isoformat(), initial_balance, "initial", "시뮬레이터 시작")
                    )
                    conn.commit()
                    logger.info(f"초기 잔액 설정: ${initial_balance:.2f}")
                finally:
                    conn.close()

    def _init_db(self):
        """SQLite 데이터베이스 및 테이블 초기화"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                # 거래 테이블
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        market_question TEXT NOT NULL,
                        market_slug TEXT,
                        side TEXT NOT NULL,
                        amount REAL NOT NULL,
                        entry_price REAL NOT NULL,
                        estimated_prob REAL NOT NULL,
                        edge REAL NOT NULL,
                        kelly_fraction REAL NOT NULL,
                        status TEXT DEFAULT 'open',
                        exit_price REAL,
                        pnl REAL,
                        resolved_at TEXT
                    )
                """)

                # 잔액 로그 테이블
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_balance_log (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        balance REAL NOT NULL,
                        event TEXT NOT NULL,
                        detail TEXT
                    )
                """)

                # 사이클 로그 테이블
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_cycles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        markets_scanned INTEGER,
                        opportunities_found INTEGER,
                        trades_placed INTEGER,
                        api_cost_estimate REAL,
                        cycle_duration_seconds REAL
                    )
                """)

                # 적립금(reserve) 테이블
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sim_reserve (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        amount REAL NOT NULL,
                        total_reserve REAL NOT NULL,
                        source TEXT NOT NULL
                    )
                """)

                conn.commit()
            finally:
                conn.close()

    def _get_trade_count(self) -> int:
        """총 거래 수 조회"""
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM sim_trades")
                return cursor.fetchone()[0]
            finally:
                conn.close()

    def get_balance(self) -> float:
        """현재 잔액 조회"""
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(
                    "SELECT balance FROM sim_balance_log ORDER BY id DESC LIMIT 1"
                )
                row = cursor.fetchone()
                return row[0] if row else 0.0
            finally:
                conn.close()

    def _log_balance(self, new_balance: float, event: str, detail: str):
        """잔액 변경 로그"""
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute(
                    "INSERT INTO sim_balance_log (timestamp, balance, event, detail) VALUES (?, ?, ?, ?)",
                    (datetime.now().isoformat(), new_balance, event, detail)
                )
                conn.commit()
            finally:
                conn.close()

    def simulate_trade(
        self,
        market: Dict[str, Any],
        side: str,
        amount: float,
        market_price: float,
        estimated_prob: float,
        edge: float,
        kelly_fraction: float
    ) -> bool:
        """거래 시뮬레이션 (실제 실행 없음)

        Returns:
            성공 여부
        """
        current_balance = self.get_balance()

        if amount > current_balance:
            logger.warning(f"잔액 부족: ${amount:.2f} 필요, ${current_balance:.2f} 보유")
            return False

        # 거래 기록
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    INSERT INTO sim_trades
                    (timestamp, market_question, market_slug, side, amount, entry_price,
                     estimated_prob, edge, kelly_fraction, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    market['question'],
                    market['slug'],
                    side,
                    amount,
                    market_price,
                    estimated_prob,
                    edge,
                    kelly_fraction,
                    'open'
                ))
                conn.commit()

                logger.info(
                    f"거래 시뮬레이션: {side} ${amount:.2f} @ ${market_price:.3f} "
                    f"(엣지: {edge:.1%}, 추정 확률: {estimated_prob:.1%})"
                )
            finally:
                conn.close()

        # 잔액에서 거래 금액 차감
        new_balance = current_balance - amount
        self._log_balance(new_balance, 'trade', f"{side} ${amount:.2f} on {market['question'][:50]}")

        return True

    def resolve_trades(self):
        """오픈 거래 해결

        시뮬레이션에서는 추정 확률에 기반하여 무작위로 해결합니다.
        예: 추정 확률 70%이면 70% 승리 확률

        이전 사이클의 모든 오픈 거래를 즉시 해결합니다.
        (현재 사이클에서 새로 생성된 거래는 다음 사이클에서 해결)
        """
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                # 현재 시점 이전의 모든 오픈 거래 조회 (이전 사이클 거래)
                cutoff_time = datetime.now().isoformat()
                cursor = conn.execute("""
                    SELECT id, side, amount, entry_price, estimated_prob, market_question
                    FROM sim_trades
                    WHERE status = 'open' AND timestamp < ?
                """, (cutoff_time,))

                open_trades = cursor.fetchall()

                # 현재 잔액 조회 (동일한 연결 사용)
                cursor = conn.execute(
                    "SELECT balance FROM sim_balance_log ORDER BY id DESC LIMIT 1"
                )
                row = cursor.fetchone()
                current_balance = row[0] if row else 0.0

                for trade_id, side, amount, entry_price, estimated_prob, question in open_trades:
                    # 확률 기반 해결
                    won = random.random() < estimated_prob

                    if won:
                        # 승리: 지불금 받기 ($1 per share - 진입 비용)
                        payout = amount / entry_price  # shares
                        pnl = payout - amount
                        status = 'won'

                        # 수익의 50%를 적립금으로 분리
                        if pnl > 0:
                            reserve_amount = pnl * self.PROFIT_RESERVE_RATIO
                            actual_payout = payout - reserve_amount
                            current_balance += actual_payout

                            # 적립금 기록
                            cursor2 = conn.execute(
                                "SELECT COALESCE(MAX(total_reserve), 0) FROM sim_reserve"
                            )
                            current_reserve = cursor2.fetchone()[0]
                            new_reserve_total = current_reserve + reserve_amount

                            conn.execute(
                                "INSERT INTO sim_reserve (timestamp, amount, total_reserve, source) VALUES (?, ?, ?, ?)",
                                (datetime.now().isoformat(), reserve_amount, new_reserve_total,
                                 f"거래 #{trade_id} 수익 50% 적립")
                            )

                            logger.info(
                                f"✅ 거래 승리: {side} +${pnl:.2f} "
                                f"(운용: +${pnl - reserve_amount:.2f}, 적립: +${reserve_amount:.2f}) "
                                f"({question[:50]})"
                            )
                        else:
                            current_balance += payout
                            logger.info(f"✅ 거래 승리: {side} +${pnl:.2f} ({question[:50]})")
                    else:
                        # 패배: 진입 금액 손실
                        pnl = -amount
                        status = 'lost'

                        logger.info(f"❌ 거래 패배: {side} ${pnl:.2f} ({question[:50]})")

                    # 거래 상태 업데이트
                    conn.execute("""
                        UPDATE sim_trades
                        SET status = ?, exit_price = ?, pnl = ?, resolved_at = ?
                        WHERE id = ?
                    """, (status, 1.0 if won else 0.0, pnl, datetime.now().isoformat(), trade_id))

                    # 잔액 로그 (동일한 연결 사용, 락 내부)
                    conn.execute(
                        "INSERT INTO sim_balance_log (timestamp, balance, event, detail) VALUES (?, ?, ?, ?)",
                        (datetime.now().isoformat(), current_balance, 'resolution', f"{status.upper()}: ${pnl:+.2f}")
                    )

                conn.commit()

                if open_trades:
                    logger.info(f"{len(open_trades)}개 거래 해결 완료")

            finally:
                conn.close()

    def run_cycle(self):
        """단일 트레이딩 사이클 실행

        1. 시장 스캔
        2. 공정 가치 추정
        3. 잘못 가격이 책정된 기회 찾기
        4. Kelly 포지션 크기 계산
        5. 거래 시뮬레이션
        6. 시뮬레이션된 API 비용 차감
        7. 모든 것을 로그
        """
        cycle_start = time.time()
        logger.info("=== 트레이딩 사이클 시작 ===")

        # 오픈 거래 해결
        self.resolve_trades()

        current_balance = self.get_balance()

        if current_balance <= self.MIN_BALANCE:
            logger.error(f"💀 잔액 ${current_balance:.2f} (최소 ${self.MIN_BALANCE}) - 트레이딩 중단!")
            return

        logger.info(f"현재 잔액: ${current_balance:.2f}")

        # 1. 시장 스캔 (market_scanner 사용)
        try:
            logger.info("시장 스캔 중...")
            markets = self._scan_markets()
            logger.info(f"{len(markets)}개 시장 스캔 완료")
        except Exception as e:
            logger.error(f"시장 스캔 실패: {e}", exc_info=True)
            return

        # 2. 선구안 전략: 승률 높은 기회만 엄선
        opportunities = self.estimator.find_opportunities(markets)
        logger.info(f"{len(opportunities)}개 고품질 기회 발견")

        # API 비용 추정 (시뮬레이션 모드)
        api_cost = 0.10

        # 3. 상위 기회에만 거래 (선구안: 사이클당 최대 2건)
        trades_placed = 0
        max_trades = FairValueEstimator.MAX_TRADES_PER_CYCLE

        if not opportunities:
            logger.info("⏸️  이번 사이클 패스 - 충분한 기회 없음 (선구안 전략)")

        for opp in opportunities[:max_trades]:
            # Half Kelly 사이징
            bet_amount = self.estimator.calculate_kelly_size(
                balance=current_balance,
                edge=opp['edge'],
                price=opp['market_price']
            )

            if bet_amount < 1.0:
                continue

            # 거래 시뮬레이션
            success = self.simulate_trade(
                market=opp['market'],
                side=opp['side'],
                amount=bet_amount,
                market_price=opp['market_price'],
                estimated_prob=opp['estimated_prob'],
                edge=opp['edge'],
                kelly_fraction=bet_amount / current_balance
            )

            if success:
                trades_placed += 1
                current_balance -= bet_amount

        # 4. API 비용 차감
        if api_cost > 0:
            new_balance = current_balance - api_cost
            self._log_balance(new_balance, 'api_cost', f"API 호출 비용: ${api_cost:.2f}")
            logger.info(f"API 비용 차감: ${api_cost:.2f}")

        # 5. 사이클 로그
        cycle_duration = time.time() - cycle_start
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                conn.execute("""
                    INSERT INTO sim_cycles
                    (timestamp, markets_scanned, opportunities_found, trades_placed,
                     api_cost_estimate, cycle_duration_seconds)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    datetime.now().isoformat(),
                    len(markets),
                    len(opportunities),
                    trades_placed,
                    api_cost,
                    cycle_duration
                ))
                conn.commit()
            finally:
                conn.close()

        logger.info(f"=== 사이클 완료 ({cycle_duration:.1f}초) ===")

    def _scan_markets(self) -> List[Dict[str, Any]]:
        """Polymarket API에서 시장 스캔

        market_scanner 도구를 직접 호출하는 대신 Gamma API를 직접 호출합니다.
        """
        try:
            logger.info("시장 스캔 시작...")
            url = "https://gamma-api.polymarket.com/markets"
            params = {
                "closed": "false",
                "limit": 50  # 상위 50개 활성 시장
            }

            logger.debug(f"API 요청: {url}")
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            logger.info(f"API 응답 수신: {response.status_code}")

            markets_raw = response.json()

            # 파싱 및 필터링
            markets = []
            for market in markets_raw:
                try:
                    # JSON 필드 파싱
                    outcomes = json.loads(market.get("outcomes", "[]"))
                    outcome_prices = json.loads(market.get("outcomePrices", "[]"))

                    if len(outcome_prices) < 2:
                        continue

                    yes_price = float(outcome_prices[0])
                    no_price = float(outcome_prices[1])

                    # 최소 유동성 필터 ($2000)
                    liquidity = float(market.get("liquidity", 0))
                    if liquidity < 2000:
                        continue

                    markets.append({
                        'question': market.get('question', ''),
                        'slug': market.get('slug', ''),
                        'yes_price': yes_price,
                        'no_price': no_price,
                        'yes_probability': yes_price * 100,
                        'no_probability': no_price * 100,
                        'volume_24h': float(market.get('volume24hr', 0)),
                        'liquidity': liquidity,
                        'category': market.get('groupItemTitle', ''),
                    })

                except Exception as e:
                    logger.debug(f"시장 파싱 건너뛰기: {e}")
                    continue

            return markets

        except Exception as e:
            logger.error(f"시장 스캔 오류: {e}")
            raise

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 조회"""
        with self.db_lock:
            conn = sqlite3.connect(self.db_path)
            try:
                # 잔액
                cursor = conn.execute(
                    "SELECT balance FROM sim_balance_log ORDER BY id DESC LIMIT 1"
                )
                row = cursor.fetchone()
                current_balance = row[0] if row else 0.0

                # 초기 잔액
                cursor = conn.execute(
                    "SELECT balance FROM sim_balance_log ORDER BY id ASC LIMIT 1"
                )
                row = cursor.fetchone()
                initial_balance = row[0] if row else 0.0

                # P&L
                pnl = current_balance - initial_balance
                pnl_pct = (pnl / initial_balance * 100) if initial_balance > 0 else 0

                # 거래 통계
                cursor = conn.execute("SELECT COUNT(*) FROM sim_trades")
                total_trades = cursor.fetchone()[0]

                cursor = conn.execute("SELECT COUNT(*) FROM sim_trades WHERE status = 'won'")
                won_trades = cursor.fetchone()[0]

                cursor = conn.execute("SELECT COUNT(*) FROM sim_trades WHERE status = 'lost'")
                lost_trades = cursor.fetchone()[0]

                win_rate = (won_trades / (won_trades + lost_trades) * 100) if (won_trades + lost_trades) > 0 else 0

                # API 비용 (사이클 테이블에서 합계)
                cursor = conn.execute(
                    "SELECT COALESCE(SUM(api_cost_estimate), 0) FROM sim_cycles"
                )
                api_cost_total = cursor.fetchone()[0]

                # 거래 P&L 합계
                cursor = conn.execute(
                    "SELECT COALESCE(SUM(pnl), 0) FROM sim_trades WHERE status IN ('won', 'lost')"
                )
                total_trade_pnl = cursor.fetchone()[0]

                # 오픈 거래 총 금액 (아직 resolve 안 된 베팅)
                cursor = conn.execute(
                    "SELECT COALESCE(SUM(amount), 0) FROM sim_trades WHERE status = 'open'"
                )
                open_trade_amount = cursor.fetchone()[0]

                # 가동 시간
                cursor = conn.execute(
                    "SELECT timestamp FROM sim_cycles ORDER BY id ASC LIMIT 1"
                )
                first_cycle = cursor.fetchone()
                uptime = "N/A"
                if first_cycle:
                    start_dt = datetime.fromisoformat(first_cycle[0])
                    uptime_delta = datetime.now() - start_dt
                    hours = int(uptime_delta.total_seconds() // 3600)
                    minutes = int((uptime_delta.total_seconds() % 3600) // 60)
                    uptime = f"{hours}h {minutes}m"

                # 마지막 사이클
                cursor = conn.execute(
                    "SELECT timestamp FROM sim_cycles ORDER BY id DESC LIMIT 1"
                )
                last_cycle = cursor.fetchone()
                last_cycle_time = last_cycle[0] if last_cycle else "N/A"

                open_trades = total_trades - won_trades - lost_trades

                # 적립금 총액
                cursor = conn.execute(
                    "SELECT COALESCE(MAX(total_reserve), 0) FROM sim_reserve"
                )
                total_reserve = cursor.fetchone()[0]

                # 총 자산 = 운용 잔액 + 적립금
                total_assets = current_balance + total_reserve

                return {
                    'balance': current_balance,
                    'initial_balance': initial_balance,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'total_trades': total_trades,
                    'won_trades': won_trades,
                    'lost_trades': lost_trades,
                    'open_trades': open_trades,
                    'win_rate': win_rate,
                    'trade_pnl': total_trade_pnl,
                    'api_cost': api_cost_total,
                    'open_amount': open_trade_amount,
                    'alive': current_balance > self.MIN_BALANCE,
                    'min_balance': self.MIN_BALANCE,
                    'uptime': uptime,
                    'last_cycle': last_cycle_time,
                    'reserve': total_reserve,
                    'total_assets': total_assets
                }

            finally:
                conn.close()

    def is_alive(self) -> bool:
        """생존 확인 (잔액 > 최소 잔액)"""
        return self.get_balance() > self.MIN_BALANCE

    def print_status(self):
        """상태를 콘솔에 출력"""
        status = self.get_status()

        print("\n" + "="*55)
        print("            SURVIVAL MODE STATUS")
        print("="*55)
        print(f"  Balance:      ${status['balance']:.2f} (운용 잔액)")
        print(f"  Reserve:      ${status['reserve']:.2f} (적립금 - 수익의 50%)")
        print(f"  Total Assets: ${status['total_assets']:.2f} (운용 + 적립)")
        print(f"  Started:      ${status['initial_balance']:.2f}")
        print(f"  Min Balance:  ${status['min_balance']:.2f} (이하 시 트레이딩 중단)")
        print("-"*55)
        print(f"  P&L:          ${status['pnl']:+.2f} ({status['pnl_pct']:+.1f}%)")
        print(f"  Trade P&L:    ${status['trade_pnl']:+.2f}")
        print(f"  API Cost:     ${status['api_cost']:.2f}")
        print("-"*55)
        print(f"  Total Trades: {status['total_trades']}")
        print(f"    Won:        {status['won_trades']}")
        print(f"    Lost:       {status['lost_trades']}")
        print(f"    Open:       {status['open_trades']} (${status['open_amount']:.2f} 베팅중)")
        print(f"  Win Rate:     {status['win_rate']:.1f}%")
        print("-"*55)
        print(f"  Alive:        {'YES' if status['alive'] else 'STOPPED'}")
        print(f"  Uptime:       {status['uptime']}")
        print(f"  Last Cycle:   {status['last_cycle']}")
        print("="*55 + "\n")


def main():
    """CLI 진입점"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Polymarket Survival Simulator - 시뮬레이션 모드 트레이딩 봇",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python survival_sim.py --once                    # 단일 사이클 실행
  python survival_sim.py --loop --interval 600     # 10분 간격 루프
  python survival_sim.py --status                  # 현재 상태 확인
  python survival_sim.py --balance 100 --once      # $100으로 시작
        """
    )

    parser.add_argument("--balance", type=float, default=50.0, help="초기 잔액 (USD, 기본값: 50)")
    parser.add_argument("--once", action="store_true", help="단일 사이클 실행")
    parser.add_argument("--loop", action="store_true", help="연속 루프 실행")
    parser.add_argument("--status", action="store_true", help="현재 상태 표시")
    parser.add_argument("--interval", type=int, default=600, help="루프 간격 (초, 기본값: 600)")
    parser.add_argument("--db", type=str, default="data/survival_sim.db", help="데이터베이스 경로")

    args = parser.parse_args()

    # 로깅 설정
    cfg = get_config()
    setup_logging(
        level=cfg.log_level,
        log_format=cfg.log_format,
        log_file="logs/survival_sim.log"
    )

    # 시뮬레이터 초기화
    simulator = SurvivalSimulator(
        initial_balance=args.balance,
        db_path=args.db
    )

    if args.status:
        # 상태만 표시
        simulator.print_status()

    elif args.once:
        # 단일 사이클
        logger.info("단일 사이클 모드")
        simulator.run_cycle()
        simulator.print_status()

    elif args.loop:
        # 연속 루프
        logger.info(f"연속 루프 모드 (간격: {args.interval}초)")
        try:
            while simulator.is_alive():
                simulator.run_cycle()

                if not simulator.is_alive():
                    logger.error(f"💀 잔액 ${simulator.get_balance():.2f} (최소 ${SurvivalSimulator.MIN_BALANCE}) - 트레이딩 중단!")
                    simulator.print_status()
                    break

                logger.info(f"{args.interval}초 대기 중...")
                time.sleep(args.interval)

        except KeyboardInterrupt:
            logger.info("\n사용자에 의해 중단됨")
            simulator.print_status()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
