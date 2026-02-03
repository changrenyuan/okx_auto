"""
专业级本地 OrderBook 维护
支持 Checksum 校验、增量更新、真空区检测
"""

import asyncio
import heapq
import zlib
from collections import defaultdict, deque
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import bisect

from utils.logger import logger


@dataclass
class OrderBookLevel:
    """订单簿层级"""
    price: float
    size: float
    orders_count: int = 0
    is_iceberg: bool = False  # 是否疑似冰山


@dataclass
class OrderBookFeatures:
    """订单簿特征"""
    # 基础指标
    best_bid: float = 0.0
    best_ask: float = 0.0
    mid_price: float = 0.0
    spread: float = 0.0
    spread_bps: float = 0.0
    
    # 深度指标
    bid_depth_5: float = 0.0  # 买一深度
    ask_depth_5: float = 0.0  # 卖一深度
    
    # OFI 指标
    ofi_1s: float = 0.0  # 1秒内的OFI
    ofi_5s: float = 0.0  # 5秒内的OFI
    
    # WMP 指标
    wmp: float = 0.0  # 加权中间价
    
    # 流动性真空
    liquidity_void_above: List[float] = None  # 上方真空区
    liquidity_void_below: List[float] = None  # 下方真空区
    
    # 订单流压力
    buy_pressure: float = 0.0
    sell_pressure: float = 0.0
    
    # 检测结果
    has_wall: bool = False  # 是否有墙
    wall_side: str = ""  # 墙的方向
    wall_price: float = 0.0  # 墙的价格
    wall_depth: float = 0.0  # 墙的深度


class ProfessionalOrderBook:
    """
    专业级本地 OrderBook 维护
    
    特性：
    - Checksum 校验（防止数据错误）
    - 增量更新（books-l2-tbt）
    - 真空区检测
    - 墙检测
    - OFI 计算
    - WMP 计算
    - 微秒级查询
    """
    
    def __init__(self, inst_id: str, max_levels: int = 400):
        """
        初始化订单簿
        
        Args:
            inst_id: 产品 ID
            max_levels: 最大深度层级
        """
        self.inst_id = inst_id
        self.max_levels = max_levels
        
        # 订单簿数据
        self.bids: Dict[float, OrderBookLevel] = {}  # price -> level
        self.asks: Dict[float, OrderBookLevel] = {}  # price -> level
        
        # 排序后的价格列表（用于快速查找）
        self.sorted_bids: List[float] = []  # 降序
        self.sorted_asks: List[float] = []  # 升序
        
        # 序列号和校验和
        self.sequence: int = -1
        self.checksum: int = 0
        
        # 历史数据（用于计算 OFI）
        self.bids_history: deque = deque(maxlen=100)  # 最近100次买一变化
        self.asks_history: deque = deque(maxlen=100)  # 最近100次卖一变化
        self.last_check_time: datetime = None
        
        # 特征缓存
        self.features: OrderBookFeatures = OrderBookFeatures()
        self.features.liquidity_void_above = []
        self.features.liquidity_void_below = []
        
        # 统计信息
        self.update_count: int = 0
        self.error_count: int = 0
        
        logger.debug(f"📚 专业订单簿初始化: {inst_id}")
    
    async def update_snapshot(self, data: Dict):
        """
        更新快照（完整覆盖）
        
        Args:
            data: 快照数据 {"bids": [...], "asks": [...], "checksum": 12345}
        """
        try:
            bids_data = data.get("bids", [])
            asks_data = data.get("asks", [])
            checksum = data.get("checksum", 0)
            
            # 清空旧数据
            self.bids.clear()
            self.asks.clear()
            self.sorted_bids.clear()
            self.sorted_asks.clear()
            
            # 更新买盘
            for level in bids_data:
                price = float(level[0])
                size = float(level[1])
                orders_count = int(level[2]) if len(level) > 2 else 0
                
                if size > 0:
                    self.bids[price] = OrderBookLevel(price, size, orders_count)
                    bisect.insort(self.sorted_bids, -price)  # 降序排列
                else:
                    if price in self.bids:
                        del self.bids[price]
            
            # 更新卖盘
            for level in asks_data:
                price = float(level[0])
                size = float(level[1])
                orders_count = int(level[2]) if len(level) > 2 else 0
                
                if size > 0:
                    self.asks[price] = OrderBookLevel(price, size, orders_count)
                    bisect.insort(self.sorted_asks, price)  # 升序排列
                else:
                    if price in self.asks:
                        del self.asks[price]
            
            # 验证校验和
            calculated_checksum = self._calculate_checksum()
            if calculated_checksum != checksum:
                logger.warning(f"⚠️  校验和不匹配: 计算={calculated_checksum}, 接收={checksum}")
                self.error_count += 1
            else:
                self.checksum = checksum
            
            self.update_count += 1
            logger.debug(f"📚 快照更新: {self.inst_id}, 买={len(self.bids)}, 卖={len(self.asks)}")
        
        except Exception as e:
            logger.error(f"❌ 更新快照失败: {e}")
            self.error_count += 1
    
    async def update_increment(self, data: Dict):
        """
        增量更新
        
        Args:
            data: 增量数据 {"bids": [...], "asks": [...], "checksum": 12345}
        """
        try:
            bids_data = data.get("bids", [])
            asks_data = data.get("asks", [])
            checksum = data.get("checksum", 0)
            
            # 更新买盘
            for level in bids_data:
                price = float(level[0])
                size = float(level[1])
                orders_count = int(level[2]) if len(level) > 2 else 0
                
                if size == 0:
                    # 删除
                    if price in self.bids:
                        del self.bids[price]
                        try:
                            self.sorted_bids.remove(-price)
                        except ValueError:
                            pass
                else:
                    # 更新或新增
                    if price not in self.bids:
                        bisect.insort(self.sorted_bids, -price)
                    self.bids[price] = OrderBookLevel(price, size, orders_count)
            
            # 更新卖盘
            for level in asks_data:
                price = float(level[0])
                size = float(level[1])
                orders_count = int(level[2]) if len(level) > 2 else 0
                
                if size == 0:
                    # 删除
                    if price in self.asks:
                        del self.asks[price]
                        try:
                            self.sorted_asks.remove(price)
                        except ValueError:
                            pass
                else:
                    # 更新或新增
                    if price not in self.asks:
                        bisect.insort(self.sorted_asks, price)
                    self.asks[price] = OrderBookLevel(price, size, orders_count)
            
            # 验证校验和
            calculated_checksum = self._calculate_checksum()
            if calculated_checksum != checksum:
                logger.error(f"❌ 校验和不匹配: 计算={calculated_checksum}, 接收={checksum}")
                self.error_count += 1
                # 校验和不匹配，需要重新同步
                return False
            else:
                self.checksum = checksum
            
            self.update_count += 1
            return True
        
        except Exception as e:
            logger.error(f"❌ 增量更新失败: {e}")
            self.error_count += 1
            return False
    
    def _calculate_checksum(self) -> int:
        """
        计算校验和
        
        OKX 算法：
        对前 25 档买盘和卖盘的 price 和 size 拼接，
        计算模 2^32 的 CRC32
        
        Returns:
            校验和
        """
        try:
            checksum_str = ""
            
            # 获取前 25 档买盘
            bids = self.get_bids(25)
            for price, size in bids:
                checksum_str += f"{price:.0f}:{size:.0f}:"
            
            # 获取前 25 档卖盘
            asks = self.get_asks(25)
            for price, size in asks:
                checksum_str += f"{price:.0f}:{size:.0f}:"
            
            # 计算 CRC32
            checksum = zlib.crc32(checksum_str.encode()) & 0xFFFFFFFF
            
            return checksum
        
        except Exception as e:
            logger.error(f"❌ 计算校验和失败: {e}")
            return 0
    
    def get_bids(self, levels: int = 10) -> List[Tuple[float, float]]:
        """
        获取买盘（前N档）
        
        Args:
            levels: 档位数
        
        Returns:
            [(price, size), ...]
        """
        try:
            result = []
            for i in range(min(levels, len(self.sorted_bids))):
                price = -self.sorted_bids[i]
                if price in self.bids:
                    size = self.bids[price].size
                    result.append((price, size))
            return result
        
        except Exception as e:
            logger.error(f"❌ 获取买盘失败: {e}")
            return []
    
    def get_asks(self, levels: int = 10) -> List[Tuple[float, float]]:
        """
        获取卖盘（前N档）
        
        Args:
            levels: 档位数
        
        Returns:
            [(price, size), ...]
        """
        try:
            result = []
            for i in range(min(levels, len(self.sorted_asks))):
                price = self.sorted_asks[i]
                if price in self.asks:
                    size = self.asks[price].size
                    result.append((price, size))
            return result
        
        except Exception as e:
            logger.error(f"❌ 获取卖盘失败: {e}")
            return []
    
    def get_best_bid(self) -> Tuple[float, float]:
        """获取买一"""
        if self.sorted_bids:
            price = -self.sorted_bids[0]
            if price in self.bids:
                size = self.bids[price].size
                return (price, size)
        return (0.0, 0.0)
    
    def get_best_ask(self) -> Tuple[float, float]:
        """获取卖一"""
        if self.sorted_asks:
            price = self.sorted_asks[0]
            if price in self.asks:
                size = self.asks[price].size
                return (price, size)
        return (0.0, 0.0)
    
    def get_mid_price(self) -> float:
        """获取中间价"""
        bid_price, _ = self.get_best_bid()
        ask_price, _ = self.get_best_ask()
        
        if bid_price > 0 and ask_price > 0:
            return (bid_price + ask_price) / 2.0
        elif bid_price > 0:
            return bid_price
        elif ask_price > 0:
            return ask_price
        else:
            return 0.0
    
    def get_wmp(self) -> float:
        """
        获取加权中间价（Weighted Mid Price）
        
        公式：Price = (BidPx * AskSize + AskPx * BidSize) / (AskSize + BidSize)
        
        Returns:
            加权中间价
        """
        try:
            bid_price, bid_size = self.get_best_bid()
            ask_price, ask_size = self.get_best_ask()
            
            if bid_size == 0 and ask_size == 0:
                return self.get_mid_price()
            
            wmp = (bid_price * ask_size + ask_price * bid_size) / (ask_size + bid_size)
            return wmp
        
        except Exception as e:
            logger.error(f"❌ 计算 WMP 失败: {e}")
            return self.get_mid_price()
    
    def get_spread(self) -> float:
        """获取点差"""
        bid_price, _ = self.get_best_bid()
        ask_price, _ = self.get_best_ask()
        
        if bid_price > 0 and ask_price > 0:
            return ask_price - bid_price
        else:
            return 0.0
    
    def get_spread_bps(self) -> float:
        """获取点差（基点）"""
        spread = self.get_spread()
        mid_price = self.get_mid_price()
        
        if mid_price > 0:
            return (spread / mid_price) * 10000
        else:
            return 0.0
    
    def calculate_ofi(self, timeframe: str = "1s") -> float:
        """
        计算 Order Flow Imbalance（订单流不平衡）
        
        公式：OFI = Σ(change in bid depth) - Σ(change in ask depth)
        
        Args:
            timeframe: 时间窗口 (1s/5s)
        
        Returns:
            OFI 值
        """
        try:
            # 简化版：使用买一和卖一的深度变化
            bid_price, bid_size = self.get_best_bid()
            ask_price, ask_size = self.get_best_ask()
            
            current_time = datetime.now()
            
            # 记录当前状态
            self.bids_history.append({
                "price": bid_price,
                "size": bid_size,
                "time": current_time
            })
            self.asks_history.append({
                "price": ask_price,
                "size": ask_size,
                "time": current_time
            })
            
            # 计算时间窗口内的 OFI
            if timeframe == "1s":
                window = 1.0
            else:
                window = 5.0
            
            # 过滤时间窗口内的数据
            recent_bids = [b for b in self.bids_history 
                          if (current_time - b["time"]).total_seconds() <= window]
            recent_asks = [a for a in self.asks_history 
                          if (current_time - a["time"]).total_seconds() <= window]
            
            if len(recent_bids) < 2 or len(recent_asks) < 2:
                return 0.0
            
            # 计算变化
            bid_change = recent_bids[-1]["size"] - recent_bids[0]["size"]
            ask_change = recent_asks[-1]["size"] - recent_asks[0]["size"]
            
            ofi = bid_change - ask_change
            
            return ofi
        
        except Exception as e:
            logger.error(f"❌ 计算 OFI 失败: {e}")
            return 0.0
    
    def detect_liquidity_void(
        self,
        direction: str = "both",
        threshold: float = 0.002,
        max_gap_levels: int = 5
    ) -> List[Tuple[float, float]]:
        """
        检测流动性真空区
        
        Args:
            direction: 方向 (both/above/below)
            threshold: 真空阈值（价格比例）
            max_gap_levels: 最大缺口档位数
        
        Returns:
            [(start_price, end_price), ...]
        """
        try:
            voids = []
            
            mid_price = self.get_mid_price()
            
            if direction in ["above", "both"]:
                # 检测上方真空
                asks = self.get_asks(50)
                for i in range(len(asks) - 1):
                    current_price = asks[i][0]
                    next_price = asks[i+1][0]
                    
                    gap_ratio = (next_price - current_price) / current_price
                    
                    if gap_ratio > threshold:
                        voids.append((current_price, next_price))
                        logger.debug(f"🕳️  上方真空区: {current_price} -> {next_price}, 比例={gap_ratio*100:.2f}%")
            
            if direction in ["below", "both"]:
                # 检测下方真空
                bids = self.get_bids(50)
                for i in range(len(bids) - 1):
                    current_price = bids[i][0]
                    next_price = bids[i+1][0]
                    
                    gap_ratio = (current_price - next_price) / current_price
                    
                    if gap_ratio > threshold:
                        voids.append((next_price, current_price))
                        logger.debug(f"🕳️  下方真空区: {next_price} -> {current_price}, 比例={gap_ratio*100:.2f}%")
            
            return voids
        
        except Exception as e:
            logger.error(f"❌ 检测流动性真空失败: {e}")
            return []
    
    def detect_wall(
        self,
        min_depth: float = 100.0,
        levels: int = 20
    ) -> Optional[Dict]:
        """
        检测墙（大额挂单）
        
        Args:
            min_depth: 最小深度阈值
            levels: 检查档位数
        
        Returns:
            {"side": "bid"/"ask", "price": price, "depth": depth} 或 None
        """
        try:
            # 检查买盘
            bids = self.get_bids(levels)
            for price, size in bids:
                if size >= min_depth:
                    return {
                        "side": "bid",
                        "price": price,
                        "depth": size
                    }
            
            # 检查卖盘
            asks = self.get_asks(levels)
            for price, size in asks:
                if size >= min_depth:
                    return {
                        "side": "ask",
                        "price": price,
                        "depth": size
                    }
            
            return None
        
        except Exception as e:
            logger.error(f"❌ 检测墙失败: {e}")
            return None
    
    def calculate_features(self) -> OrderBookFeatures:
        """
        计算所有特征
        
        Returns:
            特征对象
        """
        try:
            features = OrderBookFeatures()
            
            # 基础指标
            features.best_bid, features.bid_depth_5 = self.get_best_bid()
            features.best_ask, features.ask_depth_5 = self.get_best_ask()
            features.mid_price = self.get_mid_price()
            features.spread = self.get_spread()
            features.spread_bps = self.get_spread_bps()
            features.wmp = self.get_wmp()
            
            # OFI
            features.ofi_1s = self.calculate_ofi("1s")
            features.ofi_5s = self.calculate_ofi("5s")
            
            # 流动性真空
            voids = self.detect_liquidity_void("both", 0.002, 5)
            features.liquidity_void_above = [v for v in voids if v[0] < v[1]]
            features.liquidity_void_below = [v for v in voids if v[0] > v[1]]
            
            # 墙检测
            wall = self.detect_wall(min_depth=50.0)
            if wall:
                features.has_wall = True
                features.wall_side = wall["side"]
                features.wall_price = wall["price"]
                features.wall_depth = wall["depth"]
            
            # 压力计算
            features.buy_pressure = features.ofi_1s if features.ofi_1s > 0 else 0
            features.sell_pressure = abs(features.ofi_1s) if features.ofi_1s < 0 else 0
            
            self.features = features
            
            return features
        
        except Exception as e:
            logger.error(f"❌ 计算特征失败: {e}")
            return OrderBookFeatures()
    
    def get_summary(self) -> Dict:
        """获取订单簿摘要"""
        try:
            features = self.calculate_features()
            
            return {
                "inst_id": self.inst_id,
                "best_bid": features.best_bid,
                "best_ask": features.best_ask,
                "mid_price": features.mid_price,
                "wmp": features.wmp,
                "spread": features.spread,
                "spread_bps": features.spread_bps,
                "ofi_1s": features.ofi_1s,
                "ofi_5s": features.ofi_5s,
                "has_wall": features.has_wall,
                "wall_price": features.wall_price,
                "wall_depth": features.wall_depth,
                "liquidity_voids": len(features.liquidity_void_above) + len(features.liquidity_void_below),
                "sequence": self.sequence,
                "checksum": self.checksum,
                "update_count": self.update_count,
                "error_count": self.error_count,
            }
        
        except Exception as e:
            logger.error(f"❌ 获取摘要失败: {e}")
            return {}


class ProfessionalOrderBookManager:
    """专业订单簿管理器"""
    
    def __init__(self):
        """初始化管理器"""
        self.orderbooks: Dict[str, ProfessionalOrderBook] = {}
        logger.info("📚 专业订单簿管理器初始化完成")
    
    def get_or_create(self, inst_id: str) -> ProfessionalOrderBook:
        """获取或创建订单簿"""
        if inst_id not in self.orderbooks:
            self.orderbooks[inst_id] = ProfessionalOrderBook(inst_id)
            logger.info(f"📚 创建专业订单簿: {inst_id}")
        
        return self.orderbooks[inst_id]
    
    def remove(self, inst_id: str):
        """移除订单簿"""
        if inst_id in self.orderbooks:
            del self.orderbooks[inst_id]
            logger.info(f"📚 移除专业订单簿: {inst_id}")


# 全局管理器
pro_orderbook_manager = ProfessionalOrderBookManager()


if __name__ == "__main__":
    # 测试专业订单簿
    async def test():
        ob = ProfessionalOrderBook("BTC-USDT")
        
        # 更新快照
        snapshot = {
            "bids": [
                [50000, "10", "5"],
                [49995, "20", "10"],
                [49990, "30", "15"],
            ],
            "asks": [
                [50010, "5", "3"],
                [50015, "15", "8"],
                [50020, "25", "12"],
            ],
            "checksum": 12345
        }
        
        await ob.update_snapshot(snapshot)
        
        # 计算特征
        features = ob.calculate_features()
        
        print("摘要:", ob.get_summary())
        print("WMP:", ob.get_wmp())
        print("OFI (1s):", ob.calculate_ofi("1s"))
        print("流动性真空:", ob.detect_liquidity_void())
        print("墙检测:", ob.detect_wall())
    
    asyncio.run(test())
