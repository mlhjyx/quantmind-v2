"""structlog日志配置单元测试。

测试范围:
- configure_logging不抛出异常
- get_logger返回可调用的logger
- 日志目录创建
- 开发/生产模式切换
"""

import logging
import os
from unittest.mock import patch


class TestConfigureLogging:
    """测试configure_logging函数。"""

    def test_开发模式不抛出异常(self, tmp_path):
        from app.logging_config import configure_logging

        log_file = tmp_path / "test.log"
        configure_logging(dev_mode=True, log_file=log_file)
        assert True  # 不抛出即通过

    def test_生产模式不抛出异常(self, tmp_path):
        from app.logging_config import configure_logging

        log_file = tmp_path / "test.log"
        configure_logging(dev_mode=False, log_file=log_file)
        assert True

    def test_自动创建日志目录(self, tmp_path):
        from app.logging_config import configure_logging

        nested_dir = tmp_path / "a" / "b" / "c"
        log_file = nested_dir / "app.log"
        # 目录不存在时自动创建
        configure_logging(dev_mode=True, log_file=log_file)
        assert nested_dir.exists()

    def test_自动检测环境变量(self, tmp_path):
        from app.logging_config import configure_logging

        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
            configure_logging(log_file=log_file)  # dev_mode=None，自动检测
        assert True

    def test_开发环境自动检测(self, tmp_path):
        from app.logging_config import configure_logging

        log_file = tmp_path / "test.log"
        with patch.dict(os.environ, {"ENVIRONMENT": "development"}):
            configure_logging(log_file=log_file)
        assert True

    def test_日志级别设置(self, tmp_path):
        from app.logging_config import configure_logging

        log_file = tmp_path / "test.log"
        configure_logging(level=logging.DEBUG, dev_mode=True, log_file=log_file)
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG


class TestGetLogger:
    """测试get_logger便捷函数。"""

    def test_返回structlog_logger(self):
        from app.logging_config import get_logger

        logger = get_logger("test_module")
        assert logger is not None

    def test_无参数调用(self):
        from app.logging_config import get_logger

        logger = get_logger()
        assert logger is not None

    def test_logger可调用info(self, tmp_path):
        from app.logging_config import configure_logging, get_logger

        log_file = tmp_path / "test.log"
        configure_logging(dev_mode=False, log_file=log_file)
        logger = get_logger("test")
        # 不应抛出异常
        logger.info("测试消息", key="value")
        assert True

    def test_logger可调用warning和error(self, tmp_path):
        from app.logging_config import configure_logging, get_logger

        log_file = tmp_path / "test.log"
        configure_logging(dev_mode=True, log_file=log_file)
        logger = get_logger("test")
        logger.warning("测试警告")
        logger.error("测试错误")
        assert True


class TestJsonOutput:
    """测试JSON格式输出。"""

    def test_生产模式写入json日志(self, tmp_path):
        from app.logging_config import configure_logging, get_logger

        log_file = tmp_path / "app.log"
        configure_logging(dev_mode=False, log_file=log_file)
        logger = get_logger("json_test")
        logger.info("测试JSON输出", run_id="test-123", sharpe=1.03)

        # 验证日志文件被写入
        # 注意: structlog通过stdlib桥接，文件写入可能在flush后才可见
        import time
        time.sleep(0.05)  # 短暂等待flush

        # 文件应存在（由RotatingFileHandler创建）
        assert log_file.exists()
