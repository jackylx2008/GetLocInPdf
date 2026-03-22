import fitz  # PyMuPDF
import pypdfium2 as pdfium
import os
import yaml
import shutil
from dotenv import load_dotenv
from PIL import Image, ImageDraw
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


def to_render_rect(page, rect):
    """将 search_for 返回的坐标转换为渲染后页面的坐标系。"""
    if page.rotation == 0:
        return fitz.Rect(rect)

    p1 = fitz.Point(rect.x0, rect.y0) * page.rotation_matrix
    p2 = fitz.Point(rect.x1, rect.y1) * page.rotation_matrix
    render_rect = fitz.Rect(p1, p2)
    render_rect.normalize()
    return render_rect


def centered_rect(center_x, center_y, rect_cfg):
    """根据中心点和偏移配置生成矩形。"""
    rect = fitz.Rect(
        center_x + float(rect_cfg["x1"]),
        center_y + float(rect_cfg["y1"]),
        center_x + float(rect_cfg["x2"]),
        center_y + float(rect_cfg["y2"]),
    )
    rect.normalize()
    return rect


def clamp_rect(rect, page_width, page_height):
    """将区域限制在页面范围内。"""
    bounded = fitz.Rect(rect)
    bounded.intersect(fitz.Rect(0, 0, page_width, page_height))
    bounded.normalize()
    return bounded


def render_clip_with_pdfium(pdfium_page, clip_rect, dpi):
    """使用 pypdfium2 渲染指定区域。"""
    page_width, page_height = pdfium_page.get_size()
    clip_rect = clamp_rect(clip_rect, page_width, page_height)
    if clip_rect.is_empty or clip_rect.width <= 0 or clip_rect.height <= 0:
        return None, clip_rect

    crop = (
        clip_rect.x0,
        page_height - clip_rect.y1,
        page_width - clip_rect.x1,
        clip_rect.y0,
    )

    bitmap = pdfium_page.render(
        scale=float(dpi) / 72.0,
        crop=crop,
        rev_byteorder=True,
    )
    return bitmap.to_pil().convert("RGBA"), clip_rect


def draw_border_on_screenshot(
    img,
    clip_rect,
    border_rect,
    border_width,
    dpi,
):
    """在截图上绘制关键字红框。"""
    scale = float(dpi) / 72.0

    local_rect = fitz.Rect(
        (border_rect.x0 - clip_rect.x0) * scale,
        (border_rect.y0 - clip_rect.y0) * scale,
        (border_rect.x1 - clip_rect.x0) * scale,
        (border_rect.y1 - clip_rect.y0) * scale,
    )
    local_rect.normalize()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    width_px = max(1, int(round(float(border_width) * scale)))

    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle(
        [local_rect.x0, local_rect.y0, local_rect.x1, local_rect.y1],
        outline=(255, 0, 0, 255),
        width=width_px,
    )

    return Image.alpha_composite(img, overlay)


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
    在 PDF 中搜索关键字并在指定全图区域内截图，同时为关键字绘制红色边框。
    搜索坐标使用 PyMuPDF，区域渲染使用 pypdfium2。
    """
    if not os.path.exists(pdf_path):
        logging.error(f"PDF 文件不存在: {pdf_path}")
        return

    fitz_doc = fitz.open(pdf_path)
    pdfium_doc = pdfium.PdfDocument(pdf_path)
    found_count = 0

    try:
        for page_num in range(len(fitz_doc)):
            fitz_page = fitz_doc.load_page(page_num)
            pdfium_page = pdfium_doc[page_num]

            # 定义截图区域
            if full_page_rect_cfg:
                full_page_rect = fitz.Rect(
                    float(full_page_rect_cfg["x1"]),
                    float(full_page_rect_cfg["y1"]),
                    float(full_page_rect_cfg["x2"]),
                    float(full_page_rect_cfg["y2"]),
                )
            else:
                full_page_rect = fitz_page.rect  # 默认全页

            # 搜索关键字
            for keyword in keywords:
                text_instances = fitz_page.search_for(keyword)
                if not text_instances:
                    continue

                # 渲染基础截图
                page_img, clip_rect = render_clip_with_pdfium(
                    pdfium_page, full_page_rect, dpi
                )
                if page_img is None:
                    continue

                # 在页面上绘制红色边框
                for idx, inst in enumerate(text_instances):
                    render_inst = to_render_rect(fitz_page, inst)
                    if border_cfg:
                        # 基于中心偏移绘制边框
                        center_x = (render_inst.x0 + render_inst.x1) / 2
                        center_y = (render_inst.y0 + render_inst.y1) / 2
                        draw_rect = centered_rect(center_x, center_y, border_cfg)
                    else:
                        # 默认直接包裹关键字
                        draw_rect = render_inst

                    page_img = draw_border_on_screenshot(
                        page_img,
                        clip_rect,
                        draw_rect,
                        border_width,
                        dpi,
                    )
                    found_count += 1
                    logging.info(
                        f"在第 {page_num + 1} 页找到关键字 '{keyword}' 并以自定义范围绘制边框"
                    )

                # 保存截图
                output_path = os.path.join(
                    output_dir,
                    f"{output_filename_base}_{keyword}_P{page_num + 1}_全图截图.png",
                )
                page_img.convert("RGB").save(output_path)
                logging.info(f"截图已保存至: {output_path}")

    finally:
        fitz_doc.close()
        pdfium_doc.close()

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
