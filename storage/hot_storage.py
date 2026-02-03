"""
一级存储 (Hot Storage)
内存中的实时镜像，延迟 < 1ms

使用 Python 原生数据结构实现：
- Order Book: dict (价格 -> 数量)，O(1) 查询和更新
- 成交流: deque (固定长度)，自动弹出旧数据
- 实时指标: OFI、买卖压力等
"""

from collections import deque
from typing import Dict, List, Optional
from datetime import datetime
import time

from utils.logger import logger


class HotStorageLayer:
    """
    一级存储层 - 内存中的实时镜像
    
    特性：
    - 延迟 < 1ms
    - O(1) 查询和更新
    - 自动管理内存（固定长度队列）
    """
    
    def __init__(self, max_trades: int = 1000, max_depth: int = 400):
        """
        初始化一级存储
        
        Args:
            max_trades: 最大成交笔数
            max_depth: 最大深度层级
        """
        # ========== Order Book 存储 ==========
        # Key: 价格, Value: (数量, 订单数, 更新时间戳)
        self.bids: Dict[float, tuple] = {}  # 买盘
        self.asks: Dict[float, tuple] = {}  # 卖盘
        
        # 排序后的价格列表（用于快速遍历）
        self.sorted_bids: List[float] = []  # 降序
        self.sorted_asks: List[float] = []  # 升序
        
        # ========== 成交流存储 ==========
        # 固定长度双端队列，自动弹出旧数据
        self.trades: deque = deque(maxlen=max_trades)
        
        # ========== 实时指标 ==========
        # OFI (Order Flow Imbalance) 历史
        self.ofi_history: deque = deque(maxlen=100)
        
        # 买卖压力
        self.buy_pressure: float = 0.0
        self.sell_pressure: float = 0.0
        
        # 统计信息
        self.update_count: int = 0
        self.last_update_time: Optional[float] = None
        
        logger.info(f"🔥 一级存储初始化完成 | 成交流: {max_trades} | 深度: {max_depth}")
    
    # ========== Order Book 操作 ==========
    
    def update_bid(self, price: float, size: float, orders_count: int = 0):
        """
        更新买盘
        
        Args:
            price: 价格
            size: 数量
            orders_count: 订单数
        """
        current_time = time.time()
        
        if size > 0:
            # 更新或插入
            self.bids[price] = (size, orders_count, current_time)
            
            # 维护排序
            if price not in self.sorted_bids:
                self._insert_sorted(self.sorted_bids, price, reverse=True)
        else:
            # 删除（数量为 0）
            if price in self.bids:
                del self.bids[price]
                self.sorted_bids.remove(price)
        
        self.update_count += 1
        self.last_update_time = current_time
    
    def update_ask(self, price: float, size: float, orders_count: int = 0):
        """
        更新卖盘
        
        Args:
            price: 价格
            size: 数量
            orders_count: 订单数
        """
        current_time = time.time()
        
        if size > 0:
            # 更新或插入
            self.asks[price] = (size, orders_count, current_time)
            
            # 维护排序
            if price not in self.sorted_asks:
                self._insert_sorted(self.sorted_asks, price, reverse=False)
        else:
            # 删除（数量为 0）
            if price in self.asks:
                del self.asks[price]
                self.sorted_asks.remove(price)
        
        self.update_count += 1
        self.last_update_time = current_time
    
    def _insert_sorted(self, lst: List[float], price: float, reverse: bool = False):
        """
        插入到已排序列表（优化版，使用 bisect）
        
        Args:
            lst: 列表
            price: 价格
            reverse: 是否降序
        """
        import bisect
        # 对于降序列表，用负价格比较
        bisect.insort(lst, -price if reverse else price)
        # 如果是降序，需要转换为正数
        if reverse:
            lst[-1] = -lst[-1]
    
    def get_best_bid(self) -> Optional[tuple]:
        """
        获取买一
        
        Returns:
            (价格, 数量) 或 None
        """
        if not self.sorted_bids:
            return None
        
        price = self.sorted_bids[0]
        size, _, _ = self.bids[price]
        return (price, size)
    
    def get_best_ask(self) -> Optional[tuple]:
        """
        获取卖一
        
        Returns:
            (价格, 数量) 或 None
        """
        if not self.sorted_asks:
            return None
        
        price = self.sorted_asks[0]
        size, _, _ = self.asks[price]
        return (price, size)
    
    def get_mid_price(self) -> Optional[float]:
        """
        获取中间价
        
        Returns:
            中间价或 None
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        
        if best_bid and best_ask:
            return (best_bid[0] + best_ask[0]) / 2.0
        
        return None
    
    def get_spread(self) -> Optional[float]:
        """
        获取点差
        
        Returns:
            点差或 None
        """
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        
        if best_bid and best_ask:
            return best_ask[0] - best_bid[0]
        
        return None
    
    def get_depth_at_price(self, price: float, side: str) -> float:
        """
        获取指定价格的深度
        
        Args:
            price: 价格
            side: 方向 (bid/ask)
        
        Returns:
            深度
        """
        if side == "bid":
            return self.bids.get(price, (0, 0, 0))[0]
        else:
            return self.asks.get(price, (0, 0, 0))[0]
    
    # ========== 成交流操作 ==========
    
    def add_trade(self, trade: dict):
        """
        添加成交
        
        Args:
            trade: 成交数据
                {
                    "price": 价格,
                    "size": 数量,
                    "side": 方向 (buy/sell),
                    "timestamp": 时间戳,
                    "trade_id": 成交ID
                }
        """
        self.trades.append(trade)
        
        # 更新买卖压力
        if trade["side"] == "buy":
            self.buy_pressure += trade["size"]
        else:
            self.sell_pressure += trade["size"]
        
        # 计算实时 OFI
        self._calculate_ofi()
    
    def get_recent_trades(self, n: int = 10) -> List[dict]:
        """
        获取最近 n 笔成交
        
        Args:
            n: 数量
        
        Returns:
            成交列表
        """
        return list(self.trades)[-n:]
    
    def get_trades_in_window(self, seconds: float) -> List[dict]:
        """
        获取指定时间窗口内的成交
        
        Args:
            seconds: 时间窗口（秒）
        
        Returns:
            成交列表
        """
        current_time = time.time()
        cutoff_time = current_time - seconds
        
        return [t for t in self.trades if t["timestamp"] >= cutoff_time]
    
    def get_buy_sell_ratio(self, window_seconds: float = 1.0) -> float:
        """
        获取买卖比例
        
        Args:
            window_seconds: 时间窗口（秒）
        
        Returns:
            买卖比例（买量/卖量）
        """
        trades = self.get_trades_in_window(window_seconds)
        
        buy_volume = sum(t["size"] for t in trades if t["side"] == "buy")
        sell_volume = sum(t["size"] for t in trades if t["side"] == "sell")
        
        if sell_volume == 0:
            return float("inf") if buy_volume > 0 else 1.0
        
        return buy_volume / sell_volume
    
    # ========== OFI 计算 ==========
    
    def _calculate_ofi(self):
        """计算 OFI (Order Flow Imbalance)"""
        # OFI = (ΔBidSize - ΔAskSize) / MidPrice
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        
        if best_bid and best_ask:
            mid_price = self.get_mid_price()
            
            # 简化版 OFI（实际应该使用增量）
            bid_depth = sum(size for size, _, _ in self.bids.values())
            ask_depth = sum(size for size, _, _ in self.asks.values())
            
            ofi = (bid_depth - ask_depth) / mid_price
            self.ofi_history.append(ofi)
    
    def get_ofi(self, window: int = 10) -> float:
        """
        获取 OFI（时间窗口平均）
        
        Args:
            window: 时间窗口（样本数）
        
        Returns:
            OFI 值
        """
        if len(self.ofi_history) < window:
            return 0.0
        
        return sum(list(self.ofi_history)[-window:]) / window
    
    def get_ofi_trend(self) -> str:
        """
        获取 OFI 趋势
        
        Returns:
            趋势 (rising/falling/stable)
        """
        if len(self.ofi_history) < 10:
            return "stable"
        
        recent = list(self.ofi_history)[-10:]
        
        # 计算斜率
        x = list(range(len(recent)))
        y = recent
        
        # 简单线性回归
        n = len(recent)
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi ** 2 for xi in x)
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x ** 2)
        
        if slope > 0.001:
            return "rising"
        elif slope < -0.001:
            return "falling"
        else:
            return "stable"
    
    # ========== 统计信息 ==========
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        best_bid = self.get_best_bid()
        best_ask = self.get_best_ask()
        
        return {
            "bids_count": len(self.bids),
            "asks_count": len(self.asks),
            "best_bid": best_bid[0] if best_bid else None,
            "best_ask": best_ask[0] if best_ask else None,
            "mid_price": self.get_mid_price(),
            "spread": self.get_spread(),
            "trades_count": len(self.trades),
            "update_count": self.update_count,
            "last_update": self.last_update_time,
            "buy_pressure": self.buy_pressure,
            "sell_pressure": self.sell_pressure,
            "ofi": self.get_ofi(),
            "ofi_trend": self.get_ofi_trend()
        }
    
    def reset(self):
        """重置存储"""
        self.bids.clear()
        self.asks.clear()
        self.sorted_bids.clear()
        self.sorted_asks.clear()
        self.trades.clear()
        self.ofi_history.clear()
        self.buy_pressure = 0.0
        self.sell_pressure = 0.0
        self.update_count = 0
        self.last_update_time = None
        
        logger.info("🔄 一级存储已重置")
