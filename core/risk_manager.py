"""
风险管理器
负责风险控制，防止爆仓
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from utils.logger import logger
from utils.config import Config


@dataclass
class RiskMetrics:
    """风险指标"""
    total_balance: float = 0.0
    available_balance: float = 0.0
    total_position_value: float = 0.0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    leverage: float = 0.0
    daily_loss_ratio: float = 0.0


class RiskManager:
    """风险管理器 - 最后一道防线"""
    
    def __init__(self):
        """初始化风险管理器"""
        self.metrics = RiskMetrics()
        self.start_balance: float = 0.0
        self.daily_start_balance: float = 0.0
        self.daily_start_time: datetime = datetime.now()
        
        # 交易统计
        self.total_trades: int = 0
        self.winning_trades: int = 0
        self.losing_trades: int = 0
        
        # 风险限制
        self.max_daily_loss = Config.MAX_DAILY_LOSS  # 5%
        self.leverage_limit = Config.LEVERAGE_LIMIT  # 20x
        self.max_position_size = Config.MAX_POSITION_SIZE
        
        # 风险状态
        self.emergency_stop: bool = False
        
        logger.info("🛡️  风险管理器初始化完成")
        logger.info(f"   - 最大日亏损: {self.max_daily_loss * 100}%")
        logger.info(f"   - 杠杆限制: {self.leverage_limit}x")
        logger.info(f"   - 最大仓位: {self.max_position_size}")
    
    async def update_metrics(self, balance: Dict, positions: list):
        """
        更新风险指标
        
        Args:
            balance: 账户余额
            positions: 持仓列表
        """
        try:
            # 更新余额
            if balance and "details" in balance:
                for detail in balance["details"]:
                    if detail["ccy"] == "USDT":
                        self.metrics.total_balance = float(detail["bal"])
                        self.metrics.available_balance = float(detail["availBal"])
                        break
            
            # 初始化
            if self.start_balance == 0:
                self.start_balance = self.metrics.total_balance
                self.daily_start_balance = self.metrics.total_balance
                logger.info(f"📊 初始余额: {self.start_balance} USDT")
            
            # 更新持仓
            total_position = 0.0
            total_unrealized_pnl = 0.0
            
            for pos in positions:
                if pos["instId"].endswith("-USDT"):
                    pos_value = float(pos["notionalUsd"])
                    total_position += abs(pos_value)
                    total_unrealized_pnl += float(pos["upl"])
            
            self.metrics.total_position_value = total_position
            self.metrics.unrealized_pnl = total_unrealized_pnl
            
            # 计算杠杆率
            if self.metrics.total_balance > 0:
                self.metrics.leverage = total_position / self.metrics.total_balance
            
            # 计算日盈亏
            self.metrics.daily_pnl = self.metrics.total_balance - self.daily_start_balance
            
            # 计算日亏损比例
            if self.daily_start_balance > 0:
                self.metrics.daily_loss_ratio = self.metrics.daily_pnl / self.daily_start_balance
            
            logger.debug(f"📊 风险指标更新: "
                        f"余额={self.metrics.total_balance:.2f}, "
                        f"持仓={self.metrics.total_position_value:.2f}, "
                        f"杠杆={self.metrics.leverage:.2f}x, "
                        f"日盈亏={self.metrics.daily_pnl:.2f}")
        
        except Exception as e:
            logger.error(f"❌ 更新风险指标失败: {e}")
    
    async def pre_trade_check(
        self,
        inst_id: str,
        side: str,
        size: float,
        price: float
    ) -> tuple[bool, str]:
        """
        交易前风险检查
        
        Args:
            inst_id: 产品 ID
            side: 方向
            size: 数量
            price: 价格
        
        Returns:
            (是否通过, 原因)
        """
        logger.info(f"🔍 预交易检查: {side} {size} {inst_id} @ {price}")
        
        # 1. 检查紧急停机
        if self.emergency_stop:
            reason = "紧急停机，禁止交易"
            logger.warning(f"⚠️  {reason}")
            return False, reason
        
        # 2. 检查日亏损
        if self.metrics.daily_loss_ratio <= -self.max_daily_loss:
            reason = f"日亏损已达 {self.metrics.daily_loss_ratio * 100:.2f}%，触发熔断"
            logger.warning(f"⚠️  {reason}")
            self.emergency_stop = True
            logger.critical("🚨 触发紧急停机！")
            return False, reason
        
        # 3. 检查仓位大小
        position_value = size * price
        if position_value > self.max_position_size:
            reason = f"仓位 {position_value} 超过最大限制 {self.max_position_size}"
            logger.warning(f"⚠️  {reason}")
            return False, reason
        
        # 4. 检查可用余额
        required_margin = position_value / self.leverage_limit
        if self.metrics.available_balance < required_margin:
            reason = f"可用余额不足: 需要 {required_margin:.2f}, 可用 {self.metrics.available_balance:.2f}"
            logger.warning(f"⚠️  {reason}")
            return False, reason
        
        # 5. 检查杠杆率
        new_leverage = (self.metrics.total_position_value + position_value) / self.metrics.total_balance
        if new_leverage > self.leverage_limit:
            reason = f"杠杆率 {new_leverage:.2f}x 超过限制 {self.leverage_limit}x"
            logger.warning(f"⚠️  {reason}")
            return False, reason
        
        # 6. 凯利公式计算最佳仓位
        optimal_size = self._kelly_criterion(
            win_rate=0.55,
            avg_win=0.02,
            avg_loss=0.015
        )
        
        if position_value > optimal_size:
            logger.warning(f"⚠️  当前仓位 {position_value:.2f} 超过凯利建议 {optimal_size:.2f}")
        
        logger.log_risk_check(True)
        return True, "风险检查通过"
    
    def _kelly_criterion(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float
    ) -> float:
        """
        凯利公式计算最佳仓位
        
        Args:
            win_rate: 胜率
            avg_win: 平均盈利比例
            avg_loss: 平均亏损比例
        
        Returns:
            建议仓位
        """
        try:
            kelly_f = (win_rate * avg_win - (1 - win_rate) * avg_loss) / avg_win
            kelly_f = max(0, min(kelly_f, 0.25))  # 限制在 0-25% 之间
            
            optimal_size = self.metrics.total_balance * kelly_f
            logger.debug(f"📐 凯利公式: 胜率={win_rate:.2%}, 盈利={avg_win:.2%}, 亏损={avg_loss:.2%}, 建议={kelly_f:.2%}, 仓位={optimal_size:.2f}")
            
            return optimal_size
        
        except Exception as e:
            logger.error(f"❌ 凯利公式计算失败: {e}")
            return self.max_position_size * 0.1  # 默认 10%
    
    async def post_trade_check(self, trade_result: Dict):
        """
        交易后检查
        
        Args:
            trade_result: 交易结果
        """
        self.total_trades += 1
        
        if trade_result.get("realizedPnl"):
            pnl = float(trade_result["realizedPnl"])
            
            if pnl > 0:
                self.winning_trades += 1
                logger.log_pnl("profit", pnl, f"交易 #{self.total_trades}")
            else:
                self.losing_trades += 1
                logger.log_pnl("loss", pnl, f"交易 #{self.total_trades}")
        
        # 检查是否需要降低仓位
        if self.metrics.daily_loss_ratio < -0.03:  # 亏损超过 3%
            logger.warning("⚠️  日亏损超过 3%，建议降低仓位")
        
        # 检查是否需要紧急止损
        if self.metrics.daily_loss_ratio < -0.04:  # 亏损超过 4%
            logger.warning("⚠️  日亏损超过 4%，考虑平仓止损")
    
    async def check_emergency_stop(self) -> bool:
        """
        检查是否需要紧急停机
        
        Returns:
            是否需要停机
        """
        # 检查日亏损
        if self.metrics.daily_loss_ratio <= -self.max_daily_loss:
            logger.critical(f"🚨 日亏损达 {self.metrics.daily_loss_ratio * 100:.2f}%，触发紧急停机！")
            self.emergency_stop = True
            return True
        
        return False
    
    def get_risk_summary(self) -> Dict:
        """获取风险摘要"""
        win_rate = 0
        if self.total_trades > 0:
            win_rate = self.winning_trades / self.total_trades
        
        return {
            "total_balance": self.metrics.total_balance,
            "daily_pnl": self.metrics.daily_pnl,
            "daily_pnl_percent": self.metrics.daily_pnl / self.daily_start_balance * 100 if self.daily_start_balance > 0 else 0,
            "leverage": self.metrics.leverage,
            "unrealized_pnl": self.metrics.unrealized_pnl,
            "total_trades": self.total_trades,
            "win_rate": win_rate,
            "emergency_stop": self.emergency_stop,
        }
    
    def reset_daily(self):
        """重置每日统计"""
        self.daily_start_balance = self.metrics.total_balance
        self.daily_start_time = datetime.now()
        logger.info(f"📅 每日统计重置: 起始余额 {self.daily_start_balance}")
    
    def enable_emergency_stop(self, reason: str = "手动触发"):
        """启用紧急停机"""
        self.emergency_stop = True
        logger.critical(f"🚨 紧急停机已启用: {reason}")
    
    def disable_emergency_stop(self):
        """禁用紧急停机"""
        self.emergency_stop = False
        logger.info("✅ 紧急停机已禁用")


if __name__ == "__main__":
    # 测试风险管理器
    async def test():
        risk_manager = RiskManager()
        
        # 模拟数据
        balance = {
            "details": [
                {"ccy": "USDT", "bal": "10000", "availBal": "9000"}
            ]
        }
        
        await risk_manager.update_metrics(balance, [])
        
        # 风险检查
        passed, reason = await risk_manager.pre_trade_check("BTC-USDT", "buy", 0.1, 50000)
        logger.info(f"风险检查: {'通过' if passed else '失败'} - {reason}")
        
        # 获取风险摘要
        summary = risk_manager.get_risk_summary()
        logger.info(f"风险摘要: {summary}")
    
    import asyncio
    # asyncio.run(test())
