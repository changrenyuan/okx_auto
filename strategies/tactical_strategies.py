"""
战术策略模块
针对赌徒的三种战术
"""

from typing import Optional, Dict, List
from strategies.base_strategy import BaseStrategy
from orderbook.pro_orderbook import ProfessionalOrderBook
from orderbook.microstructure_features import MicrostructureFeatures
from utils.logger import logger
import asyncio


class TacticalStrategies:
    """
    战术策略管理器
    管理三种战术策略
    """
    
    def __init__(
        self,
        orderbook: ProfessionalOrderBook,
        features: MicrostructureFeatures,
        execution,  # ExecutionEngine
        kill_switch  # RiskKillSwitch
    ):
        """
        初始化战术策略管理器
        
        Args:
            orderbook: 专业订单簿
            features: 微观结构特征提取器
            execution: 执行引擎
            kill_switch: 风险熔断系统
        """
        self.orderbook = orderbook
        self.features = features
        self.execution = execution
        self.kill_switch = kill_switch
        
        # 初始化三个策略
        self.front_running = FrontRunningStrategy(orderbook, features)
        self.wall_riding = WallRidingStrategy(orderbook, features)
        self.spread_capturing = SpreadCapturingStrategy(orderbook, features)
        
        # 运行状态
        self.running = False
        
        logger.info("🎯 战术策略管理器初始化完成")

    async def run(self):
        """运行所有策略"""
        if not self.kill_switch.is_safe():
            return

        try:
            # 获取深度数据
            orderbook_data = self.orderbook.get_summary()

            if not orderbook_data:
                return

            inst_id = orderbook_data.get("inst_id", "")

            # 运行抢跑策略
            await self.front_running.on_depth(inst_id, orderbook_data)

            # 运行挂墙策略
            await self.wall_riding.on_depth(inst_id, orderbook_data)
            
            # 运行点差捕获策略
            await self.spread_capturing.on_depth(inst_id, orderbook_data)
        
        except Exception as e:
            logger.error(f"❌ 战术策略运行异常: {e}")
    
    async def start(self):
        """启动策略"""
        self.running = True
        logger.info("🚀 战术策略已启动")
    
    async def stop(self):
        """停止策略"""
        self.running = False
        logger.info("🛑 战术策略已停止")


class FrontRunningStrategy(BaseStrategy):
    """
    抢跑策略（Front Running）
    
    战术逻辑：
    1. 监测 Order Book 的买方深度突然断崖式下跌（撤单）
    2. 同时出现大额市价卖单
    3. 判断：赌徒在恐慌
    4. 行动：在他们砸盘之前，瞬间市价做空
    """
    
    def __init__(self, orderbook, features):
        """
        初始化抢跑策略
        
        Args:
            orderbook: 订单簿
            features: 特征提取器
        """
        super().__init__("抢跑策略")
        
        self.orderbook = orderbook
        self.features = features
        
        # 配置
        self.depth_drop_threshold = 0.5  # 深度下降阈值（50%）
        self.large_trade_threshold = 10.0  # 大单阈值
        
        # 状态
        self.bid_depth_history = []
        self.ask_depth_history = []
        
        logger.info(f"🏃 抢跑策略初始化")
        logger.info(f"   - 深度下降阈值: {self.depth_drop_threshold * 100}%")
        logger.info(f"   - 大单阈值: {self.large_trade_threshold}")
    
    async def on_market_data(self, data: dict):
        """处理行情数据"""
        pass
    
    async def on_orderbook(self, data: dict):
        """处理深度数据"""
        pass
    
    async def on_trade(self, data: dict):
        """
        处理成交数据
        
        检测大额市价单和深度撤单
        """
        try:
            if not data:
                return
            
            trade = data[0] if isinstance(data, list) else data
            inst_id = trade.get("instId", "")
            
            # 检查是否是大额市价单
            size = float(trade.get("sz", 0))
            side = trade.get("side", "")
            
            if size >= self.large_trade_threshold:
                logger.warning(f"🏃 检测到大额市价单: {side} {size} {inst_id}")
                
                # 检查对应方向深度是否突然下降
                if side == "buy":
                    # 大额买单，检查买方深度
                    pass
                else:
                    # 大额卖单，检查卖方深度
                    pass
        
        except Exception as e:
            logger.error(f"❌ 抢跑策略处理成交失败: {e}")
    
    def check_depth_drop(self, current_depth: float, prev_depth: float) -> bool:
        """检查深度是否突然下降"""
        if prev_depth == 0:
            return False
        
        drop_ratio = (prev_depth - current_depth) / prev_depth
        return drop_ratio >= self.depth_drop_threshold


class WallRidingStrategy(BaseStrategy):
    """
    挂墙策略（Wall Riding）
    
    战术逻辑：
    1. 识别出 Bid 10 处有一堵巨大的"真实买墙"（长期存在，未撤单）
    2. 在 Bid 9 挂单买入
    3. 赌徒市价砸盘砸不穿墙，价格会反弹
    4. 吃个反弹就跑
    """
    
    def __init__(self, orderbook, features):
        """
        初始化挂墙策略
        
        Args:
            orderbook: 订单簿
            features: 特征提取器
        """
        super().__init__("挂墙策略")
        
        self.orderbook = orderbook
        self.features = features
        
        # 配置
        self.wall_depth_threshold = 100.0  # 墙的深度阈值
        self.wall_persistence_time = 5  # 墙持续存在时间（秒）
        self.ride_offset = 1  # 挂单距离墙的档位数
        
        # 状态
        self.walls: Dict[str, Dict] = {}  # {inst_id: {price: time}}
        
        logger.info(f"🧱 挂墙策略初始化")
        logger.info(f"   - 墙深度阈值: {self.wall_depth_threshold}")
        logger.info(f"   - 墙持续时间: {self.wall_persistence_time}s")
    
    async def on_market_data(self, data: dict):
        """处理行情数据"""
        pass
    
    async def on_orderbook(self, data: dict):
        """
        处理深度数据
        
        检测墙的存在
        """
        try:
            if not data:
                return
            
            orderbook = data[0] if isinstance(data, list) else data
            inst_id = orderbook.get("instId", "")
            
            # 检查买盘是否有墙
            bids = orderbook.get("bids", [])
            
            for i, level in enumerate(bids[:20]):  # 检查前20档
                price = float(level[0])
                depth = float(level[1])
                
                if depth >= self.wall_depth_threshold:
                    # 检测到墙
                    if inst_id not in self.walls:
                        self.walls[inst_id] = {}
                    
                    if price not in self.walls[inst_id]:
                        self.walls[inst_id][price] = {
                            "first_seen": datetime.now(),
                            "last_seen": datetime.now(),
                            "depth": depth
                        }
                        logger.info(f"🧱 检测到墙: {inst_id} @ {price}, 深度={depth}")
                    else:
                        # 更新最后见到时间
                        self.walls[inst_id][price]["last_seen"] = datetime.now()
            
            # 检查墙是否消失
            current_time = datetime.now()
            if inst_id in self.walls:
                for price, wall_info in list(self.walls[inst_id].items()):
                    persistence = (current_time - wall_info["last_seen"]).total_seconds()
                    
                    if persistence > 2:  # 2秒未见到，认为墙消失了
                        del self.walls[inst_id][price]
                        logger.info(f"🧱 墙消失: {inst_id} @ {price}")
        
        except Exception as e:
            logger.error(f"❌ 挂墙策略处理深度失败: {e}")
    
    async def on_trade(self, data: dict):
        """处理成交数据"""
        pass
    
    def can_ride_wall(self, inst_id: str) -> Optional[Dict]:
        """
        检查是否可以挂墙
        
        Args:
            inst_id: 产品 ID
        
        Returns:
            {"wall_price": price, "ride_price": price} 或 None
        """
        try:
            if inst_id not in self.walls or not self.walls[inst_id]:
                return None
            
            current_time = datetime.now()
            
            # 检查是否有持续存在的墙
            for price, wall_info in self.walls[inst_id].items():
                persistence = (current_time - wall_info["first_seen"]).total_seconds()
                
                if persistence >= self.wall_persistence_time:
                    # 这是一个真实的墙，可以挂
                    return {
                        "wall_price": price,
                        "ride_price": price * (1 + 0.001),  # 在墙上方 0.1%
                        "wall_depth": wall_info["depth"],
                        "persistence": persistence
                    }
            
            return None
        
        except Exception as e:
            logger.error(f"❌ 检查是否可挂墙失败: {e}")
            return None


class SpreadCapturingStrategy(BaseStrategy):
    """
    点差捕获策略（Spread Capturing）
    
    战术逻辑：
    1. 极端行情下，Spread 拉大到 0.5% 以上
    2. 同时挂 Ask 1 和 Bid 1，做市商策略
    3. 双向吃赌徒的市价单
    """
    
    def __init__(self, orderbook, features):
        """
        初始化点差捕获策略
        
        Args:
            orderbook: 订单簿
            features: 特征提取器
        """
        super().__init__("点差捕获策略")
        
        self.orderbook = orderbook
        self.features = features
        
        # 配置
        self.min_spread_bps = 50  # 最小点差 0.5%
        self.max_spread_bps = 200  # 最大点差 2%
        self.position_size = 0.01  # 仓位大小
        
        # 状态
        self.active_spreads: Dict[str, Dict] = {}
        
        logger.info(f"📏 点差捕获策略初始化")
        logger.info(f"   - 最小点差: {self.min_spread_bps} bps ({self.min_spread_bps/100}%)")
        logger.info(f"   - 最大点差: {self.max_spread_bps} bps ({self.max_spread_bps/100}%)")
    
    async def on_market_data(self, data: dict):
        """处理行情数据"""
        pass
    
    async def on_orderbook(self, data: dict):
        """
        处理深度数据
        
        检测大点差并做市
        """
        try:
            if not data:
                return
            
            orderbook = data[0] if isinstance(data, list) else data
            inst_id = orderbook.get("instId", "")
            
            # 获取买一卖一
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            
            if not bids or not asks:
                return
            
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            
            # 计算点差
            spread = best_ask - best_bid
            mid_price = (best_bid + best_ask) / 2
            spread_bps = (spread / mid_price) * 10000
            
            # 检查点差是否足够大
            if self.min_spread_bps <= spread_bps <= self.max_spread_bps:
                logger.info(f"📏 检测到大点差: {inst_id}, {spread_bps:.1f} bps ({spread_bps/100:.2f}%)")
                
                # 生成做市信号
                await self._generate_market_making_signal(
                    inst_id, best_bid, best_ask, spread_bps
                )
        
        except Exception as e:
            logger.error(f"❌ 点差捕获策略处理深度失败: {e}")
    
    async def _generate_market_making_signal(
        self,
        inst_id: str,
        best_bid: float,
        best_ask: float,
        spread_bps: float
    ):
        """
        生成做市信号
        
        Args:
            inst_id: 产品 ID
            best_bid: 买一
            best_ask: 卖一
            spread_bps: 点差（基点）
        """
        try:
            signal = {
                "type": "SPREAD_CAPTURING",
                "action": "market_making",
                "instId": inst_id,
                "bid_price": best_bid,
                "ask_price": best_ask,
                "spread_bps": spread_bps,
                "size": self.position_size,
                "confidence": 0.8,
                "reason": f"点差扩大至 {spread_bps/100:.2f}%，做市套利"
            }
            
            logger.info(f"📏 生成点差捕获信号: {inst_id}, 点差={spread_bps/100:.2f}%")
            
            # 发送信号
            await self.generate_signal(signal)
        
        except Exception as e:
            logger.error(f"❌ 生成点差捕获信号失败: {e}")
    
    async def on_trade(self, data: dict):
        """处理成交数据"""
        pass


# 导出策略
__all__ = [
    "TacticalStrategies",
    "FrontRunningStrategy",
    "WallRidingStrategy",
    "SpreadCapturingStrategy"
]
