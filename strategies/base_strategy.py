"""
基础策略类
所有策略的基类
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, Optional, Callable
from datetime import datetime

from utils.logger import logger


class BaseStrategy(ABC):
    """策略基类"""
    
    def __init__(self, name: str):
        """
        初始化策略
        
        Args:
            name: 策略名称
        """
        self.name = name
        self.enabled = True
        self.signals_generated = 0
        self.signals_executed = 0
        
        # 回调函数
        self.on_signal_callback: Optional[Callable] = None
        
        logger.info(f"📊 策略初始化: {self.name}")
    
    @abstractmethod
    async def on_market_data(self, data: Dict):
        """
        处理市场数据
        
        Args:
            data: 市场数据
        """
        pass
    
    @abstractmethod
    async def on_orderbook(self, data: Dict):
        """
        处理深度数据
        
        Args:
            data: 深度数据
        """
        pass
    
    @abstractmethod
    async def on_trade(self, data: Dict):
        """
        处理成交数据
        
        Args:
            data: 成交数据
        """
        pass
    
    async def generate_signal(self, signal: Dict) -> bool:
        """
        生成交易信号
        
        Args:
            signal: 信号信息
        
        Returns:
            是否成功发送
        """
        self.signals_generated += 1
        
        logger.log_strategy_signal({
            "strategy": self.name,
            "timestamp": datetime.now().isoformat(),
            **signal
        })
        
        # 调用回调函数
        if self.on_signal_callback:
            try:
                await self.on_signal_callback(signal)
                self.signals_executed += 1
                return True
            except Exception as e:
                logger.error(f"❌ 信号回调失败: {e}")
                return False
        
        return False
    
    def set_signal_callback(self, callback: Callable):
        """
        设置信号回调函数
        
        Args:
            callback: 回调函数
        """
        self.on_signal_callback = callback
        logger.info(f"📝 策略 {self.name} 信号回调已设置")
    
    def enable(self):
        """启用策略"""
        self.enabled = True
        logger.info(f"✅ 策略 {self.name} 已启用")
    
    def disable(self):
        """禁用策略"""
        self.enabled = False
        logger.info(f"⏸️  策略 {self.name} 已禁用")
    
    def get_stats(self) -> Dict:
        """获取策略统计"""
        return {
            "name": self.name,
            "enabled": self.enabled,
            "signals_generated": self.signals_generated,
            "signals_executed": self.signals_executed,
            "execution_rate": self.signals_executed / self.signals_generated if self.signals_generated > 0 else 0
        }
    
    async def reset_stats(self):
        """重置统计"""
        self.signals_generated = 0
        self.signals_executed = 0
        logger.info(f"🔄 策略 {self.name} 统计已重置")
