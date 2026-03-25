import json
import logging
import re
from typing import Any, Dict

import yaml


logger = logging.getLogger(__name__)


def extract_json_block(text: str) -> str:
    """从模型输出中提取 JSON 主体，兼容 ```json 代码块。"""
    if not text:
        raise ValueError("empty json response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
        cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json object not found")
    return cleaned[start:end + 1]


def load_json_dict_with_fallbacks(raw_text: str) -> Dict[str, Any]:
    """优先严格 JSON，失败时允许用 YAML 宽松解析。"""
    block = extract_json_block(raw_text)
    try:
        payload = json.loads(block)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    try:
        payload = yaml.safe_load(block)
        if isinstance(payload, dict):
            logger.warning("JSON strict parse failed; used YAML fallback")
            return payload
    except Exception:
        pass

    raise ValueError("unable to parse json payload")

