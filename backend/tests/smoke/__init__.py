"""MVP 1.1b Shadow Fix — 生产入口 smoke tests.

单测验证模块逻辑, smoke 验证模块能否**真的在生产环境启动**.
捕捉 2026-04-17 Shadow bug 类缺陷: 单测 CWD=project root 永远绿,
但 CWD=backend/ 或 subprocess 启动会触发 stdlib `platform` shadow → 崩.

运行:
    pytest backend/tests/smoke/ -v -m smoke

加入日常 CI / pre-release gate (铁律 10b, MVP 交付硬标准).
"""
