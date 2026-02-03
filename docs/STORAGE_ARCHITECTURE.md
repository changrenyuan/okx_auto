# 存储架构文档

## 概述

GamblerHunter V2 采用三层存储架构，根据数据访问频率和延迟要求，将数据存储在不同层级的介质中。

## 存储层次

### 一级存储 (Hot Storage) - RAM

**延迟**: < 1ms

**存储介质**: Python 原生数据结构 (dict, list, deque)

**用途**:
- 本地 Order Book 镜像
- 最新成交 (Ticks)
- 实时指标 (OFI, 买卖压力)

**数据结构**:
```python
# Order Book
bids: Dict[float, (size, orders_count, timestamp)]  # O(1) 查询和更新
asks: Dict[float, (size, orders_count, timestamp)]

# 成交流
trades: deque(maxlen=1000)  # 固定长度，自动弹出旧数据

# 实时指标
ofi_history: deque(maxlen=100)
buy_pressure: float
sell_pressure: float
```

**为什么用字典？**
- OKX 推送增量更新（价格 30000 的数量变为 0）
- 字典查询和修改复杂度 O(1)，瞬时完成

**为什么用 deque？**
- 自动弹出旧数据，只保留最近 1000 笔成交
- 方便计算瞬时买卖压力

### 二级存储 (Warm Storage) - Redis

**延迟**: 1-5ms

**存储介质**: Redis Key-Value 缓存

**用途**:
- 账户余额
- 持仓状态
- 风控参数
- 全局开关
- 多进程共享数据

**使用场景**:
当"数据抓取进程"和"交易执行进程"分开时，Redis 是它们沟通的桥梁。

**优势**:
- Redis 运行在内存中，延迟微秒级
- 保证风控模块实时知道："我已经开了 5 手多单，不能再开了"

**数据结构**:
```python
# 账户余额
balance:{ccy} -> float

# 持仓状态
position:{inst_id} -> {inst_id, side, size, avg_price, updated_at}

# 风控参数
risk:{name} -> Any

# 全局开关
switch:{name} -> bool

# 分布式锁
lock:{name} -> 1
```

### 三级存储 (Cold Storage) - HDF5/Parquet

**延迟**: 磁盘 IO

**存储介质**: 列式存储文件

**用途**:
- 历史盘口数据
- 成交日志
- 用于回测和策略优化

**为什么不用 CSV？**
- CSV 读写慢
- 占用空间巨大
- 不适合科学计算

**推荐格式**:
- **Parquet**: 压缩率高，查询快，适合列式存储
- **HDF5**: 专为科学计算设计，支持快速随机访问

**文件组织**:
```
data/historical/
├── BTC-USDT-SWAP_2026-02-03_orderbook.parquet
├── BTC-USDT-SWAP_2026-02-03_trades.parquet
├── BTC-USDT-SWAP_2026-02-03_ohlcv.parquet
└── ...
```

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层 (Application)                      │
│  GamblerHunter V2 - 策略引擎、风险控制、交易执行              │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
┌────────────────┐ ┌────────────────┐ ┌────────────────┐
│  一级存储       │ │  二级存储       │ │  三级存储       │
│  (Hot)         │ │  (Warm)        │ │  (Cold)        │
│                │ │                │ │                │
│  RAM           │ │  Redis         │ │  Disk          │
│  < 1ms         │ │  1-5ms         │ │  IO            │
│                │ │                │ │                │
│  Order Book    │ │  账户余额      │ │  历史数据      │
│  成交流        │ │  持仓状态      │ │  回测数据      │
│  OFI 指标      │ │  风控参数      │ │  OHLCV         │
│  买卖压力      │ │  全局开关      │ │                │
└────────────────┘ └────────────────┘ └────────────────┘
```

## 使用示例

### 一级存储 (Hot Storage)

```python
from storage import StorageManager

storage = StorageManager()

# 更新 Order Book
storage.update_bid(30000.0, 10.5, 5)
storage.update_ask(30001.0, 8.3, 3)

# 获取价格
best_bid = storage.get_best_bid()  # (30000.0, 10.5)
best_ask = storage.get_best_ask()  # (30001.0, 8.3)
mid_price = storage.get_mid_price()  # 30000.5

# 添加成交
storage.add_trade({
    "price": 30000.0,
    "size": 1.0,
    "side": "buy",
    "timestamp": time.time(),
    "trade_id": "12345"
})

# 获取成交
recent_trades = storage.get_recent_trades(10)  # 最近10笔
trades_in_window = storage.get_trades_in_window(1.0)  # 最近1秒

# OFI 指标
ofi = storage.get_ofi(window=10)
ofi_trend = storage.get_ofi_trend()  # rising/falling/stable
```

### 二级存储 (Warm Storage)

```python
# 账户余额
storage.set_balance("USDT", 1000.0)
balance = storage.get_balance("USDT")  # 1000.0

# 持仓状态
storage.set_position("BTC-USDT-SWAP", "long", 10.0, 30000.0)
position = storage.get_position("BTC-USDT-SWAP")
all_positions = storage.get_all_positions()

# 风控参数
storage.set_risk_param("max_position", 100.0)
max_position = storage.get_risk_param("max_position", 100.0)

# 全局开关
storage.enable_trading()
storage.disable_trading()
is_allowed = storage.is_trading_allowed()

# 分布式锁
if storage.acquire_lock("trade_execution", timeout=10):
    try:
        # 执行交易
        pass
    finally:
        storage.release_lock("trade_execution")
```

### 三级存储 (Cold Storage)

```python
# 保存 Order Book 快照
storage.save_orderbook_snapshot(
    inst_id="BTC-USDT-SWAP",
    timestamp=datetime.now(),
    bids=[(30000.0, 10.5), (29999.0, 5.2)],
    asks=[(30001.0, 8.3), (30002.0, 3.1)]
)

# 加载 Order Book 快照
df = storage.load_orderbook_snapshot(
    inst_id="BTC-USDT-SWAP",
    date="2026-02-03",
    start_time=datetime(2026, 2, 3, 10, 0),
    end_time=datetime(2026, 2, 3, 11, 0)
)

# 保存成交数据
storage.save_trades("BTC-USDT-SWAP", trades_list)

# 加载成交数据
df = storage.load_trades(
    inst_id="BTC-USDT-SWAP",
    start_date="2026-02-01",
    end_date="2026-02-03"
)

# 保存 OHLCV 数据
storage.save_ohlcv("BTC-USDT-SWAP", ohlcv_df)

# 加载 OHLCV 数据
df = storage.load_ohlcv(
    inst_id="BTC-USDT-SWAP",
    start_date="2026-02-01",
    end_date="2026-02-03"
)
```

## 数据同步策略

### 实时同步
- Order Book 增量更新 → 一级存储
- 逐笔成交 → 一级存储

### 定期同步
- 每 60 秒将一级存储数据同步到三级存储
- 包括 Order Book 快照和成交数据

### 风控同步
- 账户余额、持仓状态实时写入二级存储
- 风控参数实时更新

## 性能指标

| 存储层级 | 延迟 | 容量 | 适用场景 |
|---------|------|------|---------|
| 一级 (RAM) | < 1ms | 有限 | 实时 Order Book、成交 |
| 二级 (Redis) | 1-5ms | 中等 | 账户状态、风控参数 |
| 三级 (Disk) | 磁盘 IO | 无限 | 历史数据、回测 |

## 最佳实践

1. **一级存储**: 存储高频访问的数据，如实时 Order Book
2. **二级存储**: 存储跨进程共享的数据，如账户状态
3. **三级存储**: 存储历史数据，用于回测和优化
4. **定期同步**: 避免数据丢失，定期将一级存储同步到三级存储
5. **数据压缩**: 使用 Parquet 格式，节省磁盘空间
6. **分布式锁**: 使用 Redis 实现跨进程锁，防止重复执行

## 故障恢复

### Redis 故障
- 系统自动降级到内存模式
- 不影响核心交易功能
- 警告日志记录

### 磁盘故障
- 历史数据丢失
- 实时交易不受影响
- 需要定期备份

### RAM 故障
- 程序崩溃
- 需要重启恢复
- 建议使用进程守护

## 依赖安装

```bash
pip install -r requirements.txt
```

可选依赖：
- Redis: `pip install redis`
- Parquet: `pip install pyarrow`
- HDF5: `pip install tables`

## 总结

三层存储架构提供了：
- ✅ 极低延迟（< 1ms）的实时数据访问
- ✅ 可靠的跨进程共享（Redis）
- ✅ 高效的历史数据存储（Parquet/HDF5）
- ✅ 灵活的数据同步策略
- ✅ 完善的故障恢复机制

这是专业级高频量化交易系统的存储架构！
