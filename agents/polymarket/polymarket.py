# core polymarket api
# https://github.com/Polymarket/py-clob-client/tree/main/examples

import os
import pdb
import time
import ast
import datetime

from dotenv import load_dotenv

from web3 import Web3
from web3.constants import MAX_INT
from web3.middleware import ExtraDataToPOAMiddleware

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, BalanceAllowanceParams, AssetType
from py_clob_client.constants import AMOY, POLYGON
from py_order_utils.builders import OrderBuilder
from py_order_utils.model import OrderData
from py_order_utils.signer import Signer
from py_clob_client.clob_types import (
    OrderArgs,
    MarketOrderArgs,
    OrderType,
    OrderBookSummary,
)
from py_clob_client.order_builder.constants import BUY

from agents.utils.objects import SimpleMarket, SimpleEvent, TradeOrderArgs

load_dotenv()


class Polymarket:
    def __init__(self) -> None:
        self.gamma_url = "https://gamma-api.polymarket.com"
        self.gamma_markets_endpoint = self.gamma_url + "/markets?closed=false&order=volume24hr&ascending=false" # only look for open markets, sort highest 24h volume first
        self.gamma_events_endpoint = self.gamma_url + "/events?active=true&archived=false&closed=false&order=volume24hr&ascending=false" # only look for open events, sort highest 24h volume first
        self.gamma_series_endpoint = self.gamma_url + "/series?closed=false&limit=1"
        
        query_limit = int(os.getenv("query_limit"))
        if query_limit:
            self.gamma_markets_endpoint += f"&limit={query_limit}"
            self.gamma_events_endpoint += f"&limit={query_limit}"

        self.clob_url = "https://clob.polymarket.com"
        self.clob_auth_endpoint = self.clob_url + "/auth/api-key"

        self.chain_id = 137  # POLYGON
        self.private_key = os.getenv("POLYGON_WALLET_PRIVATE_KEY")
        self.polygon_rpc = "https://polygon.drpc.org"

        self.exchange_address = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
        self.neg_risk_exchange_address = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

        self.usdc_address = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
        self.ctf_address = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

        self.web3 = Web3(Web3.HTTPProvider(self.polygon_rpc))
        self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        
        erc20_approve = """[{"constant": false,"inputs": [{"name": "_spender","type": "address" },{ "name": "_value", "type": "uint256" }],"name": "approve","outputs": [{ "name": "", "type": "bool" }],"payable": false,"stateMutability": "nonpayable","type": "function"}]"""
        erc1155_set_approval = """[{"inputs": [{ "internalType": "address", "name": "operator", "type": "address" },{ "internalType": "bool", "name": "approved", "type": "bool" }],"name": "setApprovalForAll","outputs": [],"stateMutability": "nonpayable","type": "function"}]"""

        self.usdc = self.web3.eth.contract(address=self.usdc_address, abi=erc20_approve)
        self.ctf = self.web3.eth.contract(address=self.ctf_address, abi=erc1155_set_approval)

        self._init_api_keys()
        run_approvals = bool(ast.literal_eval(os.getenv("run_approvals"))) 
        if run_approvals:
            self._init_approvals()
        else:
            self.client.logger.info("Skipping approvals initialization - run_approvals is False")

    def _init_api_keys(self) -> None:
        self.client = ClobClient(
            self.clob_url, 
            key=self.private_key, 
            chain_id=self.chain_id,
            signature_type=2,
            funder="0xe63CCcF0b680B448DF4D0da94F8ebb785a8A8872"
        )
        self.credentials = self.client.create_or_derive_api_creds()
        self.client.set_api_creds(self.credentials)

    def _init_approvals(self) -> None:
        self.client.logger.info("Starting approvals initialization process")
        priv_key = self.private_key
        pub_key = self.get_address_for_private_key()
        chain_id = self.chain_id
        web3 = self.web3
        nonce = web3.eth.get_transaction_count(pub_key)
        usdc = self.usdc
        ctf = self.ctf

        self.client.logger.info(f"Initializing approvals for wallet: {pub_key}")

        # CTF Exchange (0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E)
        self.client.logger.info("Starting USDC approval for CTF Exchange (0x4bFb...)")
        raw_usdc_approve_txn = usdc.functions.approve("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", int(MAX_INT, 0)
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
        send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
        usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
        print(usdc_approve_tx_receipt)
        self.client.logger.info("Completed USDC approval for CTF Exchange")
        time.sleep(1) # 1-second delay before next transaction

        nonce = web3.eth.get_transaction_count(pub_key)

        self.client.logger.info("Starting CTF approval for CTF Exchange (0x4bFb...)")
        raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E", True
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
        send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
        ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
        print(ctf_approval_tx_receipt)
        self.client.logger.info("Completed CTF approval for CTF Exchange")
        time.sleep(1) # 1-second delay before next transaction

        nonce = web3.eth.get_transaction_count(pub_key)


        # Neg Risk CTF Exchange
        raw_usdc_approve_txn = usdc.functions.approve("0xC5d563A36AE78145C45a50134d48A1215220f80a", int(MAX_INT, 0)
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
        send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
        usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
        print(usdc_approve_tx_receipt)

        nonce = web3.eth.get_transaction_count(pub_key)

        raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0xC5d563A36AE78145C45a50134d48A1215220f80a", True
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
        send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
        ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
        print(ctf_approval_tx_receipt)

        nonce = web3.eth.get_transaction_count(pub_key)

        # Neg Risk CTF Exchange (0xC5d563A36AE78145C45a50134d48A1215220f80a)
        self.client.logger.info("Starting USDC approval for Neg Risk CTF Exchange (0xC5d5...)")
        raw_usdc_approve_txn = usdc.functions.approve("0xC5d563A36AE78145C45a50134d48A1215220f80a", int(MAX_INT, 0)
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_usdc_approve_tx = web3.eth.account.sign_transaction(raw_usdc_approve_txn, private_key=priv_key)
        send_usdc_approve_tx = web3.eth.send_raw_transaction(signed_usdc_approve_tx.raw_transaction)
        usdc_approve_tx_receipt = web3.eth.wait_for_transaction_receipt(send_usdc_approve_tx, 600)
        print(usdc_approve_tx_receipt)
        self.client.logger.info("Completed USDC approval for Neg Risk CTF Exchange")
        time.sleep(1) # 1-second delay before next transaction

        nonce = web3.eth.get_transaction_count(pub_key)

        self.client.logger.info("Starting CTF approval for Neg Risk CTF Exchange (0xC5d5...)")
        raw_ctf_approval_txn = ctf.functions.setApprovalForAll("0xC5d563A36AE78145C45a50134d48A1215220f80a", True
        ).build_transaction({"chainId": chain_id, "from": pub_key, "nonce": nonce})
        signed_ctf_approval_tx = web3.eth.account.sign_transaction(raw_ctf_approval_txn, private_key=priv_key)
        send_ctf_approval_tx = web3.eth.send_raw_transaction(signed_ctf_approval_tx.raw_transaction)
        ctf_approval_tx_receipt = web3.eth.wait_for_transaction_receipt(send_ctf_approval_tx, 600)
        print(ctf_approval_tx_receipt)
        self.client.logger.info("Completed CTF approval for Neg Risk CTF Exchange")

    def get_all_markets(self) -> "list[SimpleMarket]":
        markets = []
        res = httpx.get(self.gamma_markets_endpoint)
        if res.status_code == 200:
            for market in res.json():
                try:
                    market_data = self.map_api_to_market(market)
                    markets.append(SimpleMarket(**market_data))
                except Exception as e:
                    print(e)
                    pass
        return markets

    def filter_markets_for_trading(self, markets: "list[SimpleMarket]"):
        tradeable_markets = []
        for market in markets:
            if market.active:
                tradeable_markets.append(market)
        return tradeable_markets

    def get_market(self, token_id: str) -> SimpleMarket:
        params = {"clob_token_ids": token_id}
        res = httpx.get(self.gamma_markets_endpoint, params=params)
        if res.status_code == 200:
            data = res.json()
            market = data[0]
            return self.map_api_to_market(market, token_id)

    def get_active_market_from_series(self, slug: str) -> SimpleMarket:
        params = {"slug": slug}
        res = httpx.get(self.gamma_series_endpoint, params=params)
        if res.status_code != 200:
            raise Exception(f"Failed to fetch series data: HTTP {res.status_code}")
        series_list = res.json()
        if not series_list:
            raise ValueError(f"No series found with slug: {slug}")
        series_data = series_list[0]
        events = series_data.get('events', [])
        if not events:
            raise ValueError(f"Series '{slug}' contains no events")
        
        # Filter events with endDate > current UTC time
        current_time = datetime.datetime.now(datetime.timezone.utc)
        future_events = []
        for event in events:
            try:        
                end_date = datetime.datetime.fromisoformat(event['endDate'])
                if end_date > current_time and 'startDate' in event:
                    future_events.append(event)
            except (KeyError, ValueError) as e:
                continue  # Skip events with invalid dates

        if not future_events:
            raise ValueError(f"No future events found in series '{slug}'")
        
        # Sort by endDate ascending and select first (earliest)
        future_events.sort(key=lambda e: datetime.datetime.fromisoformat(e['endDate']))
        selected_event = future_events[0]
        markets_url = f"{self.gamma_markets_endpoint}&slug={selected_event['slug']}"
        markets_res = httpx.get(markets_url)
        if markets_res.status_code != 200:
            raise Exception(f"Failed to fetch markets for event {selected_event['id']}: HTTP {markets_res.status_code}")
        
        markets = markets_res.json()
        if not markets:
            raise ValueError(f"No markets found for event {selected_event['id']}")
        
        # Return the first market (assuming it's the active one for the event)
        market_data = markets[0]
        return self.map_api_to_market(market_data)

    def map_api_to_market(self, market, token_id: str = "") -> SimpleMarket:
        market = {
            "id": int(market["id"]),
            "question": market["question"],
            "startDate": market["startDate"] if "startDate" in market else "",
            "endDate": market["endDate"] if "endDate" in market else "",
            "description": market["description"],
            "active": market["active"],
            # "deployed": market["deployed"],
            "funded": market["funded"],
            "rewardsMinSize": float(market["rewardsMinSize"]),
            "rewardsMaxSpread": float(market["rewardsMaxSpread"]),
            # "volume": float(market["volume"]),
            "spread": float(market["spread"]),
            "outcomes": str(market["outcomes"]),
            "outcome_prices": str(market["outcomePrices"]),
            "clob_token_ids": str(market["clobTokenIds"]),
            "eventStartTime": market["eventStartTime"] if "eventStartTime" in market else "",
        }
        if token_id:
            market["clob_token_ids"] = token_id
        return market

    def get_all_events(self) -> "list[SimpleEvent]":
        events = []
        res = httpx.get(self.gamma_events_endpoint)
        if res.status_code == 200:
            print(len(res.json()))
            for event in res.json():
                try:
                    event_data = self.map_api_to_event(event)
                    events.append(SimpleEvent(**event_data))
                except Exception as e:
                    print(e)
                    pass
        return events

    def map_api_to_event(self, event) -> SimpleEvent:
        description = event["description"] if "description" in event.keys() else ""
        return {
            "id": int(event["id"]),
            "ticker": event["ticker"],
            "slug": event["slug"],
            "title": event["title"],
            "description": description,
            "active": event["active"],
            "closed": event["closed"],
            "archived": event["archived"],
            "new": event["new"],
            "featured": event["featured"],
            "restricted": event["restricted"],
            "end": event["endDate"],
            "markets": ",".join([x["id"] for x in event["markets"]]),
        }

    def filter_events_for_trading(
        self, events: "list[SimpleEvent]"
    ) -> "list[SimpleEvent]":
        tradeable_events = []
        for event in events:
            if (
                event.active
                #and not event.restricted
                and not event.archived
                and not event.closed
            ):
                tradeable_events.append(event)
        return tradeable_events

    def get_all_tradeable_events(self) -> "list[SimpleEvent]":
        all_events = self.get_all_events()
        return self.filter_events_for_trading(all_events)

    def get_sampling_simplified_markets(self) -> "list[SimpleEvent]":
        markets = []
        raw_sampling_simplified_markets = self.client.get_sampling_simplified_markets()
        for raw_market in raw_sampling_simplified_markets["data"]:
            token_one_id = raw_market["tokens"][0]["token_id"]
            market = self.get_market(token_one_id)
            markets.append(market)
        return markets

    def get_orderbook(self, token_id: str) -> OrderBookSummary:
        return self.client.get_order_book(token_id)

    def get_orderbook_price(self, token_id: str, side: str, max_retries: int = 3) -> float:
        """
        Fetch orderbook price with retry logic for connection errors.

        Args:
            token_id: The token ID to fetch price for
            side: "BUY" or "SELL"
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            float: The price

        Raises:
            Exception: If all retries fail
        """
        for attempt in range(max_retries):
            try:
                return float(self.client.get_price(token_id, side)["price"])
            except (httpx.RemoteProtocolError, Exception) as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    self.client.logger.warning(f"Price fetch failed (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    self.client.logger.error(f"Price fetch failed after {max_retries} attempts: {e}")
                    raise

    def get_address_for_private_key(self):
        account = self.web3.eth.account.from_key(str(self.private_key))
        return account.address

    def build_order(
        self,
        market_token: str,
        amount: float,
        nonce: str = str(round(time.time())),  # for cancellations
        side: str = "BUY",
        expiration: str = "0",  # timestamp after which order expires
    ):
        signer = Signer(self.private_key)
        builder = OrderBuilder(self.exchange_address, self.chain_id, signer)

        buy = side == "BUY"
        side = 0 if buy else 1
        maker_amount = amount if buy else 0
        taker_amount = amount if not buy else 0
        order_data = OrderData(
            maker=self.get_address_for_private_key(),
            tokenId=market_token,
            makerAmount=maker_amount,
            takerAmount=taker_amount,
            feeRateBps="1",
            nonce=nonce,
            side=side,
            expiration=expiration,
        )
        order = builder.build_signed_order(order_data)
        return order

    def execute_order(self, price, size, side, token_id) -> str:
        return self.client.create_and_post_order(
            OrderArgs(price=price, size=size, side=side, token_id=token_id)
        )

    def execute_market_order(self, market: str, dollar_amount: str, token_id: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:                        
                order_args = MarketOrderArgs(
                    token_id=token_id,
                    amount=dollar_amount,
                    side="BUY",
                    order_type=OrderType.FOK,
                )
                signed_order = self.client.create_market_order(order_args)
                print("Execute market order... signed_order ", signed_order)
                resp = self.client.post_order(signed_order, orderType=OrderType.FOK)
                print(resp)
                print("Done!")
                return resp
            except Exception as e:
                self.client.logger.warning(f"FOK order failed (attempt {attempt + 1}/{max_retries}): {e}")
                
                # For other errors, wait before retrying
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue

                # If all retries failed, raise the exception
                raise                

    def get_usdc_balance(self) -> float:
        balance_allowance = self.client.get_balance_allowance(params=BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=2))
        balance = float(balance_allowance["balance"])/10e5
        return balance


def test():
    host = "https://clob.polymarket.com"
    key = os.getenv("POLYGON_WALLET_PRIVATE_KEY")
    print(key)
    chain_id = POLYGON

    # Create CLOB client and get/set API credentials
    client = ClobClient(host, key=key, chain_id=chain_id)
    client.set_api_creds(client.create_or_derive_api_creds())

    creds = ApiCreds(
        api_key=os.getenv("CLOB_API_KEY"),
        api_secret=os.getenv("CLOB_SECRET"),
        api_passphrase=os.getenv("CLOB_PASS_PHRASE"),
    )
    chain_id = AMOY
    client = ClobClient(host, key=key, chain_id=chain_id, creds=creds)

    print(client.get_markets())
    print(client.get_simplified_markets())
    print(client.get_sampling_markets())
    print(client.get_sampling_simplified_markets())
    print(client.get_market("condition_id"))

    print("Done!")


def gamma():
    url = "https://gamma-com"
    markets_url = url + "/markets"
    res = httpx.get(markets_url)
    code = res.status_code
    if code == 200:
        markets: list[SimpleMarket] = []
        data = res.json()
        for market in data:
            try:
                market_data = {
                    "id": int(market["id"]),
                    "question": market["question"],
                    # "start": market['startDate'],
                    "end": market["endDate"],
                    "description": market["description"],
                    "active": market["active"],
                    "deployed": market["deployed"],
                    "funded": market["funded"],
                    # "orderMinSize": float(market['orderMinSize']) if market['orderMinSize'] else 0,
                    # "orderPriceMinTickSize": float(market['orderPriceMinTickSize']),
                    "rewardsMinSize": float(market["rewardsMinSize"]),
                    "rewardsMaxSpread": float(market["rewardsMaxSpread"]),
                    "volume": float(market["volume"]),
                    "spread": float(market["spread"]),
                    "outcome_a": str(market["outcomes"][0]),
                    "outcome_b": str(market["outcomes"][1]),
                    "outcome_a_price": str(market["outcomePrices"][0]),
                    "outcome_b_price": str(market["outcomePrices"][1]),
                }
                markets.append(SimpleMarket(**market_data))
            except Exception as err:
                print(f"error {err} for market {id}")
        pdb.set_trace()
    else:
        raise Exception()


def main():
    # auth()
    # test()
    # gamma()
    print(Polymarket().get_all_events())


if __name__ == "__main__":
    load_dotenv()

    p = Polymarket()

    # k = p.get_api_key()
    # m = p.get_sampling_simplified_markets()

    # print(m)
    # m = p.get_market('11015470973684177829729219287262166995141465048508201953575582100565462316088')

    # t = m[0]['token_id']
    # o = p.get_orderbook(t)
    # pdb.set_trace()

    """
    
    (Pdb) pprint(o)
            OrderBookSummary(
                market='0x26ee82bee2493a302d21283cb578f7e2fff2dd15743854f53034d12420863b55', 
                asset_id='11015470973684177829729219287262166995141465048508201953575582100565462316088', 
                bids=[OrderSummary(price='0.01', size='600005'), OrderSummary(price='0.02', size='200000'), ...
                asks=[OrderSummary(price='0.99', size='100000'), OrderSummary(price='0.98', size='200000'), ...
            )
    
    """

    # https://polygon-rpc.com

    test_market_token_id = (
        "101669189743438912873361127612589311253202068943959811456820079057046819967115"
    )
    test_market_data = p.get_market(test_market_token_id)

    # test_size = 0.0001
    test_size = 1
    test_side = BUY
    test_price = float(ast.literal_eval(test_market_data["outcome_prices"])[0])

    # order = p.execute_order(
    #    test_price,
    #    test_size,
    #    test_side,
    #    test_market_token_id,
    # )

    # order = p.execute_market_order(test_price, test_market_token_id)

    balance = p.get_usdc_balance()
