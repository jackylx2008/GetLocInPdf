# GetLocInPdf

在 PDF 中搜索关键字，并按配置截图。

当前项目主要用于：
- 在 PDF 中搜索指定关键字
- 生成带关键字红框的全图截图
- 生成以关键字中心为基准的局部区域截图

项目内同时提供了多种渲染方案，推荐优先使用 `pypdfium2` 版本。

## 功能概览

- `full_page_screenshot.py`
  搜索关键字后，输出指定全图区域截图，并在图中标记关键字位置。

- `region_screenshot.py`
  使用 `PyMuPDF` 渲染局部区域截图。
  坐标准确，但渲染观感一般。

- `region_screenshot_pdf2image.py`
  使用 `pdf2image + Poppler` 渲染局部区域截图。
  渲染效果较好，但大页面高 DPI 时容易受整页渲染尺寸限制。

- `region_screenshot_pypdfium2.py`
  使用 `PyMuPDF` 搜索关键字，使用 `pypdfium2` 直接渲染局部区域。
  这是当前推荐方案，兼顾坐标准确性和高 DPI 局部渲染能力。

- `get_pdf_info.py`
  输出 PDF 每页尺寸，辅助配置截图范围。

## 环境要求

- Python 3.10+
- Windows 已验证

已用到的 Python 包：

```bash
pip install pymupdf pypdfium2 pdf2image pillow pyyaml python-dotenv
```

如果需要使用 `region_screenshot_pdf2image.py`，还需要安装 Poppler，并在 `.env` 中配置 `POPPLER_PATH`。

## 项目结构

```text
GetLocInPdf/
├─ config.yaml
├─ .env
├─ full_page_screenshot.py
├─ region_screenshot.py
├─ region_screenshot_pdf2image.py
├─ region_screenshot_pypdfium2.py
├─ get_pdf_info.py
├─ logging_config.py
├─ output/
└─ logs/
```

## 配置方式

项目通过 `config.yaml` 读取结构化配置，再用 `.env` 注入实际值。

### 1. `.env`

示例：

```env
LOG_LEVEL=INFO
PDF_PATH=D:/your/pdf/folder/
PDF_FILE=D:/your/pdf/folder/example.pdf
OUTPUT_DIR=./output
OUTPUT_FILENAME=result.png

FULL_PAGE_RECT_X1=280
FULL_PAGE_RECT_Y1=800
FULL_PAGE_RECT_X2=2800
FULL_PAGE_RECT_Y2=1650

FULL_PAGE_BORDER_X1=-20
FULL_PAGE_BORDER_Y1=-10
FULL_PAGE_BORDER_X2=20
FULL_PAGE_BORDER_Y2=10
FULL_PAGE_BORDER_WIDTH=3
DPI=600

REGION_RECT_X1=-50
REGION_RECT_Y1=-80
REGION_RECT_X2=50
REGION_RECT_Y2=50

REGION_BORDER_X1=-10
REGION_BORDER_Y1=-5
REGION_BORDER_X2=10
REGION_BORDER_Y2=5
REGION_BORDER_WIDTH=1.5
REGION_BORDER_OPACITY=0.5
REGION_DPI=1000

POPPLER_PATH=D:/path/to/poppler/Library/bin
```

### 2. `config.yaml`

关键字段：

- `pdf.file`
  PDF 文件完整路径

- `pdf.keywords`
  要搜索的关键字列表

- `pdf.full_page_rect`
  全图截图范围，绝对坐标

- `pdf.region_rect`
  局部截图范围，基于关键字中心点的偏移量

- `pdf.full_page_keyword_border`
  全图中关键字红框范围

- `pdf.region_keyword_border`
  局部截图中关键字红框范围

- `output.directory`
  输出目录

- `output.filename`
  输出文件基础名

## 使用方法

### 查看 PDF 页面尺寸

```bash
python get_pdf_info.py
```

用于确认页面宽高，方便配置截图范围。

### 生成全图截图

```bash
python full_page_screenshot.py
```

### 生成局部截图

`PyMuPDF` 版本：

```bash
python region_screenshot.py
```

`pdf2image` 版本：

```bash
python region_screenshot_pdf2image.py
```

推荐的 `pypdfium2` 版本：

```bash
python region_screenshot_pypdfium2.py
```

## 输出结果

输出文件默认保存在 `output/` 目录。

常见命名格式：

- `result_关键字_全图截图.png`
- `result_关键字_区域截图.png`
- 当同页命中多个同名关键字时，会自动追加 `_1`、`_2` 等后缀

日志文件默认保存在 `logs/` 目录，并按脚本名分别生成。

## 坐标说明

- PDF 默认坐标单位是 point，基准通常为 `72 DPI`
- `region_rect` 和 `region_keyword_border` 都是“相对关键字中心点的偏移量”
- 对旋转页面，项目内部已做坐标转换
- `region_screenshot.py` 和 `region_screenshot_pypdfium2.py` 当前都能正确处理旋转页截图

## 推荐方案

如果你的目标是“坐标准确 + 局部截图清晰”，推荐优先使用：

```bash
python region_screenshot_pypdfium2.py
```

原因：

- 关键字定位仍然使用 `PyMuPDF`，坐标准确
- 实际截图渲染使用 `pypdfium2`，观感通常优于 `PyMuPDF`
- 只渲染目标区域，不像 `pdf2image` 那样必须先整页高 DPI 渲染
- 对大图纸、高 DPI 局部截图更友好

## 常见问题

### 1. 找不到关键字

- 确认 `config.yaml` 中 `pdf.keywords` 配置正确
- 确认 PDF 中该文本是可搜索文本，而不是纯扫描图片

### 2. 截图区域不对

- 先运行 `get_pdf_info.py` 查看页面尺寸
- 再调整 `.env` 中的 `REGION_RECT_*` 或 `FULL_PAGE_RECT_*`
- 局部截图范围是相对关键字中心点的偏移，不是绝对坐标

### 3. `pdf2image` 高 DPI 失败

这是整页高分辨率渲染带来的限制，建议改用：

```bash
python region_screenshot_pypdfium2.py
```

### 4. `POPPLER_PATH` 报错

只影响 `region_screenshot_pdf2image.py`。
请确认它指向 Poppler 的 `bin` 目录，例如：

```text
D:/poppler/Library/bin
```

## 当前建议

日常使用建议：

1. 用 `get_pdf_info.py` 确认页面尺寸
2. 用 `full_page_screenshot.py` 调整全图范围
3. 用 `region_screenshot_pypdfium2.py` 生成最终局部截图
