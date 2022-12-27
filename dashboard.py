from finlab.online.order_executor import Position
from finlab.online.order_executor import OrderExecutor
import finlab
import datetime
import requests
import threading
import pandas as pd
import time

class Dashboard():

    def __init__(self, acc, paper_trade=False):
        self.acc = acc
        self.paper_trade = paper_trade
        self.thread_callback = None
        self.thread_balancecheck = None

    def rebalance(self, odd_lot=False, market_order=False, api_token=None):
        if not api_token:
            api_token = finlab.get_token()

        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dash_get_portfolio'
        res = requests.post(url, json={'api_token':api_token})
        port = res.json()

        ### set target qty
        # get target_qty
        target_qty_open = []
        target_qty_open_fake = []  # 因應 1.trade_at_price == 'close' 2.target_qty  == None的狀況，要塞給dash_set_qty的data，實際開盤時間是下target_qty_open
        target_qty_close = []
        for stgy in port['msg']['portfolios']:
            stgy_greedy_flag = False
            stgy_weight = []
            for asset in port['msg']['assets']:
                if stgy['id'] in asset['sqty'].keys():
                    if asset['sqty'][stgy['id']]['next_weight'] > 0 and asset['sqty'][stgy['id']]['next_qty'] == None:
                        # next_qty 為 None的所有asset一起拿next_weight用greedy allocation計算next_qty
                        stgy_greedy_flag = True
                        stgy_weight.append((asset['id'],asset['sqty'][stgy['id']]['next_weight']))
                        if asset['sqty'][stgy['id']]['trade_at_price'] == 'close':
                            # target_qty_open 裡 策略為close單的要使用qty  (還不用算next_qty)
                            target_qty_open.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': asset['sqty'][stgy['id']]['qty']})
                            target_qty_open_fake.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': None})
                    elif asset['sqty'][stgy['id']]['next_qty'] != None:
                        # next_qty 有值的直接沿用
                        if asset['sqty'][stgy['id']]['trade_at_price'] == 'open':
                            target_qty_open.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': asset['sqty'][stgy['id']]['next_qty']})
                            target_qty_open_fake.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': asset['sqty'][stgy['id']]['next_qty']})
                        elif asset['sqty'][stgy['id']]['trade_at_price'] == 'close':
                            # target_qty_open 裡 策略為close單的要使用qty
                            target_qty_open.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': asset['sqty'][stgy['id']]['qty']})
                            target_qty_open_fake.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': None})
                        target_qty_close.append({'asset_id': asset['id'],'strategy_id': stgy['id'], 'qty': asset['sqty'][stgy['id']]['next_qty']})
            if stgy_greedy_flag:
                position = Position.from_weight(dict(stgy_weight), fund=stgy['position'], odd_lot=odd_lot).position
                for p in position:
                    if stgy['trade_at'] == 'open':
                        # target_qty_open 只要計算open單的next_qty
                        target_qty_open.append({'asset_id': p['stock_id'],'strategy_id': stgy['id'], 'qty': p['quantity']})
                        target_qty_open_fake.append({'asset_id': p['stock_id'],'strategy_id': stgy['id'], 'qty': p['quantity']})
                    # target_qty_close 全部都要計算next_qty
                    target_qty_close.append({'asset_id': p['stock_id'],'strategy_id': stgy['id'], 'qty': p['quantity']})     
        # custom assets
        for asset in port['msg']['assets']:
            if asset['custom_qty'] > 0:
                target_qty_open.append({'asset_id': asset['id'], 'qty': asset['custom_qty']})
                target_qty_close.append({'asset_id': asset['id'], 'qty': asset['custom_qty']})
                target_qty_open_fake.append({'asset_id': asset['id'], 'qty': asset['custom_qty']})

        # decide open or close   判斷12點後為收盤時間
        close_time = True if (datetime.datetime.utcnow() + datetime.timedelta(hours=8)).time() > datetime.time(12,0) else False
        target_qty = target_qty_close if close_time else target_qty_open_fake
        # get present_qty
        acc_position = self.acc.get_position().position
        acc_position  = pd.DataFrame(acc_position).groupby('stock_id').sum() if len(acc_position) > 0 else []
        present_qty = []
        for i in range(len(acc_position)):
            present_qty.append({'asset_id':acc_position.index[i], 'qty': acc_position.quantity[i]})
        dash_set_qty = {
            'api_token': api_token,
            "present_qty":
                present_qty,
            "target_qty":
                target_qty,
        }
        url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dash_set_qty'
        requests.post(url, json=dash_set_qty)


        # create new position
        target_qty = target_qty_close if close_time else target_qty_open
        self.position = Position({t['asset_id']: t['qty'] for t in target_qty})

        tz = datetime.timezone(datetime.timedelta(hours=8))

        @self.acc.sdk.on('dealt')
        def on_dealt(data):
            if isinstance(data, dict):
                txn = {'api_token': api_token,
                'txn':{
                        'time': (datetime.datetime.strptime(f"{str((datetime.datetime.utcnow()+datetime.timedelta(hours=8)).date())} {data['mat_time']}", "%Y-%m-%d %H%M%S%f")-datetime.timedelta(hours=8)).replace(tzinfo=tz).isoformat(),
                        'asset_id': data['stock_no'],
                        'qty': int(data['mat_qty'])/1000 if data['buy_sell'] =='B' else -int(data['mat_qty'])/1000,
                        'price': data['mat_price'],
                        'pt': self.paper_trade # paper trade
                    }
                }
                url = 'https://asia-east2-fdata-299302.cloudfunctions.net/dash_add_txn'
                requests.post(url, json=txn)

        # create new threads to deal with trade info callback and balance check
        self.stop()
        self.stop_thread = False
        self.thread_callback = threading.Thread(target = self.callback)
        self.thread_callback.start()
        self.thread_balancecheck = threading.Thread(target = self.balancecheck)
        self.thread_balancecheck.start()

        # create order
        self.oe = OrderExecutor(self.position, self.acc)
        self.oe.create_orders(market_order=market_order)        

    def callback(self):
        self.acc.sdk.connect_websocket()

    def balancecheck(self):
        # check if balanced
        position = sorted(self.position.position, key=lambda d: d['stock_id']) 
        while True and not self.stop_thread:
            time.sleep(30)
            account_present = sorted(self.acc.get_position().position, key=lambda d: d['stock_id']) 
            if account_present == position:
                break
        # close callback thread
        self.stop()
        
    def stop(self):
        self.stop_thread = True
        if self.acc.sdk._SDK__wsHandler._WebsocketHandler__ws:
            self.acc.sdk._SDK__wsHandler._WebsocketHandler__ws.close()
        self.acc.sdk._SDK__wsHandler._WebsocketHandler__ws = None

        time.sleep(1)
        if self.thread_callback:
            self.thread_callback.join()
        if self.thread_balancecheck:
            self.thread_balancecheck.join()
    
    def update_order_price(self):
        if hasattr(self, 'oe'):
            self.oe.update_order_price()
