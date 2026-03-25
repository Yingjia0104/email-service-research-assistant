from __future__ import annotations

import logging
import os
import sys
import time
from functools import wraps
from typing import Any, Callable, Dict, MutableMapping, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter


PROXY_ENV_KEYS = ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY")
LOCAL_NO_PROXY = "127.0.0.1,localhost,0.0.0.0"


def setup_file_logger(log_file: str, *, stream=None):
    """配置 CLI 运行期日志。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8", delay=True),
            logging.StreamHandler(stream or sys.stdout),
        ],
        force=True,
    )
    return logging.getLogger(__name__)


def build_llm_sessions(
    *,
    env: Optional[MutableMapping[str, str]] = None,
) -> Tuple[requests.Session, requests.Session]:
    """为 qclaw 构建一对直连/代理 LLM 会话，并只在这里处理环境副作用。"""
    target_env = env if env is not None else os.environ
    original_proxy_env = {
        key: target_env.get(key)
        for key in PROXY_ENV_KEYS
        if target_env.get(key)
    }

    for key in PROXY_ENV_KEYS:
        target_env.pop(key, None)
    target_env["NO_PROXY"] = LOCAL_NO_PROXY

    adapter = HTTPAdapter(
        max_retries=3,
        pool_connections=10,
        pool_maxsize=10,
    )

    direct_session = requests.Session()
    direct_session.trust_env = False
    direct_session.mount("http://", adapter)
    direct_session.mount("https://", adapter)

    proxy_session = requests.Session()
    proxy_session.trust_env = False
    proxy_session.proxies.update(
        {
            "http": original_proxy_env.get("http_proxy") or original_proxy_env.get("HTTP_PROXY"),
            "https": original_proxy_env.get("https_proxy") or original_proxy_env.get("HTTPS_PROXY"),
            "all": original_proxy_env.get("ALL_PROXY"),
        }
    )
    proxy_session.mount("http://", adapter)
    proxy_session.mount("https://", adapter)

    return direct_session, proxy_session


def retry_on_error(*, logger: Any, max_retries: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """简单重试装饰器，避免入口文件自己维护这层模板代码。"""

    def decorator(func: Callable[..., Any]):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exception = exc
                    if attempt < max_retries:
                        logger.warning(f"第 {attempt + 1} 次尝试失败: {exc}, {current_delay:.1f}秒后重试...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"已达到最大重试次数 ({max_retries + 1}), 最终错误: {exc}")

            raise last_exception

        return wrapper

    return decorator
