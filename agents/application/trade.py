import logging
import shutil
import json
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
import ast
from os import getenv
import random

from agents.application.executor import Executor as Agent
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.utils.objects import SimpleMarket

logger = logging.getLogger(__name__)

# Performance tracking
TRADING_TRACKING_FILE = Path("trading_performance.json")


class Trader:
    def __init__(self, trading_strategy):
        self.polymarket = Polymarket()
        self.gamma = Gamma()
        self.agent = Agent()
        self.trading_strategy = trading_strategy

    def pre_trade_logic(self) -> None:
        self.clear_local_dbs()

    def clear_local_dbs(self) -> None:
        """Clear local database directories."""
        for db_dir in ["local_db_events", "local_db_markets"]:
            db_path = Path(db_dir)
            if db_path.exists():
                try:
                    shutil.rmtree(db_path)
                    logger.info(f"Cleared {db_dir}")
                except OSError as e:
                    logger.warning(f"Failed to clear {db_dir}: {e}")

    def ai_one_best_trade(self) -> None:
        """

        ai_one_best_trade is a strategy that evaluates all events, markets, and orderbooks

        leverages all available information sources accessible to the autonomous agent

        then executes that trade without any human intervention

        """
        try:
            self.pre_trade_logic()

            events = self.polymarket.get_all_tradeable_events()
            logger.info(f"1. FOUND {len(events)} EVENTS")

            filtered_events = self.agent.filter_events_with_rag(events)
            logger.info(f"2. FILTERED {len(filtered_events)} EVENTS")

            markets = self.agent.map_filtered_events_to_markets(filtered_events)
            logger.info(f"3. FOUND {len(markets)} MARKETS")

            filtered_markets = self.agent.filter_markets(markets)
            logger.info(f"4. FILTERED {len(filtered_markets)} MARKETS")

            if not filtered_markets:
                logger.warning("No markets found after filtering")
                return

            market = filtered_markets[0]
            best_trade_string = self.agent.source_best_trade(market)
            logger.info("5. CALCULATED TRADE:")
            logger.info(f"Trading on market id {market[0].metadata["id"]}: {market[0].metadata["question"]}")
            logger.info(best_trade_string)

            best_trade = self.agent.format_trade_prompt_for_execution(best_trade_string, market)

            # Please refer to TOS before uncommenting: polymarket.com/tos
            trade = self.polymarket.execute_market_order(best_trade)
            logger.info(f"6. TRADED {trade}")

        except Exception as e:
            logger.error(f"Error in ai_one_best_trade: {e}", exc_info=True)
            # TODO: re-enable retry
            #logger.info("Retrying...")
            #self.ai_one_best_trade()

    def initialize_trading_performance(self):
        """Initialize trading performance tracking file."""
        global TRADING_TRACKING_FILE
        performance = {
            "start_time": datetime.now().isoformat(),
            "total_trades": 0,
            "total_payout": 0.0,
            "total_dollar_amount_spent": 0.0,
            "open_positions": {},
            "closed_positions": {},
            "trade_history": [],
            "status": "running"
        }
        TRADING_TRACKING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TRADING_TRACKING_FILE, 'w') as f:
            json.dump(performance, f, indent=2)
        logger.info(f"Initialized trading performance tracking: {TRADING_TRACKING_FILE}")

    def load_trading_performance(self) -> dict:
        """Load trading performance from file."""
        if TRADING_TRACKING_FILE.exists():
            try:
                with open(TRADING_TRACKING_FILE, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load trading performance: {e}")
        return None

    def save_trading_performance(self, performance: dict):
        """Save trading performance to file."""
        try:
            with open(TRADING_TRACKING_FILE, 'w') as f:
                json.dump(performance, f, indent=2)
            logger.info(f"Saved trading performance: {performance}")
        except Exception as e:
            logger.error(f"Failed to save trading performance: {e}")

    def record_trade(self, trade_data: dict, positions: dict):
        """Record a trade in trading performance tracking."""
        performance = self.load_trading_performance()
        if not performance:
            self.initialize_trading_performance()
            performance = self.load_trading_performance()

        # Record trade
        trade_record = {
            "timestamp": datetime.now().isoformat(),
            "market_id": trade_data["market"]["id"],
            "market_question": trade_data["market"]["question"],
            "side": trade_data["side"],
            "dollar_amount": trade_data["dollar_amount"],
            "shares_amount": trade_data["dollar_amount"] / trade_data["price"],
            "entry_price": trade_data["price"]
        }
        performance["trade_history"].append(trade_record)
        performance["total_trades"] += 1
        performance["total_dollar_amount_spent"] += trade_data["dollar_amount"]

        # Update open positions (nested by market ID)
        if "open_positions" not in performance:
            performance["open_positions"] = {}
        performance["open_positions"][str(trade_data["market"]["id"])] = positions

        self.save_trading_performance(performance)
        logger.info(f"Recorded trade: {trade_record}")

    def simulate_market_outcome(self, market: SimpleMarket) -> dict:
        """
        Simulate market outcome at close based on actual market prices.
        The more expensive outcome is the one the market thinks is most likely.
        Returns: {'outcome': 'YES' or 'NO', 'payout': float}
        """
        try:
            # Use actual market prices to determine outcome
            # The higher-priced outcome is considered more likely
            outcome_prices = ast.literal_eval(market["outcome_prices"])
            yes_price = float(outcome_prices[0])
            no_price = float(outcome_prices[1])
            
            if yes_price > no_price:
                outcome = "YES"
                logger.info(f"Market outcome predicted to be: {outcome} (Yes price: ${yes_price}, No price: ${no_price})")
            elif no_price > yes_price:
                outcome = "NO"
                logger.info(f"Market outcome predicted to be: {outcome} (No price: ${no_price}, Yes price: ${yes_price})")
            else:
                # If prices are equal, flip a coin
                outcome = random.choice(["YES", "NO"])
                logger.info(f"Market prices equal (${yes_price}), random outcome: {outcome}")
            
            # Payout is always $1 per share (or equivalent value)
            # The actual payout depends on outcome matching
            return {
                "outcome": outcome,
                "payout_per_share": 1.0
            }
        except Exception as e:
            logger.error(f"Error simulating market outcome: {e}")
            return {"outcome": "NO", "payout_per_share": 1.0}

    def calculate_exit_pnl(self, positions: dict, outcome: dict) -> dict:
        """Calculate P&L for exiting arbitrage positions."""
        amount_yes = positions.get("amount_yes", 0.0)
        amount_no = positions.get("amount_no", 0.0)
        cost_yes = positions.get("cost_yes", 0.0)
        cost_no = positions.get("cost_no", 0.0)

        # Get payout for YES or NO
        payout = outcome["payout_per_share"]

        # Calculate total payout based on market outcome
        # The losing side's tokens expire worthless
        if outcome["outcome"] == "YES":
            total_payout = amount_yes * payout
        else:
            total_payout = amount_no * payout

        total_cost = cost_yes + cost_no
        profit = total_payout - total_cost

        return {
            "total_payout": total_payout,
            "total_cost": total_cost,
            "profit": profit,
            "yes_payout": amount_yes * payout if outcome["outcome"] == "YES" else 0,
            "no_payout": amount_no * payout if outcome["outcome"] == "NO" else 0,
            "realized_profit": profit
        }

    def monitor_market_prices(self, market: SimpleMarket) -> dict:
        """Monitor YES/NO prices for a market with connection error handling."""
        try:
            token_ids = ast.literal_eval(market["clob_token_ids"])
            if len(token_ids) != 2:
                return {}

            # Get best prices for YES and NO tokens with individual error handling
            yes_price = None
            no_price = None

            try:
                yes_price = self.polymarket.get_orderbook_price(token_ids[0], "BUY")
            except Exception as e:
                logger.warning(f"Failed to fetch YES price for market {market['id']}: {e}")

            try:
                no_price = self.polymarket.get_orderbook_price(token_ids[1], "BUY")
            except Exception as e:
                logger.warning(f"Failed to fetch NO price for market {market['id']}: {e}")

            # Only return if we got both prices
            if yes_price is None or no_price is None:
                logger.warning(f"Could not fetch complete prices for market {market['id']}")
                return {}

            return {
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1]
            }

        except Exception as e:
            logger.error(f"Error monitoring prices for market {market["id"]}: {e}")
            return {}

    def calculate_arbitrage_trade(self, positions: dict, prices: dict, market: SimpleMarket, skip_initial_trade_wait: bool = False) -> dict:
        """Calculate optimal arbitrage trade based on current positions and prices."""
        try:
            # Current position metrics
            amount_yes = positions["amount_yes"]
            amount_no = positions["amount_no"] 
            cost_yes = positions["cost_yes"]
            cost_no = positions["cost_no"]
            
            # Current averages
            avg_yes = cost_yes / amount_yes if amount_yes > 0 else 0
            avg_no = cost_no / amount_no if amount_no > 0 else 0
            current_pair_cost = avg_yes + avg_no

            is_initial_trade = amount_yes == 0 and amount_no == 0 # initial trade in this market

            # Restrict initial trades to first 1 minute of market window
            if is_initial_trade and not(skip_initial_trade_wait):
                try:
                    current_time = datetime.now(timezone.utc)
                    # Parse market start time
                    market_start = datetime.fromisoformat(market["eventStartTime"].replace("Z", "+00:00"))
                    # Calculate time elapsed since market start
                    time_elapsed = current_time - market_start
                    # Only trade initial positions within first 1 minute
                    if time_elapsed > timedelta(minutes=1):
                        # Calculate time until market end to wait efficiently
                        try:
                            market_end = datetime.fromisoformat(market["endDate"].replace("Z", "+00:00"))
                            time_until_end = market_end - current_time
                            # Wait until 2 minutes before market end
                            wait_target = max(timedelta(minutes=2), time_until_end - timedelta(minutes=2))

                            if time_until_end > timedelta(minutes=2):
                                wait_seconds = int(wait_target.total_seconds())
                                logger.info(f"Trade rejected: Market started {time_elapsed.total_seconds():.0f}s ago (exceeds 1min window)")
                                logger.info(f"Waiting {wait_seconds}s until near market end ({time_until_end.total_seconds():.0f}s remaining)")
                                time.sleep(wait_seconds)
                                return {}
                            else:
                                logger.info(f"Trade rejected: Market started {time_elapsed.total_seconds():.0f}s ago, market ending in {time_until_end.total_seconds():.0f}s")
                                return {}
                        except (KeyError, ValueError) as e:
                            logger.warning(f"Could not parse market end time: {e}")
                            logger.info(f"Trade rejected: Market started {time_elapsed.total_seconds():.0f}s ago (exceeds 1min window)")
                            return {}
                except (KeyError, ValueError) as e:
                    logger.warning(f"Could not parse market start time, allowing trade: {e}")

            # Price thresholds (configurable)
            cheap_threshold = float(getenv("ARBITRAGE_CHEAP_THRESHOLD", "0.49"))
            mispricing_threshold = float(getenv("ARBITRAGE_MISPRICING_THRESHOLD", "1.05"))
            safety_margin = float(getenv("ARBITRAGE_SAFETY_MARGIN", "0.99"))

            # Check for cheap opportunities
            yes_cheap = prices["yes_price"] and prices["yes_price"] < cheap_threshold
            no_cheap = prices["no_price"] and prices["no_price"] < cheap_threshold

            # NEW: Relative mispricing check - when market is inefficient
            if not (yes_cheap or no_cheap) and prices.get("yes_price") and prices.get("no_price"):
                total_price = prices["yes_price"] + prices["no_price"]
                if total_price > mispricing_threshold:
                    # Market is inefficient - trade the cheaper side
                    yes_cheap = prices["yes_price"] < prices["no_price"]
                    no_cheap = prices["no_price"] < prices["yes_price"]
                    logger.info(f"Relative mispricing detected: yes={prices['yes_price']:.3f} + no={prices['no_price']:.3f} = {total_price:.3f} > {mispricing_threshold}")

            if not (yes_cheap or no_cheap):
                return {}  # No opportunity

            # Determine trade side and size
            side = "YES" if yes_cheap else "NO"
            price = prices["yes_price"] if side == "YES" else prices["no_price"]
            
            # Calculate position size (similar to existing sizing logic)
            usdc_balance = self.polymarket.get_usdc_balance()
            
            # Only check balance for initial trades (no existing positions)
            if is_initial_trade and usdc_balance < 3:
                logger.info(f"Trade rejected: balance {usdc_balance} is below minimum $3 for initial trade")
                return {}

            base_size = max(min(usdc_balance * 0.05, 10.0), 1.0)  # ceiling of 5% of balance or $10, floor of $1
            
            # Adjust size to maintain balance
            if side == "YES":
                size_adjustment = amount_no - amount_yes  # Buy more YES if we have more NO
            else:
                size_adjustment = amount_yes - amount_no  # Buy more NO if we have more YES
                
            size = base_size * (1 + size_adjustment * 0.1)  # Small adjustment for balancing
            
            # Minimum order size is 1, if less than this then don't bother buying
            if size < 1:
                logger.info(f"Trade rejected: size {size} is below minimum amount 1")
                return {}

            # Calculate new costs and pair cost
            new_amount = amount_yes + size if side == "YES" else amount_no + size
            new_cost = cost_yes + (price * size) if side == "YES" else cost_no + (price * size)
            
            new_avg = new_cost / new_amount
            other_avg = avg_no if side == "YES" else avg_yes
            new_pair_cost = new_avg + other_avg
            
            # Safety check
            if new_pair_cost >= safety_margin:
                logger.info(f"Trade rejected: new_pair_cost {new_pair_cost} >= {safety_margin}")
                return {}
                
            # Prepare trade data (similar to existing format)
            trade = {
                "market": market,
                "side": side,
                "dollar_amount": size,
                "price": price,
                "token_id": prices["yes_token_id"] if side == "YES" else prices["no_token_id"],
                "new_pair_cost": new_pair_cost
            }
            
            logger.info(f"Calculated arbitrage trade: {trade}")
            return trade
            
        except Exception as e:
            logger.error(f"Error calculating arbitrage trade: {e}")
            return {}

    def check_arbitrage_exit(self, positions: dict) -> bool:
        """Check if arbitrage strategy should exit with guaranteed profit."""
        try:
            amount_yes = positions["amount_yes"]
            amount_no = positions["amount_no"]
            cost_yes = positions["cost_yes"]
            cost_no = positions["cost_no"]
            
            total_cost = cost_yes + cost_no
            min_amount = min(amount_yes, amount_no)
            
            # Exit when min(amount_yes, amount_no) > (cost_yes + cost_no)
            should_exit = min_amount > total_cost
            
            if should_exit:
                profit = min_amount - total_cost
                logger.info(f"Arbitrage: Guaranteed profit ${profit:.2f}")
                
            return should_exit
            
        except Exception as e:
            logger.error(f"Error checking arbitrage exit: {e}")
            return False

    def report_trading_performance(self) -> None:
        """Report trading performance summary."""
        performance = self.load_trading_performance()
        if not performance:
            logger.warning("No trading performance data found")
            return

        console = logging.getLogger(__name__)
        console.info("=" * 60)
        console.info("TRADING PERFORMANCE SUMMARY")
        console.info("=" * 60)
        console.info(f"Start Time: {performance.get('start_time', 'N/A')}")
        console.info(f"Status: {performance.get('status', 'N/A')}")
        console.info(f"Total Trades: {performance.get('total_trades', 0)}")
        console.info(f"Total Dollar Amount Spent: ${performance.get('total_dollar_amount_spent', 0):.2f}")
        console.info(f"Total Payout: ${performance.get('total_payout', 0):.2f}")

        if performance.get('trade_history'):
            console.info("\nTrade History:")
            for i, trade in enumerate(performance['trade_history'], 1):
                console.info(f"  {i}. Market: {trade.get('market_id', 'N/A')}")
                console.info(f"     {trade.get('market_question', 'N/A')}")
                console.info(f"     Side: {trade.get('side')}, Amount: ${trade.get('shares_amount')}, "
                           f"Entry Price: ${trade.get('entry_price')}, Dollar Cost: ${trade.get('dollar_amount'):.2f}")

        if performance.get('open_positions'):
            console.info("\nOpen Positions:")
            for market_id, pos in performance['open_positions'].items():
                if pos.get('amount_yes', 0) > 0 or pos.get('amount_no', 0) > 0:
                    console.info(f"  Market ID: {market_id}")
                    console.info(f"    YES: {pos.get('amount_yes')} shares, Cost: ${pos.get('cost_yes', 0):.2f}")
                    console.info(f"    NO: {pos.get('amount_no')} shares, Cost: ${pos.get('cost_no', 0):.2f}")

        if performance.get('closed_positions'):
            console.info("\nClosed Positions:")
            for market_id, pos in performance['closed_positions'].items():
                if pos.get('amount_yes', 0) > 0 or pos.get('amount_no', 0) > 0:
                    console.info(f"  Market ID: {market_id}")
                    console.info(f"    YES: {pos.get('amount_yes')} shares, Cost: ${pos.get('cost_yes', 0):.2f}")
                    console.info(f"    NO: {pos.get('amount_no')} shares, Cost: ${pos.get('cost_no', 0):.2f}")

        console.info("=" * 60)

    def arbitrage(self, dry_run: bool, slug: str) -> None:
        """Arbitrage strategy implementation."""
        try:
            self.pre_trade_logic()

            market = self.polymarket.get_active_market_from_series(slug)
            logger.debug(f"Monitoring market {market["id"]}: {market["question"]}")

            # Load positions (from the trading performance json file)
            performance = self.load_trading_performance()
            if performance and str(market["id"]) in performance.get("closed_positions", {}):
                current_positions = performance["closed_positions"][str(market["id"])].copy()
                logger.info(f"Positions for market {market['id']} have already been closed in trading_performance.json")
                return
            elif performance and str(market["id"]) in performance.get("open_positions", {}):
                current_positions = performance["open_positions"][str(market["id"])].copy()
                logger.info(f"Loaded positions for market {market['id']} from trading_performance.json")
            else:
                current_positions = {"amount_yes": 0.0, "amount_no": 0.0, "cost_yes": 0.0, "cost_no": 0.0}
                logger.info(f"No existing positions for market {market['id']}")

            # Check exit condition first
            if self.check_arbitrage_exit(current_positions):
                logger.info("Arbitrage strategy complete - profit locked in")
                # Calculate exit P&L for both modes
                outcome = self.simulate_market_outcome(market)
                pnl = self.calculate_exit_pnl(current_positions, outcome)

                if dry_run:
                    logger.info(f"DRY RUN EXIT P&L: ${pnl['profit']:.2f}")
                else:
                    logger.info(f"LIVE EXIT P&L: ${pnl['profit']:.2f}")

                # Update profit in performance tracking
                if performance:
                    performance["total_payout"] += pnl['total_payout']
                    completed_trade = {
                        "timestamp": datetime.now().isoformat(),
                        "market_id": market["id"],
                        "market_question": market["question"],
                        "exit_pnl": pnl['profit']
                    }
                    performance["trade_history"].append(completed_trade)
                    self.save_trading_performance(performance)

                # Store final positions in closed_positions before reset
                if performance:
                    if "closed_positions" not in performance:
                        performance["closed_positions"] = {}
                    # Create a copy to store the final state before reset
                    final_positions = current_positions.copy()
                    performance["closed_positions"][str(market["id"])] = final_positions

                # Reset positions to 0 after exit
                current_positions["amount_yes"] = 0.0
                current_positions["amount_no"] = 0.0
                current_positions["cost_yes"] = 0.0
                current_positions["cost_no"] = 0.0

                # Save the reset positions to prevent re-exit on next run
                if performance:
                    if "open_positions" not in performance:
                        performance["open_positions"] = {}
                    performance["open_positions"][str(market["id"])] = current_positions
                    self.save_trading_performance(performance)

                return

            prices = self.monitor_market_prices(market)
            if not prices:
                logger.warning("Could not get prices for market")
                return

            # Calculate trade
            trade = self.calculate_arbitrage_trade(current_positions, prices, market, dry_run)
            if not trade:
                logger.info("No profitable trade opportunity found")
                return

            if not dry_run:
                # Execute real trade
                trade_result = self.polymarket.execute_market_order([market], trade["dollar_amount"], trade["token_id"])
                logger.info(f"TRADE EXECUTED: {trade_result}")
                trade_amount = float(trade_result["takingAmount"]) # number of shares purchased
                trade_cost = float(trade_result["makingAmount"]) # $ cost of the shares
                # Update positions
                current_positions["market_id"] = market["id"]
                if trade["side"] == "YES":
                    current_positions["amount_yes"] += trade_amount
                    current_positions["cost_yes"] += trade_cost
                else:
                    current_positions["amount_no"] += trade_amount
                    current_positions["cost_no"] += trade_cost

                # Record trade entry in performance tracking for live mode
                trade_entry_record = {
                    "timestamp": datetime.now().isoformat(),
                    "market_id": market["id"],
                    "market_question": market["question"],
                    "side": trade["side"],
                    "dollar_amount": trade_cost,
                    "shares_amount": trade_amount,
                    "entry_price": trade_cost/trade_amount
                }
                
                if not performance:
                    # First trade ever - initialize performance tracking
                    self.initialize_trading_performance()
                    performance = self.load_trading_performance()
                    logger.info(f"Initialized performance tracking")

                performance["trade_history"].append(trade_entry_record)
                performance["total_trades"] += 1
                performance["total_dollar_amount_spent"] += trade["dollar_amount"]
                # Update open positions
                if "open_positions" not in performance:
                    performance["open_positions"] = {}
                performance["open_positions"][str(market["id"])] = current_positions
                self.save_trading_performance(performance)
                logger.info(f"Recorded live trade entry: {trade_entry_record}")
            else:
                # DRY RUN: Simulate trade execution
                logger.info(f"DRY RUN: Simulating {trade['side']} trade of ${trade['dollar_amount']} at ${trade['price']}")

                # Create simulated shares
                # In real execution, we get shares; in dry run, we simulate it
                trade_amount = trade["dollar_amount"] / trade["price"]

                # Add to positions (simulate share count as entry cost / 1 since payout is $1 per share)
                # For simulation, we'll track in cents for precision
                if trade["side"] == "YES":
                    current_positions["amount_yes"] += trade_amount
                    current_positions["cost_yes"] += trade["dollar_amount"]
                else:
                    current_positions["amount_no"] += trade_amount
                    current_positions["cost_no"] += trade["dollar_amount"]

                # Record trade in trading performance
                self.record_trade(trade, current_positions)

                avg_yes = current_positions["cost_yes"] / current_positions["amount_yes"] if current_positions["amount_yes"] > 0 else 0
                avg_no = current_positions["cost_no"] / current_positions["amount_no"] if current_positions["amount_no"] > 0 else 0
                current_pair_cost = avg_yes + avg_no

                logger.info(f"DRY RUN: Simulated {trade['side']} position - Cost: ${trade['dollar_amount']:.2f}, "
                           f"Current pair cost: {current_pair_cost:.2f}")

        except Exception as e:
            logger.error(f"Error in arbitrage: {e}", exc_info=True)

if __name__ == "__main__":
    t = Trader()
    t.ai_one_best_trade()
