import ctypes
import json
import time
from collections import OrderedDict

import eth_account
import logging
from hummingbot.logger.logger import HummingbotLogger
import msgpack
from eth_account.messages import encode_typed_data
from eth_utils import keccak, to_hex

from hummingbot.connector.derivative.lighter_perpetual import lighter_perpetual_constants as CONSTANTS
from hummingbot.connector.derivative.lighter_perpetual.lighter_perpetual_web_utils import (
    order_spec_to_order_wire,
)
from hummingbot.connector.derivative.lighter_perpetual.lighter_perpetual_skd import SignerClient

from hummingbot.core.web_assistant.auth import AuthBase
from hummingbot.core.web_assistant.connections.data_types import RESTMethod, RESTRequest, WSRequest


class LighterPerpetualAuth(AuthBase):
    """
    Auth class required by Lighter Perpetual API
    """
    _logger = None

    def __init__(self, api_key: str, api_secret: str, connector: 'LighterPerpetualDerivative'):
        self._api_key: str = api_key
        self._api_secret: str = api_secret
        self.wallet = eth_account.Account.from_key(api_secret)
        self._signer_client = None  # SignerClient instance cached after first use
        self._connector = connector

    @classmethod
    def address_to_bytes(cls, address):
        return bytes.fromhex(address[2:] if address.startswith("0x") else address)

    @classmethod
    def action_hash(cls, action, vault_address, nonce):
        data = msgpack.packb(action)
        data += nonce.to_bytes(8, "big")
        if vault_address is None:
            data += b"\x00"
        else:
            data += b"\x01"
            data += cls.address_to_bytes(vault_address)
        return keccak(data)

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(HummingbotLogger.logger_name_for_class(cls))
        return cls._logger

    def sign_inner(self, wallet, data):
        structured_data = encode_typed_data(full_message=data)
        signed = wallet.sign_message(structured_data)
        return {"r": to_hex(signed["r"]), "s": to_hex(signed["s"]), "v": signed["v"]}

    def construct_phantom_agent(self, hash, is_mainnet):
        return {"source": "a" if is_mainnet else "b", "connectionId": hash}

    def sign_l1_action(self, wallet, action, active_pool, nonce, is_mainnet):
        _hash = self.action_hash(action, active_pool, nonce)
        phantom_agent = self.construct_phantom_agent(_hash, is_mainnet)

        data = {
            "domain": {
                "chainId": 1337,
                "name": "Exchange",
                "verifyingContract": "0x0000000000000000000000000000000000000000",
                "version": "1",
            },
            "types": {
                "Agent": [
                    {"name": "source", "type": "string"},
                    {"name": "connectionId", "type": "bytes32"},
                ],
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
            },
            "primaryType": "Agent",
            "message": phantom_agent,
        }
        return self.sign_inner(wallet, data)

    async def rest_authenticate(self, request: RESTRequest) -> RESTRequest:
        request = await self.add_auth_to_headers(request)
        return request

    async def ws_authenticate(self, request: WSRequest) -> WSRequest:
        return request  # pass-through

    def _sign_update_leverage_params(self, params, base_url, timestamp):
        signature = self.sign_l1_action(
            self.wallet,
            params,
            timestamp,
            CONSTANTS.PERPETUAL_BASE_URL in base_url,
        )
        payload = {
            "action": params,
            "nonce": timestamp,
            "signature": signature,
        }
        return payload

    def _sign_cancel_params(self, params, base_url, timestamp):
        order_action = {
            "type": "cancelByCloid",
            "cancels": [params["cancels"]],
        }
        signature = self.sign_l1_action(
            self.wallet,
            order_action,
            timestamp,
            CONSTANTS.PERPETUAL_BASE_URL in base_url,
        )
        payload = {
            "action": order_action,
            "nonce": timestamp,
            "signature": signature,

        }
        return payload

    def _sign_order_params(self, params, base_url, timestamp):

        order = params["orders"]
        grouping = params["grouping"]
        order_action = {
            "type": "order",
            "orders": [order_spec_to_order_wire(order)],
            "grouping": grouping,
        }
        signature = self.sign_l1_action(
            self.wallet,
            order_action,
            timestamp,
            CONSTANTS.PERPETUAL_BASE_URL in base_url,
        )

        payload = {
            "action": order_action,
            "nonce": timestamp,
            "signature": signature,

        }
        return payload

    async def add_auth_to_headers(self, request: RESTRequest):
        if self._signer_client is None:
            try:
                account_index = await self._connector.get_account_index()
                self._signer_client = SignerClient(
                    url=CONSTANTS.PERPETUAL_BASE_URL,
                    private_key='c8d0abf9d8b4e2719586ced819f433d0f1edcb7935ab48bb7c5bc1fddc9d8bcb9a8259d0547e2769',
                    api_key_index=0,
                    account_index=account_index
                )
            except Exception as e:
                return json.dumps({"error": str(e)})

        auth, err = self._signer_client.create_auth_token_with_expiry()

        if err:
            return json.dumps({"error": err})

        headers = {}
        headers["authorization"] = auth
        request.headers = {**request.headers, **headers} if request.headers is not None else headers

        return request

    @staticmethod
    def _get_timestamp():
        return time.time()
