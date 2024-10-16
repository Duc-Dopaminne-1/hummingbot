import base64
import hashlib
import hmac
import time
from typing import Any, Dict, List
from urllib.parse import urlencode

from hummingbot.connector.time_synchronizer import TimeSynchronizer
from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest


def create_signature(timestamp, method, request_path, secret_key, body=""):
    prehash_string = timestamp + method + request_path + body
    hmac_key = hmac.new(secret_key.encode(), prehash_string.encode(), hashlib.sha256)
    signature = base64.b64encode(hmac_key.digest()).decode()
    return signature


class BitgetAuth(AuthBase):
    """
    Auth class required by Bitget  API
    """
    def __init__(self, api_key: str, secret_key: str, passphrase: str, time_provider: TimeSynchronizer):
        self._api_key: str = api_key
        self._secret_key: str = secret_key
        self._passphrase: str = passphrase
        self._time_provider: TimeSynchronizer = time_provider

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        headers = {}
        headers["Content-Type"] = "application/json"
        headers["ACCESS-KEY"] = self._api_key
        headers["ACCESS-TIMESTAMP"] = str(int(time.time() * 1000))
        headers["ACCESS-PASSPHRASE"] = self._passphrase
        # headers["locale"] = "en-US"
        path = request.throttler_limit_id
        # TODO check cho nay

        if request.method is RESTMethod.GET and request.params:
            print("444444", request.params)
            print("5555", urlencode(request.params))
            path += "?" + urlencode(request.params)
        payload = str(request.data)
        headers["ACCESS-SIGN"] = self._sign(
            self._pre_hash(headers["ACCESS-TIMESTAMP"], request.method.value, path, payload),
            self._secret_key)
        print("quai 22222", headers)
        request.headers.update(headers)
        print("rest_authenticate headers", headers)
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        """
        This method is intended to configure a websocket request to be authenticated. OKX does not use this
        functionality
        """
        return request  # pass-through

    def get_ws_auth_payload(self) -> List[Dict[str, Any]]:
        """
        Generates a dictionary with all required information for the authentication process
        :return: a dictionary of authentication info including the request signature
        """
        timestamp = str(int(self._time_provider.time()))
        signature = self._sign(self._pre_hash(timestamp, "GET", "/user/verify", ""), self._secret_key)
        auth_info = [
            {
                "apiKey": self._api_key,
                "passphrase": self._passphrase,
                "timestamp": timestamp,
                "sign": signature
            }
        ]

        return auth_info

    @staticmethod
    def _sign(message, secret_key):
        mac = hmac.new(bytes(secret_key, encoding='utf8'), bytes(message, encoding='utf-8'), digestmod='sha256')
        d = mac.digest()
        return str(base64.b64encode(d), 'utf8')

    @staticmethod
    def _pre_hash(timestamp: str, method: str, request_path: str, body: str):
        if body in ["None", "null"]:
            body = ""
        return str(timestamp) + method.upper() + request_path + body
