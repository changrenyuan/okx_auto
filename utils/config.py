"""
配置管理模块
使用 .env 文件管理所有配置
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# 加载 .env 文件
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

from utils.logger import logger


class Config:
    """配置类"""
    
    # ========== API 配置 ==========
    API_KEY: str = os.getenv("OKX_API_KEY", "")
    SECRET_KEY: str = os.getenv("OKX_SECRET_KEY", "")
    PASSPHRASE: str = os.getenv("OKX_PASSPHRASE", "")
    BASE_URL: str = os.getenv("OKX_BASE_URL", "https://www.okx.com")
    
    # ========== 日志配置 ==========
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "logs/okx_quant.log")
    
    # ========== 交易配置 ==========
    MAX_POSITION_SIZE: float = float(os.getenv("MAX_POSITION_SIZE", "1000"))
    MAX_DAILY_LOSS: float = float(os.getenv("MAX_DAILY_LOSS", "0.05"))  # 5%
    LEVERAGE_LIMIT: int = int(os.getenv("LEVERAGE_LIMIT", "20"))
    TIMEOUT: int = int(os.getenv("TIMEOUT", "30"))
    
    # ========== 策略配置 ==========
    ENABLE_LIQUIDATION_HUNTING: bool = os.getenv("ENABLE_LIQUIDATION_HUNTING", "true").lower() == "true"
    ENABLE_FUNDING_ARBITRAGE: bool = os.getenv("ENABLE_FUNDING_ARBITRAGE", "true").lower() == "true"
    ENABLE_MARKET_MAKING: bool = os.getenv("ENABLE_MARKET_MAKING", "false").lower() == "true"
    
    # ========== WebSocket 配置 ==========
    WS_RECONNECT_DELAY: int = int(os.getenv("WS_RECONNECT_DELAY", "5"))
    WS_PING_INTERVAL: int = int(os.getenv("WS_PING_INTERVAL", "20"))
    WS_CHANNELS_BOOK: str = "books-l2-tbt"  # 增量深度数据
    WS_CHANNELS_TRADE: str = "trades"  # 逐笔成交
    DEFAULT_INST_ID: str = "BTC-USDT-SWAP"  # 默认交易对
    
    # ========== 系统配置 ==========
    RUNNING: bool = True
    
    @classmethod
    def validate(cls) -> bool:
        """验证配置是否有效"""
        logger.info("🔍 验证配置...")
        
        if not cls.API_KEY or cls.API_KEY == "your-api-key-here":
            logger.error("❌ API_KEY 未配置，请在 .env 文件中设置")
            return False
        
        if not cls.SECRET_KEY or cls.SECRET_KEY == "your-secret-key-here":
            logger.error("❌ SECRET_KEY 未配置，请在 .env 文件中设置")
            return False
        
        if not cls.PASSPHRASE or cls.PASSPHRASE == "your-passphrase-here":
            logger.error("❌ PASSPHRASE 未配置，请在 .env 文件中设置")
            return False
        
        logger.info("✓ 配置验证通过")
        logger.info(f"  - API URL: {cls.BASE_URL}")
        logger.info(f"  - 最大仓位: {cls.MAX_POSITION_SIZE}")
        logger.info(f"  - 最大日亏损: {cls.MAX_DAILY_LOSS * 100}%")
        logger.info(f"  - 杠杆限制: {cls.LEVERAGE_LIMIT}x")
        logger.info(f"  - 爆仓单捕猎: {'启用' if cls.ENABLE_LIQUIDATION_HUNTING else '禁用'}")
        logger.info(f"  - 资金费率套利: {'启用' if cls.ENABLE_FUNDING_ARBITRAGE else '禁用'}")
        logger.info(f"  - 做市商策略: {'启用' if cls.ENABLE_MARKET_MAKING else '禁用'}")
        
        return True
    
    @classmethod
    def get(cls, key: str, default: Optional[str] = None) -> Optional[str]:
        """获取配置值"""
        return os.getenv(key, default)


# 创建 __init__.py 使 utils 成为一个包
def init_utils():
    """初始化工具模块"""
    logger.info("🔧 初始化工具模块...")


if __name__ == "__main__":
    # 测试配置
    print("配置信息:")
    print(f"API_KEY: {Config.API_KEY[:10]}..." if Config.API_KEY else "API_KEY: 未设置")
    print(f"BASE_URL: {Config.BASE_URL}")
    print(f"MAX_DAILY_LOSS: {Config.MAX_DAILY_LOSS}")
    
    # 验证配置
    Config.validate()
