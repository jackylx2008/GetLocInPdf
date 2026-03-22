import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import fitz  # PyMuPDF，用于文本检索、页面几何信息和坐标处理
import pypdfium2 as pdfium
import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw

# 加载环境变量
load_dotenv(dotenv_path="common.env")

RectConfig = fitz.Rect | Mapping[str, Any]
ColorConfig = str | Sequence[int]


@dataclass(frozen=True)
class BorderStyle:
    """关键字边框样式。"""

    width: float = 1.5
    color: ColorConfig = (255, 0, 0)
    opacity: float = 1.0
    fill: bool = False


@dataclass(frozen=True)
class ScreenshotResult:
    """截图结果元数据，供后续脚本继续处理。"""

    keyword: str
    page_number: int
    match_index: int
    output_path: str


@dataclass(frozen=True)
class PageContext:
    """单页处理上下文。"""

    page_number: int
    fitz_page: fitz.Page
    pdfium_page: pdfium.PdfPage


class ConfigLoader:
    """配置加载器。"""

    @staticmethod
    def load(config_path: str = "config.yaml") -> dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as file:
            content = file.read()
            for key, value in os.environ.items():
                content = content.replace(f"${{{key}}}", value)
            return yaml.safe_load(content)


class OutputManager:
    """输出目录管理器。"""

    @staticmethod
    def prepare(output_dir: str, clear_existing: bool = False) -> None:
        if clear_existing and os.path.exists(output_dir):
            logging.info("正在清空输出目录: %s", output_dir)
            shutil.rmtree(output_dir)
        os.makedirs(output_dir, exist_ok=True)


class RectHelper:
    """PDF 坐标与截图区域辅助工具。"""

    @staticmethod
    def to_render_rect(page: fitz.Page, rect: fitz.Rect) -> fitz.Rect:
        if page.rotation == 0:
            return fitz.Rect(rect)

        p1 = fitz.Point(rect.x0, rect.y0) * page.rotation_matrix
        p2 = fitz.Point(rect.x1, rect.y1) * page.rotation_matrix
        render_rect = fitz.Rect(p1, p2)
        render_rect.normalize()
        return render_rect

    @staticmethod
    def coerce(rect_cfg: RectConfig) -> fitz.Rect:
        if isinstance(rect_cfg, fitz.Rect):
            rect = fitz.Rect(rect_cfg)
        else:
            rect = fitz.Rect(
                float(rect_cfg["x1"]),
                float(rect_cfg["y1"]),
                float(rect_cfg["x2"]),
                float(rect_cfg["y2"]),
            )
        rect.normalize()
        return rect

    @classmethod
    def centered(
        cls, center_x: float, center_y: float, rect_cfg: RectConfig
    ) -> fitz.Rect:
        rect_cfg = cls.coerce(rect_cfg)
        rect = fitz.Rect(
            center_x + rect_cfg.x0,
            center_y + rect_cfg.y0,
            center_x + rect_cfg.x1,
            center_y + rect_cfg.y1,
        )
        rect.normalize()
        return rect

    @staticmethod
    def clamp(rect: fitz.Rect, page_width: float, page_height: float) -> fitz.Rect:
        bounded = fitz.Rect(rect)
        bounded.intersect(fitz.Rect(0, 0, page_width, page_height))
        bounded.normalize()
        return bounded


class ColorHelper:
    """颜色转换工具。"""

    @staticmethod
    def normalize(color: ColorConfig) -> tuple[int, int, int]:
        if isinstance(color, str):
            value = color.strip().lstrip("#")
            if len(value) != 6:
                raise ValueError(f"不支持的颜色格式: {color}")
            # pylint: disable=use-list-literal
            rgb = tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))
            return (rgb[0], rgb[1], rgb[2])

        values = tuple(int(channel) for channel in color)
        if len(values) != 3:
            raise ValueError(f"颜色必须包含 3 个通道: {color}")
        processed = tuple(max(0, min(255, channel)) for channel in values)
        return (processed[0], processed[1], processed[2])


class PdfPageRenderer:
    """负责 PDF 区域渲染与边框绘制。"""

    def __init__(self, dpi: float) -> None:
        self.dpi = float(dpi)
        self.scale = self.dpi / 72.0

    def render_clip(
        self,
        pdfium_page: pdfium.PdfPage,
        clip_rect: fitz.Rect,
    ) -> tuple[Image.Image | None, fitz.Rect]:
        page_width, page_height = pdfium_page.get_size()
        clip_rect = RectHelper.clamp(clip_rect, page_width, page_height)
        if clip_rect.is_empty or clip_rect.width <= 0 or clip_rect.height <= 0:
            return None, clip_rect

        crop = (
            clip_rect.x0,
            page_height - clip_rect.y1,
            page_width - clip_rect.x1,
            clip_rect.y0,
        )
        bitmap = pdfium_page.render(
            scale=int(round(self.scale)),
            crop=crop,
            rev_byteorder=True,
        )
        return bitmap.to_pil().convert("RGBA"), clip_rect

    def draw_border(
        self,
        image: Image.Image,
        clip_rect: fitz.Rect,
        border_rect: fitz.Rect,
        border_style: BorderStyle,
    ) -> Image.Image:
        color = ColorHelper.normalize(border_style.color)
        alpha = max(0, min(255, int(round(float(border_style.opacity) * 255))))
        local_rect = fitz.Rect(
            (border_rect.x0 - clip_rect.x0) * self.scale,
            (border_rect.y0 - clip_rect.y0) * self.scale,
            (border_rect.x1 - clip_rect.x0) * self.scale,
            (border_rect.y1 - clip_rect.y0) * self.scale,
        )
        local_rect.normalize()

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        width_px = max(1, int(round(float(border_style.width) * self.scale)))
        fill_rgba = (*color, alpha) if border_style.fill else None

        draw = ImageDraw.Draw(overlay, "RGBA")
        draw.rectangle(
            [local_rect.x0, local_rect.y0, local_rect.x1, local_rect.y1],
            outline=(*color, alpha),
            fill=fill_rgba,
            width=width_px,
        )
        return Image.alpha_composite(image, overlay)


class PdfKeywordDocument:
    """统一管理 PyMuPDF 检索文档与 pypdfium2 渲染文档生命周期。"""

    def __init__(self, pdf_path: str) -> None:
        self.pdf_path = pdf_path
        self.fitz_doc: fitz.Document | None = None
        self.pdfium_doc: pdfium.PdfDocument | None = None

    def __enter__(self) -> "PdfKeywordDocument":
        self.fitz_doc = fitz.open(self.pdf_path)
        self.pdfium_doc = pdfium.PdfDocument(self.pdf_path)
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self.fitz_doc is not None:
            self.fitz_doc.close()
        if self.pdfium_doc is not None:
            self.pdfium_doc.close()

    def iter_pages(self) -> Sequence[PageContext]:
        assert self.fitz_doc is not None
        assert self.pdfium_doc is not None
        return [
            PageContext(
                page_number=page_num + 1,
                fitz_page=self.fitz_doc.load_page(page_num),
                pdfium_page=self.pdfium_doc[page_num],
            )
            for page_num in range(len(self.fitz_doc))
        ]


class KeywordScreenshotJob(ABC):
    """截图任务基类，负责输入校验与文档生命周期。"""

    def __init__(
        self,
        pdf_path: str,
        keywords: str | Sequence[str],
        output_dir: str,
        output_filename_base: str,
        border_style: BorderStyle | None = None,
        dpi: float = 300,
    ) -> None:
        self.pdf_path = pdf_path
        self.keywords = self._normalize_keywords(keywords)
        self.output_dir = output_dir
        self.output_filename_base = output_filename_base
        self.border_style = border_style or self.default_border_style()
        self.renderer = PdfPageRenderer(dpi)

    @staticmethod
    def _normalize_keywords(keywords: str | Sequence[str]) -> list[str]:
        if isinstance(keywords, str):
            return [keywords]
        return [keyword for keyword in keywords if keyword]

    def run(self) -> list[ScreenshotResult]:
        if not os.path.exists(self.pdf_path):
            logging.error("PDF 文件不存在: %s", self.pdf_path)
            return []
        if not self.keywords:
            logging.warning("未提供任何关键字，已跳过截图。")
            return []

        OutputManager.prepare(self.output_dir)
        with PdfKeywordDocument(self.pdf_path) as document:
            return self.capture(document)

    def _search_keyword(self, page: PageContext, keyword: str) -> list[fitz.Rect]:
        return page.fitz_page.search_for(keyword)

    @staticmethod
    def _keyword_center(rect: fitz.Rect) -> tuple[float, float]:
        return (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2

    @abstractmethod
    def default_border_style(self) -> BorderStyle:
        """子类提供默认边框样式。"""

    @abstractmethod
    def capture(self, document: PdfKeywordDocument) -> list[ScreenshotResult]:
        """执行具体截图逻辑。"""


class FullPageScreenshotJob(KeywordScreenshotJob):
    """全图截图任务。"""

    def __init__(
        self,
        pdf_path: str,
        keywords: str | Sequence[str],
        output_dir: str,
        output_filename_base: str,
        full_page_rect: RectConfig | None = None,
        border_rect: RectConfig | None = None,
        border_style: BorderStyle | None = None,
        dpi: float = 300,
    ) -> None:
        super().__init__(
            pdf_path=pdf_path,
            keywords=keywords,
            output_dir=output_dir,
            output_filename_base=output_filename_base,
            border_style=border_style,
            dpi=dpi,
        )
        self.full_page_rect = full_page_rect
        self.border_rect = border_rect

    def default_border_style(self) -> BorderStyle:
        return BorderStyle(fill=False)

    def capture(self, document: PdfKeywordDocument) -> list[ScreenshotResult]:
        results: list[ScreenshotResult] = []
        total_matches = 0

        for page in document.iter_pages():
            page_clip_rect = (
                RectHelper.coerce(self.full_page_rect)
                if self.full_page_rect
                else page.fitz_page.rect
            )
            base_img, clip_rect = self.renderer.render_clip(
                page.pdfium_page,
                page_clip_rect,
            )
            if base_img is None:
                logging.warning("第 %s 页截图区域无效，已跳过。", page.page_number)
                continue

            for keyword in self.keywords:
                text_instances = self._search_keyword(page, keyword)
                if not text_instances:
                    continue

                page_img = base_img.copy()
                for match_index, inst in enumerate(text_instances, start=1):
                    render_inst = RectHelper.to_render_rect(page.fitz_page, inst)
                    draw_rect = self._resolve_border_rect(render_inst)
                    page_img = self.renderer.draw_border(
                        page_img,
                        clip_rect,
                        draw_rect,
                        self.border_style,
                    )
                    total_matches += 1
                    logging.info(
                        "在第 %s 页找到关键字 '%s'，匹配序号 %s。",
                        page.page_number,
                        keyword,
                        match_index,
                    )

                output_path = os.path.join(
                    self.output_dir,
                    f"{self.output_filename_base}_{keyword}_P{page.page_number}_全图截图.png",
                )
                page_img.convert("RGB").save(output_path)
                results.append(
                    ScreenshotResult(
                        keyword=keyword,
                        page_number=page.page_number,
                        match_index=0,
                        output_path=output_path,
                    )
                )
                logging.info("截图已保存至: %s", output_path)

        if total_matches == 0:
            logging.warning("未找到任何关键字。")
        else:
            logging.info(
                "处理完成，共找到 %s 处关键字，输出 %s 张全图截图。",
                total_matches,
                len(results),
            )
        return results

    def _resolve_border_rect(self, render_inst: fitz.Rect) -> fitz.Rect:
        if not self.border_rect:
            return render_inst
        center_x, center_y = self._keyword_center(render_inst)
        return RectHelper.centered(center_x, center_y, self.border_rect)


class RegionScreenshotJob(KeywordScreenshotJob):
    """区域截图任务。"""

    def __init__(
        self,
        pdf_path: str,
        keywords: str | Sequence[str],
        output_dir: str,
        output_filename_base: str,
        region_rect: RectConfig,
        border_rect: RectConfig | None = None,
        border_style: BorderStyle | None = None,
        dpi: float = 300,
    ) -> None:
        super().__init__(
            pdf_path=pdf_path,
            keywords=keywords,
            output_dir=output_dir,
            output_filename_base=output_filename_base,
            border_style=border_style,
            dpi=dpi,
        )
        self.region_rect = region_rect
        self.border_rect = border_rect

    def default_border_style(self) -> BorderStyle:
        return BorderStyle(fill=True)

    def capture(self, document: PdfKeywordDocument) -> list[ScreenshotResult]:
        results: list[ScreenshotResult] = []

        for page in document.iter_pages():
            page_width, page_height = page.pdfium_page.get_size()
            for keyword in self.keywords:
                text_instances = self._search_keyword(page, keyword)
                if not text_instances:
                    continue

                for match_index, inst in enumerate(text_instances, start=1):
                    render_inst = RectHelper.to_render_rect(page.fitz_page, inst)
                    center_x, center_y = self._keyword_center(render_inst)
                    clip_rect = RectHelper.centered(
                        center_x, center_y, self.region_rect
                    )
                    clip_rect = RectHelper.clamp(clip_rect, page_width, page_height)
                    if (
                        clip_rect.is_empty
                        or clip_rect.width <= 0
                        or clip_rect.height <= 0
                    ):
                        logging.error(
                            "第 %s 页关键字 '%s' 的截图区域无效: %s",
                            page.page_number,
                            keyword,
                            clip_rect,
                        )
                        continue

                    region_img, actual_clip = self.renderer.render_clip(
                        page.pdfium_page,
                        clip_rect,
                    )
                    if region_img is None:
                        logging.error(
                            "第 %s 页关键字 '%s' 渲染失败。",
                            page.page_number,
                            keyword,
                        )
                        continue

                    draw_rect = self._resolve_border_rect(page, inst, render_inst)
                    region_img = self.renderer.draw_border(
                        region_img,
                        actual_clip,
                        draw_rect,
                        self.border_style,
                    )

                    suffix = f"_{match_index}" if len(text_instances) > 1 else ""
                    output_path = os.path.join(
                        self.output_dir,
                        f"{self.output_filename_base}_{keyword}_P{page.page_number}_区域截图{suffix}.png",
                    )
                    region_img.convert("RGB").save(output_path)
                    results.append(
                        ScreenshotResult(
                            keyword=keyword,
                            page_number=page.page_number,
                            match_index=match_index,
                            output_path=output_path,
                        )
                    )
                    logging.info(
                        "区域截图已保存: %s (页码=%s, 匹配=%s)",
                        output_path,
                        page.page_number,
                        match_index,
                    )

        if not results:
            logging.warning("未找到任何关键字。")
        else:
            logging.info("处理完成，共生成 %s 张区域截图。", len(results))
        return results

    def _resolve_border_rect(
        self,
        page: PageContext,
        source_inst: fitz.Rect,
        render_inst: fitz.Rect,
    ) -> fitz.Rect:
        if not self.border_rect:
            return fitz.Rect(render_inst)

        source_center_x, source_center_y = self._keyword_center(source_inst)
        source_border_rect = RectHelper.centered(
            source_center_x,
            source_center_y,
            self.border_rect,
        )
        return RectHelper.to_render_rect(page.fitz_page, source_border_rect)


def load_config(config_path: str = "config.yaml") -> dict[str, Any]:
    """兼容旧调用方式的配置加载入口。"""
    return ConfigLoader.load(config_path)


def prepare_output_dir(output_dir: str, clear_existing: bool = False) -> None:
    """兼容旧调用方式的输出目录入口。"""
    OutputManager.prepare(output_dir, clear_existing=clear_existing)


def capture_full_page_screenshots(
    pdf_path: str,
    keywords: str | Sequence[str],
    output_dir: str,
    output_filename_base: str,
    full_page_rect: RectConfig | None = None,
    border_rect: RectConfig | None = None,
    border_style: BorderStyle | None = None,
    dpi: float = 300,
) -> list[ScreenshotResult]:
    """兼容旧调用方式的全图截图入口。"""
    return FullPageScreenshotJob(
        pdf_path=pdf_path,
        keywords=keywords,
        output_dir=output_dir,
        output_filename_base=output_filename_base,
        full_page_rect=full_page_rect,
        border_rect=border_rect,
        border_style=border_style,
        dpi=dpi,
    ).run()


def capture_region_screenshots(
    pdf_path: str,
    keywords: str | Sequence[str],
    output_dir: str,
    output_filename_base: str,
    region_rect: RectConfig,
    border_rect: RectConfig | None = None,
    border_style: BorderStyle | None = None,
    dpi: float = 300,
) -> list[ScreenshotResult]:
    """兼容旧调用方式的区域截图入口。"""
    return RegionScreenshotJob(
        pdf_path=pdf_path,
        keywords=keywords,
        output_dir=output_dir,
        output_filename_base=output_filename_base,
        region_rect=region_rect,
        border_rect=border_rect,
        border_style=border_style,
        dpi=dpi,
    ).run()
