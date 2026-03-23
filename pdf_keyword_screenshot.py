import logging
import math
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import fitz  # PyMuPDF，用于文本检索、页面几何信息和坐标处理
import pypdfium2 as pdfium
import yaml
from dotenv import load_dotenv
from line_box_cache import AxisAlignedLine, LineCacheStore, get_page_axis_lines
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
    offset: float = 0.0
    fill: bool = False
    outline_color: ColorConfig | None = None
    outline_opacity: float | None = None
    fill_color: ColorConfig | None = None
    fill_opacity: float | None = None


@dataclass(frozen=True)
class ArrowStyle:
    """区域截图箭头样式。"""

    color: ColorConfig = (255, 0, 0)
    opacity: float = 1.0
    corner_gap: float = 0.0
    size: float = 18.0
    tail_length: float = 36.0


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


@dataclass(frozen=True)
class LineBoxDetectionConfig:
    """区域截图中基于矢量线自动识别红框的配置。"""

    mode: str = "nearest_line_box"
    min_length: float = 20.0
    axis_tolerance: float = 0.5
    search_margin: float = 200.0
    cache_enabled: bool = True
    cache_dir: str = "cache/line_boxes"


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
    def to_render_point(page: fitz.Page, point: fitz.Point) -> fitz.Point:
        if page.rotation == 0:
            return fitz.Point(point)
        return fitz.Point(point) * page.rotation_matrix

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

    @staticmethod
    def expand(rect: fitz.Rect, offset: float) -> fitz.Rect:
        expanded = fitz.Rect(rect)
        if offset == 0:
            expanded.normalize()
            return expanded
        expanded.x0 -= offset
        expanded.y0 -= offset
        expanded.x1 += offset
        expanded.y1 += offset
        expanded.normalize()
        return expanded


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
            scale=self.scale,
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
        draw_arrow: bool = False,
        arrow_style: ArrowStyle | None = None,
    ) -> Image.Image:
        outline_color_cfg = (
            border_style.outline_color
            if border_style.outline_color is not None
            else border_style.color
        )
        outline_opacity_value = (
            border_style.outline_opacity
            if border_style.outline_opacity is not None
            else border_style.opacity
        )
        fill_color_cfg = (
            border_style.fill_color
            if border_style.fill_color is not None
            else outline_color_cfg
        )
        fill_opacity_value = (
            border_style.fill_opacity
            if border_style.fill_opacity is not None
            else outline_opacity_value
        )
        outline_color = ColorHelper.normalize(outline_color_cfg)
        outline_alpha = max(
            0,
            min(255, int(round(float(outline_opacity_value) * 255))),
        )
        fill_color = ColorHelper.normalize(fill_color_cfg)
        fill_alpha = max(
            0,
            min(255, int(round(float(fill_opacity_value) * 255))),
        )
        effective_scale_x = (
            image.width / clip_rect.width if clip_rect.width > 0 else self.scale
        )
        effective_scale_y = (
            image.height / clip_rect.height if clip_rect.height > 0 else self.scale
        )
        adjusted_border_rect = RectHelper.expand(
            border_rect,
            float(border_style.offset),
        )
        adjusted_border_rect.intersect(clip_rect)
        adjusted_border_rect.normalize()
        if adjusted_border_rect.is_empty or adjusted_border_rect.width <= 0:
            adjusted_border_rect = fitz.Rect(border_rect)
            adjusted_border_rect.normalize()
            adjusted_border_rect.intersect(clip_rect)
            adjusted_border_rect.normalize()
        if adjusted_border_rect.is_empty or adjusted_border_rect.height <= 0:
            adjusted_border_rect = fitz.Rect(border_rect)
            adjusted_border_rect.normalize()
            adjusted_border_rect.intersect(clip_rect)
            adjusted_border_rect.normalize()
        local_rect = fitz.Rect(
            (adjusted_border_rect.x0 - clip_rect.x0) * effective_scale_x,
            (adjusted_border_rect.y0 - clip_rect.y0) * effective_scale_y,
            (adjusted_border_rect.x1 - clip_rect.x0) * effective_scale_x,
            (adjusted_border_rect.y1 - clip_rect.y0) * effective_scale_y,
        )
        local_rect.normalize()

        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        effective_scale = max(effective_scale_x, effective_scale_y)
        width_px = max(1, int(round(float(border_style.width) * effective_scale)))
        fill_rgba = (*fill_color, fill_alpha) if border_style.fill else None

        draw = ImageDraw.Draw(overlay, "RGBA")
        draw.rectangle(
            [local_rect.x0, local_rect.y0, local_rect.x1, local_rect.y1],
            outline=(*outline_color, outline_alpha),
            fill=fill_rgba,
            width=width_px,
        )
        if draw_arrow:
            effective_arrow_style = arrow_style or ArrowStyle(
                color=outline_color_cfg,
                opacity=float(outline_opacity_value),
                corner_gap=0.0,
                size=18.0,
                tail_length=36.0,
            )
            self._draw_corner_arrow(
                draw,
                image_size=image.size,
                target_rect=local_rect,
                color=ColorHelper.normalize(effective_arrow_style.color),
                alpha=max(
                    0,
                    min(255, int(round(float(effective_arrow_style.opacity) * 255))),
                ),
                corner_gap_px=float(effective_arrow_style.corner_gap) * effective_scale,
                arrow_size_px=float(effective_arrow_style.size) * effective_scale,
                tail_length_px=float(effective_arrow_style.tail_length) * effective_scale,
            )
        return Image.alpha_composite(image, overlay)

    def _draw_corner_arrow(
        self,
        draw: ImageDraw.ImageDraw,
        image_size: tuple[int, int],
        target_rect: fitz.Rect,
        color: tuple[int, int, int],
        alpha: int,
        corner_gap_px: float,
        arrow_size_px: float,
        tail_length_px: float,
    ) -> None:
        arrow_geometry = self._resolve_corner_arrow_geometry(
            image_size,
            target_rect,
            corner_gap_px=corner_gap_px,
            arrow_size_px=arrow_size_px,
            tail_length_px=tail_length_px,
        )
        if arrow_geometry is None:
            return

        tail, tip, left_wing, right_wing, shaft_width = arrow_geometry
        rgba = (*color, alpha)
        draw.line([tail, tip], fill=rgba, width=shaft_width)
        draw.polygon([tip, left_wing, right_wing], fill=rgba)

    def _resolve_corner_arrow_geometry(
        self,
        image_size: tuple[int, int],
        target_rect: fitz.Rect,
        corner_gap_px: float = 0.0,
        arrow_size_px: float = 18.0,
        tail_length_px: float = 36.0,
    ) -> tuple[
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        tuple[float, float],
        int,
    ] | None:
        image_width, image_height = image_size
        if image_width <= 0 or image_height <= 0:
            return None

        margin = max(12.0, min(float(min(image_width, image_height)) * 0.03, 36.0))
        shaft_width = max(4, int(round(min(image_width, image_height) * 0.006)))
        desired_head_length = max(12.0, float(arrow_size_px))
        desired_head_width = max(10.0, desired_head_length * 0.75)
        desired_tail_length = max(12.0, float(tail_length_px))
        desired_total_length = desired_head_length + desired_tail_length

        candidates = [
            ("top_left", (target_rect.x0, target_rect.y0), (-1.0, -1.0)),
            ("top_right", (target_rect.x1, target_rect.y0), (1.0, -1.0)),
            ("bottom_right", (target_rect.x1, target_rect.y1), (1.0, 1.0)),
            ("bottom_left", (target_rect.x0, target_rect.y1), (-1.0, 1.0)),
        ]
        best_candidate: tuple[float, tuple[tuple[float, float], ...], int] | None = None

        for _, tip, outward in candidates:
            unit_outward = self._normalize_vector(outward)
            if unit_outward is None:
                continue
            shifted_tip = (
                tip[0] + unit_outward[0] * max(0.0, corner_gap_px),
                tip[1] + unit_outward[1] * max(0.0, corner_gap_px),
            )

            max_length = self._max_arrow_length(
                tip=shifted_tip,
                outward=unit_outward,
                image_width=image_width,
                image_height=image_height,
                margin=margin,
            )
            min_visible_length = max(20.0, desired_total_length * 0.45)
            if max_length < min_visible_length:
                continue

            scale_ratio = min(1.0, max_length / desired_total_length)
            head_length = desired_head_length * scale_ratio
            head_width = desired_head_width * scale_ratio
            tail_length = desired_tail_length * scale_ratio
            total_length = head_length + tail_length
            tail = (
                shifted_tip[0] + unit_outward[0] * total_length,
                shifted_tip[1] + unit_outward[1] * total_length,
            )
            line_unit = self._normalize_vector(
                (shifted_tip[0] - tail[0], shifted_tip[1] - tail[1])
            )
            if line_unit is None:
                continue

            base_center = (
                shifted_tip[0] - line_unit[0] * head_length,
                shifted_tip[1] - line_unit[1] * head_length,
            )
            perp = (-line_unit[1], line_unit[0])
            left_wing = (
                base_center[0] + perp[0] * (head_width / 2),
                base_center[1] + perp[1] * (head_width / 2),
            )
            right_wing = (
                base_center[0] - perp[0] * (head_width / 2),
                base_center[1] - perp[1] * (head_width / 2),
            )
            points = (tail, shifted_tip, left_wing, right_wing)
            if not self._points_inside_image(points, image_width, image_height, margin=1.0):
                continue

            score = total_length
            if best_candidate is None or score > best_candidate[0]:
                best_candidate = (score, points, shaft_width)

        if best_candidate is None:
            return None

        _, points, width = best_candidate
        return points[0], points[1], points[2], points[3], width

    @staticmethod
    def _normalize_vector(
        vector: tuple[float, float]
    ) -> tuple[float, float] | None:
        length = math.hypot(vector[0], vector[1])
        if length == 0:
            return None
        return (vector[0] / length, vector[1] / length)

    @staticmethod
    def _max_arrow_length(
        tip: tuple[float, float],
        outward: tuple[float, float],
        image_width: int,
        image_height: int,
        margin: float,
    ) -> float:
        limits: list[float] = []
        if outward[0] < 0:
            limits.append((tip[0] - margin) / abs(outward[0]))
        elif outward[0] > 0:
            limits.append(((image_width - margin) - tip[0]) / outward[0])

        if outward[1] < 0:
            limits.append((tip[1] - margin) / abs(outward[1]))
        elif outward[1] > 0:
            limits.append(((image_height - margin) - tip[1]) / outward[1])

        if not limits:
            return 0.0
        return max(0.0, min(limits))

    @staticmethod
    def _points_inside_image(
        points: Sequence[tuple[float, float]],
        image_width: int,
        image_height: int,
        margin: float = 0.0,
    ) -> bool:
        for point_x, point_y in points:
            if point_x < margin or point_x > (image_width - margin):
                return False
            if point_y < margin or point_y > (image_height - margin):
                return False
        return True


class NearestLineBoxDetector:
    """根据关键词中心向四个方向检索最近的水平 / 垂直边线。"""

    def __init__(
        self,
        config: LineBoxDetectionConfig | None = None,
        pdf_path: str | None = None,
    ) -> None:
        self.config = config or LineBoxDetectionConfig()
        self.pdf_path = os.path.abspath(pdf_path) if pdf_path else None
        self.line_cache_store = LineCacheStore(
            cache_dir=self.config.cache_dir,
            enabled=self.config.cache_enabled,
        )
        self._page_line_cache: dict[
            int, tuple[list[AxisAlignedLine], list[AxisAlignedLine]]
        ] = {}

    def detect(self, page: fitz.Page, keyword_rect: fitz.Rect) -> fitz.Rect | None:
        if self.config.mode != "nearest_line_box":
            return None

        center_x = (keyword_rect.x0 + keyword_rect.x1) / 2
        center_y = (keyword_rect.y0 + keyword_rect.y1) / 2
        vertical_lines, horizontal_lines = self._collect_lines(page)
        boundary_vertical_lines, boundary_horizontal_lines = self._prepare_boundary_lines(
            vertical_lines,
            horizontal_lines,
        )
        room_rect = self._detect_smallest_enclosing_room(
            boundary_vertical_lines,
            boundary_horizontal_lines,
            keyword_rect,
        )
        if room_rect is not None:
            return self._refine_room_rect(
                room_rect,
                boundary_vertical_lines,
                boundary_horizontal_lines,
                keyword_rect,
            )

        # 回退到旧的“就近边框”策略，尽量保持原有兼容性。
        projection_tolerance = max(1.0, float(self.config.axis_tolerance) * 2)
        primary_min_length = float(self.config.min_length)

        left = self._pick_vertical_boundary(
            boundary_vertical_lines or vertical_lines,
            center_x,
            center_y,
            direction="left",
            projection_tolerance=projection_tolerance,
            min_length=primary_min_length,
        )
        right = self._pick_vertical_boundary(
            boundary_vertical_lines or vertical_lines,
            center_x,
            center_y,
            direction="right",
            projection_tolerance=projection_tolerance,
            min_length=primary_min_length,
        )

        if not all((left, right)):
            return None

        top = self._pick_horizontal_closing_boundary(
            boundary_horizontal_lines or horizontal_lines,
            left,
            right,
            center_y,
            direction="up",
        ) or self._pick_horizontal_boundary(
            boundary_horizontal_lines or horizontal_lines,
            center_x,
            center_y,
            direction="up",
            projection_tolerance=projection_tolerance,
            min_length=primary_min_length,
        )
        bottom = self._pick_horizontal_closing_boundary(
            boundary_horizontal_lines or horizontal_lines,
            left,
            right,
            center_y,
            direction="down",
        ) or self._pick_horizontal_boundary(
            boundary_horizontal_lines or horizontal_lines,
            center_x,
            center_y,
            direction="down",
            projection_tolerance=projection_tolerance,
            min_length=primary_min_length,
        )

        if not all((top, bottom)):
            return None
        if left.axis_value >= right.axis_value or top.axis_value >= bottom.axis_value:
            return None

        border_rect = fitz.Rect(
            left.axis_value,
            top.axis_value,
            right.axis_value,
            bottom.axis_value,
        )
        border_rect.normalize()
        return border_rect

    def _prepare_boundary_lines(
        self,
        vertical_lines: Sequence[AxisAlignedLine],
        horizontal_lines: Sequence[AxisAlignedLine],
    ) -> tuple[list[AxisAlignedLine], list[AxisAlignedLine]]:
        filtered_vertical = self._filter_room_boundary_lines(vertical_lines)
        filtered_horizontal = self._filter_room_boundary_lines(horizontal_lines)
        return (
            self._merge_axis_lines(filtered_vertical),
            self._merge_axis_lines(filtered_horizontal),
        )

    def _filter_room_boundary_lines(
        self,
        lines: Sequence[AxisAlignedLine],
    ) -> list[AxisAlignedLine]:
        filtered_lines = [
            line for line in lines if self._is_room_boundary_layer(line.layer)
        ]
        return filtered_lines if filtered_lines else list(lines)

    def _is_room_boundary_layer(self, layer: str | None) -> bool:
        if not layer:
            return False

        layer_upper = layer.upper()
        if layer_upper == "A-WALL":
            return True
        return "00-WALL" in layer_upper

    def _merge_axis_lines(
        self,
        lines: Sequence[AxisAlignedLine],
    ) -> list[AxisAlignedLine]:
        if not lines:
            return []

        axis_merge_tolerance = max(0.5, float(self.config.axis_tolerance) * 2)
        span_gap_tolerance = max(3.0, float(self.config.axis_tolerance) * 10)
        sorted_lines = sorted(
            lines,
            key=lambda line: (
                line.orientation,
                line.layer or "",
                round(line.axis_value / axis_merge_tolerance),
                line.span_start,
                line.span_end,
            ),
        )
        merged_lines: list[AxisAlignedLine] = []

        for line in sorted_lines:
            if not merged_lines:
                merged_lines.append(line)
                continue

            previous = merged_lines[-1]
            same_group = (
                previous.orientation == line.orientation
                and (previous.layer or "") == (line.layer or "")
                and abs(previous.axis_value - line.axis_value) <= axis_merge_tolerance
                and line.span_start <= (previous.span_end + span_gap_tolerance)
            )
            if not same_group:
                merged_lines.append(line)
                continue

            merged_lines[-1] = AxisAlignedLine(
                orientation=previous.orientation,
                axis_value=round((previous.axis_value + line.axis_value) / 2, 2),
                span_start=min(previous.span_start, line.span_start),
                span_end=max(previous.span_end, line.span_end),
                layer=previous.layer or line.layer,
            )

        return merged_lines

    def _detect_smallest_enclosing_room(
        self,
        vertical_lines: Sequence[AxisAlignedLine],
        horizontal_lines: Sequence[AxisAlignedLine],
        keyword_rect: fitz.Rect,
    ) -> fitz.Rect | None:
        if not vertical_lines or not horizontal_lines:
            return None

        center_x = (keyword_rect.x0 + keyword_rect.x1) / 2
        center_y = (keyword_rect.y0 + keyword_rect.y1) / 2
        projection_tolerance = max(1.0, float(self.config.axis_tolerance) * 2)
        search_margin = float(self.config.search_margin)
        min_room_width = max(
            keyword_rect.width + projection_tolerance * 2,
            12.0,
        )
        min_room_height = max(
            keyword_rect.height + projection_tolerance * 6,
            12.0,
        )
        min_clearance = max(2.0, projection_tolerance)

        left_candidates = [
            line
            for line in vertical_lines
            if line.axis_value < center_x
            and line.covers(center_y, projection_tolerance)
            and (center_x - line.axis_value) <= search_margin
        ]
        right_candidates = [
            line
            for line in vertical_lines
            if line.axis_value > center_x
            and line.covers(center_y, projection_tolerance)
            and (line.axis_value - center_x) <= search_margin
        ]
        left_candidates = sorted(left_candidates, key=lambda line: center_x - line.axis_value)[:16]
        right_candidates = sorted(right_candidates, key=lambda line: line.axis_value - center_x)[:16]

        candidates: list[tuple[float, float, float, fitz.Rect]] = []
        for left in left_candidates:
            for right in right_candidates:
                if left.axis_value >= right.axis_value:
                    continue

                width = right.axis_value - left.axis_value
                if width < min_room_width:
                    continue

                top_candidates = self._find_closing_boundaries(
                    horizontal_lines,
                    left.axis_value,
                    right.axis_value,
                    center_y,
                    direction="up",
                )[:12]
                bottom_candidates = self._find_closing_boundaries(
                    horizontal_lines,
                    left.axis_value,
                    right.axis_value,
                    center_y,
                    direction="down",
                )[:12]

                for top in top_candidates:
                    for bottom in bottom_candidates:
                        if top.axis_value >= bottom.axis_value:
                            continue

                        height = bottom.axis_value - top.axis_value
                        if height < min_room_height:
                            continue

                        border_rect = fitz.Rect(
                            left.axis_value,
                            top.axis_value,
                            right.axis_value,
                            bottom.axis_value,
                        )
                        border_rect.normalize()
                        if not self._rect_contains_point(
                            border_rect,
                            center_x,
                            center_y,
                            tolerance=projection_tolerance,
                        ):
                            continue

                        clearances = (
                            center_x - border_rect.x0,
                            border_rect.x1 - center_x,
                            center_y - border_rect.y0,
                            border_rect.y1 - center_y,
                        )
                        if min(clearances) < min_clearance:
                            continue

                        area = border_rect.width * border_rect.height
                        perimeter = border_rect.width + border_rect.height
                        distance_penalty = (
                            (center_x - left.axis_value)
                            + (right.axis_value - center_x)
                            + (center_y - top.axis_value)
                            + (bottom.axis_value - center_y)
                        )
                        candidates.append(
                            (
                                area,
                                perimeter,
                                distance_penalty,
                                border_rect,
                            )
                        )

        if not candidates:
            return None
        return min(candidates)[3]

    def _refine_room_rect(
        self,
        border_rect: fitz.Rect,
        vertical_lines: Sequence[AxisAlignedLine],
        horizontal_lines: Sequence[AxisAlignedLine],
        keyword_rect: fitz.Rect,
    ) -> fitz.Rect:
        center_x = (keyword_rect.x0 + keyword_rect.x1) / 2
        center_y = (keyword_rect.y0 + keyword_rect.y1) / 2
        projection_tolerance = max(1.0, float(self.config.axis_tolerance) * 2)
        distance_band = max(1.0, float(self.config.axis_tolerance) * 2)

        left = self._pick_inward_vertical_boundary(
            vertical_lines,
            center_x,
            center_y,
            border_rect,
            direction="left",
            projection_tolerance=projection_tolerance,
            distance_band=distance_band,
        )
        right = self._pick_inward_vertical_boundary(
            vertical_lines,
            center_x,
            center_y,
            border_rect,
            direction="right",
            projection_tolerance=projection_tolerance,
            distance_band=distance_band,
        )
        top = self._pick_inward_horizontal_boundary(
            horizontal_lines,
            center_x,
            center_y,
            border_rect,
            direction="up",
            projection_tolerance=projection_tolerance,
            distance_band=distance_band,
        )
        bottom = self._pick_inward_horizontal_boundary(
            horizontal_lines,
            center_x,
            center_y,
            border_rect,
            direction="down",
            projection_tolerance=projection_tolerance,
            distance_band=distance_band,
        )

        refined = fitz.Rect(
            left.axis_value if left is not None else border_rect.x0,
            top.axis_value if top is not None else border_rect.y0,
            right.axis_value if right is not None else border_rect.x1,
            bottom.axis_value if bottom is not None else border_rect.y1,
        )
        refined.normalize()
        if (
            refined.x0 >= refined.x1
            or refined.y0 >= refined.y1
            or not self._rect_contains_point(
                refined,
                center_x,
                center_y,
                tolerance=projection_tolerance,
            )
        ):
            return border_rect
        return refined

    def _pick_inward_vertical_boundary(
        self,
        lines: Sequence[AxisAlignedLine],
        center_x: float,
        center_y: float,
        border_rect: fitz.Rect,
        direction: str,
        projection_tolerance: float,
        distance_band: float,
    ) -> AxisAlignedLine | None:
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if not line.covers(center_y, projection_tolerance):
                continue
            if direction == "left":
                if line.axis_value < border_rect.x0 or line.axis_value >= center_x:
                    continue
                distance = center_x - line.axis_value
                axis_rank = -line.axis_value
            else:
                if line.axis_value > border_rect.x1 or line.axis_value <= center_x:
                    continue
                distance = line.axis_value - center_x
                axis_rank = line.axis_value

            candidates.append((distance, -line.length, axis_rank, line))

        if not candidates:
            return None

        nearest_distance = min(candidate[0] for candidate in candidates)
        shortlisted = [
            candidate
            for candidate in candidates
            if candidate[0] <= (nearest_distance + distance_band)
        ]
        return min(shortlisted, key=lambda candidate: (candidate[1], candidate[0], candidate[2]))[3]

    def _pick_inward_horizontal_boundary(
        self,
        lines: Sequence[AxisAlignedLine],
        center_x: float,
        center_y: float,
        border_rect: fitz.Rect,
        direction: str,
        projection_tolerance: float,
        distance_band: float,
    ) -> AxisAlignedLine | None:
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if not line.covers(center_x, projection_tolerance):
                continue
            if direction == "up":
                if line.axis_value < border_rect.y0 or line.axis_value >= center_y:
                    continue
                distance = center_y - line.axis_value
                axis_rank = -line.axis_value
            else:
                if line.axis_value > border_rect.y1 or line.axis_value <= center_y:
                    continue
                distance = line.axis_value - center_y
                axis_rank = line.axis_value

            candidates.append((distance, -line.length, axis_rank, line))

        if not candidates:
            return None

        nearest_distance = min(candidate[0] for candidate in candidates)
        shortlisted = [
            candidate
            for candidate in candidates
            if candidate[0] <= (nearest_distance + distance_band)
        ]
        return min(shortlisted, key=lambda candidate: (candidate[1], candidate[0], candidate[2]))[3]

    def _find_closing_boundaries(
        self,
        lines: Sequence[AxisAlignedLine],
        interval_start: float,
        interval_end: float,
        center_y: float,
        direction: str,
    ) -> list[AxisAlignedLine]:
        endpoint_tolerance = max(3.0, float(self.config.axis_tolerance) * 10)
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if direction == "up":
                distance = center_y - line.axis_value
            else:
                distance = line.axis_value - center_y

            if distance <= 0 or distance > float(self.config.search_margin):
                continue

            left_gap = self._line_edge_gap(line, interval_start)
            right_gap = self._line_edge_gap(line, interval_end)
            overlap = min(line.span_end, interval_end) - max(line.span_start, interval_start)
            if overlap <= 0:
                continue
            if left_gap > endpoint_tolerance or right_gap > endpoint_tolerance:
                continue

            candidates.append(
                (
                    distance,
                    left_gap + right_gap,
                    -overlap,
                    line,
                )
            )

        return [candidate[3] for candidate in sorted(candidates)]

    @staticmethod
    def _rect_contains_point(
        outer_rect: fitz.Rect,
        point_x: float,
        point_y: float,
        tolerance: float = 0.0,
    ) -> bool:
        return (
            outer_rect.x0 <= (point_x + tolerance)
            and outer_rect.y0 <= (point_y + tolerance)
            and outer_rect.x1 >= (point_x - tolerance)
            and outer_rect.y1 >= (point_y - tolerance)
        )

    def _collect_lines(
        self,
        page: fitz.Page,
    ) -> tuple[list[AxisAlignedLine], list[AxisAlignedLine]]:
        lines, _ = get_page_axis_lines(
            page,
            self.pdf_path,
            self.line_cache_store,
            axis_tolerance=float(self.config.axis_tolerance),
            min_length=float(self.config.min_length),
            memory_cache=self._page_line_cache,
        )
        return lines

    def _pick_vertical_boundary(
        self,
        lines: Sequence[AxisAlignedLine],
        center_x: float,
        center_y: float,
        direction: str,
        projection_tolerance: float,
        min_length: float,
    ) -> AxisAlignedLine | None:
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if line.length < min_length:
                continue
            if not line.covers(center_y, projection_tolerance):
                continue

            if direction == "left":
                distance = center_x - line.axis_value
            else:
                distance = line.axis_value - center_x

            if distance <= 0 or distance > float(self.config.search_margin):
                continue

            candidates.append(
                (distance, -line.length, line.axis_value, line)
            )

        if not candidates:
            return None
        return min(candidates)[3]

    def _pick_horizontal_boundary(
        self,
        lines: Sequence[AxisAlignedLine],
        center_x: float,
        center_y: float,
        direction: str,
        projection_tolerance: float,
        min_length: float,
    ) -> AxisAlignedLine | None:
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if line.length < min_length:
                continue
            if not line.covers(center_x, projection_tolerance):
                continue

            if direction == "up":
                distance = center_y - line.axis_value
            else:
                distance = line.axis_value - center_y

            if distance <= 0 or distance > float(self.config.search_margin):
                continue

            candidates.append(
                (distance, -line.length, line.axis_value, line)
            )

        if not candidates:
            return None
        return min(candidates)[3]

    def _pick_horizontal_closing_boundary(
        self,
        lines: Sequence[AxisAlignedLine],
        left: AxisAlignedLine,
        right: AxisAlignedLine,
        center_y: float,
        direction: str,
    ) -> AxisAlignedLine | None:
        interval_start = left.axis_value
        interval_end = right.axis_value
        endpoint_tolerance = max(2.5, float(self.config.axis_tolerance) * 6)
        candidates: list[tuple[float, float, float, AxisAlignedLine]] = []

        for line in lines:
            if direction == "up":
                distance = center_y - line.axis_value
            else:
                distance = line.axis_value - center_y

            if distance <= 0 or distance > float(self.config.search_margin):
                continue

            left_gap = self._line_edge_gap(line, interval_start)
            right_gap = self._line_edge_gap(line, interval_end)
            if left_gap > endpoint_tolerance or right_gap > endpoint_tolerance:
                continue

            overlap = min(line.span_end, interval_end) - max(line.span_start, interval_start)
            if overlap <= 0:
                continue

            candidates.append(
                (
                    distance,
                    left_gap + right_gap,
                    -overlap,
                    line.axis_value,
                    line.span_start,
                    line.span_end,
                    line,
                )
            )

        if not candidates:
            return None
        return min(candidates)[6]

    @staticmethod
    def _line_edge_gap(line: AxisAlignedLine, boundary_value: float) -> float:
        if line.covers(boundary_value):
            return 0.0
        return min(
            abs(line.span_start - boundary_value),
            abs(line.span_end - boundary_value),
        )


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
        line_box_detection: LineBoxDetectionConfig | None = None,
        draw_arrow: bool = True,
        arrow_style: ArrowStyle | None = None,
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
        self.draw_arrow = draw_arrow
        self.arrow_style = arrow_style or ArrowStyle()
        self.line_box_detector = NearestLineBoxDetector(
            line_box_detection,
            pdf_path=pdf_path,
        )

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
                    draw_rect = self._resolve_border_rect(page, inst, render_inst)
                    page_img = self.renderer.draw_border(
                        page_img,
                        clip_rect,
                        draw_rect,
                        self.border_style,
                        draw_arrow=self.draw_arrow,
                        arrow_style=self.arrow_style,
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

    def _resolve_border_rect(
        self,
        page: PageContext,
        source_inst: fitz.Rect,
        render_inst: fitz.Rect,
    ) -> fitz.Rect:
        auto_border_rect = self.line_box_detector.detect(page.fitz_page, render_inst)
        if auto_border_rect is not None:
            logging.info(
                "第 %s 页全图截图使用就近矢量线边框: %s",
                page.page_number,
                auto_border_rect,
            )
            return auto_border_rect

        if not self.border_rect:
            logging.warning(
                "第 %s 页全图截图未找到就近矢量线边框，已回退到关键字原始框。",
                page.page_number,
            )
            return fitz.Rect(render_inst)

        source_center_x, source_center_y = self._keyword_center(source_inst)
        source_border_rect = RectHelper.centered(
            source_center_x,
            source_center_y,
            self.border_rect,
        )
        logging.warning(
            "第 %s 页全图截图未找到就近矢量线边框，已回退到配置边框。",
            page.page_number,
        )
        return RectHelper.to_render_rect(page.fitz_page, source_border_rect)


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
        line_box_detection: LineBoxDetectionConfig | None = None,
        draw_arrow: bool = True,
        arrow_style: ArrowStyle | None = None,
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
        self.draw_arrow = draw_arrow
        self.arrow_style = arrow_style or ArrowStyle()
        self.line_box_detector = NearestLineBoxDetector(
            line_box_detection,
            pdf_path=pdf_path,
        )

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
                        draw_arrow=self.draw_arrow,
                        arrow_style=self.arrow_style,
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
        auto_border_rect = self.line_box_detector.detect(page.fitz_page, render_inst)
        if auto_border_rect is not None:
            logging.info(
                "第 %s 页使用就近矢量线边框: %s",
                page.page_number,
                auto_border_rect,
            )
            return auto_border_rect

        if not self.border_rect:
            logging.warning(
                "第 %s 页未找到就近矢量线边框，已回退到关键字原始框。",
                page.page_number,
            )
            return fitz.Rect(render_inst)

        source_center_x, source_center_y = self._keyword_center(source_inst)
        source_border_rect = RectHelper.centered(
            source_center_x,
            source_center_y,
            self.border_rect,
        )
        logging.warning(
            "第 %s 页未找到就近矢量线边框，已回退到配置边框。",
            page.page_number,
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
    line_box_detection: LineBoxDetectionConfig | None = None,
    draw_arrow: bool = True,
    arrow_style: ArrowStyle | None = None,
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
        line_box_detection=line_box_detection,
        draw_arrow=draw_arrow,
        arrow_style=arrow_style,
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
    line_box_detection: LineBoxDetectionConfig | None = None,
    draw_arrow: bool = True,
    arrow_style: ArrowStyle | None = None,
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
        line_box_detection=line_box_detection,
        draw_arrow=draw_arrow,
        arrow_style=arrow_style,
        dpi=dpi,
    ).run()
