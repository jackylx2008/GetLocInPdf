import logging
import os

from logging_config import setup_logger
from pdf_keyword_screenshot import (
    BorderStyle,
    capture_region_screenshots,
    load_config,
    prepare_output_dir,
)


def main():
    setup_logger(log_level=logging.INFO)

    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])

    region_rect = config["pdf"].get("region_rect")
    region_border = config["pdf"].get("region_keyword_border")
    border_style = BorderStyle(
        width=config["pdf"].get("region_border_width", 1.5),
        color=config["pdf"].get("region_border_color", (255, 0, 0)),
        opacity=config["pdf"].get("region_border_opacity", 1.0),
        fill=True,
    )
    dpi = config["pdf"].get("region_dpi", 300)

    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]
    prepare_output_dir(output_dir, clear_existing=False)

    if not region_rect:
        logging.error(
            "未在配置中找到 region_rect (区域截图范围)，请检查 config.yaml 和 .env"
        )
        return

    logging.info(f"开始区域截图处理 PDF: {pdf_file}")
    logging.info(f"搜索关键字: {keywords}")
    logging.info(f"区域截图 DPI: {dpi}")
    logging.info(f"区域截图边框颜色: {border_style.color}")
    logging.info(f"区域截图边框透明度: {border_style.opacity}")

    capture_region_screenshots(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        region_rect=region_rect,
        border_rect=region_border,
        border_style=border_style,
        dpi=dpi,
    )


if __name__ == "__main__":
    main()
