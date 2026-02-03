"""
WebSocket 数据流模块
实时监听市场数据，毫秒级响应
"""

import asyncio
import json
import websockets
from typing import Callable, Dict, List, Optional
from datetime import datetime

from utils.logger import logger
from utils.config import Config


class WebSocketStreamer:
    """WebSocket 实时数据流"""
    
    def __init__(self):
        """初始化 WebSocket 流"""
        # 根据交易模式选择 WebSocket 地址
        if Config.TRADING_MODE == "paper":
            # 模拟盘地址
            # 注意：模拟盘可能不支持公共频道，需要使用私有频道连接
            self.ws_url = "wss://wspap.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://wspap.okx.com:8443/ws/v5/private"
            self.use_private_channel = True  # 模拟盘使用私有频道
            logger.info("🧪 使用模拟盘 WebSocket 地址（私有频道）")
        else:
            # 实盘地址
            self.ws_url = "wss://ws.okx.com:8443/ws/v5/public"
            self.ws_private_url = "wss://ws.okx.com:8443/ws/v5/private"
            self.use_private_channel = False  # 实盘使用公共频道
            logger.info("💼 使用实盘 WebSocket 地址（公共频道）")

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.running = False

        # 记录当前的连接类型（用于重连）
        self.current_private = False

        # 回调函数
        self.callbacks: Dict[str, List[Callable]] = {
            "ticker": [],
            "orderbook": [],
            "trades": [],
            "liquidation": [],
            "account": [],
            "orders": [],
        }

        # 订阅的频道
        self.subscriptions: List[str] = []

        logger.info("🔌 WebSocket 流初始化完成")
    
    def register_callback(self, channel: str, callback: Callable):
        """
        注册回调函数
        
        Args:
            channel: 频道名称 (ticker/orderbook/trades/liquidation/account/orders)
            callback: 回调函数
        """
        if channel in self.callbacks:
            self.callbacks[channel].append(callback)
            logger.info(f"📝 注册回调: {channel}")
        else:
            logger.warning(f"⚠️  未知频道: {channel}")
    
    async def connect(self, private: bool = False):
        """
        连接 WebSocket

        Args:
            private: 是否连接私有频道（需要签名）
        """
        # 模拟盘必须使用私有频道（公共频道也需要认证）
        if Config.TRADING_MODE == "paper":
            private = True

        url = self.ws_private_url if private else self.ws_url

        try:
            logger.info(f"🔗 连接 WebSocket: {url}")
            self.ws = await websockets.connect(url)
            self.current_private = private  # 记录连接类型
            self.running = True
            logger.info("✅ WebSocket 连接成功")

            # 如果是私有频道，需要认证
            if private:
                await self._authenticate()
        
        except Exception as e:
            logger.error(f"❌ WebSocket 连接失败: {e}")
            raise
    
    async def _authenticate(self):
        """私有频道认证"""
        try:
            # 生成登录消息（使用毫秒级时间戳）
            timestamp = str(int(datetime.now().timestamp() * 1000))
            sign = self._generate_sign(timestamp, "GET", "/users/self/verify")
            
            auth_msg = {
                "op": "login",
                "args": [{
                    "apiKey": Config.API_KEY,
                    "passphrase": Config.PASSPHRASE,
                    "timestamp": timestamp,
                    "sign": sign
                }]
            }
            
            logger.info(f"🔐 发送认证消息: {auth_msg}")
            await self.ws.send(json.dumps(auth_msg))
            
            # 等待认证响应
            response = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = json.loads(response)
            
            logger.info(f"📥 认证响应: {data}")
            
            if data.get("event") == "login" and data.get("code") == "0":
                logger.info("✅ 认证成功")
            else:
                logger.error(f"❌ 认证失败: {data}")
                raise Exception(f"WebSocket 认证失败: {data}")
        
        except asyncio.TimeoutError:
            logger.error("❌ 认证超时")
            raise
    
    def _generate_sign(self, timestamp: str, method: str, request_path: str) -> str:
        """生成签名"""
        import hmac
        import base64
        import hashlib
        
        # 签名格式: timestamp + method + request_path
        message = timestamp + method + request_path
        logger.debug(f"🔑 签名输入: {message}")
        
        mac = hmac.new(
            bytes(Config.SECRET_KEY, encoding="utf8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    async def subscribe(self, channels: List[Dict]):
        """
        订阅频道
        
        Args:
            channels: 频道列表
                [{"channel": "tickers", "instId": "BTC-USDT"}]
        """
        if not self.ws:
            logger.error("❌ WebSocket 未连接")
            return
        
        sub_msg = {
            "op": "subscribe",
            "args": channels
        }
        
        try:
            await self.ws.send(json.dumps(sub_msg))
            self.subscriptions.extend(channels)
            logger.info(f"📡 订阅频道: {[c['channel'] for c in channels]}")
        except Exception as e:
            logger.error(f"❌ 订阅失败: {e}")
    
    async def unsubscribe(self, channels: List[Dict]):
        """
        取消订阅
        
        Args:
            channels: 频道列表
        """
        if not self.ws:
            return
        
        unsub_msg = {
            "op": "unsubscribe",
            "args": channels
        }
        
        try:
            await self.ws.send(json.dumps(unsub_msg))
            logger.info(f"📡 取消订阅: {[c['channel'] for c in channels]}")
        except Exception as e:
            logger.error(f"❌ 取消订阅失败: {e}")
    
    async def listen(self):
        """监听 WebSocket 消息"""
        if not self.ws:
            logger.error("❌ WebSocket 未连接")
            return
        
        logger.info("👂 开始监听 WebSocket 消息...")
        
        try:
            while self.running:
                try:
                    message = await asyncio.wait_for(self.ws.recv(), timeout=30)
                    data = json.loads(message)
                    await self._handle_message(data)
                
                except asyncio.TimeoutError:
                    # 发送 ping 保持连接
                    await self.ws.ping()
                    logger.debug("💓 发送 ping")
                
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("⚠️  WebSocket 连接关闭，尝试重连...")
                    await self._reconnect()
        
        except Exception as e:
            logger.error(f"❌ 监听异常: {e}")
    
    async def _handle_message(self, data: dict):
        """处理接收到的消息"""
        try:
            # 处理频道数据
            if "data" in data and "arg" in data:
                channel = data["arg"]["channel"]
                payload = data["data"]
                
                # 触发对应的回调
                if channel == "tickers" and "ticker" in self.callbacks:
                    for callback in self.callbacks["ticker"]:
                        await callback(payload)
                
                elif channel == "books" and "orderbook" in self.callbacks:
                    for callback in self.callbacks["orderbook"]:
                        await callback(payload)
                
                elif channel == "trades" and "trades" in self.callbacks:
                    for callback in self.callbacks["trades"]:
                        await callback(payload)
                
                elif channel == "liquidation-orders" and "liquidation" in self.callbacks:
                    for callback in self.callbacks["liquidation"]:
                        await callback(payload)
                
                elif channel == "account" and "account" in self.callbacks:
                    for callback in self.callbacks["account"]:
                        await callback(payload)
                
                elif channel == "orders" and "orders" in self.callbacks:
                    for callback in self.callbacks["orders"]:
                        await callback(payload)
            
            # 处理事件消息
            elif "event" in data:
                if data["event"] == "subscribe":
                    logger.debug(f"✓ 订阅确认: {data}")
                elif data["event"] == "unsubscribe":
                    logger.debug(f"✓ 取消订阅确认: {data}")
                elif data["event"] == "error":
                    logger.error(f"❌ WebSocket 错误: {data}")
        
        except Exception as e:
            logger.error(f"❌ 处理消息失败: {e}")
    
    async def _reconnect(self):
        """重新连接"""
        logger.info("🔄 开始重连...")

        # 等待一段时间
        await asyncio.sleep(Config.WS_RECONNECT_DELAY)

        try:
            # 关闭旧连接
            if self.ws:
                await self.ws.close()

            # 重新连接（使用之前记录的连接类型）
            await self.connect(private=self.current_private)

            # 重新订阅频道
            if self.subscriptions:
                await self.subscribe(self.subscriptions)

            logger.info("✅ 重连成功")

        except Exception as e:
            logger.error(f"❌ 重连失败: {e}")
    
    async def close(self):
        """关闭连接"""
        logger.info("🔌 关闭 WebSocket 连接...")
        self.running = False
        
        if self.ws:
            await self.ws.close()
            logger.info("✅ WebSocket 已关闭")
    
    @staticmethod
    async def stream_tickers(inst_ids: List[str], callback: Callable):
        """
        便捷方法：监听行情
        
        Args:
            inst_ids: 交易对列表 ["BTC-USDT", "ETH-USDT"]
            callback: 回调函数
        """
        streamer = WebSocketStreamer()
        
        await streamer.connect()
        await streamer.subscribe([{
            "channel": "tickers",
            "instId": ",".join(inst_ids)
        }])
        
        streamer.register_callback("ticker", callback)
        await streamer.listen()
    
    @staticmethod
    async def stream_orderbook(inst_id: str, callback: Callable, book_type: str = "books"):
        """
        便捷方法：监听深度
        
        Args:
            inst_id: 交易对
            callback: 回调函数
            book_type: 深度类型 (books5/books-l2-tbt/books)
        """
        streamer = WebSocketStreamer()
        
        await streamer.connect()
        await streamer.subscribe([{
            "channel": book_type,
            "instId": inst_id
        }])
        
        streamer.register_callback("orderbook", callback)
        await streamer.listen()


if __name__ == "__main__":
    # 测试 WebSocket
    async def test_ticker(data):
        logger.log_market_data("BTC-USDT", "ticker", data)
    
    async def test_orderbook(data):
        logger.log_market_data("BTC-USDT", "orderbook", data)
    
    async def main():
        # 测试行情
        logger.info("🧪 测试 WebSocket 行情流...")
        await WebSocketStreamer.stream_tickers(["BTC-USDT"], test_ticker)
    
    # asyncio.run(main())
