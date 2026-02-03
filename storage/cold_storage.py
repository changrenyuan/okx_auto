"""
三级存储 (Cold Storage)
高性能时序文件，用于历史数据和回测

使用 HDF5/Parquet 实现：
- 历史盘口数据
- 成交日志
- 用于回测和策略优化
"""

import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
    PARQUET_AVAILABLE = True
except ImportError:
    PARQUET_AVAILABLE = False

try:
    import h5py
    HDF5_AVAILABLE = True
except ImportError:
    HDF5_AVAILABLE = False

from utils.logger import logger


class ColdStorageLayer:
    """
    三级存储层 - 历史数据存储
    
    特性：
    - 列式存储，快速读取
    - 支持时间范围查询
    - 数据压缩
    - 适合回测和策略优化
    """
    
    def __init__(
        self,
        data_dir: str = "data/historical",
        format: str = "parquet"  # parquet 或 hdf5
    ):
        """
        初始化三级存储
        
        Args:
            data_dir: 数据目录
            format: 存储格式 (parquet/hdf5)
        """
        self.data_dir = Path(data_dir)
        self.format = format.lower()
        
        # 创建数据目录
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 检查可用性
        if self.format == "parquet" and not PARQUET_AVAILABLE:
            logger.warning("⚠️  Parquet 不可用，使用 HDF5")
            self.format = "hdf5"
        elif self.format == "hdf5" and not HDF5_AVAILABLE:
            logger.warning("⚠️  HDF5 不可用，使用 Parquet")
            self.format = "parquet"
        
        logger.info(f"🧊 三级存储初始化完成 | 格式: {self.format} | 目录: {self.data_dir}")
    
    def _get_file_path(self, inst_id: str, date: str, data_type: str) -> Path:
        """
        获取文件路径
        
        Args:
            inst_id: 产品 ID
            date: 日期 (YYYY-MM-DD)
            data_type: 数据类型 (orderbook/trades/ohlcv)
        
        Returns:
            文件路径
        """
        filename = f"{inst_id}_{date}_{data_type}.{self.format}"
        return self.data_dir / filename
    
    # ========== Order Book 快照 ==========
    
    def save_orderbook_snapshot(
        self,
        inst_id: str,
        timestamp: datetime,
        bids: List[tuple],
        asks: List[tuple]
    ):
        """
        保存 Order Book 快照
        
        Args:
            inst_id: 产品 ID
            timestamp: 时间戳
            bids: [(价格, 数量), ...]
            asks: [(价格, 数量), ...]
        """
        try:
            date_str = timestamp.strftime("%Y-%m-%d")
            file_path = self._get_file_path(inst_id, date_str, "orderbook")
            
            # 构造 DataFrame
            data = []
            
            # 买盘
            for price, size in bids:
                data.append({
                    "timestamp": timestamp,
                    "side": "bid",
                    "price": price,
                    "size": size,
                    "inst_id": inst_id
                })
            
            # 卖盘
            for price, size in asks:
                data.append({
                    "timestamp": timestamp,
                    "side": "ask",
                    "price": price,
                    "size": size,
                    "inst_id": inst_id
                })
            
            df = pd.DataFrame(data)
            
            # 保存
            self._save_dataframe(df, file_path)
        
        except Exception as e:
            logger.error(f"❌ 保存 Order Book 快照失败: {e}")
    
    def load_orderbook_snapshot(
        self,
        inst_id: str,
        date: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        加载 Order Book 快照
        
        Args:
            inst_id: 产品 ID
            date: 日期 (YYYY-MM-DD)
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            DataFrame
        """
        try:
            file_path = self._get_file_path(inst_id, date, "orderbook")
            
            if not file_path.exists():
                logger.warning(f"⚠️  文件不存在: {file_path}")
                return pd.DataFrame()
            
            df = self._load_dataframe(file_path)
            
            # 时间过滤
            if start_time or end_time:
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"])
                    
                    if start_time:
                        df = df[df["timestamp"] >= start_time]
                    
                    if end_time:
                        df = df[df["timestamp"] <= end_time]
            
            return df
        
        except Exception as e:
            logger.error(f"❌ 加载 Order Book 快照失败: {e}")
            return pd.DataFrame()
    
    # ========== 成交数据 ==========
    
    def save_trades(
        self,
        inst_id: str,
        trades: List[dict]
    ):
        """
        保存成交数据
        
        Args:
            inst_id: 产品 ID
            trades: [成交数据, ...]
                每个成交数据包含: price, size, side, timestamp, trade_id
        """
        try:
            if not trades:
                return
            
            # 按日期分组
            trades_by_date = {}
            
            for trade in trades:
                timestamp = trade.get("timestamp")
                if isinstance(timestamp, str):
                    timestamp = pd.to_datetime(timestamp)
                elif isinstance(timestamp, (int, float)):
                    # Unix 时间戳转换为 datetime
                    timestamp = pd.to_datetime(timestamp, unit='ms')
                
                if timestamp is None:
                    continue
                
                date_str = timestamp.strftime("%Y-%m-%d")
                
                if date_str not in trades_by_date:
                    trades_by_date[date_str] = []
                
                trades_by_date[date_str].append(trade)
            
            # 保存每个日期的数据
            for date_str, daily_trades in trades_by_date.items():
                df = pd.DataFrame(daily_trades)
                file_path = self._get_file_path(inst_id, date_str, "trades")
                
                self._save_dataframe(df, file_path)
            
            logger.info(f"💾 保存成交数据: {inst_id} | {len(trades)} 笔")
        
        except Exception as e:
            logger.error(f"❌ 保存成交数据失败: {e}")
    
    def load_trades(
        self,
        inst_id: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        加载成交数据
        
        Args:
            inst_id: 产品 ID
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            DataFrame
        """
        try:
            all_data = []
            
            current_date = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            
            while current_date <= end_datetime:
                date_str = current_date.strftime("%Y-%m-%d")
                file_path = self._get_file_path(inst_id, date_str, "trades")
                
                if file_path.exists():
                    df = self._load_dataframe(file_path)
                    all_data.append(df)
                
                current_date += pd.Timedelta(days=1)
            
            if all_data:
                return pd.concat(all_data, ignore_index=True)
            else:
                return pd.DataFrame()
        
        except Exception as e:
            logger.error(f"❌ 加载成交数据失败: {e}")
            return pd.DataFrame()
    
    # ========== OHLCV 数据 ==========
    
    def save_ohlcv(
        self,
        inst_id: str,
        ohlcv_data: pd.DataFrame
    ):
        """
        保存 OHLCV 数据
        
        Args:
            inst_id: 产品 ID
            ohlcv_data: OHLCV DataFrame
                columns: timestamp, open, high, low, close, volume
        """
        try:
            if ohlcv_data.empty:
                return
            
            # 按日期分组保存
            ohlcv_data["timestamp"] = pd.to_datetime(ohlcv_data["timestamp"])
            ohlcv_data["date"] = ohlcv_data["timestamp"].dt.date
            
            for date, group in ohlcv_data.groupby("date"):
                date_str = date.strftime("%Y-%m-%d")
                file_path = self._get_file_path(inst_id, date_str, "ohlcv")
                
                group = group.drop(columns=["date"])
                self._save_dataframe(group, file_path)
            
            logger.info(f"💾 保存 OHLCV 数据: {inst_id} | {len(ohlcv_data)} 条")
        
        except Exception as e:
            logger.error(f"❌ 保存 OHLCV 数据失败: {e}")
    
    def load_ohlcv(
        self,
        inst_id: str,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """
        加载 OHLCV 数据
        
        Args:
            inst_id: 产品 ID
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
        
        Returns:
            DataFrame
        """
        try:
            all_data = []
            
            current_date = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date)
            
            while current_date <= end_datetime:
                date_str = current_date.strftime("%Y-%m-%d")
                file_path = self._get_file_path(inst_id, date_str, "ohlcv")
                
                if file_path.exists():
                    df = self._load_dataframe(file_path)
                    all_data.append(df)
                
                current_date += pd.Timedelta(days=1)
            
            if all_data:
                return pd.concat(all_data, ignore_index=True).sort_values("timestamp")
            else:
                return pd.DataFrame()
        
        except Exception as e:
            logger.error(f"❌ 加载 OHLCV 数据失败: {e}")
            return pd.DataFrame()
    
    # ========== 底层存储操作 ==========
    
    def _save_dataframe(self, df: pd.DataFrame, file_path: Path):
        """
        保存 DataFrame
        
        Args:
            df: DataFrame
            file_path: 文件路径
        """
        if self.format == "parquet":
            df.to_parquet(file_path, index=False, compression="snappy")
        else:  # hdf5
            # HDF5 模式
            df.to_hdf(file_path, key="data", mode="a", complevel=9, complib="blosc")
    
    def _load_dataframe(self, file_path: Path) -> pd.DataFrame:
        """
        加载 DataFrame
        
        Args:
            file_path: 文件路径
        
        Returns:
            DataFrame
        """
        if self.format == "parquet":
            return pd.read_parquet(file_path)
        else:  # hdf5
            return pd.read_hdf(file_path, key="data")
    
    # ========== 数据管理 ==========
    
    def get_available_dates(self, inst_id: str, data_type: str) -> List[str]:
        """
        获取可用的日期列表
        
        Args:
            inst_id: 产品 ID
            data_type: 数据类型
        
        Returns:
            日期列表
        """
        pattern = f"{inst_id}_*_{data_type}.{self.format}"
        files = list(self.data_dir.glob(pattern))
        
        dates = []
        for file in files:
            parts = file.stem.split("_")
            if len(parts) >= 2:
                dates.append(parts[1])
        
        return sorted(dates)
    
    def delete_data(self, inst_id: str, date: str, data_type: str):
        """
        删除数据
        
        Args:
            inst_id: 产品 ID
            date: 日期 (YYYY-MM-DD)
            data_type: 数据类型
        """
        try:
            file_path = self._get_file_path(inst_id, date, data_type)
            
            if file_path.exists():
                file_path.unlink()
                logger.info(f"🗑️  删除数据: {file_path}")
            else:
                logger.warning(f"⚠️  文件不存在: {file_path}")
        
        except Exception as e:
            logger.error(f"❌ 删除数据失败: {e}")
    
    def get_storage_size(self) -> Dict[str, int]:
        """
        获取存储大小
        
        Returns:
            {data_type: size_bytes}
        """
        try:
            sizes = {}
            
            for file in self.data_dir.glob(f"*.{self.format}"):
                data_type = file.stem.split("_")[-1]
                size = file.stat().st_size
                
                if data_type not in sizes:
                    sizes[data_type] = 0
                
                sizes[data_type] += size
            
            return sizes
        
        except Exception as e:
            logger.error(f"❌ 获取存储大小失败: {e}")
            return {}
