import logging
import shutil
from pathlib import Path
from json import load, dump
import ast
from os import getenv

from agents.application.executor import Executor as Agent
from agents.polymarket.gamma import GammaMarketClient as Gamma
from agents.polymarket.polymarket import Polymarket
from agents.utils.objects import SimpleMarket

logger = logging.getLogger(__name__)


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

    def load_arbitrage_positions(self, market_id: int) -> dict:
        """Load arbitrage positions from persistent storage."""
        positions_file = Path("arbitrage_positions.json")
        if positions_file.exists():
            try:
                with open(positions_file, 'r') as f:
                    positions = load(f)
                    logger.info(f"Loaded existing arbitrage positions: {positions}")
                    current_positions = positions.get(str(market_id),{"qty_yes": 0.0, "qty_no": 0.0, "cost_yes": 0.0, "cost_no": 0.0})
                    return current_positions
            except Exception as e:
                logger.warning(f"Failed to load positions: {e}")
        return {"qty_yes": 0.0, "qty_no": 0.0, "cost_yes": 0.0, "cost_no": 0.0}

    def save_arbitrage_positions(self, current_positions: dict, market_id: int):
        """Save arbitrage positions to persistent storage."""
        positions_file = Path("arbitrage_positions.json")
        try:
            positions = {}
            if positions_file.exists():
                with open(positions_file, 'r') as f:
                    positions = load(f)
            
            # Update with current market's positions
            positions[str(market_id)] = current_positions

            with open(positions_file, 'w') as f:
                dump(positions, f, indent=2)

            logger.info(f"Saved arbitrage positions for market {market_id}: {positions}")
        except Exception as e:
            logger.error(f"Failed to save positions: {e}")

    def monitor_market_prices(self, market: SimpleMarket) -> dict:
        """Monitor YES/NO prices for a market."""
        try:
            token_ids = ast.literal_eval(market["clob_token_ids"])
            if len(token_ids) != 2:
                return {}
                
            # Get best prices for YES and NO tokens
            yes_price = self.polymarket.get_orderbook_price(token_ids[0], "BUY")
            no_price = self.polymarket.get_orderbook_price(token_ids[1], "BUY")
                        
            return {
                "yes_price": yes_price,
                "no_price": no_price,
                "yes_token_id": token_ids[0],
                "no_token_id": token_ids[1]
            }
            
        except Exception as e:
            logger.error(f"Error monitoring prices for market {market.id}: {e}")
            return {}

    def calculate_arbitrage_trade(self, positions: dict, prices: dict, market: SimpleMarket) -> dict:
        """Calculate optimal arbitrage trade based on current positions and prices."""
        try:
            # Current position metrics
            qty_yes = positions["qty_yes"]
            qty_no = positions["qty_no"] 
            cost_yes = positions["cost_yes"]
            cost_no = positions["cost_no"]
            
            # Current averages
            avg_yes = cost_yes / qty_yes if qty_yes > 0 else 0
            avg_no = cost_no / qty_no if qty_no > 0 else 0
            current_pair_cost = avg_yes + avg_no
            
            # Price thresholds (configurable)
            cheap_threshold = float(getenv("ARBITRAGE_CHEAP_THRESHOLD", "0.49"))
            safety_margin = float(getenv("ARBITRAGE_SAFETY_MARGIN", "0.99"))
            
            # Check for cheap opportunities
            yes_cheap = prices["yes_price"] and prices["yes_price"] < cheap_threshold
            no_cheap = prices["no_price"] and prices["no_price"] < cheap_threshold
            
            if not (yes_cheap or no_cheap):
                return {}  # No opportunity
                
            # Determine trade side and size
            side = "YES" if yes_cheap else "NO"
            price = prices["yes_price"] if side == "YES" else prices["no_price"]
            
            # Calculate position size (similar to existing sizing logic)
            usdc_balance = self.polymarket.get_usdc_balance()
            base_size = min(usdc_balance * 0.05, 10.0)  # 5% of balance or $10 max
            
            # Adjust size to maintain balance
            if side == "YES":
                size_adjustment = qty_no - qty_yes  # Buy more YES if we have more NO
            else:
                size_adjustment = qty_yes - qty_no  # Buy more NO if we have more YES
                
            size = base_size * (1 + size_adjustment * 0.1)  # Small adjustment for balancing
            
            # Minimum order size is 1, if less than this then don't bother buying
            if size < 1:
                logger.info(f"Trade rejected: size {size} is below minimum amount 1")
                return {}

            # Calculate new costs and pair cost
            new_qty = qty_yes + size if side == "YES" else qty_no + size
            new_cost = cost_yes + (price * size) if side == "YES" else cost_no + (price * size)
            
            new_avg = new_cost / new_qty
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
                "amount": size,
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
            qty_yes = positions["qty_yes"]
            qty_no = positions["qty_no"]
            cost_yes = positions["cost_yes"]
            cost_no = positions["cost_no"]
            
            total_cost = cost_yes + cost_no
            min_qty = min(qty_yes, qty_no)
            
            # Exit when min(qty_yes, qty_no) > (cost_yes + cost_no)
            should_exit = min_qty > total_cost
            
            if should_exit:
                profit = min_qty - total_cost
                logger.info(f"Arbitrage: Guaranteed profit ${profit:.2f}")
                
            return should_exit
            
        except Exception as e:
            logger.error(f"Error checking arbitrage exit: {e}")
            return False

    def arbitrage(self, dry_run: bool, slug: str) -> None:
        """Arbitrage strategy implementation."""
        try:
            self.pre_trade_logic()
               
            market = self.polymarket.get_active_market_from_series(slug)
            logger.info(f"Monitoring market {market["id"]}: {market["question"]}")

            # Load positions
            current_positions = self.load_arbitrage_positions(market["id"])
            
            # Check exit condition first
            if self.check_arbitrage_exit(current_positions):
                logger.info("Arbitrage strategy complete - profit locked in")
                return

            prices = self.monitor_market_prices(market)
            if not prices:
                logger.warning("Could not get prices for market")
                return
                
            # Calculate trade
            trade = self.calculate_arbitrage_trade(current_positions, prices, market)
            if not trade:
                logger.info("No profitable trade opportunity found")
                return
                            
            if(not(dry_run)):
                # Execute trade (similar to existing execution)
                # Note: Would need to adapt execute_market_order for limit orders
                # For now, using market order as example
                trade_result = self.polymarket.execute_market_order([market], trade["amount"], trade["token_id"])
                logger.info(f"TRADE EXECUTED: {trade_result}")
                # Update positions
                current_positions["market_id"] = market["id"]
                if trade["side"] == "YES":
                    current_positions["qty_yes"] += trade["amount"]
                    current_positions["cost_yes"] += trade["price"] * trade["amount"]
                else:
                    current_positions["qty_no"] += trade["amount"]
                    current_positions["cost_no"] += trade["price"] * trade["amount"]
                
                # Save updated positions
                self.save_arbitrage_positions(current_positions, market["id"])
            else:
                logger.info(f"DRY RUN, TRADE NOT EXECUTED")
            
        except Exception as e:
            logger.error(f"Error in arbitrage: {e}", exc_info=True)

if __name__ == "__main__":
    t = Trader()
    t.ai_one_best_trade()
