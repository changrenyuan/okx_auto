#!/usr/bin/env python3
"""
GamblerHunter V2 - 赌徒猎手系统
基于市场微观结构的高频量化交易系统

核心能力：
1. 本地 OrderBook 维护 + Checksum 校验
2. 订单流分析（OFI、WMP、流动性真空）
3. 三种战术策略：抢跑、挂墙、点差捕获
4. 风险熔断系统（Kill Switch）
5. 三层存储架构（Hot/Warm/Cold）
"""

import asyncio
import signal
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import logger
from utils.config import Config
from core import WebSocketStreamer, ExecutionEngine, RiskKillSwitch
from orderbook import ProfessionalOrderBook as ProOrderBook, MicrostructureFeatures
from strategies import TacticalStrategies
from storage import StorageManager


class GamblerHunterV2:
    """赌徒猎手系统 V2"""
    
    def __init__(self):
        """初始化系统"""
        self.config = Config

        # 显示交易模式警告
        if Config.TRADING_MODE == "live":
            logger.critical("=" * 60)
            logger.critical("🚨🚨🚨 实盘交易模式 🚨🚨🚨")
            logger.critical("=" * 60)
            logger.critical("⚠️  当前将使用真实资金进行交易！")
            logger.critical("⚠️  请确保：")
            logger.critical("   1. 已充分测试策略")
            logger.critical("   2. 风险参数已设置")
            logger.critical("   3. 已设置止损")
            logger.critical("   4. 资金在可承受范围内")
            logger.critical("=" * 60)
        else:
            logger.info("=" * 60)
            logger.info("🧪 模拟交易模式")
            logger.info("=" * 60)
            logger.info("✓ 当前为模拟交易，不会使用真实资金")
            logger.info("=" * 60)

        # 存储管理器（三层存储架构）
        self.storage = StorageManager(
            redis_host="localhost",
            redis_port=6379,
            data_dir="data/historical",
            max_trades=1000
        )

        # 核心模块
        self.execution = ExecutionEngine()
        self.kill_switch = RiskKillSwitch(self.execution)
        
        # OrderBook 和特征提取
        self.orderbook = ProOrderBook(Config.DEFAULT_INST_ID)
        self.features = MicrostructureFeatures(Config.DEFAULT_INST_ID, self.orderbook)
        
        # 战略模块
        self.strategies = TacticalStrategies(
            self.orderbook,
            self.features,
            self.execution,
            self.kill_switch
        )
        
        # WebSocket 流
        self.streamer = WebSocketStreamer()
        
        # 运行状态
        self.running = False
        
        logger.info("🎮 GamblerHunter V2 初始化完成")
    
    async def start(self):
        """启动系统"""
        logger.info("🚀 启动 GamblerHunter V2...")
        
        # 启动执行引擎
        await self.execution.start()
        
        # 启动熔断系统
        await self.kill_switch.start()
        
        # 连接 WebSocket
        try:
            await self.streamer.connect()
            
            # 注册回调
            self.streamer.register_callback("orderbook", self._on_orderbook_data)
            self.streamer.register_callback("trades", self._on_trade_data)
            
            # 订阅频道
            await self.streamer.subscribe([
                {"channel": Config.WS_CHANNELS_BOOK, "instId": Config.DEFAULT_INST_ID},
                {"channel": Config.WS_CHANNELS_TRADE, "instId": Config.DEFAULT_INST_ID}
            ])
            
            # 启动监听任务
            asyncio.create_task(self.streamer.listen())
            
        except Exception as e:
            logger.error(f"❌ WebSocket 连接失败: {e}")
            logger.warning("⚠️  系统将在离线模式下运行（无法接收实时数据）")
        
        self.running = True
        logger.info("✅ GamblerHunter V2 已启动")
        
        # 运行主循环
        await self._run_loop()
    
    async def stop(self):
        """停止系统"""
        logger.info("🛑 停止 GamblerHunter V2...")
        self.running = False
        
        try:
            if self.streamer.ws:
                await self.streamer.close()
                logger.info("✅ WebSocket 已关闭")
        except Exception as e:
            logger.error(f"❌ 关闭 WebSocket 失败: {e}")
        
        # 最后一次同步到冷存储
        await self.storage.sync_to_cold()
        
        # 关闭存储
        self.storage.close()
        
        await self.kill_switch.stop()
        await self.execution.stop()
        
        logger.info("✅ GamblerHunter V2 已停止")
    
    async def _on_orderbook_data(self, data):
        """
        处理 OrderBook 数据回调
        
        Args:
            data: OrderBook 数据
        """
        if not self.kill_switch.is_safe():
            return
        
        try:
            # 处理 OrderBook 更新
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    # 更新 OrderBook
                    self.orderbook.update_snapshot(item)
                    
                    # 更新热存储（同步到内存）
                    if "bids" in item and "asks" in item:
                        for bid in item["bids"][:5]:  # 保存前5档
                            price = float(bid[0])
                            size = float(bid[1])
                            orders_count = int(bid[2]) if len(bid) > 2 else 0
                            self.storage.update_bid(price, size, orders_count)
                        
                        for ask in item["asks"][:5]:  # 保存前5档
                            price = float(ask[0])
                            size = float(ask[1])
                            orders_count = int(ask[2]) if len(ask) > 2 else 0
                            self.storage.update_ask(price, size, orders_count)
                
                # 运行策略
                await self.strategies.run()
        
        except Exception as e:
            logger.error(f"❌ 处理 OrderBook 异常: {e}")
    
    async def _on_trade_data(self, data):
        """
        处理逐笔成交回调
        
        Args:
            data: 逐笔成交数据
        """
        if not self.kill_switch.is_safe():
            return
        
        try:
            # 处理逐笔成交
            if isinstance(data, list) and len(data) > 0:
                for trade in data:
                    # 更新特征
                    self.features.update_trade(trade)
                    
                    # 更新热存储（同步到内存）
                    trade_data = {
                        "price": float(trade.get("px", 0)),
                        "size": float(trade.get("sz", 0)),
                        "side": trade.get("side", ""),
                        "timestamp": float(trade.get("ts", 0)) / 1000,  # 毫秒转秒
                        "trade_id": trade.get("tradeId", "")
                    }
                    self.storage.add_trade(trade_data)
                
                # 运行策略
                await self.strategies.run()
        
        except Exception as e:
            logger.error(f"❌ 处理逐笔成交异常: {e}")
    
    async def _run_loop(self):
        """主循环"""
        logger.info("📊 主循环已启动")
        
        # 冷存储同步计时器
        last_cold_sync = 0
        cold_sync_interval = 60  # 60秒同步一次
        
        while self.running:
            try:
                current_time = asyncio.get_event_loop().time()
                
                # 定期检查状态
                status = self.kill_switch.get_status()
                
                if status["triggered"]:
                    logger.critical(f"🚨 熔断触发: {status['reason']}")
                    break
                
                # 定期同步到冷存储
                if current_time - last_cold_sync > cold_sync_interval:
                    await self.storage.sync_to_cold()
                    last_cold_sync = current_time
                
                # 获取存储统计
                storage_stats = self.storage.get_stats()
                
                # 记录状态
                logger.info(
                    f"📊 系统状态 | "
                    f"亏损: {status['daily_loss']:.2%}/{status['max_loss']:.2%} | "
                    f"延迟: {status['avg_latency']:.1f}ms/{status['max_latency']}ms | "
                    f"成交: {storage_stats['hot']['trades_count']} | "
                    f"OFI: {storage_stats['hot']['ofi']:.4f} ({storage_stats['hot']['ofi_trend']})"
                )
                
                await asyncio.sleep(10)
            
            except Exception as e:
                logger.error(f"❌ 主循环异常: {e}")
                await asyncio.sleep(1)


async def main():
    """主函数"""
    # 创建系统实例
    hunter = GamblerHunterV2()
    
    # 设置信号处理
    def signal_handler(sig, frame):
        logger.info("收到退出信号，正在关闭系统...")
        asyncio.create_task(hunter.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 启动系统
        await hunter.start()
    
    except KeyboardInterrupt:
        logger.info("用户中断")
    
    except Exception as e:
        logger.critical(f"系统异常: {e}")
    
    finally:
        # 停止系统
        await hunter.stop()


if __name__ == "__main__":
    asyncio.run(main())
