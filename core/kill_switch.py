"""
风险熔断系统（Kill Switch）
实时监控网络延迟、亏损幅度，自动熔断
"""

import asyncio
from typing import Optional
from datetime import datetime
import time

from utils.logger import logger
from utils.config import Config


class RiskKillSwitch:
    """风险熔断系统"""
    
    def __init__(self, execution_engine):
        """
        初始化风险熔断系统
        
        Args:
            execution_engine: 执行引擎实例
        """
        self.execution = execution_engine
        
        # 熔断参数
        self.max_daily_loss_ratio = 0.05  # 最大日亏损 5%
        self.max_position_ratio = 0.5     # 最大仓位 50%
        self.max_latency_ms = 100         # 最大网络延迟 100ms
        
        # 状态
        self.is_triggered = False
        self.trigger_reason = ""
        self.trigger_time = None
        
        # 数据
        self.daily_start_balance = 0.0
        self.current_balance = 0.0
        self.latency_samples = []
        
        # 运行状态
        self.running = False
        self.monitor_task = None
        
        logger.info("🛡️  风险熔断系统初始化完成")
    
    async def start(self):
        """启动熔断监控"""
        if self.running:
            logger.warning("⚠️  熔断系统已在运行")
            return
        
        logger.info("🚀 启动风险熔断系统...")
        
        # 获取初始余额
        balance_data = await self.execution.get_balance()
        if balance_data:
            self.daily_start_balance = float(balance_data["details"][0]["eq"])
            self.current_balance = self.daily_start_balance
            logger.info(f"📊 初始余额: {self.daily_start_balance}")
        
        self.running = True
        self.monitor_task = asyncio.create_task(self._monitor_loop())
        
        logger.info("✅ 风险熔断系统已启动")
    
    async def stop(self):
        """停止熔断监控"""
        logger.info("🛑 停止风险熔断系统...")
        self.running = False
        
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        logger.info("✅ 风险熔断系统已停止")
    
    async def _monitor_loop(self):
        """监控循环"""
        logger.info("👀 风险监控任务已启动")
        
        while self.running:
            try:
                if self.is_triggered:
                    logger.warning("⚠️  熔断已触发，等待手动恢复")
                    await asyncio.sleep(10)
                    continue
                
                # 更新数据
                await self._update_data()
                
                # 检查熔断条件
                await self._check_conditions()
                
                await asyncio.sleep(1)
            
            except Exception as e:
                logger.error(f"❌ 监控异常: {e}")
                await asyncio.sleep(1)
    
    async def _update_data(self):
        """更新监控数据"""
        # 更新余额
        balance_data = await self.execution.get_balance()
        if balance_data:
            self.current_balance = float(balance_data["details"][0]["eq"])
        
        # 更新延迟
        avg_latency = self.execution.get_avg_latency()
        if avg_latency > 0:
            self.latency_samples.append(avg_latency)
            if len(self.latency_samples) > 100:
                self.latency_samples.pop(0)
    
    async def _check_conditions(self):
        """检查熔断条件"""
        # 1. 检查日亏损
        if self.daily_start_balance > 0:
            loss_ratio = (self.daily_start_balance - self.current_balance) / self.daily_start_balance
            if loss_ratio > self.max_daily_loss_ratio:
                await self._trigger("daily_loss", f"日亏损超过限制: {loss_ratio:.2%}")
                return
        
        # 2. 检查网络延迟
        if self.latency_samples:
            avg_latency = sum(self.latency_samples) / len(self.latency_samples)
            if avg_latency > self.max_latency_ms:
                await self._trigger("latency", f"网络延迟过高: {avg_latency:.1f}ms")
                return
    
    async def _trigger(self, reason: str, message: str):
        """
        触发熔断
        
        Args:
            reason: 触发原因
            message: 触发消息
        """
        self.is_triggered = True
        self.trigger_reason = reason
        self.trigger_time = datetime.now()
        
        logger.critical(f"🚨 熔断触发: {message}")
        
        # 撤销所有订单
        positions = await self.execution.get_positions()
        for pos in positions:
            inst_id = pos["instId"]
            await self.execution.cancel_all_orders(inst_id)
        
        logger.critical("🚨 已撤销所有订单")
    
    async def reset(self):
        """重置熔断系统"""
        logger.info("🔄 重置熔断系统...")
        
        self.is_triggered = False
        self.trigger_reason = ""
        self.trigger_time = None
        self.daily_start_balance = self.current_balance
        
        logger.info("✅ 熔断系统已重置")
    
    def is_safe(self) -> bool:
        """检查是否安全（未熔断）"""
        return not self.is_triggered
    
    def get_status(self) -> dict:
        """获取熔断状态"""
        daily_loss = 0.0
        if self.daily_start_balance > 0:
            daily_loss = (self.daily_start_balance - self.current_balance) / self.daily_start_balance
        
        avg_latency = 0.0
        if self.latency_samples:
            avg_latency = sum(self.latency_samples) / len(self.latency_samples)
        
        return {
            "triggered": self.is_triggered,
            "reason": self.trigger_reason,
            "trigger_time": self.trigger_time,
            "daily_loss": daily_loss,
            "max_loss": self.max_daily_loss_ratio,
            "avg_latency": avg_latency,
            "max_latency": self.max_latency_ms
        }
