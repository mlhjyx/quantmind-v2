"""EmailBackupStub — S6 email 备份桩 (retry 耗尽后 fallback).

设计:
  - 当前为文件桩 (写 JSONL 到 logs/email_backup.jsonl)
  - 每条记录含: timestamp, rule_id, code, reason, retry_count
  - TODO: S8+ 接真实 SMTP (settings.EMAIL_* env)

用法:
    stub = EmailBackupStub()
    stub.backup(rule_result, retry_count=3)

关联铁律: 33 (fail-loud on write failure) / 24
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..interface import RuleResult

logger = logging.getLogger(__name__)

_DEFAULT_LOG_PATH = Path("logs/email_backup.jsonl")


class EmailBackupStub:
    """Email 备份桩 — retry 耗尽后将告警写入 JSONL 文件.

    不在 __init__ 时创建文件 (反 import 时文件副作用), 首次 backup() 时 lazily 创建.
    """

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path or _DEFAULT_LOG_PATH
        self._lock = threading.Lock()
        self._backup_count: int = 0

    def backup(self, result: RuleResult, retry_count: int = 3) -> None:
        """将 RuleResult 写入 email backup log.

        Args:
            result: 发送失败的 RuleResult.
            retry_count: 已重试次数.

        Raises:
            OSError: 文件写入失败 (铁律 33 fail-loud).
        """
        record: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "rule_id": result.rule_id,
            "code": result.code,
            "shares": result.shares,
            "reason": result.reason,
            "metrics": result.metrics,
            "retry_exhausted_after": retry_count,
        }
        with self._lock:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._backup_count += 1
        logger.warning(
            "[email-backup] rule_id=%s code=%s backed up (retry=%d exhausted)",
            result.rule_id,
            result.code,
            retry_count,
        )

    @property
    def backup_count(self) -> int:
        """累计 backup 次数."""
        with self._lock:
            return self._backup_count

    @property
    def log_path(self) -> Path:
        """backup log 文件路径."""
        return self._log_path
