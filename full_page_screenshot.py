import os
import logging
from logging_config import setup_logger
from pdf_keyword_screenshot import (
    BorderStyle,
    capture_full_page_screenshots,
    load_config,
    prepare_output_dir,
)


def main():
    # 初始化日志
    setup_logger(log_level=logging.INFO)

    # 加载配置
    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])
    full_page_rect = config["pdf"].get("full_page_rect")
    full_page_keyword_border = config["pdf"].get("full_page_keyword_border")
    full_page_border_style = BorderStyle(
        width=config["pdf"].get("full_page_border_width", 1.5),
        color=config["pdf"].get("full_page_border_color", (255, 0, 0)),
        opacity=config["pdf"].get("full_page_border_opacity", 1.0),
        fill=False,
    )
    full_page_dpi = config["pdf"].get("full_page_dpi", 300)
    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    prepare_output_dir(output_dir, clear_existing=True)

    logging.info(f"开始处理 PDF: {pdf_file}")
    logging.info(f"搜索关键字: {keywords}")
    logging.info(f"截图 DPI: {full_page_dpi}")
    if full_page_rect:
        logging.info(f"设置全图截图区域: {full_page_rect}")
    if full_page_keyword_border:
        logging.info(f"设置全图截图关键字边框偏移量: {full_page_keyword_border}")
    logging.info(f"设置全图截图关键字边框宽度: {full_page_border_style.width}")
    logging.info(f"设置全图截图关键字边框颜色: {full_page_border_style.color}")
    logging.info(f"设置全图截图关键字边框透明度: {full_page_border_style.opacity}")

    capture_full_page_screenshots(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        full_page_rect=full_page_rect,
        border_rect=full_page_keyword_border,
        border_style=full_page_border_style,
        dpi=full_page_dpi,
    )


if __name__ == "__main__":
    main()
