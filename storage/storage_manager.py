"""
存储管理器
统一管理三层存储架构

职责：
- 统一存储接口
- 数据同步策略
- 存储路由和缓存管理
"""

from typing import Optional, Dict, List, Any
from datetime import datetime

from storage.hot_storage import HotStorageLayer
from storage.warm_storage import WarmStorageLayer
from storage.cold_storage import ColdStorageLayer
from utils.logger import logger


class StorageManager:
    """
    存储管理器 - 统一管理三层存储
    
    存储层次：
    1. 热存储 (Hot): RAM - < 1ms - Order Book、成交流
    2. 温存储 (Warm): Redis - 1-5ms - 账户状态、持仓
    3. 冷存储 (Cold): Disk - 磁盘IO - 历史数据、回测
    """
    
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        data_dir: str = "data/historical",
        max_trades: int = 1000,
        key_prefix: str = "okx_quant:"
    ):
        """
        初始化存储管理器
        
        Args:
            redis_host: Redis 主机
            redis_port: Redis 端口
            data_dir: 数据目录
            max_trades: 最大成交笔数
            key_prefix: Redis 键前缀
        """
        # 初始化三层存储
        self.hot = HotStorageLayer(max_trades=max_trades)
        self.warm = WarmStorageLayer(
            host=redis_host,
            port=redis_port,
            key_prefix=key_prefix
        )
        self.cold = ColdStorageLayer(data_dir=data_dir)
        
        # 配置
        self.auto_save_to_cold = True
        self.cold_save_interval = 60  # 秒
        
        # 状态
        self.running = False
        
        logger.info("📦 存储管理器初始化完成")
        logger.info(f"  - 热存储 (RAM): {max_trades} 笔成交")
        logger.info(f"  - 温存储 (Redis): {redis_host}:{redis_port}")
        logger.info(f"  - 冷存储: {data_dir}")
    
    # ========== Order Book 操作 ==========
    
    def update_bid(self, price: float, size: float, orders_count: int = 0):
        """
        更新买盘（热存储）
        
        Args:
            price: 价格
            size: 数量
            orders_count: 订单数
        """
        self.hot.update_bid(price, size, orders_count)
    
    def update_ask(self, price: float, size: float, orders_count: int = 0):
        """
        更新卖盘（热存储）
        
        Args:
            price: 价格
            size: 数量
            orders_count: 订单数
        """
        self.hot.update_ask(price, size, orders_count)
    
    def get_best_bid(self) -> Optional[tuple]:
        """获取买一"""
        return self.hot.get_best_bid()
    
    def get_best_ask(self) -> Optional[tuple]:
        """获取卖一"""
        return self.hot.get_best_ask()
    
    def get_mid_price(self) -> Optional[float]:
        """获取中间价"""
        return self.hot.get_mid_price()
    
    def get_spread(self) -> Optional[float]:
        """获取点差"""
        return self.hot.get_spread()
    
    def get_depth_at_price(self, price: float, side: str) -> float:
        """获取指定价格的深度"""
        return self.hot.get_depth_at_price(price, side)
    
    # ========== 成交操作 ==========
    
    def add_trade(self, trade: dict):
        """
        添加成交（热存储）
        
        Args:
            trade: 成交数据
        """
        self.hot.add_trade(trade)
    
    def get_recent_trades(self, n: int = 10) -> List[dict]:
        """获取最近 n 笔成交"""
        return self.hot.get_recent_trades(n)
    
    def get_trades_in_window(self, seconds: float) -> List[dict]:
        """获取指定时间窗口内的成交"""
        return self.hot.get_trades_in_window(seconds)
    
    def get_buy_sell_ratio(self, window_seconds: float = 1.0) -> float:
        """获取买卖比例"""
        return self.hot.get_buy_sell_ratio(window_seconds)
    
    # ========== OFI 指标 ==========
    
    def get_ofi(self, window: int = 10) -> float:
        """获取 OFI"""
        return self.hot.get_ofi(window)
    
    def get_ofi_trend(self) -> str:
        """获取 OFI 趋势"""
        return self.hot.get_ofi_trend()
    
    # ========== 账户状态（温存储）==========
    
    def set_balance(self, ccy: str, balance: float):
        """设置账户余额"""
        self.warm.set_balance(ccy, balance)
    
    def get_balance(self, ccy: str) -> float:
        """获取账户余额"""
        return self.warm.get_balance(ccy)
    
    def set_position(self, inst_id: str, side: str, size: float, avg_price: float):
        """设置持仓"""
        self.warm.set_position(inst_id, side, size, avg_price)
    
    def get_position(self, inst_id: str) -> Optional[dict]:
        """获取持仓"""
        return self.warm.get_position(inst_id)
    
    def get_all_positions(self) -> Dict[str, dict]:
        """获取所有持仓"""
        return self.warm.get_all_positions()
    
    def delete_position(self, inst_id: str):
        """删除持仓"""
        self.warm.delete_position(inst_id)
    
    # ========== 风控参数（温存储）==========
    
    def set_risk_param(self, name: str, value: Any):
        """设置风控参数"""
        self.warm.set_risk_param(name, value)
    
    def get_risk_param(self, name: str, default: Any = None) -> Any:
        """获取风控参数"""
        return self.warm.get_risk_param(name, default)
    
    def set_daily_pnl(self, value: float):
        """设置当日盈亏"""
        self.warm.set_daily_pnl(value)
    
    def get_daily_pnl(self) -> float:
        """获取当日盈亏"""
        return self.warm.get_daily_pnl()
    
    # ========== 全局开关（温存储）==========
    
    def set_global_switch(self, name: str, enabled: bool):
        """设置全局开关"""
        self.warm.set_global_switch(name, enabled)
    
    def get_global_switch(self, name: str, default: bool = False) -> bool:
        """获取全局开关"""
        return self.warm.get_global_switch(name, default)
    
    def is_trading_allowed(self) -> bool:
        """检查是否允许交易"""
        return self.warm.is_trading_allowed()
    
    def enable_trading(self):
        """启用交易"""
        self.warm.enable_trading()
    
    def disable_trading(self):
        """禁用交易"""
        self.warm.disable_trading()
    
    # ========== 历史数据（冷存储）==========
    
    def save_orderbook_snapshot(
        self,
        inst_id: str,
        timestamp: datetime,
        bids: List[tuple],
        asks: List[tuple]
    ):
        """保存 Order Book 快照"""
        self.cold.save_orderbook_snapshot(inst_id, timestamp, bids, asks)
    
    def load_orderbook_snapshot(
        self,
        inst_id: str,
        date: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ):
        """加载 Order Book 快照"""
        return self.cold.load_orderbook_snapshot(inst_id, date, start_time, end_time)
    
    def save_trades(self, inst_id: str, trades: List[dict]):
        """保存成交数据"""
        self.cold.save_trades(inst_id, trades)
    
    def load_trades(self, inst_id: str, start_date: str, end_date: str):
        """加载成交数据"""
        return self.cold.load_trades(inst_id, start_date, end_date)
    
    def save_ohlcv(self, inst_id: str, ohlcv_data):
        """保存 OHLCV 数据"""
        self.cold.save_ohlcv(inst_id, ohlcv_data)
    
    def load_ohlcv(self, inst_id: str, start_date: str, end_date: str):
        """加载 OHLCV 数据"""
        return self.cold.load_ohlcv(inst_id, start_date, end_date)
    
    # ========== 分布式锁（温存储）==========
    
    def acquire_lock(self, lock_name: str, timeout: int = 10) -> bool:
        """获取分布式锁"""
        return self.warm.acquire_lock(lock_name, timeout)
    
    def release_lock(self, lock_name: str):
        """释放分布式锁"""
        self.warm.release_lock(lock_name)
    
    # ========== 统计信息 ==========
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "hot": self.hot.get_stats(),
            "warm": self.warm.get_stats(),
            "cold": self.cold.get_storage_size()
        }
    
    # ========== 数据同步 ==========
    
    async def sync_to_cold(self):
        """同步数据到冷存储"""
        try:
            # 保存 Order Book 快照
            best_bid = self.hot.get_best_bid()
            best_ask = self.hot.get_best_ask()
            
            if best_bid and best_ask:
                bids = [
                    (price, self.hot.get_depth_at_price(price, "bid"))
                    for price in self.hot.sorted_bids[:10]
                ]
                asks = [
                    (price, self.hot.get_depth_at_price(price, "ask"))
                    for price in self.hot.sorted_asks[:10]
                ]
                
                self.save_orderbook_snapshot(
                    inst_id="BTC-USDT-SWAP",
                    timestamp=datetime.now(),
                    bids=bids,
                    asks=asks
                )
            
            # 保存成交数据
            trades = list(self.hot.trades)
            if trades:
                self.save_trades("BTC-USDT-SWAP", trades)
            
            logger.debug("💾 数据已同步到冷存储")
        
        except Exception as e:
            logger.error(f"❌ 同步到冷存储失败: {e}")
    
    def reset(self):
        """重置存储"""
        self.hot.reset()
        logger.info("🔄 存储管理器已重置")
    
    def close(self):
        """关闭存储"""
        self.warm.close()
        logger.info("🔌 存储管理器已关闭")
