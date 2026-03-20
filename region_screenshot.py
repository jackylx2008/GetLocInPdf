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
        content = f.read()
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
        return yaml.safe_load(content)


def capture_region_screenshot(
    pdf_path,
    keywords,
    output_dir,
    output_filename_base,
    region_rect_cfg,
    border_cfg=None,
    border_width=1.5,
    border_opacity=1.0,  # 增加透明度参数
    dpi=300,
):
    """
    在 PDF 中搜索关键字，并以关键字中心为原点，根据偏移量进行区域截图
    """
    if not os.path.exists(pdf_path):
        logging.error(f"PDF 文件不存在: {pdf_path}")
        return

    doc = fitz.open(pdf_path)
    found_count = 0

    # 计算缩放倍数
    zoom = float(dpi) / 72
    matrix = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        # 每次重新加载页面以确保绘制边框不重叠
        page = doc.load_page(page_num)

        for keyword in keywords:
            text_instances = page.search_for(keyword)

            if text_instances:
                for idx, inst in enumerate(text_instances):
                    # 重新加载页面以确保当前截图只包含当前关键字的边框
                    current_page = doc.load_page(page_num)

                    # 处理旋转页面坐标映射
                    if current_page.rotation != 0:
                        rm = current_page.rotation_matrix
                        p1 = fitz.Point(inst.x0, inst.y0) * rm
                        p2 = fitz.Point(inst.x1, inst.y1) * rm
                        actual_inst = fitz.Rect(p1, p2)
                        actual_inst.normalize()
                    else:
                        actual_inst = inst

                    center_x = (actual_inst.x0 + actual_inst.x1) / 2
                    center_y = (actual_inst.y0 + actual_inst.y1) / 2

                    logging.info(f"页面旋转角度: {current_page.rotation}")
                    logging.info(
                        f"关键字 '{keyword}' 中心点坐标: ({center_x}, {center_y})"
                    )

                    # 1. 计算截图区域 (基于关键字中心)
                    clip = fitz.Rect(
                        center_x + float(region_rect_cfg["x1"]),
                        center_y + float(region_rect_cfg["y1"]),
                        center_x + float(region_rect_cfg["x2"]),
                        center_y + float(region_rect_cfg["y2"]),
                    )

                    # 2. 绘制边框
                    # 对于旋转页面，draw_rect 必须使用 search_for 返回的原始坐标
                    if border_cfg:
                        # 基于原始坐标中心点偏移
                        orig_center_x = (inst.x0 + inst.x1) / 2
                        orig_center_y = (inst.y0 + inst.y1) / 2
                        draw_rect = fitz.Rect(
                            orig_center_x + float(border_cfg["x1"]),
                            orig_center_y + float(border_cfg["y1"]),
                            orig_center_x + float(border_cfg["x2"]),
                            orig_center_y + float(border_cfg["y2"]),
                        )
                    else:
                        draw_rect = inst

                    logging.info(f"最终绘制红框坐标 (原始系): {draw_rect}")
                    current_page.draw_rect(
                        draw_rect,
                        color=(1, 0, 0),
                        width=float(border_width),
                        fill_opacity=float(border_opacity),  # 使用透明度填充
                        stroke_opacity=float(border_opacity),  # 使用透明度描边
                    )

                    # 3. 保存截图
                    # get_pixmap 的 clip 使用旋转后的坐标系（即 actual 系）
                    pix = current_page.get_pixmap(clip=clip, matrix=matrix)

                    # 文件名区分：{base}_{keyword}_区域截图_{索引}.png
                    suffix = f"_{idx+1}" if len(text_instances) > 1 else ""
                    output_path = os.path.join(
                        output_dir,
                        f"{output_filename_base}_{keyword}_区域截图{suffix}.png",
                    )
                    pix.save(output_path)

                    found_count += 1
                    logging.info(f"区域截图已保存: {output_path}")

    doc.close()
    if found_count == 0:
        logging.warning("未找到任何关键字。")
    else:
        logging.info(f"处理完成，共生成 {found_count} 张区域截图。")


def main():
    setup_logger(log_level=logging.INFO)

    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])

    # 区域截图专用配置
    region_rect = config["pdf"].get("region_rect")
    region_border = config["pdf"].get("region_keyword_border")
    border_width = config["pdf"].get("region_border_width", 1.5)
    border_opacity = config["pdf"].get("region_border_opacity", 1.0)
    dpi = config["pdf"].get("region_dpi", 300)

    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    # 如果配置不存在则跳过
    if not region_rect:
        logging.error(
            "未在配置中找到 region_rect (区域截图范围)，请检查 config.yaml 和 .env"
        )
        return

    # 注意：这里我们不清空目录，因为可能已经有全图截图了
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    logging.info(f"开始区域截图处理 PDF: {pdf_file}")
    logging.info(f"搜索关键字: {keywords}")

    capture_region_screenshot(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        region_rect,
        region_border,
        border_width,
        border_opacity,
        dpi,
    )


if __name__ == "__main__":
    main()
