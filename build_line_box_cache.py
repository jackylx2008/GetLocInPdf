import logging
import os
from typing import Any

import yaml
from dotenv import load_dotenv

from line_box_cache import build_pdf_line_cache, discover_pdf_files
from logging_config import setup_logger


load_dotenv(dotenv_path="common.env")


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as file:
        content = file.read()
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
        return yaml.safe_load(content)


def main() -> None:
    setup_logger(log_level=logging.INFO)

    config = load_config()
    pdf_dir = config["pdf"].get("path") or os.environ.get("PDF_PATH")
    if not pdf_dir:
        logging.error("未配置 PDF_PATH 或 config.yaml 中的 pdf.path。")
        return

    cache_dir = config["pdf"].get("region_line_cache_dir", "cache/line_boxes")
    axis_tolerance = float(config["pdf"].get("region_line_axis_tolerance", 0.5))
    min_length = float(config["pdf"].get("region_line_min_length", 20.0))

    pdf_files = discover_pdf_files(pdf_dir)
    if not pdf_files:
        logging.warning("在目录中未找到 PDF 文件: %s", pdf_dir)
        return

    logging.info("开始构建矢量线缓存，PDF 目录: %s", pdf_dir)
    logging.info("命中参数: axis_tolerance=%s, min_length=%s", axis_tolerance, min_length)
    logging.info("缓存目录: %s", cache_dir)
    logging.info("待处理 PDF 数量: %s", len(pdf_files))

    total_pages = 0
    total_built_pages = 0
    total_disk_hit_pages = 0

    for pdf_path in pdf_files:
        stats = build_pdf_line_cache(
            pdf_path=pdf_path,
            cache_dir=cache_dir,
            axis_tolerance=axis_tolerance,
            min_length=min_length,
        )
        total_pages += int(stats["pages"])
        total_built_pages += int(stats["built_pages"])
        total_disk_hit_pages += int(stats["disk_hit_pages"])
        logging.info(
            "完成 PDF: %s | 页数=%s, 新建缓存=%s, 已有缓存=%s, 耗时=%.2fs",
            os.path.basename(str(stats["pdf_path"])),
            stats["pages"],
            stats["built_pages"],
            stats["disk_hit_pages"],
            stats["elapsed_seconds"],
        )

    logging.info(
        "全部完成，共处理 %s 个 PDF、%s 页；新建缓存 %s 页，复用缓存 %s 页。",
        len(pdf_files),
        total_pages,
        total_built_pages,
        total_disk_hit_pages,
    )


if __name__ == "__main__":
    main()
