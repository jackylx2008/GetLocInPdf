"""
日志配置模块。

提供日志记录器的设置和初始化功能。
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from typing import Optional

# 动态添加项目根目录到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def setup_logger(
    log_level: int = logging.DEBUG,
    log_file: Optional[str] = None,
    filemode: str = "w",
):
    """
    设置日志记录器。

    :param log_level: 日志级别，默认为 DEBUG。
    :param log_file: 日志文件路径，如果为 None，则根据主模块名自动生成，如 ./logs/process_grid.log。
    :param filemode: 文件打开模式，默认为 'w' (覆盖)。
    :return: 配置好的日志记录器。
    """
    # 如果未显式指定日志文件，则按“一个脚本一个日志”规则自动生成
    if log_file is None:
        main_module = os.path.splitext(os.path.basename(sys.argv[0]))[0] or "app"
        log_file = os.path.join(".", "logs", f"{main_module}.log")

    # 创建日志文件夹
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    # 配置日志格式
    log_format = "%(asctime)s - %(levelname)s - %(module)s - %(message)s"

    # 设置日志级别
    app_logger = logging.getLogger()
    app_logger.setLevel(log_level)

    # 清除已有的处理器，避免重复添加
    if app_logger.handlers:
        app_logger.handlers.clear()

    # 控制台日志处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    # 文件日志处理器（使用滚动记录，防止单个文件过大）
    # maxBytes=10MB, backupCount=5
    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    # 添加处理器
    app_logger.addHandler(console_handler)
    app_logger.addHandler(file_handler)

    return app_logger


# 单独运行时的测试代码
if __name__ == "__main__":
    # 示例日志文件路径
    LOG_FILE_PATH = "./logs/test_logger.log"

    # 初始化日志记录器
    logger = setup_logger(log_level=logging.INFO, log_file=LOG_FILE_PATH)

    # 测试日志输出
    logger.debug("This is a DEBUG message.")
    logger.info("This is an INFO message.")
    logger.warning("This is a WARNING message.")
    logger.error("This is an ERROR message.")
    logger.critical("This is a CRITICAL message.")
