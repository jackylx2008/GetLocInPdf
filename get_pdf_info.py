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
        print("错误: 无法在 config.yaml 中找到 pdf.file 配置。")
        return

    pdf_path = config["pdf"]["file"]

    if not os.path.exists(pdf_path):
        print(f"错误: PDF 文件不存在: {pdf_path}")
        return

    print(f"\n正在分析文件: {os.path.basename(pdf_path)}")
    print("-" * 50)

    doc = fitz.open(pdf_path)
    print(f"总页数: {len(doc)}")

    for i, page in enumerate(doc):
        rect = page.rect
        width = rect.width
        height = rect.height
        print(
            f"第 {i+1} 页: 宽度 = {width:.2f}, 高度 = {height:.2f} (坐标范围: 0, 0 到 {width:.2f}, {height:.2f})"
        )

    doc.close()
    print("-" * 50)
    print("你可以根据以上数值在 .env 中设置 RECT_X1, RECT_Y1, RECT_X2, RECT_Y2。\n")


if __name__ == "__main__":
    get_pdf_info()
