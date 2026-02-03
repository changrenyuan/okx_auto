"""
简单的 API 测试脚本
测试登录、账户信息、持仓等基础功能
"""

import os
import requests
import json
import hmac
import base64
import hashlib
import time
from datetime import datetime


class OKXTestClient:
    """OKX API 测试客户端"""

    def __init__(self):
        """初始化客户端"""
        self.api_key = os.getenv('OKX_API_KEY', '46bc0312-6920-415a-91c6-5fd0e44595ea')
        self.secret_key = os.getenv('OKX_SECRET_KEY', '8D7A8E1471B9C0881B0D8F5802CDB870')
        self.passphrase = os.getenv('OKX_PASSPHRASE', '2011WHUcry*')
        self.base_url = os.getenv('OKX_BASE_URL', 'https://www.okx.com')

        # 代理设置
        http_proxy = os.getenv('HTTP_PROXY')
        https_proxy = os.getenv('HTTPS_PROXY')

        self.proxies = None
        if http_proxy or https_proxy:
            self.proxies = {
                'http': http_proxy or https_proxy,
                'https': https_proxy or http_proxy
            }
            print(f"✅ 使用代理: {self.proxies}")
        else:
            print("⚠️  未检测到代理设置")

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """生成签名"""
        message = timestamp + method.upper() + request_path + body
        mac = hmac.new(
            bytes(self.secret_key, encoding="utf8"),
            bytes(message, encoding="utf-8"),
            digestmod=hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _request(self, method: str, path: str, params: dict = None, body: dict = None) -> dict:
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
        timestamp = str(int(time.time()))
        url = self.base_url + path
        body_str = json.dumps(body) if body else ""

        # 生成签名
        sign_str = self._sign(timestamp, method, path, body_str)

        # 请求头
        headers = {
            "Content-Type": "application/json",
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": sign_str,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
        }

        print(f"\n📡 请求: {method} {url}")
        print(f"📋 参数: {params}")
        if body:
            print(f"📦 请求体: {body}")

        try:
            if method == "GET":
                response = requests.get(url, params=params, headers=headers, proxies=self.proxies, timeout=10)
            elif method == "POST":
                response = requests.post(url, data=body_str, headers=headers, proxies=self.proxies, timeout=10)
            elif method == "DELETE":
                response = requests.delete(url, data=body_str, headers=headers, proxies=self.proxies, timeout=10)

            result = response.json()
            print(f"✅ 状态码: {response.status_code}")
            print(f"📥 响应: {json.dumps(result, indent=2, ensure_ascii=False)}")

            return result

        except requests.exceptions.ProxyError as e:
            print(f"❌ 代理错误: {e}")
            raise
        except requests.exceptions.ConnectTimeout as e:
            print(f"❌ 连接超时: {e}")
            raise
        except requests.exceptions.SSLError as e:
            print(f"❌ SSL 错误: {e}")
            raise
        except Exception as e:
            print(f"❌ 请求失败: {e}")
            raise

    def test_server_time(self):
        """测试 1: 获取服务器时间（不需要认证）"""
        print("\n" + "=" * 60)
        print("🧪 测试 1: 获取服务器时间")
        print("=" * 60)

        try:
            result = self._request("GET", "/api/v5/public/time")
            if result.get("code") == "0":
                print("✅ 服务器时间测试成功")
                return True
            else:
                print(f"❌ 服务器时间测试失败: {result.get('msg')}")
                return False
        except Exception as e:
            print(f"❌ 服务器时间测试异常: {e}")
            return False

    def test_account_balance(self):
        """测试 2: 获取账户余额（需要认证）"""
        print("\n" + "=" * 60)
        print("🧪 测试 2: 获取账户余额")
        print("=" * 60)

        try:
            result = self._request("GET", "/api/v5/account/balance")
            if result.get("code") == "0":
                print("✅ 账户余额测试成功")

                # 打印余额详情
                data = result.get("data", [])
                if data:
                    details = data[0].get("details", [])
                    print(f"💰 余额详情:")
                    for detail in details:
                        ccy = detail.get("ccy")
                        bal = detail.get("bal")
                        avail = detail.get("availBal")
                        if float(bal) > 0:
                            print(f"   {ccy}: 总额 {bal}, 可用 {avail}")

                return True
            else:
                print(f"❌ 账户余额测试失败: {result.get('msg')}")
                print(f"错误码: {result.get('code')}")
                return False
        except Exception as e:
            print(f"❌ 账户余额测试异常: {e}")
            return False

    def test_positions(self):
        """测试 3: 获取持仓信息"""
        print("\n" + "=" * 60)
        print("🧪 测试 3: 获取持仓信息")
        print("=" * 60)

        try:
            result = self._request("GET", "/api/v5/account/positions")
            if result.get("code") == "0":
                print("✅ 持仓信息测试成功")

                # 打印持仓详情
                data = result.get("data", [])
                if data:
                    print(f"📊 持仓详情:")
                    for pos in data:
                        instId = pos.get("instId")
                        posSide = pos.get("posSide")
                        posSize = pos.get("pos")
                        unrealizedPL = pos.get("upl")
                        if float(posSize) > 0:
                            print(f"   {instId} | {posSide} | 数量: {posSize} | 未实现盈亏: {unrealizedPL}")
                else:
                    print("📊 当前无持仓")

                return True
            else:
                print(f"❌ 持仓信息测试失败: {result.get('msg')}")
                print(f"错误码: {result.get('code')}")
                return False
        except Exception as e:
            print(f"❌ 持仓信息测试异常: {e}")
            return False


def main():
    """主测试函数"""
    print("=" * 60)
    print("🧪 OKX API 连接测试")
    print("=" * 60)
    print(f"🕐 开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 创建客户端
    client = OKXTestClient()

    # 测试结果
    results = []

    # 测试 1: 服务器时间
    results.append(client.test_server_time())

    # 测试 2: 账户余额
    results.append(client.test_account_balance())

    # 测试 3: 持仓信息
    results.append(client.test_positions())

    # 汇总结果
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)

    total = len(results)
    passed = sum(results)
    failed = total - passed

    print(f"总计: {total} 个测试")
    print(f"通过: {passed} 个")
    print(f"失败: {failed} 个")

    if all(results):
        print("✅ 所有测试通过！API 连接正常")
        print("💡 可以继续运行 main.py")
    else:
        print("❌ 部分测试失败，请检查：")
        print("   1. API Key 是否正确")
        print("   2. 代理是否正常工作")
        print("   3. IP 白名单是否配置")
        print("   4. API 权限是否包含'交易'和'读取'")


if __name__ == "__main__":
    main()
