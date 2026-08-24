"""集中式配置加载。

项目所有入口（Streamlit 网页 / GitHub Actions 定时报告）统一从这里读取模型名等配置，
避免模型名散落在 app.py 和 report_generator.py 里导致不一致。
"""
from __future__ import annotations

import json
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
_cache: dict | None = None


def load_config() -> dict:
    """加载 config.json（带内存缓存）。"""
    global _cache
    if _cache is None:
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def get_model(kind: str = "fast") -> str:
    """按用途返回模型名。kind 可选 fast / pro / report。"""
    models = load_config().get("models", {})
    return models.get(kind, "deepseek-v4-flash")
