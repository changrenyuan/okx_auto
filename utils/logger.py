"""
日志配置模块
提供统一的日志接口，详细记录每一步操作
"""

import logging
import os
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


class QuantLogger:
    """量化交易专用日志记录器"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化日志系统"""
        if hasattr(self, '_initialized'):
            return
            
        self._initialized = True
        self._setup_logger()
    
    def _setup_logger(self):
        """配置日志系统"""
        # 创建日志目录
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        # 获取日志级别
        log_level = os.getenv("LOG_LEVEL", "INFO")
        log_file = os.getenv("LOG_FILE", "logs/okx_quant.log")
        
        # 创建 logger
        self.logger = logging.getLogger("OKX_Quant")
        self.logger.setLevel(getattr(logging, log_level.upper()))
        
        # 避免重复添加 handler
        if self.logger.handlers:
            return
        
        # 控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # 文件处理器（按大小轮转）
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
        
        # 每天的日志文件
        daily_log_file = log_dir / f"okx_quant_{datetime.now().strftime('%Y%m%d')}.log"
        daily_handler = RotatingFileHandler(
            daily_log_file,
            maxBytes=50*1024*1024,  # 50MB
            backupCount=3,
            encoding='utf-8'
        )
        daily_handler.setLevel(logging.DEBUG)
        daily_handler.setFormatter(file_formatter)
        self.logger.addHandler(daily_handler)
        
        self.info("✓ 日志系统初始化完成")
    
    def debug(self, msg, *args, **kwargs):
        """DEBUG 级别日志"""
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg, *args, **kwargs):
        """INFO 级别日志"""
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg, *args, **kwargs):
        """WARNING 级别日志"""
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg, *args, **kwargs):
        """ERROR 级别日志"""
        self.logger.error(msg, *args, **kwargs)
    
    def critical(self, msg, *args, **kwargs):
        """CRITICAL 级别日志"""
        self.logger.critical(msg, *args, **kwargs)
    
    # ========== 特殊场景日志 ==========
    
    def log_api_request(self, method, endpoint, params=None, body=None):
        """记录 API 请求"""
        self.debug(f"📤 API 请求: {method} {endpoint}")
        if params:
            self.debug(f"   参数: {params}")
        if body:
            self.debug(f"   请求体: {body}")
    
    def log_api_response(self, method, endpoint, status_code, data):
        """记录 API 响应"""
        self.debug(f"📥 API 响应: {method} {endpoint} - Status: {status_code}")
        self.debug(f"   数据: {data}")
    
    def log_order(self, action, order_info):
        """记录订单操作"""
        if action == "place":
            self.info(f"📌 下单: {order_info}")
        elif action == "cancel":
            self.warning(f"❌ 撤单: {order_info}")
        elif action == "filled":
            self.info(f"✅ 成交: {order_info}")
        elif action == "failed":
            self.error(f"⛔ 订单失败: {order_info}")
    
    def log_strategy_signal(self, signal):
        """记录策略信号"""
        self.info(f"🎯 策略信号: {signal}")
    
    def log_risk_check(self, passed, reason=""):
        """记录风险检查"""
        if passed:
            self.info(f"✅ 风险检查通过")
        else:
            self.warning(f"⚠️  风险检查失败: {reason}")
    
    def log_market_data(self, inst_id, data_type, data):
        """记录市场数据"""
        self.debug(f"📊 市场数据 [{inst_id}] ({data_type}): {data}")
    
    def log_websocket(self, event, detail=""):
        """记录 WebSocket 事件"""
        self.info(f"🔌 WebSocket: {event} {detail}")
    
    def log_pnl(self, action, amount, reason=""):
        """记录盈亏"""
        if amount > 0:
            self.info(f"💰 盈利: +{amount} ({reason})")
        elif amount < 0:
            self.warning(f"📉 亏损: {amount} ({reason})")
    
    def log_system(self, event, detail=""):
        """记录系统事件"""
        self.info(f"🔧 系统: {event} - {detail}")


# 全局日志实例
logger = QuantLogger()


# 便捷函数
def get_logger():
    """获取日志实例"""
    return logger


if __name__ == "__main__":
    # 测试日志
    logger.info("测试开始")
    logger.debug("调试信息")
    logger.warning("警告信息")
    logger.error("错误信息")
    logger.log_api_request("POST", "/api/v5/trade/order", {"instId": "BTC-USDT"})
    logger.log_order("place", {"side": "buy", "px": "30000", "sz": "0.1"})
    logger.log_strategy_signal({"type": "BUY", "price": 30000})
    logger.log_risk_check(True)
    logger.log_pnl(100.5, "BTC-USDT")
