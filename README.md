# GetLocInPdf

在 PDF 中搜索关键字，并在图中标记并生成截图。项目已全面切换至 `pypdfium2` 作为核心 PDF 渲染引擎，以提供更高的渲染质量和更好的高 DPI 支持。

## 功能概览

- **[full_page_screenshot.py](full_page_screenshot.py)**  
  搜索关键字后，在指定的“全图区域”（可通过配置定义，如页面主体或忽略边距）生成截图，并在图中绘制关键字红框。
- **[region_screenshot.py](region_screenshot.py)**  
  搜索关键字后，以关键字中心为原点，根据配置的偏移量生成局部区域截图，并在图中绘制关键字红框（支持透明度配置）。
- **[get_pdf_info.py](get_pdf_info.py)**  
  辅助工具，输出 PDF 每页的原始尺寸（Points），用于辅助配置 `config.yaml` 中的坐标范围。

## 环境要求

- Python 3.10+
- 依赖项：
  ```bash
  pip install pymupdf pypdfium2 pillow pyyaml python-dotenv
  ```

## 核心配置 (config.yaml)

项目使用 `config.yaml` 结合 `.env` 环境变量进行配置。

### DPI 设置 (关键)

DPI（每英寸点数）直接决定了输出图片的清晰度和文件大小。项目支持为不同截图模式独立设置 DPI：

- **全页截图 DPI (`full_page_dpi`)**：
  在 `config.yaml` 中通过 `${DPI}` 环境变量注入。
  - 建议值：`100` - `300`。
  - 影响：控制 [full_page_screenshot.py](full_page_screenshot.py) 生成图片的精细度。

- **区域截图 DPI (`region_dpi`)**：
  在 `config.yaml` 中通过 `${REGION_DPI}` 环境变量注入。
  - 建议值：`1000` - `1200`（由于局部截图范围较小，通常可以使用更高 DPI 以获得极高清晰度）。
  - 影响：控制 [region_screenshot.py](region_screenshot.py) 生成图片的精细度。

### 坐标与边框配置

所有坐标单位均为 PDF 标准点 (Points, 1/72 inch)。

1.  **全图区域 (`full_page_rect`)**：
    指定要截取的页面范围。例如，若只想截取图纸中间部分，可设置 `x1, y1` 为左上角坐标，`x2, y2` 为右下角坐标。
2.  **区域偏移 (`region_rect`)**：
    基于关键字中心的偏移。例如 `x1: -50, y1: -50, x2: 50, y2: 50` 将截取以关键字为中心、宽高各 100 点的方形区域。
3.  **关键字红框 (`keyword_border`)**：
    - `x1, y1, x2, y2`：相对于关键字中心的偏移，定义红框的大小。
    - `width`：边框线宽（按 DPI 自动缩放）。
    - `opacity`：仅在区域截图模式支持，设置红框的透明度（0.0 - 1.0）。

## 项目结构

```text
GetLocInPdf/
├─ config.yaml           # 结构化配置文件
├─ .env                  # 环境变量（路径、DPI、开关等）
├─ full_page_screenshot.py # 全图/大区截图脚本
├─ region_screenshot.py    # 局部区域截图脚本
├─ get_pdf_info.py       # 查看 PDF 页面尺寸工具
├─ logging_config.py     # 日志格式定义
├─ output/               # 截图结果输出目录
└─ logs/                 # 运行日志
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
使用 `python get_pdf_info.py` 获取页面宽高，辅助配置 `config.yaml` 中的坐标。

### 2. 生成截图
- 运行 `python full_page_screenshot.py` 生成全页/大区截图。
- 运行 `python region_screenshot.py` 生成局部截图。

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

3. 用 `region_screenshot_pypdfium2.py` 生成最终局部截图
