from binance import client
from binance.enums import SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT, ORDER_TYPE_MARKET

from finlab.online.base_account import OrderCondition, Account, Action, Order, Stock, OrderStatus
from finlab.online.order_executor import Position
import os
import os
import sys
import time
import math
import logging
import datetime
import traceback
import pandas as pd
import cachetools.func
from typing import Union
from decimal import Decimal



def round_step_size(quantity: Union[float, Decimal], step_size: Union[float, Decimal], round_up: bool = False) -> Decimal:
    """Rounds a given quantity to a specific step size, either rounding up or down.

    :param quantity: required
    :param step_size: required
    :param round_up: If True, round up; if False, round down.

    :return: decimal
    """
    quantity = Decimal(str(quantity))
    step_size = Decimal(str(step_size))

    if round_up:
        rounded_quantity = math.ceil(quantity / step_size) * step_size
    else:
        rounded_quantity = math.floor(quantity / step_size) * step_size

    return rounded_quantity.normalize()

def retry(f, n_retry, *args, **argvs):
  for i in range(1, n_retry + 1):
    try:
      return f(*args, **argvs)
    except Exception as e:
      exc_type, exc_obj, exc_tb = sys.exc_info()
      fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)
      print(traceback.format_exc())
      print(args, argvs)

      if i != n_retry:
        time.sleep(30)

class BinanceHelper(object):
  
  @staticmethod
  def get_spot_balance(client):

    spot_account_balance = pd.DataFrame(retry(client.get_account, 3)['balances']).set_index('asset').astype(float)
    spot_account_balance = spot_account_balance.sum(axis=1)[spot_account_balance.sum(axis=1)!=0]
    spot_account_balance.index = spot_account_balance.index + 'USDT'

    spot_tickers = BinanceHelper.get_spot_asset_price(client)
    spot_tickers['USDTUSDT'] = 1
    spot_tickers = pd.Series(spot_tickers)
    return (spot_tickers.loc[spot_account_balance.index.intersection(spot_tickers.index)] * spot_account_balance).sum()
  
  @staticmethod
  def get_futures_balance(client):
    
    def list_select(list, key, value):
      ret = [l for l in list if l[key] == value]
      if len(ret) == 0:
        return None
      else:
        return ret[0]
      
    # calculate futures balance
    futures_position_information = retry(client.futures_position_information, 3)
    future_account_balance = retry(client.futures_account_balance, 3)
    futures_position_information = pd.DataFrame(futures_position_information).astype({'entryPrice': 'float', 'positionAmt':'float', 'unRealizedProfit':'float'})
    futures_total_balance = futures_position_information.unRealizedProfit.sum()+float(list_select(future_account_balance, 'asset', 'USDT')['balance'])\
      +float(list_select(future_account_balance, 'asset', 'BNB')['balance']) * BinanceHelper.get_futures_asset_price(client)['BNBUSDT']

    return futures_total_balance
  
  @staticmethod
  @cachetools.func.ttl_cache(ttl=60)
  def get_spot_asset_price(client):
      all_tickers = retry(client.get_all_tickers, 3)
      all_ticker_price = {d['symbol']: Decimal(d['price']) for d in all_tickers}
      return all_ticker_price
  
  @staticmethod
  @cachetools.func.ttl_cache(ttl=60)
  def get_futures_asset_price(client):
    all_tickers = retry(client.futures_mark_price, 3)
    all_ticker_price = {m['symbol']: Decimal(m['markPrice']) for m in all_tickers}
    return all_ticker_price
  
  @staticmethod
  def get_spot_position(client):
    # spot balance
    account = retry(client.get_account, 3)['balances']
    spot_balance = {obj['asset']:Decimal(obj['free']) + Decimal(obj['locked']) for obj in account if Decimal(obj['free']) != 0}
    return {k:v for k, v in spot_balance.items()}
  
  @staticmethod
  def get_futures_position(client):

    futures_balance = client.futures_position_information()
    futures_balance = pd.DataFrame(futures_balance)\
      .astype({'entryPrice': 'float', 'positionAmt':'float', 'unRealizedProfit':'float'})

    futures_balance = futures_balance.loc[futures_balance.symbol.str[-4:] == 'USDT']
    futures_balance.index = futures_balance.symbol.str[:-4]
    futures_balance = futures_balance.positionAmt.to_dict()
    return {k:v for k, v in futures_balance.items() if v != 0}


class BinanceSimpleClient():

  def __init__(self, client):
    self.client = client
    
    futures_exchange_info = retry(client.futures_exchange_info, 3)
    exchange_info = retry(client.get_exchange_info, 3)

    if futures_exchange_info is None:
        raise Exception('Cannot connect to binance client.futures_exchange_info')
    
    if exchange_info is None:
        raise Exception('Cannot connect to binance client.exchange_info')

    self.market_info = {
      'FUTURES': pd.DataFrame(futures_exchange_info['symbols']).set_index('symbol'),
      'SPOT': pd.DataFrame(exchange_info['symbols']).set_index('symbol'),
    }

  def round_price(self, symbol, price, round_up=False, market_type='SPOT'):
    info = self.market_info[market_type]
    ticksize = Decimal(self.list_select(info.loc[symbol].filters, 'filterType', 'PRICE_FILTER')['tickSize'])
    #return round(int(price / ticksize) * ticksize, 9)
    return round_step_size(price, ticksize, round_up=round_up)

  def round_quantity(self, symbol, quantity, round_up=False, market_type='SPOT'):

    info = self.market_info[market_type]
    symbol_info = self.list_select(info.loc[symbol].filters, 'filterType', 'LOT_SIZE')
    step_size = Decimal(symbol_info['stepSize'])
    min_qty = Decimal(symbol_info['minQty'])
    
    sign = (quantity < 0) * -2 + 1
    ret = sign * round_step_size(abs(quantity), step_size, round_up=round_up)
    # ret = round(sign * (int((quantity-min_qty) / step_size) * step_size + min_qty), 9)
    
    if abs(ret) < min_qty:
      ret = 0
      
    return ret
  
  @staticmethod
  def list_select(list, key, value):
    ret = [l for l in list if l[key] == value]
    if len(ret) == 0:
      return None
    else:
      return ret[0]

  def pass_min_notional(self, symbol, quantity, market_type, price=None):
    info = self.market_info[market_type]
    notional = self.list_select(info.loc[symbol].filters, 'filterType', 'NOTIONAL')
    min_notional = Decimal(notional.get('minNotional', notional.get('notional', 0)))
    
    present_price = price
    if present_price is None:
      if market_type == 'SPOT':
        present_price = BinanceHelper.get_spot_asset_price(self.client)[symbol]
      elif market_type == 'FUTURES':
        present_price = BinanceHelper.get_futures_asset_price(self.client)[symbol]

    if abs(quantity) * present_price < min_notional:
        return False
    return True

  def create_order(self, symbol, quantity, market_type, price=None, stop_price=None):

    if symbol == 'NBTUSDT':
      return None

    side = SIDE_BUY if quantity > 0 else SIDE_SELL

    if stop_price is not None:
        assert price is not None

    ORDER_TYPE_STOP = 'STOP'

    order_type = ORDER_TYPE_STOP if stop_price is not None else \
        ORDER_TYPE_LIMIT if price is not None else ORDER_TYPE_MARKET

    
    if price is not None:
      price = self.round_price(symbol, price, round_up=False, market_type=market_type)

    if stop_price is not None:
      stop_price = self.round_price(symbol, stop_price, round_up=False, market_type=market_type)

    # recalculate amount according to step size
    quantity = self.round_quantity(symbol, quantity, round_up=False, market_type=market_type)
    icebergQty = self.round_quantity(symbol, quantity/Decimal('9.5'), round_up=False, market_type=market_type)

    # check min invest value (notional)
    
    pass_notional = self.pass_min_notional(symbol, quantity, market_type=market_type, price=price)

    min_notional_iceberg = 0.05 if symbol[-3:] == 'BTC' else 1000 if symbol[-4:] == 'USDT' else 1000

    use_iceberg = (abs(quantity) * abs(price) > min_notional_iceberg) & (abs(icebergQty)*10 > abs(quantity))
    
    params = {
      'side':side,
      'type':order_type,
      'symbol':symbol,
      'quantity': format(abs(quantity), 'f') if isinstance(quantity, Decimal) else abs(quantity),
    }
    
    if use_iceberg and market_type == 'SPOT' and icebergQty != 0:
      params['icebergQty'] = format(abs(icebergQty), 'f') if isinstance(icebergQty, Decimal) else abs(icebergQty)

    if market_type == 'FUTURES' and side == SIDE_BUY:
      params['reduceOnly'] = 'true'

    if price is not None:

      precision = 8
      price_str = '{:0.0{}f}'.format(price, precision)
      params['price'] = price_str
      params['timeInForce'] = 'GTC' #if order_type != ORDER_TYPE_LIMIT else 'GTX'

    if stop_price is not None:
      params['stopPrice'] = stop_price

    if market_type == 'SPOT':
      order_func = self.client.create_order
    elif market_type == 'FUTURES':
      order_func = self.client.futures_create_order
    else:
      raise Exception('market_type not in ["SPOT", "FUTURES"]')
    
    if (not pass_notional or quantity == 0) and 'reduceOnly' not in params:
      return None

    order = retry(order_func, 1, **params)

    return order


class BinanceAccount(Account):

    def __init__(self, base_currency='USDT'):

        if 'BINANCE_API_KEY' in os.environ:
            key = os.environ['BINANCE_API_KEY']
            secret = os.environ['BINANCE_API_SECRET']
            self.simple_client = BinanceSimpleClient(client.Client(key, secret))
        else:
            self.simple_client = BinanceSimpleClient(client.Client())

        self.threading = None
        self.base_currency = base_currency

    def create_order(self, action, stock_id, quantity, price=None, odd_lot=False, best_price_limit=False, market_order=False, order_cond=OrderCondition.CASH, extra_bid_pct=0) -> str:

        if quantity <= 0:
            raise ValueError("quantity should be larger than zero")

        if best_price_limit and market_order:
            raise ValueError(
                "The flags best_price_limit and  market_order should not both be True")

        if not market_order:
            assert price is not None

        if action == Action.SELL:
            quantity = - abs(quantity)

        # create_order(self, symbol, quantity, market_type, price=None, stop_price=None):

        args = {
            'symbol': stock_id+self.base_currency,
            'quantity': quantity,
            'market_type': 'SPOT',
        }

        if not market_order:
            args['price'] = price
        
        order = self.simple_client.create_order(**args)

        if not order or not 'orderId' in order:
            print('client order not success')
            return ''

        return stock_id + '|' + str(order['orderId'])

    def update_order(self, order_id, price=None, quantity=None):

        stock_id, order_id = order_id.split('|')

        if isinstance(price, int):
            price = Decimal(price)

        order = self.simple_client.client.get_order(symbol=stock_id, orderId=order_id)
        self.simple_client.client.cancel_order(symbol=stock_id, orderId=order_id)

        if quantity:
          quantity = quantity - order['executedQty']
        else:
          quantity = (order['executedQty'] - order['origQty']) * ((order['side'] == 'BUY')*2 - 1)

        self.simple_client.create_order(symbol=stock_id, quantity=quantity, price=price, market_type='SPOT')
        return

    def cancel_order(self, order_id):
        stock_id, order_id = order_id.split('|')

        try:
            self.simple_client.client.cancel_order(symbol=stock_id, orderId=order_id)
        except Exception as e:
            logging.warning(f"cancel_order: Cannot cancel order {order_id}: {e}")

    def get_orders(self):

        orders = self.simple_client.client.get_open_orders()
        ret = {}
        for o in orders:
            status = OrderStatus.NEW
            if o['executedQty'] == 0:
                status = OrderStatus.NEW
            elif o['origQty'] != o['executedQty']:
                status = 'Filling'
                status = OrderStatus.PARTIALLY_FILLED
            else:
                status = OrderStatus.FILLED

            if o['status'] == 'CANCELED':
                status = OrderStatus.CANCEL

            ret[str(o['symbol'])+'|'+str(o['orderId'])] = Order(order_id=o['orderId'], action=o['side'], price=o['price'], 
                quantity=o['origQty'], filled_quantity=o['executedQty'], status=status, 
                time=datetime.datetime.fromtimestamp(int(o['time'])/1000), 
                stock_id=o['symbol'], order_condition=OrderCondition.CASH, org_order=o)
        return ret

    def get_stocks(self, stock_ids):

        if not stock_ids:
            return {}

        ret = {}

        all_symbols = set(t['symbol'] for t in self.simple_client.client.get_all_tickers())

        symbols = '["'+ '","'.join([s+self.base_currency for s in stock_ids if s+self.base_currency in all_symbols]) + '"]'
        tickers = self.simple_client.client.get_ticker(symbols=symbols)

        for t in tickers:
            asset = t['symbol'].replace(self.base_currency, '')
            ret[asset] = Stock(stock_id=asset, open=Decimal(t['openPrice']), 
                               high=Decimal(t['highPrice']), low=Decimal(t['lowPrice']), 
                close=Decimal(t['lastPrice']), bid_price=Decimal(t['bidPrice']), bid_volume=Decimal(t['bidQty']), 
                ask_price=Decimal(t['askPrice']), ask_volume=Decimal(t['askQty']))
            
        return ret

    def get_position(self):
        ret = BinanceHelper.get_spot_position(self.simple_client.client)
        return Position.from_list([
           {'stock_id': sym, 'quantity': amount, 'order_condition': OrderCondition.CASH} 
           for sym, amount in ret.items()])
        
    def get_total_balance(self):
        
        return BinanceHelper.get_spot_balance(self.simple_client.client)

    def support_day_trade_condition(self):
        return True

    def on_trades(self, func):
        pass
    
    def sep_odd_lot_order(self):
        return False
      
