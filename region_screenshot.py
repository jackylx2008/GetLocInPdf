import logging
import os

import fitz  # PyMuPDF
import pypdfium2 as pdfium
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw

from logging_config import setup_logger

# 加载环境变量
load_dotenv()


def load_config(config_path="config.yaml"):
    """加载并解析 YAML 配置文件，替换环境变量占位符。"""
    with open(config_path, "r", encoding="utf-8") as f:
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


def draw_border_on_region(
    region_img,
    clip_rect,
    border_rect,
    border_width,
    border_opacity,
    dpi,
):
    """在区域截图上绘制关键字红框。"""
    scale = float(dpi) / 72.0

    local_rect = fitz.Rect(
        (border_rect.x0 - clip_rect.x0) * scale,
        (border_rect.y0 - clip_rect.y0) * scale,
        (border_rect.x1 - clip_rect.x0) * scale,
        (border_rect.y1 - clip_rect.y0) * scale,
    )
    local_rect.normalize()

    overlay = Image.new("RGBA", region_img.size, (0, 0, 0, 0))
    alpha = max(0, min(255, int(round(float(border_opacity) * 255))))
    width_px = max(1, int(round(float(border_width) * scale)))

    draw = ImageDraw.Draw(overlay, "RGBA")
    draw.rectangle(
        [local_rect.x0, local_rect.y0, local_rect.x1, local_rect.y1],
        outline=(255, 0, 0, alpha),
        fill=(255, 0, 0, alpha),
        width=width_px,
    )

    return Image.alpha_composite(region_img, overlay)


def capture_region_screenshot(
    pdf_path,
    keywords,
    output_dir,
    output_filename_base,
    region_rect_cfg,
    border_cfg=None,
    border_width=1.5,
    border_opacity=1.0,
    dpi=300,
):
    """
    在 PDF 中搜索关键字，并以关键字中心为原点，根据偏移量进行区域截图。
    搜索坐标使用 PyMuPDF，区域渲染使用 pypdfium2。
    """
    if not os.path.exists(pdf_path):
        logging.error(f"PDF 文件不存在: {pdf_path}")
        return

    os.makedirs(output_dir, exist_ok=True)

    fitz_doc = fitz.open(pdf_path)
    pdfium_doc = pdfium.PdfDocument(pdf_path)
    found_count = 0

    try:
        for page_num in range(len(fitz_doc)):
            fitz_page = fitz_doc.load_page(page_num)
            pdfium_page = pdfium_doc[page_num]
            page_width, page_height = pdfium_page.get_size()

            for keyword in keywords:
                text_instances = fitz_page.search_for(keyword)
                if not text_instances:
                    continue

                for idx, inst in enumerate(text_instances):
                    render_inst = to_render_rect(fitz_page, inst)
                    center_x = (render_inst.x0 + render_inst.x1) / 2
                    center_y = (render_inst.y0 + render_inst.y1) / 2

                    logging.info(f"页面旋转角度: {fitz_page.rotation}")
                    logging.info(
                        f"关键字 '{keyword}' 中心点坐标: ({center_x}, {center_y})"
                    )

                    clip_rect = centered_rect(center_x, center_y, region_rect_cfg)
                    clip_rect = clamp_rect(clip_rect, page_width, page_height)

                    if (
                        clip_rect.is_empty
                        or clip_rect.width <= 0
                        or clip_rect.height <= 0
                    ):
                        logging.error(f"无效截图区域: {clip_rect}")
                        continue

                    logging.info(f"最终截图区域坐标: {clip_rect}")
                    region_img, actual_clip = render_clip_with_pdfium(
                        pdfium_page,
                        clip_rect,
                        dpi,
                    )
                    if region_img is None:
                        logging.error(f"渲染失败，截图区域无效: {clip_rect}")
                        continue

                    if border_cfg:
                        orig_center_x = (inst.x0 + inst.x1) / 2
                        orig_center_y = (inst.y0 + inst.y1) / 2
                        border_rect = centered_rect(
                            orig_center_x,
                            orig_center_y,
                            border_cfg,
                        )
                        border_rect = to_render_rect(fitz_page, border_rect)
                    else:
                        border_rect = fitz.Rect(render_inst)

                    region_img = draw_border_on_region(
                        region_img,
                        actual_clip,
                        border_rect,
                        border_width,
                        border_opacity,
                        dpi,
                    )

                    suffix = f"_{idx + 1}" if len(text_instances) > 1 else ""
                    output_path = os.path.join(
                        output_dir,
                        f"{output_filename_base}_{keyword}_区域截图{suffix}.png",
                    )
                    region_img.convert("RGB").save(output_path)

                    found_count += 1
                    logging.info(f"区域截图已保存: {output_path}")
    finally:
        fitz_doc.close()
        pdfium_doc.close()

    if found_count == 0:
        logging.warning("未找到任何关键字。")
    else:
        logging.info(f"处理完成，共生成 {found_count} 张区域截图。")


def main():
    setup_logger(log_level=logging.INFO)

    config = load_config()
    pdf_file = config["pdf"]["file"]
    keywords = config["pdf"].get("keywords", [])

    region_rect = config["pdf"].get("region_rect")
    region_border = config["pdf"].get("region_keyword_border")
    border_width = config["pdf"].get("region_border_width", 1.5)
    border_opacity = config["pdf"].get("region_border_opacity", 1.0)
    dpi = config["pdf"].get("region_dpi", 300)

    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    if not region_rect:
        logging.error(
            "未在配置中找到 region_rect (区域截图范围)，请检查 config.yaml 和 .env"
        )
        return

    logging.info(f"开始区域截图处理 PDF: {pdf_file}")
    logging.info(f"搜索关键字: {keywords}")
    logging.info(f"区域截图 DPI: {dpi}")

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
