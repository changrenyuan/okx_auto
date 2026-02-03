"""
执行引擎
负责下单、撤单、追单等执行逻辑
支持 Post-Only、IOC、TWAP 等订单类型
"""

import asyncio
import hmac
import base64
import hashlib
import json
import time
from typing import Dict, Optional, List
from datetime import datetime
import aiohttp

from utils.logger import logger
from utils.config import Config


class ExecutionEngine:
    """执行引擎 - 高效执行交易信号"""
    
    def __init__(self):
        """初始化执行引擎"""
        self.base_url = Config.BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
        self.order_queue = asyncio.Queue()
        self.running = False
        
        # 网络延迟监控
        self.latency_samples = []
        self.max_latency_ms = 100  # 最大允许延迟（毫秒）
        self.kill_switch_enabled = True
        
        # 限流控制
        self.rate_limit_remaining = 20
        self.rate_limit_reset = time.time()
        
        logger.info("🎯 执行引擎初始化完成")
    
    async def start(self):
        """启动执行引擎"""
        if self.running:
            logger.warning("⚠️  执行引擎已在运行")
            return
        
        logger.info("🚀 启动执行引擎...")
        self.session = aiohttp.ClientSession()
        self.running = True
        
        # 启动订单处理任务
        asyncio.create_task(self._process_orders())
        
        logger.info("✅ 执行引擎已启动")
    
    async def stop(self):
        """停止执行引擎"""
        logger.info("🛑 停止执行引擎...")
        self.running = False
        
        if self.session:
            await self.session.close()
            logger.info("✅ 执行引擎已停止")
    
    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成签名"""
        if not body:
            body = ""
        
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            bytes(Config.SECRET_KEY, encoding="utf8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()
    
    async def _request(
        self,
        method: str,
        path: str,
        params: Dict = None,
        body: Dict = None
    ) -> Dict:
        """
        发送 HTTP 请求
        
        Args:
            method: 请求方法
            path: 请求路径
            params: URL 参数
            body: 请求体
        
        Returns:
            响应数据
        """
        # 检查 Kill Switch
        if self.kill_switch_enabled and self._check_kill_switch():
            logger.critical("🚨 Kill Switch 已触发，拒绝请求")
            raise Exception("Kill Switch triggered")
        
        # 记录开始时间
        start_time = time.time()
        
        timestamp = str(int(time.time()))
        url = self.base_url + path
        
        # 准备请求体
        body_str = json.dumps(body) if body else ""
        
        # 生成签名
        sign_str = self._sign(timestamp, method, path, body_str)
        
        # 请求头
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": Config.API_KEY,
            "OK-ACCESS-SIGN": sign_str,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": Config.PASSPHRASE,
        }
        
        # 记录请求
        logger.log_api_request(method, path, params, body)
        
        try:
            if method == "GET":
                async with self.session.get(url, params=params, headers=headers) as response:
                    result = await response.json()
                    logger.log_api_response(method, path, response.status, result)
                    return result
            
            elif method == "POST":
                async with self.session.post(url, data=body_str, headers=headers) as response:
                    result = await response.json()
                    logger.log_api_response(method, path, response.status, result)
                    return result
            
            elif method == "DELETE":
                async with self.session.delete(url, data=body_str, headers=headers) as response:
                    result = await response.json()
                    logger.log_api_response(method, path, response.status, result)
                    return result
        
        except aiohttp.ClientError as e:
            logger.error(f"❌ 请求失败: {e}")
            raise
        finally:
            # 记录延迟
            latency = (time.time() - start_time) * 1000  # 毫秒
            self.latency_samples.append(latency)
            if len(self.latency_samples) > 100:
                self.latency_samples.pop(0)
    
    def _check_kill_switch(self) -> bool:
        """
        检查是否需要触发 Kill Switch
        
        Returns:
            是否触发
        """
        if not self.latency_samples:
            return False
        
        avg_latency = sum(self.latency_samples) / len(self.latency_samples)
        
        if avg_latency > self.max_latency_ms:
            logger.critical(f"🚨 网络延迟过高: {avg_latency:.1f}ms > {self.max_latency_ms}ms")
            return True
        
        return False
    
    async def _process_orders(self):
        """处理订单队列"""
        logger.info("📋 订单处理任务已启动")
        
        while self.running:
            try:
                # 从队列获取订单
                order = await asyncio.wait_for(self.order_queue.get(), timeout=1.0)
                
                # 执行订单
                await self._execute_order(order)
            
            except asyncio.TimeoutError:
                continue
            
            except Exception as e:
                logger.error(f"❌ 处理订单异常: {e}")
    
    async def _execute_order(self, order: Dict):
        """
        执行订单
        
        Args:
            order: 订单信息
        """
        try:
            logger.log_order("place", order)
            
            # 发送订单请求
            response = await self._request("POST", "/api/v5/trade/order", body=order)
            
            if response.get("code") == "0" and response.get("data"):
                order_data = response["data"][0]
                order_id = order_data["ordId"]
                logger.info(f"✅ 订单已提交: {order_id}")
                
                # 返回订单 ID
                return order_id
            
            else:
                error_msg = response.get("msg", "未知错误")
                logger.error(f"❌ 下单失败: {error_msg}")
                return None
        
        except Exception as e:
            logger.error(f"❌ 执行订单异常: {e}")
            return None
    
    async def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        px: Optional[str] = None,
        td_mode: str = "cash",
        ccy: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
        reduce_only: bool = False,
        attach_ord_algo: Optional[Dict] = None
    ) -> Optional[str]:
        """
        下单
        
        Args:
            inst_id: 产品 ID
            side: 订单方向 (buy/sell)
            ord_type: 订单类型 (market/limit/post_only/fok/ioc)
            sz: 委托数量
            px: 委托价格（限价单必填）
            td_mode: 交易模式 (cash/cross/isolated)
            ccy: 保证金币种
            cl_ord_id: 客户自定义订单 ID
            reduce_only: 是否仅减仓
            attach_ord_algo: 止损止盈参数
        
        Returns:
            订单 ID
        """
        body = {
            "instId": inst_id,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "tdMode": td_mode,
        }
        
        if px:
            body["px"] = px
        if ccy:
            body["ccy"] = ccy
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        if reduce_only:
            body["reduceOnly"] = "true"
        if attach_ord_algo:
            body["attachAlgoOrds"] = [attach_ord_algo]
        
        # 添加到队列
        await self.order_queue.put(body)
        
        logger.info(f"📌 订单已加入队列: {side} {sz} {inst_id} @ {px}")
    
    async def place_post_only_order(
        self,
        inst_id: str,
        side: str,
        sz: str,
        px: str
    ) -> Optional[str]:
        """
        下 Post-Only 订单（只做 Maker）
        
        优势：
        - 只做 Maker，赚取手续费返佣（Rebate）
        - 避免吃单成本
        
        Args:
            inst_id: 产品 ID
            side: 订单方向
            sz: 委托数量
            px: 委托价格
        
        Returns:
            订单 ID
        """
        return await self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="post_only",
            sz=sz,
            px=px
        )
    
    async def place_ioc_order(
        self,
        inst_id: str,
        side: str,
        sz: str,
        px: Optional[str] = None
    ) -> Optional[str]:
        """
        下 IOC 订单（立即成交或取消）
        
        优势：
        - 要么全吃，要么撤销
        - 防止只吃了一半被挂在山顶
        
        Args:
            inst_id: 产品 ID
            side: 订单方向
            sz: 委托数量
            px: 委托价格（可选，不填则为市价）
        
        Returns:
            订单 ID
        """
        return await self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="ioc",
            sz=sz,
            px=px
        )
    
    async def place_fok_order(
        self,
        inst_id: str,
        side: str,
        sz: str,
        px: str
    ) -> Optional[str]:
        """
        下 FOK 订单（全部成交或取消）
        
        优势：
        - 只有完全成交才会接受
        - 避免部分成交
        
        Args:
            inst_id: 产品 ID
            side: 订单方向
            sz: 委托数量
            px: 委托价格
        
        Returns:
            订单 ID
        """
        return await self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="fok",
            sz=sz,
            px=px
        )
    
    async def place_twap_order(
        self,
        inst_id: str,
        side: str,
        total_sz: str,
        num_slices: int = 10,
        interval: int = 1
    ) -> List[str]:
        """
        下 TWAP 订单（时间加权平均价格）
        
        优势：
        - 将大单切碎，避免冲击市场
        - 不惊动赌徒
        
        Args:
            inst_id: 产品 ID
            side: 订单方向
            total_sz: 总数量
            num_slices: 切片数量
            interval: 间隔（秒）
        
        Returns:
            订单 ID 列表
        """
        try:
            slice_sz = float(total_sz) / num_slices
            order_ids = []
            
            for i in range(num_slices):
                # 市价单
                order_id = await self.place_order(
                    inst_id=inst_id,
                    side=side,
                    ord_type="market",
                    sz=str(slice_sz)
                )
                
                if order_id:
                    order_ids.append(order_id)
                
                if i < num_slices - 1:
                    await asyncio.sleep(interval)
            
            logger.info(f"📊 TWAP 订单已提交: {len(order_ids)}/{num_slices} 个切片")
            return order_ids
        
        except Exception as e:
            logger.error(f"❌ TWAP 订单失败: {e}")
            return []
    
    async def cancel_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> bool:
        """
        撤销订单
        
        Args:
            inst_id: 产品 ID
            ord_id: 订单 ID
            cl_ord_id: 客户自定义订单 ID
        
        Returns:
            是否成功
        """
        body = {"instId": inst_id}
        
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        
        logger.log_order("cancel", body)
        
        try:
            response = await self._request("POST", "/api/v5/trade/cancel-order", body=body)
            
            if response.get("code") == "0":
                logger.info(f"✅ 撤单成功")
                return True
            else:
                logger.error(f"❌ 撤单失败: {response.get('msg')}")
                return False
        
        except Exception as e:
            logger.error(f"❌ 撤单异常: {e}")
            return False
    
    async def cancel_all_orders(self, inst_id: str) -> int:
        """
        撤销所有订单
        
        Args:
            inst_id: 产品 ID
        
        Returns:
            成功撤销的数量
        """
        try:
            body = {"instId": inst_id}
            
            response = await self._request("POST", "/api/v5/trade/cancel-batch-orders", body=body)
            
            if response.get("code") == "0" and response.get("data"):
                success_count = len([r for r in response["data"] if r["sCode"] == "0"])
                logger.info(f"✅ 批量撤单成功: {success_count} 个")
                return success_count
            else:
                logger.error(f"❌ 批量撤单失败: {response.get('msg')}")
                return 0
        
        except Exception as e:
            logger.error(f"❌ 批量撤单异常: {e}")
            return 0
    
    async def get_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> Optional[Dict]:
        """
        查询订单详情
        
        Args:
            inst_id: 产品 ID
            ord_id: 订单 ID
            cl_ord_id: 客户自定义订单 ID
        
        Returns:
            订单信息
        """
        params = {"instId": inst_id}
        
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        
        try:
            response = await self._request("GET", "/api/v5/trade/order", params=params)
            
            if response.get("code") == "0" and response.get("data"):
                return response["data"][0]
            else:
                return None
        
        except Exception as e:
            logger.error(f"❌ 查询订单异常: {e}")
            return None
    
    async def get_balance(self, ccy: str = None) -> Optional[Dict]:
        """
        查询账户余额
        
        Args:
            ccy: 币种
        
        Returns:
            余额信息
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        
        try:
            response = await self._request("GET", "/api/v5/account/balance", params=params)
            
            if response.get("code") == "0" and response.get("data"):
                return response["data"][0]
            else:
                return None
        
        except Exception as e:
            logger.error(f"❌ 查询余额异常: {e}")
            return None
    
    async def get_positions(self, inst_type: str = None, inst_id: str = None) -> List[Dict]:
        """
        查询持仓
        
        Args:
            inst_type: 产品类型
            inst_id: 产品 ID
        
        Returns:
            持仓列表
        """
        params = {}
        if inst_type:
            params["instType"] = inst_type
        if inst_id:
            params["instId"] = inst_id
        
        try:
            response = await self._request("GET", "/api/v5/account/positions", params=params)
            
            if response.get("code") == "0":
                return response.get("data", [])
            else:
                return []
        
        except Exception as e:
            logger.error(f"❌ 查询持仓异常: {e}")
            return []
    
    def get_avg_latency(self) -> float:
        """获取平均延迟（毫秒）"""
        if not self.latency_samples:
            return 0.0
        
        return sum(self.latency_samples) / len(self.latency_samples)
    
    def enable_kill_switch(self):
        """启用 Kill Switch"""
        self.kill_switch_enabled = True
        logger.warning("⚠️  Kill Switch 已启用")
    
    def disable_kill_switch(self):
        """禁用 Kill Switch"""
        self.kill_switch_enabled = False
        logger.info("✅ Kill Switch 已禁用")
    
    async def _process_orders(self):
        """处理订单队列"""
        logger.info("📋 订单处理任务已启动")
        
        while self.running:
            try:
                # 从队列获取订单
                order = await asyncio.wait_for(self.order_queue.get(), timeout=1.0)
                
                # 执行订单
                await self._execute_order(order)
            
            except asyncio.TimeoutError:
                continue
            
            except Exception as e:
                logger.error(f"❌ 处理订单异常: {e}")
    
    async def _execute_order(self, order: Dict):
        """
        执行订单
        
        Args:
            order: 订单信息
        """
        try:
            logger.log_order("place", order)
            
            # 发送订单请求
            response = await self._request("POST", "/api/v5/trade/order", body=order)
            
            if response.get("code") == "0" and response.get("data"):
                order_data = response["data"][0]
                order_id = order_data["ordId"]
                logger.info(f"✅ 订单已提交: {order_id}")
                
                # 返回订单 ID
                return order_id
            
            else:
                error_msg = response.get("msg", "未知错误")
                logger.error(f"❌ 下单失败: {error_msg}")
                return None
        
        except Exception as e:
            logger.error(f"❌ 执行订单异常: {e}")
            return None
    
    async def place_order(
        self,
        inst_id: str,
        side: str,
        ord_type: str,
        sz: str,
        px: Optional[str] = None,
        td_mode: str = "cash",
        ccy: Optional[str] = None,
        cl_ord_id: Optional[str] = None,
        reduce_only: bool = False,
        attach_ord_algo: Optional[Dict] = None
    ) -> Optional[str]:
        """
        下单
        
        Args:
            inst_id: 产品 ID
            side: 订单方向 (buy/sell)
            ord_type: 订单类型 (market/limit/post_only/fok/ioc)
            sz: 委托数量
            px: 委托价格（限价单必填）
            td_mode: 交易模式 (cash/cross/isolated)
            ccy: 保证金币种
            cl_ord_id: 客户自定义订单 ID
            reduce_only: 是否仅减仓
            attach_ord_algo: 止损止盈参数
        
        Returns:
            订单 ID
        """
        body = {
            "instId": inst_id,
            "side": side,
            "ordType": ord_type,
            "sz": sz,
            "tdMode": td_mode,
        }
        
        if px:
            body["px"] = px
        if ccy:
            body["ccy"] = ccy
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        if reduce_only:
            body["reduceOnly"] = "true"
        if attach_ord_algo:
            body["attachAlgoOrds"] = [attach_ord_algo]
        
        # 添加到队列
        await self.order_queue.put(body)
        
        logger.info(f"📌 订单已加入队列: {side} {sz} {inst_id} @ {px}")
    
    async def cancel_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> bool:
        """
        撤销订单
        
        Args:
            inst_id: 产品 ID
            ord_id: 订单 ID
            cl_ord_id: 客户自定义订单 ID
        
        Returns:
            是否成功
        """
        body = {"instId": inst_id}
        
        if ord_id:
            body["ordId"] = ord_id
        if cl_ord_id:
            body["clOrdId"] = cl_ord_id
        
        logger.log_order("cancel", body)
        
        try:
            response = await self._request("POST", "/api/v5/trade/cancel-order", body=body)
            
            if response.get("code") == "0":
                logger.info(f"✅ 撤单成功")
                return True
            else:
                logger.error(f"❌ 撤单失败: {response.get('msg')}")
                return False
        
        except Exception as e:
            logger.error(f"❌ 撤单异常: {e}")
            return False
    
    async def get_order(self, inst_id: str, ord_id: str = None, cl_ord_id: str = None) -> Optional[Dict]:
        """
        查询订单详情
        
        Args:
            inst_id: 产品 ID
            ord_id: 订单 ID
            cl_ord_id: 客户自定义订单 ID
        
        Returns:
            订单信息
        """
        params = {"instId": inst_id}
        
        if ord_id:
            params["ordId"] = ord_id
        if cl_ord_id:
            params["clOrdId"] = cl_ord_id
        
        try:
            response = await self._request("GET", "/api/v5/trade/order", params=params)
            
            if response.get("code") == "0" and response.get("data"):
                return response["data"][0]
            else:
                return None
        
        except Exception as e:
            logger.error(f"❌ 查询订单异常: {e}")
            return None
    
    async def get_balance(self, ccy: str = None) -> Optional[Dict]:
        """
        查询账户余额
        
        Args:
            ccy: 币种
        
        Returns:
            余额信息
        """
        params = {}
        if ccy:
            params["ccy"] = ccy
        
        try:
            response = await self._request("GET", "/api/v5/account/balance", params=params)
            
            if response.get("code") == "0" and response.get("data"):
                return response["data"][0]
            else:
                return None
        
        except Exception as e:
            logger.error(f"❌ 查询余额异常: {e}")
            return None
    
    async def get_positions(self, inst_type: str = None, inst_id: str = None) -> List[Dict]:
        """
        查询持仓
        
        Args:
            inst_type: 产品类型
            inst_id: 产品 ID
        
        Returns:
            持仓列表
        """
        params = {}
        if inst_type:
            params["instType"] = inst_type
        if inst_id:
            params["instId"] = inst_id
        
        try:
            response = await self._request("GET", "/api/v5/account/positions", params=params)
            
            if response.get("code") == "0":
                return response.get("data", [])
            else:
                return []
        
        except Exception as e:
            logger.error(f"❌ 查询持仓异常: {e}")
            return []
    
    # ========== 执行策略方法 ==========
    
    async def execute_liquidity_hunt(self, inst_id: str, side: str, price: float, size: float):
        """
        执行爆仓单捕猎策略
        快速成交，不挂单
        
        Args:
            inst_id: 产品 ID
            side: 方向
            price: 目标价格
            size: 数量
        """
        logger.info(f"🎯 执行爆仓单捕猎: {side} {size} {inst_id} @ {price}")
        
        # 使用市价单快速成交
        order_id = await self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="market",
            sz=str(size)
        )
        
        if order_id:
            logger.info(f"✅ 爆仓单捕猎订单已提交: {order_id}")
        else:
            logger.error(f"❌ 爆仓单捕猎失败")
    
    async def execute_funding_arbitrage(self, inst_id: str, size: float):
        """
        执行资金费率套利策略
        现货买入 + 合约做空
        
        Args:
            inst_id: 产品 ID
            size: 数量
        """
        logger.info(f"💰 执行资金费率套利: {size} {inst_id}")
        
        # 1. 现货买入
        order_id_spot = await self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=str(size)
        )
        
        if not order_id_spot:
            logger.error(f"❌ 现货买入失败")
            return
        
        # 2. 合约做空（需要等待现货成交）
        await asyncio.sleep(1)
        
        # 合约交易对通常是 BTC-USDT-SWAP
        swap_inst_id = inst_id.replace("-USDT", "-USDT-SWAP")
        
        order_id_swap = await self.place_order(
            inst_id=swap_inst_id,
            side="sell",
            ord_type="market",
            sz=str(size),
            td_mode="cross"
        )
        
        if order_id_swap:
            logger.info(f"✅ 资金费率套利对冲完成")
        else:
            logger.error(f"❌ 合约做空失败，需要手动平仓现货")


if __name__ == "__main__":
    # 测试执行引擎
    async def test():
        engine = ExecutionEngine()
        await engine.start()
        
        # 查询余额
        balance = await engine.get_balance()
        logger.info(f"余额: {balance}")
        
        # 下测试订单（需要配置 API）
        # await engine.place_order(
        #     inst_id="BTC-USDT",
        #     side="buy",
        #     ord_type="limit",
        #     sz="0.001",
        #     px="30000"
        # )
        
        await asyncio.sleep(5)
        await engine.stop()
    
    # asyncio.run(test())
    
    async def execute_liquidity_hunt(self, inst_id: str, side: str, price: float, size: float):
        """
        执行爆仓单捕猎策略
        快速成交，不挂单
        
        Args:
            inst_id: 产品 ID
            side: 方向
            price: 目标价格
            size: 数量
        """
        logger.info(f"🎯 执行爆仓单捕猎: {side} {size} {inst_id} @ {price}")
        
        # 使用市价单快速成交
        order_id = await self.place_order(
            inst_id=inst_id,
            side=side,
            ord_type="market",
            sz=str(size)
        )
        
        if order_id:
            logger.info(f"✅ 爆仓单捕猎订单已提交: {order_id}")
        else:
            logger.error(f"❌ 爆仓单捕猎失败")
    
    async def execute_funding_arbitrage(self, inst_id: str, size: float):
        """
        执行资金费率套利策略
        现货买入 + 合约做空
        
        Args:
            inst_id: 产品 ID
            size: 数量
        """
        logger.info(f"💰 执行资金费率套利: {size} {inst_id}")
        
        # 1. 现货买入
        order_id_spot = await self.place_order(
            inst_id=inst_id,
            side="buy",
            ord_type="market",
            sz=str(size)
        )
        
        if not order_id_spot:
            logger.error(f"❌ 现货买入失败")
            return
        
        # 2. 合约做空（需要等待现货成交）
        await asyncio.sleep(1)
        
        # 合约交易对通常是 BTC-USDT-SWAP
        swap_inst_id = inst_id.replace("-USDT", "-USDT-SWAP")
        
        order_id_swap = await self.place_order(
            inst_id=swap_inst_id,
            side="sell",
            ord_type="market",
            sz=str(size),
            td_mode="cross"
        )
        
        if order_id_swap:
            logger.info(f"✅ 资金费率套利对冲完成")
        else:
            logger.error(f"❌ 合约做空失败，需要手动平仓现货")
