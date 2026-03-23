"""全图截图入口脚本。"""

import logging
import os
from importlib import import_module

from logging_config import setup_logger


def _first_config_value(config: dict, *keys, default=None):
    """按顺序返回第一个存在的配置值。"""
    for key in keys:
        if not key:
            continue
        value = config.get(key)
        if value is not None:
            return value
    return default


def main():  # pylint: disable=too-many-locals
    """读取配置并生成全图截图。"""
    # 初始化日志
    setup_logger(log_level=logging.INFO)
    screenshot_module = import_module("pdf_keyword_screenshot")
    arrow_style_cls = screenshot_module.ArrowStyle
    border_style_cls = screenshot_module.BorderStyle
    line_box_detection_cls = screenshot_module.LineBoxDetectionConfig
    capture_full_page_screenshots = screenshot_module.capture_full_page_screenshots
    load_config = screenshot_module.load_config
    prepare_output_dir = screenshot_module.prepare_output_dir

    # 加载配置
    config = load_config()
    pdf_config = config["pdf"]
    pdf_file = pdf_config["file"]
    keywords = pdf_config.get("keywords", [])
    full_page_rect = pdf_config.get("full_page_rect")
    full_page_keyword_border = pdf_config.get("full_page_keyword_border")
    full_page_border_color = _first_config_value(
        pdf_config,
        "full_page_border_outline_color",
        "full_page_border_color",
        "region_border_outline_color",
        "region_border_color",
        default=(255, 0, 0),
    )
    full_page_border_opacity = _first_config_value(
        pdf_config,
        "full_page_border_outline_opacity",
        "full_page_border_opacity",
        "region_border_outline_opacity",
        "region_border_opacity",
        default=1.0,
    )
    full_page_border_style = border_style_cls(
        width=_first_config_value(
            pdf_config,
            "full_page_border_width",
            "region_border_width",
            default=1.5,
        ),
        color=full_page_border_color,
        opacity=full_page_border_opacity,
        offset=_first_config_value(
            pdf_config,
            "full_page_border_offset",
            "region_border_offset",
            default=0.0,
        ),
        fill=False,
    )
    full_page_arrow_color = _first_config_value(
        pdf_config,
        "full_page_arrow_color",
        "region_arrow_color",
        default=full_page_border_color,
    )
    full_page_arrow_style = arrow_style_cls(
        color=full_page_arrow_color,
        opacity=_first_config_value(
            pdf_config,
            "full_page_arrow_opacity",
            "region_arrow_opacity",
            default=1.0,
        ),
        corner_gap=_first_config_value(
            pdf_config,
            "full_page_arrow_corner_gap",
            "region_arrow_corner_gap",
            default=0.0,
        ),
        size=_first_config_value(
            pdf_config,
            "full_page_arrow_size",
            "region_arrow_size",
            default=18.0,
        ),
        tail_length=_first_config_value(
            pdf_config,
            "full_page_arrow_tail_length",
            "region_arrow_tail_length",
            default=36.0,
        ),
    )
    line_box_detection = line_box_detection_cls(
        mode=_first_config_value(
            pdf_config,
            "full_page_border_mode",
            "region_border_mode",
            default="nearest_line_box",
        ),
        min_length=_first_config_value(
            pdf_config,
            "full_page_line_min_length",
            "region_line_min_length",
            default=20.0,
        ),
        axis_tolerance=_first_config_value(
            pdf_config,
            "full_page_line_axis_tolerance",
            "region_line_axis_tolerance",
            default=0.5,
        ),
        search_margin=_first_config_value(
            pdf_config,
            "full_page_line_search_margin",
            "region_line_search_margin",
            default=200.0,
        ),
        cache_enabled=_first_config_value(
            pdf_config,
            "full_page_line_cache_enabled",
            "region_line_cache_enabled",
            default=True,
        ),
        cache_dir=_first_config_value(
            pdf_config,
            "full_page_line_cache_dir",
            "region_line_cache_dir",
            default="cache/line_boxes",
        ),
    )
    full_page_dpi = pdf_config.get("full_page_dpi", 300)
    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    prepare_output_dir(output_dir, clear_existing=True)

    logging.info("开始处理 PDF: %s", pdf_file)
    logging.info("搜索关键字: %s", keywords)
    logging.info("截图 DPI: %s", full_page_dpi)
    if full_page_rect:
        logging.info("设置全图截图区域: %s", full_page_rect)
    if full_page_keyword_border:
        logging.info("设置全图截图关键字边框偏移量: %s", full_page_keyword_border)
    logging.info("设置全图截图关键字边框宽度: %s", full_page_border_style.width)
    logging.info("设置全图截图关键字边框颜色: %s", full_page_border_style.color)
    logging.info("设置全图截图关键字边框透明度: %s", full_page_border_style.opacity)
    logging.info("设置全图截图关键字边框外扩: %s", full_page_border_style.offset)
    logging.info("全图截图边框模式: %s", line_box_detection.mode)
    logging.info("全图截图矢量线缓存: %s", line_box_detection.cache_enabled)
    logging.info("全图截图箭头颜色: %s", full_page_arrow_style.color)
    logging.info("全图截图箭头透明度: %s", full_page_arrow_style.opacity)
    logging.info("全图截图箭头角点间距: %s", full_page_arrow_style.corner_gap)
    logging.info("全图截图箭头大小: %s", full_page_arrow_style.size)
    logging.info("全图截图箭头尾部直线长度: %s", full_page_arrow_style.tail_length)
    logging.info("全图截图箭头: 自动选择可完整显示的角点")

    capture_full_page_screenshots(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        full_page_rect=full_page_rect,
        border_rect=full_page_keyword_border,
        border_style=full_page_border_style,
        line_box_detection=line_box_detection,
        draw_arrow=True,
        arrow_style=full_page_arrow_style,
        dpi=full_page_dpi,
    )


if __name__ == "__main__":
    main()
