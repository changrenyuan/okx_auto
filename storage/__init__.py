"""
存储模块
三层存储架构：
1. Hot Storage - RAM (< 1ms)
2. Warm Storage - Redis (1-5ms)
3. Cold Storage - HDF5/Parquet (磁盘 IO)
"""

from .hot_storage import HotStorageLayer
from .warm_storage import WarmStorageLayer
from .cold_storage import ColdStorageLayer
from .storage_manager import StorageManager

__all__ = [
    "HotStorageLayer",
    "WarmStorageLayer",
    "ColdStorageLayer",
    "StorageManager"
]
