import fitz  # PyMuPDF
import os
import yaml
import shutil
from dotenv import load_dotenv
import logging
from logging_config import setup_logger

# 加载环境变量
load_dotenv()


def load_config(config_path="config.yaml"):
    """加载并解析 YAML 配置文件，替换环境变量占位符"""
    with open(config_path, "r", encoding="utf-8") as f:
        # 简单替换 ${VAR} 占位符
        content = f.read()
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
        return yaml.safe_load(content)


def capture_keyword_screenshot(
    pdf_path,
    keywords,
    output_dir,
    output_filename_base,
    full_page_rect_cfg=None,
    border_cfg=None,
    border_width=1.5,
    dpi=300,
):
    """
    在 PDF 中搜索关键字并在指定全图区域内截图，同时为关键字绘制红色边框
    """
    if not os.path.exists(pdf_path):
        logging.error(f"PDF 文件不存在: {pdf_path}")
        return

    doc = fitz.open(pdf_path)

    found_count = 0

    # 计算缩放倍数 (72 是 PDF 默认 DPI)
    zoom = float(dpi) / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        page = doc[page_num]

        # 定义截图区域
        if full_page_rect_cfg:
            full_page_rect = fitz.Rect(
                float(full_page_rect_cfg["x1"]),
                float(full_page_rect_cfg["y1"]),
                float(full_page_rect_cfg["x2"]),
                float(full_page_rect_cfg["y2"]),
            )
        else:
            full_page_rect = page.rect  # 默认全页

        # 搜索关键字
        for keyword in keywords:
            text_instances = page.search_for(keyword)

            if text_instances:
                # 在页面上绘制红色边框
                for inst in text_instances:
                    if border_cfg:
                        # 基于中心偏移绘制边框
                        center_x = (inst.x0 + inst.x1) / 2
                        center_y = (inst.y0 + inst.y1) / 2
                        draw_rect = fitz.Rect(
                            center_x + float(border_cfg["x1"]),
                            center_y + float(border_cfg["y1"]),
                            center_x + float(border_cfg["x2"]),
                            center_y + float(border_cfg["y2"]),
                        )
                    else:
                        # 默认直接包裹关键字
                        draw_rect = inst

                    page.draw_rect(
                        draw_rect, color=(1, 0, 0), width=float(border_width)
                    )
                    found_count += 1
                    logging.info(
                        f"在第 {page_num + 1} 页找到关键字 '{keyword}' 并以自定义范围绘制边框"
                    )

                # 截图（基于 full_page_rect）
                # 注意：draw_rect 后需要重新获取像素图才能包含图形
                clip = full_page_rect
                clip.intersect(page.rect)

                pix = page.get_pixmap(clip=clip, matrix=matrix)
                output_path = os.path.join(
                    output_dir,
                    f"{output_filename_base}_{keyword}_全图截图.png",
                )
                pix.save(output_path)
                logging.info(f"截图已保存至: {output_path}")

    doc.close()
    if found_count == 0:
        logging.warning("未找到任何关键字。")
    else:
        logging.info(f"处理完成，共生成 {found_count} 张截图。")


def main():
    # 初始化日志
    setup_logger(log_level=logging.INFO)

    # 加载配置
    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])
    full_page_rect = config["pdf"].get("full_page_rect")
    full_page_keyword_border = config["pdf"].get("full_page_keyword_border")
    full_page_border_width = config["pdf"].get("full_page_border_width", 1.5)
    full_page_dpi = config["pdf"].get("full_page_dpi", 300)
    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    # 清空输出目录
    if os.path.exists(output_dir):
        logging.info(f"正在清空输出目录: {output_dir}")
        shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    logging.info(f"开始处理 PDF: {pdf_file}")
    logging.info(f"搜索关键字: {keywords}")
    logging.info(f"截图 DPI: {full_page_dpi}")
    if full_page_rect:
        logging.info(f"设置全图截图区域: {full_page_rect}")
    if full_page_keyword_border:
        logging.info(f"设置全图截图关键字边框偏移量: {full_page_keyword_border}")
    logging.info(f"设置全图截图关键字边框宽度: {full_page_border_width}")

    capture_keyword_screenshot(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        full_page_rect,
        full_page_keyword_border,
        full_page_border_width,
        full_page_dpi,
    )


if __name__ == "__main__":
    main()
