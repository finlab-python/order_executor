from finlab.online.position import Position
from finlab.online.enums import *
from finlab import data
from decimal import Decimal
import pandas as pd
import requests
import logging
import numbers
import copy
import math

logger = logging.getLogger(__name__)

class OrderExecutor():

    def __init__(
            self, target_position, account):
        """對比實際帳戶與欲部屬的股票部位，進行同步
            Arguments:
                target_position (Position): 想要部屬的股票部位。
                account (Account): 目前支援永豐與富果帳戶，請參考 Account 來實做。
        """

        if isinstance(target_position, dict):
            target_position = Position(target_position)

        self.account = account
        self.target_position = target_position

    def show_alerting_stocks(self):
        """產生下單部位是否有警示股，以及相關資訊"""

        present_position = self.account.get_position()
        new_orders = (self.target_position - present_position).position

        stock_ids = [o['stock_id'] for o in new_orders]
        quantity = {o['stock_id']: o['quantity'] for o in new_orders}

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_3')
        dfs = pd.read_html(res.text)
        credit_sids = dfs[0][dfs[0]['股票代碼'].astype(str).isin(stock_ids)]['股票代碼']

        res = requests.get('https://www.sinotrade.com.tw/Stock/Stock_3_8_1')
        dfs = pd.read_html(res.text)
        credit_sids = pd.concat(
            [credit_sids, dfs[0][dfs[0]['股票代碼'].astype(str).isin(stock_ids)]['股票代碼'].astype(str)])
        credit_sids.name = None

        if credit_sids.any():
            close = data.get('price:收盤價').ffill().iloc[-1]
            for sid in list(credit_sids.values):
                quantity[sid] = float(quantity[sid])
                if quantity[sid] > 0:
                    total_amount = quantity[sid]*close[sid]*1000*1.1
                    print(
                        f"買入 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")
                else:
                    total_amount = quantity[sid]*close[sid]*1000*0.9
                    print(
                        f"賣出 {sid} {quantity[sid]:>5} 張 - 總價約 {total_amount:>15.2f}")

    def cancel_orders(self):
        """刪除所有未實現委託單"""
        orders = self.account.get_orders()
        for oid, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:
                self.account.cancel_order(oid)

    def generate_orders(self, progress=1, progress_precision=0):
        """
        Generate orders based on the difference between target position and present position.
        
        Returns:
        orders (dict): Orders to be executed.
        """

        target_position = Position.from_list(copy.copy(self.target_position.position))

        if hasattr(self.account, 'base_currency'):
            base_currency = self.account.base_currency
            for pp in target_position.position:
                if pp['stock_id'][-len(base_currency):] == base_currency:
                    pp['stock_id'] = pp['stock_id'][:-len(base_currency)]
                else:
                    raise ValueError(f"Stock ID {pp['stock_id']} does not end with {base_currency}")

        present_position = self.account.get_position()
        orders = (target_position - present_position)
        if progress != 1:
            if not (progress >= 0 and progress <= 1):
                raise ValueError("progress should be in the range of 0 to 1")
            if progress_precision is None:
                raise ValueError("progress_precision should be set when progress is not 1")
            
            orders = Position.from_list([{**o, 'quantity': round(float(o['quantity'])*progress, progress_precision)} for o in orders.position])

        return orders.position
    
    def execute_orders(self, orders, market_order=False, best_price_limit=False, view_only=False, extra_bid_pct=0, cancel_orders=True, buy_only=False, sell_only=False):
        """產生委託單，將部位同步成 self.target_position
        預設以該商品最後一筆成交價設定為限價來下單
        
        Attributes:
            orders (list): 欲下單的部位，通常是由 `self.generate_orders` 產生。
            market_order (bool): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
            best_price_limit (bool): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
            view_only (bool): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想；
                假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
            buy_only (bool): 若設為 True，只下買單
            sell_only (bool): 若設為 True，只下賣單
        """

        if [market_order, best_price_limit, bool(extra_bid_pct)].count(True) > 1:
            raise ValueError("Only one of 'market_order', 'best_price_limit', or 'extra_bid_pct' can be set.")
        if extra_bid_pct < -0.1 or extra_bid_pct > 0.1:
            raise ValueError("The extra_bid_pct parameter is out of the valid range 0 to 0.1")
        if buy_only and sell_only:
            raise ValueError("The buy_only and sell_only parameters cannot be set to True at the same time.")

        if cancel_orders:
            self.cancel_orders()

        stocks = self.account.get_stocks(list({o['stock_id'] for o in orders}))

        pinfo = None
        if hasattr(self.account, 'get_price_info'):
            pinfo = self.account.get_price_info()

        # make orders
        for o in orders:

            if o['quantity'] == 0:
                continue

            action = Action.BUY if o['quantity'] > 0 else Action.SELL
            
            if buy_only and action == Action.SELL:
                continue

            if sell_only and action == Action.BUY:
                continue
            
            if o['stock_id'] not in stocks:
                logging.warning(o['stock_id'] + 'not in stocks... skipped!')
                continue

            stock = stocks[o['stock_id']]
            price: float = stock.close if isinstance(stock.close, numbers.Number) else (
                    stock.bid_price if action == Action.BUY else stock.ask_price
                    )

            if extra_bid_pct != 0:
                price = calculate_price_with_extra_bid(price, extra_bid_pct if action == Action.BUY else -extra_bid_pct)

            if pinfo and o['stock_id'] in pinfo:
                limitup = float(pinfo[o['stock_id']]['漲停價'])
                limitdn = float(pinfo[o['stock_id']]['跌停價'])
                price = max(price, limitdn)
                price = min(price, limitup)
            else:
                logger.warning('No price info for stock %s', o['stock_id'])

            if isinstance(price, Decimal):
                price = format(price, 'f')

            if best_price_limit:
                price_string = 'LOWEST' if action == Action.BUY else 'HIGHEST'
            elif market_order:
                price_string = 'HIGHEST' if action == Action.BUY else 'LOWEST'
            else:
                price_string = str(price)

            extra_bid_text = ''
            if extra_bid_pct > 0:
                extra_bid_text = f'with extra bid {extra_bid_pct*100}%'

            # logger.warning('%-11s %-6s X %-10s @ %-11s %s %s', action, o['stock_id'], abs(o['quantity']), price_string, extra_bid_text, o['order_condition'])
            # use print f-string format instead of logger
            action_str = 'BUY' if action == Action.BUY else 'SELL'
            order_condition_str = 'CASH' if o['order_condition'] == OrderCondition.CASH else 'MARGIN_TRADING' if o['order_condition'] == OrderCondition.MARGIN_TRADING else 'SHORT_SELLING' if o['order_condition'] == OrderCondition.SHORT_SELLING else 'DAY_TRADING_LONG' if o['order_condition'] == OrderCondition.DAY_TRADING_LONG else 'DAY_TRADING_SHORT' if o['order_condition'] == OrderCondition.DAY_TRADING_SHORT else 'UNKNOWN'
            print(f'{action_str:<11} {o["stock_id"]:10} X {round(abs(o["quantity"]), 3):<10} @ {price_string:<11} {extra_bid_text} {order_condition_str}')


            quantity = abs(o['quantity'])
            board_lot_quantity = int(abs(quantity // 1))
            odd_lot_quantity = int(abs(round(1000 * (quantity % 1))))

            if view_only:
                continue

            if self.account.sep_odd_lot_order():
                if odd_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=odd_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              odd_lot=True,
                                              best_price_limit=best_price_limit,
                                              )

                if board_lot_quantity != 0:
                    self.account.create_order(action=action,
                                              stock_id=o['stock_id'],
                                              quantity=board_lot_quantity,
                                              price=price, market_order=market_order,
                                              order_cond=o['order_condition'],
                                              best_price_limit=best_price_limit,
                                              )
            else:
                self.account.create_order(action=action,
                                          stock_id=o['stock_id'],
                                          quantity=quantity,
                                          price=price, market_order=market_order,
                                          order_cond=o['order_condition'],
                                          best_price_limit=best_price_limit,
                                          )
                
        return orders


    def create_orders(self, market_order=False, best_price_limit=False, view_only=False, extra_bid_pct=0, progress=1, progress_precision=0, buy_only=False, sell_only=False):
        """產生委託單，將部位同步成 self.target_position
        預設以該商品最後一筆成交價設定為限價來下單
        
        Attributes:
            market_order (bool): 以類市價盡量即刻成交：所有買單掛漲停價，所有賣單掛跌停價
            best_price_limit (bool): 掛芭樂價：所有買單掛跌停價，所有賣單掛漲停價
            view_only (bool): 預設為 False，會實際下單。若設為 True，不會下單，只會回傳欲執行的委託單資料(dict)
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.05 時，將以當前價的 +(-)5% 的限價進買入(賣出)，也就是更有機會可以成交，但是成交價格可能不理想；
                假如設定為 -0.05 時，將以當前價的 -(+)5% 進行買入賣出，也就是限價單將不會立即成交，然而假如成交後，價格比較理想。參數有效範圍為 -0.1 到 0.1 內。
            progress (float): 進度，預設為 1，即全部下單。若設定為 0.5，則只下一半的單。
            progress_precision (int): 進度的精度，預設為 0，即只下整數張。若設定為 1，則下到 0.1 張。
            buy_only (bool): 若設為 True，只下買單
            sell_only (bool): 若設為 True，只下賣單
        """
        self.cancel_orders()
        orders = self.generate_orders(progress, progress_precision)
        return self.execute_orders(orders, market_order, best_price_limit, view_only, extra_bid_pct, cancel_orders=False, buy_only=buy_only, sell_only=sell_only)
    
    
    def update_order_price(self, extra_bid_pct=0):
        """更新委託單，將委託單的限價調整成當天最後一筆價格。
        （讓沒成交的限價單去追價）
        Attributes:
            extra_bid_pct (float): 以該百分比值乘以價格進行追價下單，如設定為 0.1 時，將以超出(低於)現價之10%價格下單，以漲停(跌停)價為限。參數有效範圍為 0 到 0.1 內
            """
        if extra_bid_pct < -0.1 or extra_bid_pct > 0.1:
            raise ValueError("The extra_bid_pct parameter is out of the valid range 0 to 0.1")
        orders = self.account.get_orders()
        sids = set([o.stock_id for i, o in orders.items()])
        stocks = self.account.get_stocks(sids)

        pinfo = None
        if hasattr(self.account, 'get_price_info'):
            pinfo = self.account.get_price_info()

        for i, o in orders.items():
            if o.status == OrderStatus.NEW or o.status == OrderStatus.PARTIALLY_FILLED:

                price = stocks[o.stock_id].close

                if o.price == price:
                    continue
                
                price = calculate_price_with_extra_bid(price, extra_bid_pct if o.action == Action.BUY else -extra_bid_pct)

                if pinfo and o.stock_id in pinfo:
                    up_limit = float(pinfo[o.stock_id]['漲停價'])
                    dn_limit = float(pinfo[o.stock_id]['跌停價'])
                    price = max(price, dn_limit)
                    price = min(price, up_limit)
                else:
                    logger.warning('No price info for stock %s', o.stock_id)

                self.account.update_order(i, price=price)


    def get_order_info(self):

        def calc_order_info(oe):
            target = oe.target_position
            current = oe.account.get_position()
            return {
                'target': target.to_list(),
                'current': current.to_list(),
                'orders': (target - current).to_list()
            }

        def get_symbols(orders):
            return [(o['stock_id'], str(o['order_condition'])) for o in orders]


        def find_symbols(orders, symbol):
            ret = [o for o in orders if o['stock_id'] == symbol]
            if len(ret) == 0:
                return {'quantity': 0, 'symbol': symbol[0], 'order_condition': symbol[1]}
            return ret[0]

        orders = calc_order_info(self)
        symbols = sorted(list(set(get_symbols(orders['target']) + get_symbols(orders['current']))))
        stocks = self.account.get_stocks(list(set([s[0] for s in symbols])))

        order_info = []
        for s in symbols:
            pqty = float(find_symbols(orders['current'], s[0])['quantity'])
            tqty = float(find_symbols(orders['target'], s[0])['quantity'])
            order_info.append({
                'price': stocks[s[0]].close,
                'current_qty': pqty,
                'target_qty': tqty,
                'order_qty': tqty - pqty,
                'symbol': s[0],
                'order_condition': s[1],
                })
                
        return sorted(order_info, key=lambda x: x['order_qty'] * x['price'], reverse=True)
                

def calculate_price_with_extra_bid(price: float, extra_bid_pct: float) -> float:

    if extra_bid_pct == 0:
        return price

    if extra_bid_pct > 0:
        result = price * (1 + extra_bid_pct)
        if result <= 10:
            result = math.floor(round(result, 3) * 100) / 100
        elif result <= 50:
            result = math.floor(result * 20) / 20
        elif result <= 100:
            result = math.floor(result * 10) / 10
        elif result <= 500:
            result = math.floor(result * 2) / 2
        elif result <= 1000:
            result = math.floor(result)
        else:
            result = math.floor(result / 5) * 5
    else:
        result = price * (1 + extra_bid_pct)
        if result <= 10:
            result = math.ceil(round(result, 3) * 100) / 100
        elif result <= 50:
            result = math.ceil(result * 20) / 20
        elif result <= 100:
            result = math.ceil(result * 10) / 10
        elif result <= 500:
            result = math.ceil(result * 2) / 2
        elif result <= 1000:
            result = math.ceil(result)
        else:
            result = math.ceil(result / 5) * 5

    return result