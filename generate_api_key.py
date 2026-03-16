#!/usr/bin/env python3
"""
生成 QClaw API Key
用法: python generate_api_key.py
"""

import secrets
import string
import os

def generate_api_key(length=32):
    """
    生成安全的随机API Key
    
    Args:
        length: Key长度，默认32字符
    
    Returns:
        随机生成的API Key
    """
    # 使用secrets模块（比random更安全）
    # 包含大小写字母和数字
    alphabet = string.ascii_letters + string.digits
    api_key = ''.join(secrets.choice(alphabet) for _ in range(length))
    return api_key

def main():
    # 生成API Key
    api_key = generate_api_key(32)
    
    print("="*60)
    print("🔑 QClaw API Key 生成器")
    print("="*60)
    print(f"\n生成的 API Key:\n{api_key}\n")
    
    # 配置文件路径
    config_path = os.path.expanduser("~/.qclaw/config.yaml")
    env_path = os.path.expanduser("~/.bashrc")  # 或 ~/.zshrc
    
    print("="*60)
    print("📁 配置方式（选择一种）")
    print("="*60)
    
    print("\n【方式1】环境变量（推荐，更安全）")
    print(f"编辑文件: {env_path}")
    print(f"添加以下行:")
    print(f"    export QCLAW_API_KEY=\"{api_key}\"")
    print(f"然后执行: source {env_path}")
    
    print("\n【方式2】配置文件（方便但安全性较低）")
    print(f"创建/编辑文件: {config_path}")
    print("添加以下内容:")
    print(f"""
qclaw:
  api_key: "{api_key}"
  endpoint: "http://localhost:8080"
""")
    
    print("\n【方式3】临时使用（仅本次会话）")
    print(f"    export QCLAW_API_KEY=\"{api_key}\"")
    
    print("\n" + "="*60)
    print("⚠️  重要提示")
    print("="*60)
    print("1. 请妥善保管此API Key，不要分享给他人")
    print("2. 如果泄露，请重新生成并更新配置")
    print("3. QClaw服务端也需要配置相同的Key用于验证")
    print("="*60)

if __name__ == "__main__":
    main()
