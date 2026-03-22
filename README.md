# GetLocInPdf

在 PDF 中搜索关键字，并在图中标记并生成截图。项目当前采用 `pypdfium2` 负责 PDF 渲染，采用 `PyMuPDF` 负责文本检索、页面几何信息读取与坐标处理。

## 功能概览

- **[full_page_screenshot.py](full_page_screenshot.py)**  
  搜索关键字后，在指定的“全图区域”（可通过配置定义，如页面主体或忽略边距）生成截图，并在图中绘制关键字红框。
- **[region_screenshot.py](region_screenshot.py)**  
  搜索关键字后，以关键字中心为原点，根据配置的偏移量生成局部区域截图，并在图中绘制关键字红框（支持透明度配置）。
- **[pdf_keyword_screenshot.py](pdf_keyword_screenshot.py)**  
  公共截图模块，封装 `PyMuPDF` 检索与坐标处理、`pypdfium2` 渲染和边框绘制逻辑，供其他脚本直接调用。
- **[get_pdf_info.py](get_pdf_info.py)**  
  辅助工具，输出 PDF 每页的原始尺寸（Points），用于辅助配置 `config.yaml` 中的坐标范围。

## 环境要求

- Python 3.10+
- 依赖项：
  ```bash
  pip install pymupdf pypdfium2 pillow pyyaml python-dotenv
  ```
  其中 `pymupdf` 用于检索和坐标处理，`pypdfium2` 用于截图渲染。

## 核心配置 (config.yaml)

项目通过 `config.yaml` 配合 `.env` 驱动。所有坐标单位均为 PDF 标准点 `Points (1/72 inch)`。

关键字段：

- `pdf.file`：目标 PDF 文件路径。
- `pdf.keywords`：待搜索的关键字列表。
- `pdf.full_page_rect`：全图截图的绝对区域。
- `pdf.region_rect`：区域截图相对于关键字中心的偏移区域。
- `pdf.full_page_keyword_border` / `pdf.region_keyword_border`：关键字边框相对于中心点的偏移范围。
- `pdf.full_page_dpi` / `pdf.region_dpi`：两种截图模式的 DPI。全图通常用 `100-300`，区域通常用 `1000-1200`。
- `pdf.*_border_width`：边框线宽，会按 DPI 自动缩放。
- `pdf.*_border_opacity`：边框透明度，范围 `0.0-1.0`。
- `pdf.*_border_color`：边框颜色，支持 RGB 元组或十六进制字符串，如 `#FF0000`。

## 项目结构

```text
GetLocInPdf/
├─ config.yaml                 # 主配置
├─ .env                        # 路径、DPI 等环境变量
├─ pdf_keyword_screenshot.py   # 公共截图核心
├─ full_page_screenshot.py     # 全图截图入口
├─ region_screenshot.py        # 区域截图入口
├─ get_pdf_info.py             # 页面尺寸查看工具
├─ logging_config.py           # 日志配置
├─ output/                     # 截图输出目录
└─ logs/                       # 日志输出目录
```

## 配置指南

项目主要通过 `config.yaml` 结合 `.env` 环境变量进行驱动。

### 1. `.env` 配置
创建 `.env` 文件并设置以下关键变量：
- `PDF_FILE`: PDF 文件的绝对路径。
- `DPI`: 全页截图的分辨率。
- `REGION_DPI`: 区域截图的分辨率。
- `OUTPUT_DIR`: 截图保存目录。

### 2. `config.yaml` 关键字段
- `pdf.keywords`: 要搜索的关键字列表。
- `pdf.full_page_rect`: 全图截图的绝对坐标范围。
- `pdf.region_rect`: 局部区域截图相对于关键字中心点的偏移量。
- `pdf.region_keyword_border`: 关键字红框相对于中心点的偏移量。

## 使用方法

### 1. 查看 PDF 页面尺寸
使用 `python get_pdf_info.py` 获取页面宽高，辅助配置 `config.yaml` 中的坐标。这个工具通过 `PyMuPDF` 读取 PDF 页面尺寸，不参与截图渲染。

### 2. 生成截图
- 运行 `python full_page_screenshot.py` 生成全页/大区截图。
- 运行 `python region_screenshot.py` 生成局部截图。

### 3. 在其他脚本中直接调用
```python
from pdf_keyword_screenshot import (
    BorderStyle,
    capture_full_page_screenshots,
    capture_region_screenshots,
)

capture_full_page_screenshots(
    pdf_path="demo.pdf",
    keywords=["C.L1M2.M060"],
    output_dir="output",
    output_filename_base="demo",
    dpi=300,
    border_style=BorderStyle(color="#FF0000", opacity=0.8),
)

capture_region_screenshots(
    pdf_path="demo.pdf",
    keywords=["C.L1M2.M060"],
    output_dir="output",
    output_filename_base="demo",
    region_rect={"x1": -80, "y1": -40, "x2": 80, "y2": 40},
    dpi=1200,
    border_style=BorderStyle(color=(255, 0, 0), opacity=0.35, fill=True),
)
```

## 输出结果
截图保存在 `output/` 目录，日志保存在 `logs/` 目录。
文件名格式：`{文件名}_{关键字}_P{页码}_截图类型.png`。

## 常见问题

### 1. 找不到关键字

- 确认 `config.yaml` 中 `pdf.keywords` 配置正确
- 确认 PDF 中该文本是可搜索文本，而不是纯扫描图片

### 2. 截图区域不对

- 先运行 `get_pdf_info.py` 查看页面尺寸
- 再调整 `.env` 中的 `REGION_RECT_*` 或 `FULL_PAGE_RECT_*`
- 局部截图范围是相对关键字中心点的偏移，不是绝对坐标
