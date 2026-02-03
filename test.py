"""
测试脚本
验证系统各个模块是否正常工作
"""

import asyncio
from utils.logger import logger
from utils.config import Config
from core.execution_engine import ExecutionEngine
from core.risk_manager import RiskManager
from strategies.liquidity_hunting import LiquidationHuntingStrategy
from strategies.funding_arbitrage import FundingArbitrageStrategy


async def test_config():
    """测试配置"""
    logger.info("🧪 测试配置...")
    
    if Config.validate():
        logger.info("✅ 配置测试通过")
        return True
    else:
        logger.error("❌ 配置测试失败")
        return False


async def test_risk_manager():
    """测试风险管理器"""
    logger.info("🧪 测试风险管理器...")
    
    risk_manager = RiskManager()
    
    # 模拟数据
    balance = {
        "details": [
            {"ccy": "USDT", "bal": "10000", "availBal": "9000"}
        ]
    }
    
    await risk_manager.update_metrics(balance, [])
    
    # 测试风险检查
    passed, reason = await risk_manager.pre_trade_check("BTC-USDT", "buy", 0.1, 50000)
    
    if passed:
        logger.info("✅ 风险管理器测试通过")
        return True
    else:
        logger.error(f"❌ 风险管理器测试失败: {reason}")
        return False


async def test_strategy(strategy, name):
    """测试策略"""
    logger.info(f"🧪 测试{name}策略...")
    
    # 模拟数据
    ticker_data = [{
        "instId": "BTC-USDT",
        "last": "50000",
        "bidPx": "49995",
        "askPx": "50005",
        "vol24h": "1000",
        "fundingRate": "0.0001"
    }]
    
    try:
        await strategy.on_market_data(ticker_data)
        logger.info(f"✅ {name}策略测试通过")
        return True
    except Exception as e:
        logger.error(f"❌ {name}策略测试失败: {e}")
        return False


async def test_execution_engine():
    """测试执行引擎（需要 API 密钥）"""
    logger.info("🧪 测试执行引擎...")
    
    if Config.API_KEY == "your-api-key-here":
        logger.warning("⚠️  跳过执行引擎测试（未配置 API 密钥）")
        return True
    
    engine = ExecutionEngine()
    await engine.start()
    
    try:
        balance = await engine.get_balance()
        if balance:
            logger.info(f"✅ 执行引擎测试通过，余额: {balance}")
            return True
        else:
            logger.error("❌ 执行引擎测试失败（无法获取余额）")
            return False
    except Exception as e:
        logger.error(f"❌ 执行引擎测试失败: {e}")
        return False
    finally:
        await engine.stop()


async def main():
    """主测试函数"""
    logger.info("=" * 60)
    logger.info("🧪 OKX 量化交易系统测试")
    logger.info("=" * 60)
    
    results = []
    
    # 测试配置
    results.append(await test_config())
    
    # 测试风险管理器
    results.append(await test_risk_manager())
    
    # 测试策略
    liq_strategy = LiquidationHuntingStrategy()
    results.append(await test_strategy(liq_strategy, "爆仓单捕猎"))
    
    arb_strategy = FundingArbitrageStrategy()
    results.append(await test_strategy(arb_strategy, "资金费率套利"))
    
    # 测试执行引擎
    results.append(await test_execution_engine())
    
    # 汇总结果
    logger.info("")
    logger.info("=" * 60)
    logger.info("📊 测试结果汇总")
    logger.info("=" * 60)
    
    total = len(results)
    passed = sum(results)
    failed = total - passed
    
    logger.info(f"总计: {total} 个测试")
    logger.info(f"通过: {passed} 个")
    logger.info(f"失败: {failed} 个")
    
    if all(results):
        logger.info("✅ 所有测试通过！")
    else:
        logger.error("❌ 部分测试失败，请检查配置和依赖")


if __name__ == "__main__":
    asyncio.run(main())
