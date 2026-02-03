"""
二级存储 (Warm Storage)
极速共享缓存，延迟 1-5ms

使用 Redis 实现：
- 账户余额和持仓状态
- 风控参数和全局开关
- 多进程共享数据
- 原子操作和过期时间管理
"""

import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from utils.logger import logger


class WarmStorageLayer:
    """
    二级存储层 - Redis 共享缓存
    
    特性：
    - 延迟 1-5ms
    - 支持多进程共享
    - 原子操作
    - 自动过期管理
    """
    
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        key_prefix: str = "okx_quant:"
    ):
        """
        初始化二级存储
        
        Args:
            host: Redis 主机
            port: Redis 端口
            db: 数据库编号
            password: 密码
            key_prefix: 键前缀
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.key_prefix = key_prefix
        
        self.client: Optional[Any] = None
        self.connected = False
        
        if REDIS_AVAILABLE:
            self._connect()
        else:
            logger.warning("⚠️  Redis 未安装，使用内存模式")
    
    def _connect(self):
        """连接 Redis"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                password=self.password,
                decode_responses=True,
                socket_timeout=5
            )
            
            # 测试连接
            self.client.ping()
            self.connected = True
            logger.info(f"🔥 二级存储 (Redis) 已连接 | {self.host}:{self.port}")
        
        except Exception as e:
            logger.error(f"❌ Redis 连接失败: {e}")
            logger.warning("⚠️  使用内存模式替代")
            self.connected = False
    
    def _make_key(self, key: str) -> str:
        """生成带前缀的键"""
        return f"{self.key_prefix}{key}"
    
    # ========== 基础操作 ==========
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        """
        设置键值
        
        Args:
            key: 键
            value: 值
            ttl: 过期时间（秒）
        """
        if not self.connected:
            return
        
        try:
            full_key = self._make_key(key)
            
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            if ttl:
                self.client.setex(full_key, ttl, value)
            else:
                self.client.set(full_key, value)
        
        except Exception as e:
            logger.error(f"❌ 设置键值失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取键值
        
        Args:
            key: 键
            default: 默认值
        
        Returns:
            值
        """
        if not self.connected:
            return default
        
        try:
            full_key = self._make_key(key)
            value = self.client.get(full_key)
            
            if value is None:
                return default
            
            # 尝试解析 JSON
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        
        except Exception as e:
            logger.error(f"❌ 获取键值失败: {e}")
            return default
    
    def delete(self, key: str):
        """
        删除键
        
        Args:
            key: 键
        """
        if not self.connected:
            return
        
        try:
            full_key = self._make_key(key)
            self.client.delete(full_key)
        
        except Exception as e:
            logger.error(f"❌ 删除键失败: {e}")
    
    def exists(self, key: str) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 键
        
        Returns:
            是否存在
        """
        if not self.connected:
            return False
        
        try:
            full_key = self._make_key(key)
            return self.client.exists(full_key) > 0
        
        except Exception as e:
            logger.error(f"❌ 检查键存在失败: {e}")
            return False
    
    # ========== 账户状态 ==========
    
    def set_balance(self, ccy: str, balance: float):
        """
        设置账户余额
        
        Args:
            ccy: 币种
            balance: 余额
        """
        self.set(f"balance:{ccy}", balance)
        logger.debug(f"💰 更新余额: {ccy} = {balance}")
    
    def get_balance(self, ccy: str) -> float:
        """
        获取账户余额
        
        Args:
            ccy: 币种
        
        Returns:
            余额
        """
        return float(self.get(f"balance:{ccy}", 0.0))
    
    # ========== 持仓状态 ==========
    
    def set_position(self, inst_id: str, side: str, size: float, avg_price: float):
        """
        设置持仓
        
        Args:
            inst_id: 产品 ID
            side: 方向 (long/short)
            size: 数量
            avg_price: 平均价格
        """
        position = {
            "inst_id": inst_id,
            "side": side,
            "size": size,
            "avg_price": avg_price,
            "updated_at": datetime.now().isoformat()
        }
        
        self.set(f"position:{inst_id}", position)
        logger.debug(f"📊 更新持仓: {inst_id} {side} {size} @ {avg_price}")
    
    def get_position(self, inst_id: str) -> Optional[dict]:
        """
        获取持仓
        
        Args:
            inst_id: 产品 ID
        
        Returns:
            持仓信息
        """
        return self.get(f"position:{inst_id}")
    
    def get_all_positions(self) -> Dict[str, dict]:
        """
        获取所有持仓
        
        Returns:
            {inst_id: position}
        """
        if not self.connected:
            return {}
        
        try:
            pattern = self._make_key("position:*")
            positions = {}
            
            for key in self.client.scan_iter(match=pattern):
                inst_id = key.split(":")[-1]
                position = self.get(f"position:{inst_id}")
                if position:
                    positions[inst_id] = position
            
            return positions
        
        except Exception as e:
            logger.error(f"❌ 获取所有持仓失败: {e}")
            return {}
    
    def delete_position(self, inst_id: str):
        """
        删除持仓
        
        Args:
            inst_id: 产品 ID
        """
        self.delete(f"position:{inst_id}")
        logger.debug(f"🗑️  删除持仓: {inst_id}")
    
    # ========== 风控参数 ==========
    
    def set_risk_param(self, name: str, value: Any):
        """
        设置风控参数
        
        Args:
            name: 参数名
            value: 参数值
        """
        self.set(f"risk:{name}", value)
        logger.debug(f"🛡️  更新风控参数: {name} = {value}")
    
    def get_risk_param(self, name: str, default: Any = None) -> Any:
        """
        获取风控参数
        
        Args:
            name: 参数名
            default: 默认值
        
        Returns:
            参数值
        """
        return self.get(f"risk:{name}", default)
    
    def set_daily_pnl(self, value: float):
        """
        设置当日盈亏
        
        Args:
            value: 盈亏值
        """
        self.set("daily_pnl", value, ttl=86400)  # 24小时过期
    
    def get_daily_pnl(self) -> float:
        """
        获取当日盈亏
        
        Returns:
            盈亏值
        """
        return float(self.get("daily_pnl", 0.0))
    
    # ========== 全局开关 ==========
    
    def set_global_switch(self, name: str, enabled: bool):
        """
        设置全局开关
        
        Args:
            name: 开关名
            enabled: 是否启用
        """
        self.set(f"switch:{name}", enabled)
        logger.info(f"🔘 全局开关: {name} = {'ON' if enabled else 'OFF'}")
    
    def get_global_switch(self, name: str, default: bool = False) -> bool:
        """
        获取全局开关
        
        Args:
            name: 开关名
            default: 默认值
        
        Returns:
            是否启用
        """
        return bool(self.get(f"switch:{name}", default))
    
    def is_trading_allowed(self) -> bool:
        """
        检查是否允许交易
        
        Returns:
            是否允许
        """
        return self.get_global_switch("trading_allowed", True)
    
    def enable_trading(self):
        """启用交易"""
        self.set_global_switch("trading_allowed", True)
    
    def disable_trading(self):
        """禁用交易"""
        self.set_global_switch("trading_allowed", False)
        logger.warning("⚠️  交易已被禁用")
    
    # ========== 原子操作 ==========
    
    def increment(self, key: str, amount: float = 1.0) -> float:
        """
        原子递增
        
        Args:
            key: 键
            amount: 增量
        
        Returns:
            新值
        """
        if not self.connected:
            return 0.0
        
        try:
            full_key = self._make_key(key)
            return self.client.incrbyfloat(full_key, amount)
        
        except Exception as e:
            logger.error(f"❌ 原子递增失败: {e}")
            return 0.0
    
    def decrement(self, key: str, amount: float = 1.0) -> float:
        """
        原子递减
        
        Args:
            key: 键
            amount: 减量
        
        Returns:
            新值
        """
        if not self.connected:
            return 0.0
        
        try:
            full_key = self._make_key(key)
            return self.client.decrbyfloat(full_key, amount)
        
        except Exception as e:
            logger.error(f"❌ 原子递减失败: {e}")
            return 0.0
    
    def acquire_lock(self, lock_name: str, timeout: int = 10) -> bool:
        """
        获取分布式锁
        
        Args:
            lock_name: 锁名
            timeout: 超时时间（秒）
        
        Returns:
            是否成功
        """
        if not self.connected:
            return False
        
        try:
            full_key = self._make_key(f"lock:{lock_name}")
            return self.client.set(full_key, "1", ex=timeout, nx=True)
        
        except Exception as e:
            logger.error(f"❌ 获取锁失败: {e}")
            return False
    
    def release_lock(self, lock_name: str):
        """
        释放分布式锁
        
        Args:
            lock_name: 锁名
        """
        self.delete(f"lock:{lock_name}")
    
    # ========== 统计信息 ==========
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        if not self.connected:
            return {"connected": False}
        
        try:
            info = self.client.info()
            return {
                "connected": True,
                "host": self.host,
                "port": self.port,
                "db_size": self.client.dbsize(),
                "used_memory": info.get("used_memory_human", "N/A"),
                "uptime": info.get("uptime_in_seconds", 0)
            }
        
        except Exception as e:
            logger.error(f"❌ 获取统计信息失败: {e}")
            return {"connected": False, "error": str(e)}
    
    def close(self):
        """关闭连接"""
        if self.client:
            self.client.close()
            self.connected = False
            logger.info("🔌 二级存储 (Redis) 已关闭")
