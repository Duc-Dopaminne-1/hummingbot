import asyncio
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from bidict import bidict

from hummingbot.connector.constants import s_decimal_NaN
from hummingbot.connector.exchange.bitget import (
    bitget_constants as CONSTANTS,
    bitget_utils,
    bitget_web_utils as web_utils,
)
from hummingbot.connector.exchange.bitget.bitget_api_order_book_data_source import BitgetAPIOrderBookDataSource
from hummingbot.connector.exchange.bitget.bitget_api_user_stream_data_source import BitgetAPIUserStreamDataSource
from hummingbot.connector.exchange.bitget.bitget_auth import BitgetAuth
from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.connector.utils import TradeFillOrderDetails, combine_to_hb_trading_pair
from hummingbot.core.data_type.common import OrderType, PositionAction, TradeType
from hummingbot.core.data_type.in_flight_order import InFlightOrder, OrderUpdate, TradeUpdate
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.data_type.trade_fee import DeductedFromReturnsTradeFee, TokenAmount, TradeFeeBase
from hummingbot.core.data_type.user_stream_tracker_data_source import UserStreamTrackerDataSource
from hummingbot.core.event.events import MarketEvent, OrderFilledEvent
from hummingbot.core.utils.async_utils import safe_gather
from hummingbot.core.web_assistant.connections.data_types import RESTMethod
from hummingbot.core.web_assistant.web_assistants_factory import WebAssistantsFactory

if TYPE_CHECKING:
    from hummingbot.client.config.config_helpers import ClientConfigAdapter


def _symbol_and_product_type(full_symbol: str) -> str:
    return full_symbol.split(CONSTANTS.SYMBOL_AND_PRODUCT_TYPE_SEPARATOR)


def format_symbol(symbol):
    if "_SPBL" in symbol:
        return symbol.replace("_SPBL", "")
    return symbol


class BitgetExchange(ExchangePyBase):
    UPDATE_ORDER_STATUS_MIN_INTERVAL = 10.0

    web_utils = web_utils

    def __init__(self,
                 client_config_map: "ClientConfigAdapter",
                 bitget_api_key: str,
                 bitget_api_secret: str,
                 bitget_passphrase: str = None,
                 trading_pairs: Optional[List[str]] = None,
                 trading_required: bool = True,
                 domain: str = CONSTANTS.DEFAULT_DOMAIN,
                 ):
        self.api_key = bitget_api_key
        self.secret_key = bitget_api_secret
        self.bitget_passphrase = bitget_passphrase
        self._domain = domain
        self._trading_required = trading_required
        self._trading_pairs = trading_pairs
        self._last_trades_poll_bitget_timestamp = 1.0
        super().__init__(client_config_map)

    @staticmethod
    def bitget_order_type(order_type: OrderType) -> str:
        return order_type.name.upper()

    @staticmethod
    def to_hb_order_type(bitget_type: str) -> OrderType:
        return OrderType[bitget_type]

    @property
    def authenticator(self):
        return BitgetAuth(
            api_key=self.api_key,
            secret_key=self.secret_key,
            passphrase=self.bitget_passphrase,
            time_provider=self._time_synchronizer)

    @property
    def name(self) -> str:
        return "bitget"
        # if self._domain == "com":
        #     return "bitget"
        # else:
        #     return f"bitget_{self._domain}"

    @property
    def rate_limits_rules(self):
        return CONSTANTS.RATE_LIMITS

    @property
    def domain(self):
        return self._domain

    @property
    def client_order_id_max_length(self):
        return CONSTANTS.MAX_ORDER_ID_LEN

    @property
    def client_order_id_prefix(self):
        return CONSTANTS.HBOT_ORDER_ID_PREFIX

    @property
    def trading_rules_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def trading_pairs_request_path(self):
        return CONSTANTS.EXCHANGE_INFO_PATH_URL

    @property
    def check_network_request_path(self):
        return CONSTANTS.PING_PATH_URL

    @property
    def trading_pairs(self):
        return self._trading_pairs

    @property
    def is_cancel_request_in_exchange_synchronous(self) -> bool:
        return True

    @property
    def is_trading_required(self) -> bool:
        return self._trading_required

    def supported_order_types(self):
        return [OrderType.LIMIT, OrderType.LIMIT_MAKER, OrderType.MARKET]

    async def get_all_pairs_prices(self) -> List[Dict[str, str]]:
        pairs_prices = await self._api_get(path_url=CONSTANTS.TICKER_BOOK_PATH_URL, headers={"Content-Type": "application/json"})
        return pairs_prices

    def _is_request_exception_related_to_time_synchronizer(self, request_exception: Exception):
        return str(CONSTANTS.TIMESTAMP_RELATED_ERROR_CODE) in str(
            request_exception
        ) and CONSTANTS.TIMESTAMP_RELATED_ERROR_MESSAGE in str(request_exception)

    def _is_order_not_found_during_status_update_error(self, status_update_exception: Exception) -> bool:
        return str(CONSTANTS.ORDER_NOT_EXIST_ERROR_CODE) in str(
            status_update_exception
        ) and CONSTANTS.ORDER_NOT_EXIST_MESSAGE in str(status_update_exception)

    def _is_order_not_found_during_cancelation_error(self, cancelation_exception: Exception) -> bool:
        return str(CONSTANTS.UNKNOWN_ORDER_ERROR_CODE) in str(
            cancelation_exception
        ) and CONSTANTS.UNKNOWN_ORDER_MESSAGE in str(cancelation_exception)

    def _create_web_assistants_factory(self) -> WebAssistantsFactory:
        return web_utils.build_api_factory(
            throttler=self._throttler,
            time_synchronizer=self._time_synchronizer,
            domain=self._domain,
            auth=self._auth)

    def _create_order_book_data_source(self) -> OrderBookTrackerDataSource:
        return BitgetAPIOrderBookDataSource(
            trading_pairs=self._trading_pairs,
            connector=self,
            domain=self.domain,
            api_factory=self._web_assistants_factory)

    def _create_user_stream_data_source(self) -> UserStreamTrackerDataSource:
        return BitgetAPIUserStreamDataSource(
            auth=self._auth,
            trading_pairs=self._trading_pairs,
            connector=self,
            api_factory=self._web_assistants_factory,
            domain=self.domain,
        )

    def _get_fee(self,
                 base_currency: str,
                 quote_currency: str,
                 order_type: OrderType,
                 order_side: TradeType,
                 amount: Decimal,
                 price: Decimal = s_decimal_NaN,
                 is_maker: Optional[bool] = None) -> TradeFeeBase:
        is_maker = order_type is OrderType.LIMIT_MAKER
        return DeductedFromReturnsTradeFee(percent=self.estimate_fee_pct(is_maker))

    async def _place_order(self,
                           order_id: str,
                           trading_pair: str,
                           amount: Decimal,
                           trade_type: TradeType,
                           order_type: OrderType,
                           price: Decimal,
                           **kwargs) -> Tuple[str, float]:
        order_result = None

        amount_str = f"{amount:f}"
        type_str = BitgetExchange.bitget_order_type(order_type)
        side_str = CONSTANTS.SIDE_BUY if trade_type is TradeType.BUY else CONSTANTS.SIDE_SELL
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        api_params = {"symbol": symbol,
                      "side": side_str,
                      "quantity": amount_str,
                      "force": "normal",
                      # "quoteOrderQty": amount_str,
                      "orderType": "limit" if order_type.is_limit_type() else "market",
                      "type": type_str,
                      "clientOid": order_id}
        if order_type.is_limit_type():
            price_str = f"{price:f}"
            api_params["price"] = price_str
        else:
            if trade_type == TradeType.BUY:
                if price.is_nan():
                    price = self.get_price_for_volume(
                        trading_pair,
                        True,
                        amount
                    ).result_price
                del api_params['quantity']
                api_params.update({
                    "quoteOrderQty": f"{price * amount:f}",
                })
        if order_type == OrderType.LIMIT:
            api_params["timeInForce"] = CONSTANTS.TIME_IN_FORCE_GTC

        print("888888 CREATE ORDER_PATH_URL", api_params)
        self.logger().info(f"888888 CREATE ORDER_PATH_UR 1 = {api_params}")
        try:
            order_result = await self._api_post(
                path_url=CONSTANTS.ORDER_PATH_URL,
                data=api_params,
                is_auth_required=True)
            self.logger().info(f"888888 CREATE RESULT = {order_result}")
            print("888888 CREATE RESULT 1", order_result)
            o_id = str(order_result["data"]["orderId"])
            transact_time = order_result["requestTime"] * 1e-3
        except IOError as e:
            error_description = str(e)
            is_server_overloaded = ("status is 503" in error_description
                                    and "Unknown error, please check your request or try again later." in error_description)
            if is_server_overloaded:
                o_id = "UNKNOWN"
                transact_time = self._time_synchronizer.time()
            else:
                raise
        return o_id, transact_time

    async def _place_cancel(self, order_id: str, tracked_order: InFlightOrder):
        symbol = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)
        api_params = {
            "symbol": symbol,
            "orderId": tracked_order.exchange_order_id # order_id,
        }
        self.logger().info(f"99999999 _place_cancel = {api_params}")
        print("99999999 _place_cancel 1", api_params)
        cancel_result = await self._api_post(
            path_url=CONSTANTS.CANCEL_ACTIVE_ORDER_PATH_URL,
            data=api_params,
            is_auth_required=True)
        self.logger().info(f"99999999 cancel_result = {cancel_result}")
        print("99999999 cancel_result 1", cancel_result)
        if cancel_result.get("msg") == "success":
            return True
        return False

    async def _format_trading_rules(self, exchange_info_dict: Dict[str, Any]) -> List[TradingRule]:
        trading_pair_rules = exchange_info_dict.get("data", [])
        retval = []
        for rule in filter(bitget_utils.is_exchange_information_valid, trading_pair_rules):
            try:
                trading_pair = await self.trading_pair_associated_to_exchange_symbol(symbol=rule.get("symbol"))
                min_order_size = Decimal(rule.get("minTradeAmount"))
                min_price_inc = Decimal(f"1e-{rule['priceScale']}")
                min_amount_inc = Decimal(f"1e-{rule['quantityScale']}")
                min_notional = Decimal(rule['minTradeUSDT'])
                # print("1111111 min_order_size", min_order_size)
                # print("1111111 min_price_inc", min_price_inc)
                # print("1111111 min_amount_inc", min_amount_inc)
                # print("1111111 min_notional", min_notional)
                # self.logger().info(f"1111111 trading_pair {trading_pair}")
                # self.logger().info(f"1111111 min_order_size {min_order_size}")
                # self.logger().info(f"1111111 min_price_inc {min_price_inc}")
                # self.logger().info(f"1111111 min_amount_inc {min_amount_inc}")
                # self.logger().info(f"1111111 min_notional {min_notional}")
                # min_order_size = Decimal(f"1e-{rule.get('quantityScale')}")
                # min_price_inc = Decimal(f"1e-{rule['priceScale']}")
                # min_amount_inc = Decimal(f"1e-{rule['quantityScale']}")
                # min_notional = Decimal(rule['minTradeUSDT'])

                retval.append(
                    TradingRule(trading_pair,
                                min_order_size=min_order_size,
                                min_price_increment=min_price_inc,
                                min_base_amount_increment=min_amount_inc,
                                min_notional_size=min_notional))

            except Exception:
                self.logger().exception(f"Error parsing the trading pair rule {rule}. Skipping.")
        return retval

    async def _status_polling_loop_fetch_updates(self):
        await self._update_order_fills_from_trades()
        await super()._status_polling_loop_fetch_updates()

    async def _update_trading_fees(self):
        """
        Update fees information from the exchange
        """
        pass

    async def _user_stream_event_listener(self):
        """
        Listens to message in _user_stream_tracker.user_stream queue.
        """
        async for event_message in self._iter_user_event_queue():
            try:
                # In case the message is a simple string like "pong"
                if isinstance(event_message, str):
                    if event_message == "pong":
                        # You can log the pong or simply continue
                        self.logger().info("Received pong message, continuing...")
                        continue

                self.logger().info(f"DDDDD {event_message}")
                print("DDDDD", event_message)
                endpoint = event_message["arg"]["channel"]
                payload = event_message["data"]

                if endpoint == CONSTANTS.WS_SUBSCRIPTION_ORDERS_ENDPOINT_NAME:
                    for order_msg in payload:
                        self.logger().info(f"222222 REERRRRRR {order_msg}")
                        self._process_trade_event_message(order_msg)
                        self._process_order_event_message(order_msg)
                elif endpoint == CONSTANTS.WS_SUBSCRIPTION_WALLET_ENDPOINT_NAME:
                    for wallet_msg in payload:
                        self._process_spot_event_message(wallet_msg)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().exception("Unexpected error in user stream listener loop.")

    def _process_trade_event_message(self, trade_msg: Dict[str, Any]):
        """
        Updates in-flight order and trigger order filled event for trade message received. Triggers order completed
        event if the total executed amount equals to the specified order amount.

        :param trade_msg: The trade event message payload
        """

        client_order_id = str(trade_msg["clOrdId"])
        fillable_order = self._order_tracker.all_fillable_orders.get(client_order_id)
        self.logger().info(f"222222 fillable_order {fillable_order}")
        if fillable_order is not None and "ordId" in trade_msg:
            trade_update = self._parse_websocket_trade_update(trade_msg=trade_msg, tracked_order=fillable_order)
            if trade_update:
                self._order_tracker.process_trade_update(trade_update)

    def _parse_websocket_trade_update(self, trade_msg: Dict, tracked_order: InFlightOrder) -> TradeUpdate:
        trade_id: str = trade_msg["ordId"]

        if trade_id is not None:
            trade_id = str(trade_id)
            fee_asset = trade_msg["fillFeeCcy"]
            fee_amount = Decimal(trade_msg["fillFee"])
            position_side = trade_msg["side"]
            position_action = (PositionAction.OPEN
                               if (tracked_order.trade_type is TradeType.BUY and position_side == "buy"
                                   or tracked_order.trade_type is TradeType.SELL and position_side == "sell")
                               else PositionAction.CLOSE)

            flat_fees = [] if fee_amount == Decimal("0") else [TokenAmount(amount=fee_amount, token=fee_asset)]

            fee = TradeFeeBase.new_perpetual_fee(
                fee_schema=self.trade_fee_schema(),
                position_action=position_action,
                percent_token=fee_asset,
                flat_fees=flat_fees,
            )

            exec_price = Decimal(trade_msg["fillPx"]) if "fillPx" in trade_msg else Decimal(trade_msg["px"])
            exec_time = int(trade_msg["cTime"]) * 1e-3

            trade_update: TradeUpdate = TradeUpdate(
                trade_id=trade_id,
                client_order_id=tracked_order.client_order_id,
                exchange_order_id=str(trade_msg["ordId"]),
                trading_pair=tracked_order.trading_pair,
                fill_timestamp=exec_time,
                fill_price=exec_price,
                fill_base_amount=Decimal(trade_msg["fillSz"]),
                fill_quote_amount=exec_price * Decimal(trade_msg["fillSz"]),
                fee=fee,
            )

            return trade_update

    def _process_order_event_message(self, order_msg: Dict[str, Any]):
        order_status = CONSTANTS.ORDER_STATE[order_msg["status"]]
        client_order_id = str(order_msg["clOrdId"])
        updatable_order = self._order_tracker.all_updatable_orders.get(client_order_id)

        if updatable_order is not None:
            new_order_update: OrderUpdate = OrderUpdate(
                trading_pair=updatable_order.trading_pair,
                update_timestamp=self.current_timestamp,
                new_state=order_status,
                client_order_id=client_order_id,
                exchange_order_id=order_msg["ordId"],
            )
            self._order_tracker.process_order_update(new_order_update)

    def _process_spot_event_message(self, spot_msg: Dict[str, Any]):
        self.logger().debug(f"3333 CCCCCCCCCCC {spot_msg}")
        coin_name = spot_msg.get("coinName", None)  # This is the name of the asset (e.g., USDT, BTC)
        if coin_name is not None:
            available = Decimal(str(spot_msg["available"]))  # Available balance
            frozen = Decimal(str(spot_msg["frozen"]))  # Frozen balance (in open orders)
            total = available + frozen  # Total balance (available + frozen)

            # Update the balance in the account dictionary
            self._account_balances[coin_name] = total
            self._account_available_balances[coin_name] = available

    def _create_trade_update_with_order_fill_data(
            self,
            order_fill: Dict[str, Any],
            order: InFlightOrder):

        fee = TradeFeeBase.new_spot_fee(
            fee_schema=self.trade_fee_schema(),
            trade_type=order.trade_type,
            percent_token=order_fill["N"],
            flat_fees=[TokenAmount(
                amount=Decimal(order_fill["n"]),
                token=order_fill["N"]
            )]
        )
        trade_update = TradeUpdate(
            trade_id=str(order_fill["t"]),
            client_order_id=order.client_order_id,
            exchange_order_id=order.exchange_order_id,
            trading_pair=order.trading_pair,
            fee=fee,
            fill_base_amount=Decimal(order_fill["v"]),
            fill_quote_amount=Decimal(order_fill["a"]),
            fill_price=Decimal(order_fill["p"]),
            fill_timestamp=order_fill["T"] * 1e-3,
        )
        return trade_update

    def _process_trade_message(self, trade: Dict[str, Any], client_order_id: Optional[str] = None):
        client_order_id = client_order_id or str(trade["c"])
        tracked_order = self._order_tracker.all_fillable_orders.get(client_order_id)
        if tracked_order is None:
            self.logger().debug(f"Ignoring trade message with id {client_order_id}: not in in_flight_orders.")
        else:
            trade_update = self._create_trade_update_with_order_fill_data(
                order_fill=trade,
                order=tracked_order)
            self._order_tracker.process_trade_update(trade_update)

    def _create_order_update_with_order_status_data(self, order_status: Dict[str, Any], order: InFlightOrder):
        client_order_id = str(order_status["d"].get("c", ""))
        order_update = OrderUpdate(
            trading_pair=order.trading_pair,
            update_timestamp=int(order_status["t"] * 1e-3),
            new_state=CONSTANTS.WS_ORDER_STATE[order_status["d"]["s"]],
            client_order_id=client_order_id,
            exchange_order_id=str(order_status["d"]["i"]),
        )
        return order_update

    def _process_order_message(self, raw_msg: Dict[str, Any]):
        order_msg = raw_msg.get("d", {})
        client_order_id = str(order_msg.get("c", ""))
        tracked_order = self._order_tracker.all_updatable_orders.get(client_order_id)
        if not tracked_order:
            self.logger().debug(f"Ignoring order message with id {client_order_id}: not in in_flight_orders.")
            return

        order_update = self._create_order_update_with_order_status_data(order_status=raw_msg, order=tracked_order)
        self._order_tracker.process_order_update(order_update=order_update)

    async def _update_order_fills_from_trades(self):
        """
        This is intended to be a backup measure to get filled events with trade ID for orders,
        in case bitget's user stream events are not working.
        NOTE: It is not required to copy this functionality in other connectors.
        This is separated from _update_order_status which only updates the order status without producing filled
        events, since bitget's get order endpoint does not return trade IDs.
        The minimum poll interval for order status is 10 seconds.
        """
        small_interval_last_tick = self._last_poll_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL
        small_interval_current_tick = self.current_timestamp / self.UPDATE_ORDER_STATUS_MIN_INTERVAL
        long_interval_last_tick = self._last_poll_timestamp / self.LONG_POLL_INTERVAL
        long_interval_current_tick = self.current_timestamp / self.LONG_POLL_INTERVAL

        if (long_interval_current_tick > long_interval_last_tick
                or (self.in_flight_orders and small_interval_current_tick > small_interval_last_tick)):
            query_time = int(self._last_trades_poll_bitget_timestamp * 1e3)
            self._last_trades_poll_bitget_timestamp = self._time_synchronizer.time()
            order_by_exchange_id_map = {}
            for order in self._order_tracker.all_fillable_orders.values():
                order_by_exchange_id_map[order.exchange_order_id] = order

            tasks = []
            trading_pairs = self.trading_pairs
            for trading_pair in trading_pairs:
                trading_pair = trading_pair.replace("-", "")
                params = {
                 "symbol": format_symbol(trading_pair),
               }

            self.logger().debug(f"55555 aaaaa {params}")
            if self._last_poll_timestamp > 0:
             params["startTime"] = query_time
             tasks.append(self._api_get(
                    path_url=CONSTANTS.MY_TRADES_PATH_URL,
                    params=params,
                    is_auth_required=True,
                    headers={"Content-Type": "application/json"}))

            self.logger().debug(f"Polling for order fills of {len(tasks)} trading pairs.")
            results = await safe_gather(*tasks, return_exceptions=True)
            data = results[0]["data"] if len(results) > 0 and "data" in results[0] else []
            for trades, trading_pair in zip(data, trading_pairs):
                if isinstance(trades, Exception):
                    self.logger().network(
                        f"Error fetching trades update for the order {trading_pair}: {trades}.",
                        app_warning_msg=f"Failed to fetch trade update for {trading_pair}."
                    )
                    continue

                for trade in trades:
                    if not isinstance(trade, dict):
                        self.logger().error(f"Unexpected trade data format: {trade}")
                        continue  # Skip this trade if it's not a dictionary

                    exchange_order_id = str(trade["tradeId"])
                    if exchange_order_id in order_by_exchange_id_map:
                        # Xử lý lệnh đã được theo dõi
                        tracked_order = order_by_exchange_id_map[exchange_order_id]
                        fee = TradeFeeBase.new_spot_fee(
                            fee_schema=self.trade_fee_schema(),
                            trade_type=tracked_order.trade_type,
                            percent_token=trade["commissionAsset"],
                            flat_fees=[TokenAmount(amount=Decimal(trade["commission"]), token=trade["commissionAsset"])]
                        )
                        trade_update = TradeUpdate(
                            trade_id=str(trade["id"]),
                            client_order_id=tracked_order.client_order_id,
                            exchange_order_id=exchange_order_id,
                            trading_pair=trading_pair,
                            fee=fee,
                            fill_base_amount=Decimal(trade["qty"]),
                            fill_quote_amount=Decimal(trade["quoteQty"]),
                            fill_price=Decimal(trade["price"]),
                            fill_timestamp=trade["time"] * 1e-3,
                        )
                        self._order_tracker.process_trade_update(trade_update)
                    elif self.is_confirmed_new_order_filled_event(str(trade["id"]), exchange_order_id, trading_pair):
                        # Xử lý lệnh đã được khớp nhưng không được theo dõi
                        self._current_trade_fills.add(TradeFillOrderDetails(
                            market=self.display_name,
                            exchange_trade_id=str(trade["id"]),
                            symbol=trading_pair))
                        self.trigger_event(
                            MarketEvent.OrderFilled,
                            OrderFilledEvent(
                                timestamp=float(trade["time"]) * 1e-3,
                                order_id=self._exchange_order_ids.get(str(trade["orderId"]), None),
                                trading_pair=trading_pair,
                                trade_type=TradeType.BUY if trade["isBuyer"] else TradeType.SELL,
                                order_type=OrderType.LIMIT_MAKER if trade["isMaker"] else OrderType.LIMIT,
                                price=Decimal(trade["price"]),
                                amount=Decimal(trade["qty"]),
                                trade_fee=DeductedFromReturnsTradeFee(
                                    flat_fees=[
                                        TokenAmount(
                                            trade["commissionAsset"],
                                            Decimal(trade["commission"])
                                        )
                                    ]
                                ),
                                exchange_trade_id=str(trade["id"])
                            ))
                        self.logger().info(f"Recreating missing trade in TradeFill: {trade}")

    async def product_type_for_trading_pair(self, trading_pair: str) -> str:
        full_symbol = await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        return _symbol_and_product_type(full_symbol=full_symbol)[-1]

    async def _all_trade_updates_for_order(self, order: InFlightOrder) -> List[TradeUpdate]:
        trade_updates = []

        if order.exchange_order_id is not None:
            exchange_order_id = order.exchange_order_id
            trading_pair = await self.exchange_symbol_associated_to_pair(trading_pair=order.trading_pair)
            print("55555 1 bbbbbb",  format_symbol(trading_pair))
            self.logger().info(f"55555 bbbbbb = {format_symbol(trading_pair)}")
            all_fills_response = await self._api_get(
                path_url=CONSTANTS.MY_TRADES_PATH_URL,
                params={
                    "symbol": format_symbol(trading_pair),
                    "orderId": exchange_order_id
                },
                is_auth_required=True,
                limit_id=CONSTANTS.MY_TRADES_PATH_URL,
                headers={"Content-Type": "application/json"})
            print("66666 1 bbbbbb",all_fills_response)
            self.logger().info(f"66666 bbbbbb = {all_fills_response}")
            for trade in all_fills_response["data"]:
                exchange_order_id = str(trade["tradeId"])
                fee = TradeFeeBase.new_spot_fee(
                    fee_schema=self.trade_fee_schema(),
                    trade_type=order.trade_type,
                    percent_token=trade["feeDetail"]["totalFee"],
                    flat_fees=[TokenAmount(amount=Decimal(trade["feeDetail"]["totalFee"]), token=trade["symbol"])]
                )
                trade_update = TradeUpdate(
                    trade_id=str(trade["tradeId"]),
                    client_order_id=order.client_order_id,
                    exchange_order_id=exchange_order_id,
                    trading_pair=trading_pair,
                    fee=fee,
                    fill_base_amount=Decimal(trade["amount"]),
                    fill_quote_amount=Decimal(trade["size"]),
                    fill_price=Decimal(trade["priceAvg"]),
                    fill_timestamp=trade["cTime"] * 1e-3,
                )
                trade_updates.append(trade_update)

        return trade_updates

    async def _request_order_status(self, tracked_order: InFlightOrder) -> OrderUpdate:
        trading_pair = await self.exchange_symbol_associated_to_pair(trading_pair=tracked_order.trading_pair)
        self.logger().info(f"77777 GET = {format_symbol(trading_pair)} {tracked_order.exchange_order_id}")
        print("77777 GET 1", format_symbol(trading_pair))
        print("77777 GET 2", tracked_order.exchange_order_id)
        updated_order_data = await self._api_get(
            path_url=CONSTANTS.QUERY_ACTIVE_ORDER_PATH_URL,
            params={
                "symbol": format_symbol(trading_pair),
                # "clientOid": tracked_order.exchange_order_id
            },
            is_auth_required=True,
            headers={"Content-Type": "application/json"})
        self.logger().info(f"77777 RESULT 1 = {updated_order_data}")

        updated_order_data = updated_order_data.get('data', [])
        self.logger().info(f"77777 RESULT 2 = {updated_order_data}")
        if tracked_order.exchange_order_id:
            updated_order_data = [order for order in updated_order_data if order.get('orderId') == tracked_order.exchange_order_id]
        updated_order_data = updated_order_data[0]
        self.logger().info(f"77777 RESULT 3 = {updated_order_data}")
        new_state = CONSTANTS.ORDER_STATE[updated_order_data["status"]]
        self.logger().info(f"77777 RESULT 4 = {updated_order_data}")

        order_update = OrderUpdate(
            client_order_id=tracked_order.client_order_id,
            exchange_order_id=str(updated_order_data["orderId"]),
            trading_pair=tracked_order.trading_pair,
            update_timestamp=self.current_timestamp,
            new_state=new_state,
        )

        return order_update

    async def _update_balances(self):

        local_asset_names = set(self._account_balances.keys())
        remote_asset_names = set()

        account_info = await self._api_get(
            path_url=CONSTANTS.ACCOUNTS_PATH_URL,
            is_auth_required=True,
            headers={"Content-Type": "application/json"})

        self._account_available_balances = {}
        self._account_balances = {}
        remote_asset_names = set()

        # Lấy balances từ account_info
        balances = account_info["data"]

        # Duyệt qua từng phần tử của balances
        for balance_entry in balances:
            asset_name = balance_entry["coin"]  # Thay "asset" bằng "coin"
            free_balance = Decimal(balance_entry["available"])  # Thay "free" bằng "available"
            locked_balance = Decimal(balance_entry["locked"])  # Dùng "locked" hoặc "frozen" nếu có

            # Tổng số dư bao gồm cả số dư đang bị khóa
            total_balance = free_balance + locked_balance

            # Lưu trữ số dư vào dictionary
            self._account_available_balances[asset_name] = free_balance
            self._account_balances[asset_name] = total_balance

            # Thêm tên tài sản vào tập hợp remote_asset_names

            remote_asset_names.add(asset_name)

        asset_names_to_remove = local_asset_names.difference(remote_asset_names)
        for asset_name in asset_names_to_remove:
            del self._account_available_balances[asset_name]
            del self._account_balances[asset_name]

    def _initialize_trading_pair_symbols_from_exchange_info(self, exchange_info: Dict[str, Any]):

        mapping = bidict()
        # print("hello 2", bitget_utils.is_exchange_information_valid)
        # print("hello 2", exchange_info["data"])
        for symbol_data in filter(bitget_utils.is_exchange_information_valid, exchange_info["data"]):
            mapping[symbol_data["symbol"]] = combine_to_hb_trading_pair(base=symbol_data["baseCoin"],
                                                                        quote=symbol_data["quoteCoin"])
        self._set_trading_pair_symbol_map(mapping)

    async def _get_last_traded_price(self, trading_pair: str) -> float:

        # params = {
        #     "symbol": await self.exchange_symbol_associated_to_pair(trading_pair=trading_pair)
        # }

        params = {
            "symbol":  trading_pair.replace("-", "")
        }
        print("2222222 11 params", params)


        resp_json = await self._api_request(
            method=RESTMethod.GET,
            path_url=CONSTANTS.TICKER_PRICE_CHANGE_PATH_URL,
            params=params,
            headers={"Content-Type": "application/json"}
        )

        print("2222222 5555 resp_json", float(resp_json['data'][0]['lastPr']))
        return float(resp_json['data'][0]['lastPr'])

    async def _make_network_check_request(self):
        pass
        # await self._api_get(path_url=self.check_network_request_path, headers={"Content-Type": "application/json"})

    async def _make_trading_rules_request(self) -> Any:

        exchange_info = await self._api_get(path_url=self.trading_rules_request_path, headers={"Content-Type": "application/json"})

        return exchange_info

    async def _make_trading_pairs_request(self) -> Any:
        exchange_info = await self._api_get(path_url=self.trading_pairs_request_path, headers={"Content-Type": "application/json"})
        return exchange_info
