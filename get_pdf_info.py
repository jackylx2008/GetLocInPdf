import fitz  # PyMuPDF，用于读取 PDF 页面尺寸信息
import os
import yaml
from dotenv import load_dotenv

# 加载环境变量
load_dotenv(dotenv_path="common.env")


def load_config(config_path="config.yaml"):
    """加载并解析 YAML 配置文件，替换环境变量占位符"""
    if not os.path.exists(config_path):
        return None
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
        # 简单替换 ${VAR} 占位符
        for key, value in os.environ.items():
            content = content.replace(f"${{{key}}}", value)
        return yaml.safe_load(content)


def get_pdf_info():
    """读取配置中的 PDF 文件，输出每页的尺寸信息"""
    config = load_config()
    if not config or "pdf" not in config or "file" not in config["pdf"]:
        print("错误: 未在 config.yaml 中找到 pdf.file 配置，请先填写要分析的 PDF 文件路径。")
        return

    pdf_path = config["pdf"]["file"]

    if not os.path.exists(pdf_path):
        print(f"错误: 未找到 PDF 文件，请检查 pdf.file 配置是否正确: {pdf_path}")
        return

    print(f"\n正在分析文件: {os.path.basename(pdf_path)}")
    print("-" * 50)

    with fitz.open(pdf_path) as doc:
        page_count = int(len(doc))
        print(f"总页数: {page_count}")

        for page_index in range(page_count):
            page = doc.load_page(page_index)
            rect = page.rect
            width = float(rect.width)
            height = float(rect.height)
            print(
                f"第 {page_index + 1} 页: 宽度 = {width:.2f}, 高度 = {height:.2f} "
                f"(坐标范围: 0, 0 到 {width:.2f}, {height:.2f})"
            )

    print("-" * 50)
    print("你可以根据以上数值在 .env 中设置 RECT_X1, RECT_Y1, RECT_X2, RECT_Y2。\n")


if __name__ == "__main__":
    get_pdf_info()
