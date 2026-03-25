from __future__ import annotations

import os
from typing import MutableMapping, Optional


PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")


def prepare_service_environment(env: Optional[MutableMapping[str, str]] = None) -> None:
    """清理会干扰 IMAP/SMTP 的代理环境变量。"""
    target_env = env if env is not None else os.environ
    for key in PROXY_ENV_KEYS:
        target_env.pop(key, None)
