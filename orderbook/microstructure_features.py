"""
市场微观结构特征提取器
从订单簿中提取赌徒行为特征
"""

import asyncio
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque

from utils.logger import logger
from orderbook.pro_orderbook import ProfessionalOrderBook, OrderBookFeatures


class MicrostructureFeatures:
    """
    市场微观结构特征
    
    所有特征都基于订单簿的实时状态，
    不依赖历史价格（K线）
    """
    
    def __init__(self, inst_id: str, orderbook: ProfessionalOrderBook):
        """
        初始化特征提取器
        
        Args:
            inst_id: 产品 ID
            orderbook: 专业订单簿
        """
        self.inst_id = inst_id
        self.orderbook = orderbook
        
        # OFI 历史
        self.ofi_history: deque = deque(maxlen=100)
        self.ofi_timestamps: deque = deque(maxlen=100)
        
        # Spread 历史
        self.spread_history: deque = deque(maxlen=100)
        
        # 深度历史
        self.depth_history: deque = deque(maxlen=100)
        
        # 上次更新时间
        self.last_update: Optional[datetime] = None
        
        logger.debug(f"🔬 微观结构特征提取器初始化: {inst_id}")
    
    def update(self):
        """更新特征"""
        try:
            current_time = datetime.now()
            self.last_update = current_time
            
            # 计算基础特征
            features = self.orderbook.calculate_features()
            
            # 记录 OFI
            self.ofi_history.append(features.ofi_1s)
            self.ofi_timestamps.append(current_time)
            
            # 记录 Spread
            self.spread_history.append(features.spread_bps)
            
            # 记录深度
            self.depth_history.append({
                "bid_depth": features.bid_depth_5,
                "ask_depth": features.ask_depth_5,
                "time": current_time
            })
        
        except Exception as e:
            logger.error(f"❌ 更新特征失败: {e}")
    
    def get_ofi_trend(self, window: int = 10) -> str:
        """
        获取 OFI 趋势
        
        Args:
            window: 时间窗口（样本数）
        
        Returns:
            趋势方向 (rising/falling/stable)
        """
        try:
            if len(self.ofi_history) < window:
                return "stable"
            
            recent_ofi = list(self.ofi_history)[-window:]
            
            # 计算线性回归斜率
            x = np.arange(len(recent_ofi))
            y = np.array(recent_ofi)
            
            slope = np.polyfit(x, y, 1)[0]
            
            if slope > 0.01:
                return "rising"  # 买入压力增加
            elif slope < -0.01:
                return "falling"  # 卖出压力增加
            else:
                return "stable"
        
        except Exception as e:
            logger.error(f"❌ 计算 OFI 趋势失败: {e}")
            return "stable"
    
    def get_spread_status(self) -> str:
        """
        获取点差状态
        
        Returns:
            状态 (normal/wide/extreme)
        """
        try:
            features = self.orderbook.calculate_features()
            
            if features.spread_bps > 50:  # > 0.5%
                return "extreme"
            elif features.spread_bps > 20:  # > 0.2%
                return "wide"
            else:
                return "normal"
        
        except Exception as e:
            logger.error(f"❌ 获取点差状态失败: {e}")
            return "normal"
    
    def detect_liquidity_squeeze(self, threshold: float = 0.7) -> bool:
        """
        检测流动性挤压
        
        Args:
            threshold: 阈值
        
        Returns:
            是否检测到流动性挤压
        """
        try:
            features = self.orderbook.calculate_features()
            
            # 计算不平衡比例
            total_depth = features.bid_depth_5 + features.ask_depth_5
            
            if total_depth == 0:
                return False
            
            imbalance = abs(features.bid_depth_5 - features.ask_depth_5) / total_depth
            
            if imbalance > threshold:
                logger.warning(f"🔥 流动性挤压检测: 不平衡={imbalance:.2%}")
                return True
            
            return False
        
        except Exception as e:
            logger.error(f"❌ 检测流动性挤压失败: {e}")
            return False
    
    def detect_spoofing(self, levels: int = 10) -> Optional[Dict]:
        """
        检测诱单（Spoofing）
        
        特征：某个价位的大单突然撤单
        
        Args:
            levels: 检查档位数
        
        Returns:
            {"side": "bid"/"ask", "price": price} 或 None
        """
        try:
            if len(self.depth_history) < 5:
                return None
            
            # 检查买盘
            bids = self.orderbook.get_bids(levels)
            current_depth = {price: size for price, size in bids}
            
            prev_depth = self.depth_history[-5]["bid_depth"] if self.depth_history else 0
            
            # 简化检测：如果买一深度突然大幅减少
            if len(self.depth_history) >= 2:
                current_bid_depth = self.orderbook.get_best_bid()[1]
                prev_bid_depth = self.depth_history[-2]["bid_depth"]
                
                if prev_bid_depth > 10 and current_bid_depth < prev_bid_depth * 0.3:
                    logger.warning(f"🎭 检测到诱单: 买一深度大幅减少")
                    return {"side": "bid", "price": self.orderbook.get_best_bid()[0]}
            
            return None
        
        except Exception as e:
            logger.error(f"❌ 检测诱单失败: {e}")
            return None
    
    def calculate_pressure_index(self) -> Dict:
        """
        计算压力指数
        
        Returns:
            {"buy_pressure": float, "sell_pressure": float, "net_pressure": float}
        """
        try:
            features = self.orderbook.calculate_features()
            
            # 买入压力：OFI 为正
            buy_pressure = max(0, features.ofi_1s)
            
            # 卖出压力：OFI 为负
            sell_pressure = max(0, -features.ofi_1s)
            
            # 净压力
            net_pressure = buy_pressure - sell_pressure
            
            return {
                "buy_pressure": buy_pressure,
                "sell_pressure": sell_pressure,
                "net_pressure": net_pressure,
                "imbalance": features.ofi_1s / (features.bid_depth_5 + features.ask_depth_5) if (features.bid_depth_5 + features.ask_depth_5) > 0 else 0
            }
        
        except Exception as e:
            logger.error(f"❌ 计算压力指数失败: {e}")
            return {"buy_pressure": 0, "sell_pressure": 0, "net_pressure": 0, "imbalance": 0}
    
    def get_all_features(self) -> Dict:
        """
        获取所有特征
        
        Returns:
            特征字典
        """
        try:
            features = self.orderbook.calculate_features()
            
            return {
                "inst_id": self.inst_id,
                # 基础价格
                "best_bid": features.best_bid,
                "best_ask": features.best_ask,
                "mid_price": features.mid_price,
                "wmp": features.wmp,
                
                # 点差
                "spread": features.spread,
                "spread_bps": features.spread_bps,
                "spread_status": self.get_spread_status(),
                
                # OFI
                "ofi_1s": features.ofi_1s,
                "ofi_5s": features.ofi_5s,
                "ofi_trend": self.get_ofi_trend(),
                
                # 深度
                "bid_depth_5": features.bid_depth_5,
                "ask_depth_5": features.ask_depth_5,
                
                # 压力
                "pressure": self.calculate_pressure_index(),
                
                # 检测结果
                "has_wall": features.has_wall,
                "wall_side": features.wall_side,
                "wall_price": features.wall_price,
                "liquidity_voids": len(features.liquidity_void_above) + len(features.liquidity_void_below),
                "liquidity_squeeze": self.detect_liquidity_squeeze(),
                
                # 时间戳
                "timestamp": datetime.now().isoformat(),
            }
        
        except Exception as e:
            logger.error(f"❌ 获取所有特征失败: {e}")
            return {}


class MicrostructureAnalyzer:
    """
    市场微观结构分析器（单例）
    
    集成特征提取和赌徒行为识别
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化分析器"""
        if hasattr(self, '_initialized'):
            return
        
        self._initialized = True
        self.extractors: Dict[str, MicrostructureFeatures] = {}
        logger.info("🔬 市场微观结构分析器初始化完成")
    
    def get_or_create(self, inst_id: str, orderbook: ProfessionalOrderBook) -> MicrostructureFeatures:
        """获取或创建特征提取器"""
        if inst_id not in self.extractors:
            self.extractors[inst_id] = MicrostructureFeatures(inst_id, orderbook)
            logger.info(f"🔬 创建微观结构特征提取器: {inst_id}")
        
        return self.extractors[inst_id]
    
    def analyze(self, inst_id: str) -> Optional[Dict]:
        """
        分析市场微观结构
        
        Args:
            inst_id: 产品 ID
        
        Returns:
            分析结果
        """
        try:
            if inst_id not in self.extractors:
                return None
            
            extractor = self.extractors[inst_id]
            extractor.update()
            
            features = extractor.get_all_features()
            
            # 添加赌徒行为识别
            gambler_signals = self._identify_gambler_behavior(features)
            
            features["gambler_signals"] = gambler_signals
            
            return features
        
        except Exception as e:
            logger.error(f"❌ 分析微观结构失败: {e}")
            return None
    
    def _identify_gambler_behavior(self, features: Dict) -> Dict:
        """
        识别赌徒行为
        
        Args:
            features: 特征数据
        
        Returns:
            赌徒行为信号
        """
        try:
            signals = {
                "panic_selling": False,
                "fomo_buying": False,
                "chasing_rally": False,
                "panic_covering": False,
                "reason": []
            }
            
            # 恐慌抛售
            if (features["spread_status"] == "extreme" and 
                features["pressure"]["sell_pressure"] > 100 and
                features["ofi_trend"] == "falling"):
                signals["panic_selling"] = True
                signals["reason"].append("恐慌抛售：点差扩大，卖出压力剧增")
            
            # FOMO 买入
            if (features["spread_status"] == "wide" and 
                features["pressure"]["buy_pressure"] > 100 and
                features["ofi_trend"] == "rising"):
                signals["fomo_buying"] = True
                signals["reason"].append("FOMO 买入：点差扩大，买入压力剧增")
            
            # 追涨
            if (features["wmp"] > features["mid_price"] * 1.001 and 
                features["ofi_1s"] > 50):
                signals["chasing_rally"] = True
                signals["reason"].append("追涨：WMP 高于中间价，买入强劲")
            
            # 恐慌平仓
            if (features["spread_status"] == "extreme" and 
                features["pressure"]["buy_pressure"] > 100 and
                features["ofi_trend"] == "rising"):
                signals["panic_covering"] = True
                signals["reason"].append("恐慌平仓：空单恐慌平仓")
            
            return signals
        
        except Exception as e:
            logger.error(f"❌ 识别赌徒行为失败: {e}")
            return {"panic_selling": False, "fomo_buying": False, "reason": []}


# 全局分析器实例
microstructure_analyzer = MicrostructureAnalyzer()


if __name__ == "__main__":
    # 测试微观结构分析
    async def test():
        from orderbook.pro_orderbook import pro_orderbook_manager
        
        # 创建订单簿
        orderbook = pro_orderbook_manager.get_or_create("BTC-USDT")
        
        # 创建特征提取器
        analyzer = MicrostructureAnalyzer()
        extractor = analyzer.get_or_create("BTC-USDT", orderbook)
        
        # 更新快照
        snapshot = {
            "bids": [[50000, "100", "50"], [49995, "50", "25"]],
            "asks": [[50010, "10", "5"], [50015, "20", "10"]],
            "checksum": 12345
        }
        
        await orderbook.update_snapshot(snapshot)
        
        # 提取特征
        features = extractor.get_all_features()
        print("特征:", features)
    
    asyncio.run(test())
