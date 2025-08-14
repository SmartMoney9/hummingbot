import ctypes
import logging
import os
import platform
import time
from typing import Optional


class StrOrErr(ctypes.Structure):
    _fields_ = [("str", ctypes.c_char_p), ("err", ctypes.c_char_p)]


def _initialize_signer():
    is_linux = platform.system() == "Linux"
    is_mac = platform.system() == "Darwin"
    is_x64 = platform.machine().lower() in ("amd64", "x86_64")
    is_arm = platform.machine().lower() == "arm64"

    current_file_directory = os.path.dirname(os.path.abspath(__file__))
    path_to_signer_folders = os.path.join(current_file_directory, "signers")

    if is_arm and is_mac:
        return ctypes.CDLL(os.path.join(path_to_signer_folders, "signer-arm64.dylib"))
    elif is_linux and is_x64:
        return ctypes.CDLL(os.path.join(path_to_signer_folders, "signer-amd64.so"))
    else:
        raise Exception(
            f"Unsupported platform/architecture: {platform.system()}/{platform.machine()} only supports Linux(x86) and Darwin(arm64)"
        )


class SignerClient:
    DEFAULT_10_MIN_AUTH_EXPIRY = -1
    MINUTE = 60

    def __init__(
        self,
        url: str,
        private_key: str,
        api_key_index: int = 0,
        account_index: int = 0,
    ):
        """Lightweight subset of original SignerClient providing auth token generation.
        We must call native CreateClient before CreateAuthToken or the signer lib returns 'client is not created'.
        """
        if private_key.startswith("0x"):
            private_key = private_key[2:]
        self.url = url
        self.private_key = private_key
        self.api_key_index = api_key_index
        self.account_index = account_index
        # Chain id logic preserved from original: mainnet contains 'mainnet'
        self.chain_id = 304 if "mainnet" in url else 300
        self.signer = _initialize_signer()
        self._native_created = False
        self._cached_auth_token: Optional[str] = None
        self._cached_auth_expiry: int = 0
        self._create_native_client()

    def _create_native_client(self):
        # Native CreateClient(url, privKey, chainId, apiKeyIndex, accountIndex) -> *char (err or null)
        self.signer.CreateClient.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_longlong,
        ]
        self.signer.CreateClient.restype = ctypes.c_char_p
        err = self.signer.CreateClient(
            self.url.encode("utf-8"),
            self.private_key.encode("utf-8"),
            self.chain_id,
            self.api_key_index,
            self.account_index,
        )
        if err:
            raise Exception(err.decode("utf-8"))
        self._native_created = True

    def _check_client(self) -> Optional[str]:
        # Optional existence check (if provided by native lib)
        if not hasattr(self.signer, "CheckClient"):
            return None
        self.signer.CheckClient.argtypes = [ctypes.c_int, ctypes.c_longlong]
        self.signer.CheckClient.restype = ctypes.c_char_p
        res = self.signer.CheckClient(self.api_key_index, self.account_index)
        return res.decode("utf-8") if res else None

    def create_auth_token_with_expiry(self, deadline: int = DEFAULT_10_MIN_AUTH_EXPIRY):
        now = int(time.time())
        # Serve cached token if valid (30s buffer)
        if self._cached_auth_token and now + 30 < self._cached_auth_expiry:
            return self._cached_auth_token, None

        if deadline == SignerClient.DEFAULT_10_MIN_AUTH_EXPIRY:
            deadline = int(now + 10 * SignerClient.MINUTE)

        if not self._native_created:
            # Should not happen, but attempt re-create
            self._create_native_client()
        else:
            # If native lib reports missing client, re-create
            err = self._check_client()
            if err:
                logging.warning(f"Native signer reports issue '{err}', recreating client")
                self._create_native_client()

        self.signer.CreateAuthToken.argtypes = [ctypes.c_longlong]
        self.signer.CreateAuthToken.restype = StrOrErr
        result = self.signer.CreateAuthToken(deadline)
        auth = result.str.decode("utf-8") if result.str else None
        error = result.err.decode("utf-8") if result.err else None
        if auth and not error:
            self._cached_auth_token = auth
            self._cached_auth_expiry = deadline
        return auth, error
