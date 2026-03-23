import logging
import os

from logging_config import setup_logger
from pdf_keyword_screenshot import (
    ArrowStyle,
    BorderStyle,
    LineBoxDetectionConfig,
    capture_region_screenshots,
    load_config,
    prepare_output_dir,
)


def main():
    setup_logger(log_level=logging.INFO)

    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])
    region_border_color = config["pdf"].get("region_border_color", (255, 0, 0))
    region_border_opacity = config["pdf"].get("region_border_opacity", 1.0)
    region_border_outline_color = (
        config["pdf"].get("region_border_outline_color") or region_border_color
    )
    region_border_outline_opacity = (
        config["pdf"].get("region_border_outline_opacity")
        if config["pdf"].get("region_border_outline_opacity") is not None
        else region_border_opacity
    )
    region_border_fill_color = (
        config["pdf"].get("region_border_fill_color") or region_border_color
    )
    region_border_fill_opacity = (
        config["pdf"].get("region_border_fill_opacity")
        if config["pdf"].get("region_border_fill_opacity") is not None
        else region_border_opacity
    )
    region_arrow_color = (
        config["pdf"].get("region_arrow_color") or region_border_outline_color
    )

    region_rect = config["pdf"].get("region_rect")
    region_border = config["pdf"].get("region_keyword_border")
    border_style = BorderStyle(
        width=config["pdf"].get("region_border_width", 1.5),
        color=region_border_color,
        opacity=region_border_opacity,
        fill=True,
        outline_color=region_border_outline_color,
        outline_opacity=region_border_outline_opacity,
        fill_color=region_border_fill_color,
        fill_opacity=region_border_fill_opacity,
    )
    arrow_style = ArrowStyle(
        color=region_arrow_color,
        opacity=config["pdf"].get("region_arrow_opacity", 1.0),
        corner_gap=config["pdf"].get("region_arrow_corner_gap", 0.0),
    )
    line_box_detection = LineBoxDetectionConfig(
        mode=config["pdf"].get("region_border_mode", "nearest_line_box"),
        min_length=config["pdf"].get("region_line_min_length", 20.0),
        axis_tolerance=config["pdf"].get("region_line_axis_tolerance", 0.5),
        search_margin=config["pdf"].get("region_line_search_margin", 200.0),
        cache_enabled=config["pdf"].get("region_line_cache_enabled", True),
        cache_dir=config["pdf"].get("region_line_cache_dir", "cache/line_boxes"),
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
    logging.info(f"区域截图边框颜色: {border_style.outline_color}")
    logging.info(f"区域截图边框透明度: {border_style.outline_opacity}")
    logging.info(f"区域截图填充颜色: {border_style.fill_color}")
    logging.info(f"区域截图填充透明度: {border_style.fill_opacity}")
    logging.info(f"区域截图边框模式: {line_box_detection.mode}")
    logging.info(f"区域截图矢量线缓存: {line_box_detection.cache_enabled}")
    logging.info(f"区域截图箭头颜色: {arrow_style.color}")
    logging.info(f"区域截图箭头透明度: {arrow_style.opacity}")
    logging.info(f"区域截图箭头角点间距: {arrow_style.corner_gap}")
    logging.info("区域截图箭头: 自动选择可完整显示的角点")

    capture_region_screenshots(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        region_rect=region_rect,
        border_rect=region_border,
        border_style=border_style,
        line_box_detection=line_box_detection,
        arrow_style=arrow_style,
        dpi=dpi,
    )


if __name__ == "__main__":
    main()
