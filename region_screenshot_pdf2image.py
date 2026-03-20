import os
import yaml
import logging
from pdf2image import convert_from_path
from PIL import Image, ImageDraw
import fitz  # 依然需要 PyMuPDF 进行关键字搜索和坐标获取
from dotenv import load_dotenv
from logging_config import setup_logger

# 加载环境变量
load_dotenv()


def load_config(config_path="config.yaml"):
    """加载并解析 YAML 配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
        # 记录替换前的环境变量
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
        config = yaml.safe_load(content)
        # 强制修正：如果某些路径包含反斜杠，统一转为正斜杠，避免 Poppler 报错
        if "pdf" in config and "poppler_path" in config["pdf"]:
            if config["pdf"]["poppler_path"]:
                p_path = config["pdf"]["poppler_path"].replace("\\", "/")
                config["pdf"]["poppler_path"] = p_path
                logging.info(f"Using poppler path: {p_path}")
        return config


def to_render_rect(page, rect):
    """将 search_for 返回的 PDF 坐标转换为渲染后图片使用的坐标系。"""
    if page.rotation == 0:
        return fitz.Rect(rect)

    p1 = fitz.Point(rect.x0, rect.y0) * page.rotation_matrix
    p2 = fitz.Point(rect.x1, rect.y1) * page.rotation_matrix
    render_rect = fitz.Rect(p1, p2)
    render_rect.normalize()
    return render_rect


def capture_region_pdf2image(
    pdf_path,
    keywords,
    output_dir,
    output_filename_base,
    region_rect_cfg,
    border_cfg=None,
    border_width=2,
    dpi=300,
    poppler_path=None,
):
    """
    使用 pdf2image 渲染页面，并进行区域截图
    注意：搜索关键字依然使用 PyMuPDF，它是目前最准的
    """
    if not os.path.exists(pdf_path):
        logging.error(f"PDF 文件不存在: {pdf_path}")
        return

    os.makedirs(output_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    found_count = 0

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)

        # 搜索关键字位置 (MuPDF 坐标系)
        for keyword in keywords:
            text_instances = page.search_for(keyword)

            if text_instances:
                # 只有找到关键字时，才调用 pdf2image 渲染这一页
                # 这样可以节省大量内存和时间
                logging.info(f"正在使用 pdf2image 渲染第 {page_num + 1} 页...")
                images = convert_from_path(
                    pdf_path,
                    dpi=dpi,
                    first_page=page_num + 1,
                    last_page=page_num + 1,
                    poppler_path=poppler_path,
                )

                if not images:
                    continue

                pil_img = images[0]
                draw = ImageDraw.Draw(pil_img)
                img_width, img_height = pil_img.size
                logging.info(f"Image info: {img_width}x{img_height}, DPI={dpi}")
                logging.info(f"Page rotation: {page.rotation}")

                # 计算缩放比例 (MuPDF 默认 72 DPI)
                scale = dpi / 72.0

                for idx, inst in enumerate(text_instances):
                    # pdf2image 输出的是“最终显示方向”的位图，因此这里必须使用旋转后的坐标
                    render_inst = to_render_rect(page, inst)
                    center_x = (render_inst.x0 + render_inst.x1) / 2
                    center_y = (render_inst.y0 + render_inst.y1) / 2

                    # 1. 计算截图区域 (像素坐标)
                    # 这里的 region_rect_cfg 是 PDF Point 偏移量
                    points = [
                        (center_x + float(region_rect_cfg["x1"])) * scale,
                        (center_y + float(region_rect_cfg["y1"])) * scale,
                        (center_x + float(region_rect_cfg["x2"])) * scale,
                        (center_y + float(region_rect_cfg["y2"])) * scale,
                    ]

                    x_coords = [points[0], points[2]]
                    y_coords = [points[1], points[3]]

                    left = max(0, min(x_coords))
                    top = max(0, min(y_coords))
                    right = min(img_width, max(x_coords))
                    bottom = min(img_height, max(y_coords))

                    logging.info(
                        f"Crop coordinates: left={left}, top={top}, right={right}, bottom={bottom}"
                    )

                    if right <= left or bottom <= top:
                        logging.error(
                            f"Invalid crop box: {left}, {top}, {right}, {bottom}"
                        )
                        continue

                    crop_box = (left, top, right, bottom)

                    # 2. 绘制边框 (在原图上绘制，然后再裁剪)
                    if border_cfg:
                        bx1 = (center_x + float(border_cfg["x1"])) * scale
                        by1 = (center_y + float(border_cfg["y1"])) * scale
                        bx2 = (center_x + float(border_cfg["x2"])) * scale
                        by2 = (center_y + float(border_cfg["y2"])) * scale
                    else:
                        bx1, by1, bx2, by2 = (
                            render_inst.x0 * scale,
                            render_inst.y0 * scale,
                            render_inst.x1 * scale,
                            render_inst.y1 * scale,
                        )

                    # pdf2image 渲染出来的图通常色彩更浓郁
                    draw.rectangle(
                        [bx1, by1, bx2, by2],
                        outline="red",
                        width=max(1, int(round(border_width * scale / 2))),
                    )

                    # 3. 裁剪并保存
                    region_img = pil_img.crop(crop_box)

                    suffix = f"_{idx+1}" if len(text_instances) > 1 else ""
                    output_path = os.path.join(
                        output_dir,
                        f"{output_filename_base}_{keyword}_pdf2image_区域截图{suffix}.png",
                    )
                    region_img.save(output_path)

                    found_count += 1
                    logging.info(f"pdf2image 区域截图已保存: {output_path}")

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

    # 尝试从配置获取 poppler 路径 (Windows 建议配置)
    poppler_path = config["pdf"].get("poppler_path")

    region_rect = config["pdf"].get("region_rect")
    region_border = config["pdf"].get("region_keyword_border")
    border_width = config["pdf"].get("region_border_width", 1.5)
    dpi = config["pdf"].get("region_dpi", 300)

    output_dir = config["output"]["directory"]
    output_base = os.path.splitext(config["output"]["filename"])[0]

    if not region_rect:
        logging.error("未配置 region_rect")
        return

    capture_region_pdf2image(
        pdf_file,
        keywords,
        output_dir,
        output_base,
        region_rect,
        region_border,
        border_width,
        dpi,
        poppler_path,
    )


if __name__ == "__main__":
    main()
