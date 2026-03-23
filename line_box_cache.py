"""页面矢量线缓存与批量预建工具。"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import fitz


@dataclass(frozen=True)
class AxisAlignedLine:
    """归一化后的水平 / 垂直线段。"""

    orientation: str
    axis_value: float
    span_start: float
    span_end: float
    layer: str | None = None

    @property
    def length(self) -> float:
        return self.span_end - self.span_start

    def covers(self, value: float, tolerance: float = 0.0) -> bool:
        return (self.span_start - tolerance) <= value <= (self.span_end + tolerance)


class LineCacheStore:
    """缓存页面矢量线提取结果，避免重复调用 get_cdrawings()."""

    CACHE_VERSION = "v2"

    def __init__(self, cache_dir: str | None, enabled: bool = True) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled and bool(cache_dir)

    def load(
        self,
        pdf_path: str | None,
        page_number: int,
        axis_tolerance: float,
        min_length: float,
    ) -> tuple[list[AxisAlignedLine], list[AxisAlignedLine]] | None:
        cache_path = self._cache_path(
            pdf_path,
            page_number,
            axis_tolerance,
            min_length,
        )
        if not cache_path or not os.path.exists(cache_path):
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as file:
                payload = json.load(file)
        except (OSError, ValueError, TypeError):
            return None

        vertical_lines = [
            AxisAlignedLine(**line_payload)
            for line_payload in payload.get("vertical_lines", [])
        ]
        horizontal_lines = [
            AxisAlignedLine(**line_payload)
            for line_payload in payload.get("horizontal_lines", [])
        ]
        return vertical_lines, horizontal_lines

    def save(
        self,
        pdf_path: str | None,
        page_number: int,
        axis_tolerance: float,
        min_length: float,
        vertical_lines: Sequence[AxisAlignedLine],
        horizontal_lines: Sequence[AxisAlignedLine],
    ) -> None:
        cache_path = self._cache_path(
            pdf_path,
            page_number,
            axis_tolerance,
            min_length,
        )
        if not cache_path:
            return

        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        payload = {
            "vertical_lines": [
                {
                    "orientation": line.orientation,
                    "axis_value": line.axis_value,
                    "span_start": line.span_start,
                    "span_end": line.span_end,
                    "layer": line.layer,
                }
                for line in vertical_lines
            ],
            "horizontal_lines": [
                {
                    "orientation": line.orientation,
                    "axis_value": line.axis_value,
                    "span_start": line.span_start,
                    "span_end": line.span_end,
                    "layer": line.layer,
                }
                for line in horizontal_lines
            ],
        }

        try:
            with open(cache_path, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=True)
        except OSError:
            logging.debug("矢量线缓存写入失败，将继续使用即时提取结果: %s", cache_path, exc_info=True)

    def _cache_path(
        self,
        pdf_path: str | None,
        page_number: int,
        axis_tolerance: float,
        min_length: float,
    ) -> str | None:
        if not self.enabled or not pdf_path:
            return None

        try:
            stat = os.stat(pdf_path)
        except OSError:
            return None

        key = "|".join(
            (
                self.CACHE_VERSION,
                os.path.abspath(pdf_path),
                str(stat.st_mtime_ns),
                str(stat.st_size),
                str(page_number),
                f"{axis_tolerance:.4f}",
                f"{min_length:.4f}",
            )
        )
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir or "", f"{digest}.json")


def normalize_line_cache_min_length(min_length: float) -> float:
    return min(5.0, float(min_length))


def _to_render_point(page: fitz.Page, point: fitz.Point) -> fitz.Point:
    if page.rotation == 0:
        return fitz.Point(point)
    return fitz.Point(point) * page.rotation_matrix


def collect_page_axis_lines(
    page: fitz.Page,
    axis_tolerance: float,
    min_length: float,
) -> tuple[list[AxisAlignedLine], list[AxisAlignedLine]]:
    vertical_lines: dict[tuple[str, float, float, float, str | None], AxisAlignedLine] = {}
    horizontal_lines: dict[tuple[str, float, float, float, str | None], AxisAlignedLine] = {}

    for drawing in page.get_drawings():
        layer = drawing.get("layer")
        normalized_layer = str(layer) if layer is not None else None
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue

            start = _to_render_point(page, fitz.Point(item[1]))
            end = _to_render_point(page, fitz.Point(item[2]))
            delta_x = abs(start.x - end.x)
            delta_y = abs(start.y - end.y)

            if delta_x <= axis_tolerance and delta_y >= min_length:
                axis_value = round((start.x + end.x) / 2, 2)
                span_start = round(min(start.y, end.y), 2)
                span_end = round(max(start.y, end.y), 2)
                line = AxisAlignedLine(
                    orientation="vertical",
                    axis_value=axis_value,
                    span_start=span_start,
                    span_end=span_end,
                    layer=normalized_layer,
                )
                vertical_lines[
                    ("vertical", axis_value, span_start, span_end, normalized_layer)
                ] = line
            elif delta_y <= axis_tolerance and delta_x >= min_length:
                axis_value = round((start.y + end.y) / 2, 2)
                span_start = round(min(start.x, end.x), 2)
                span_end = round(max(start.x, end.x), 2)
                line = AxisAlignedLine(
                    orientation="horizontal",
                    axis_value=axis_value,
                    span_start=span_start,
                    span_end=span_end,
                    layer=normalized_layer,
                )
                horizontal_lines[
                    ("horizontal", axis_value, span_start, span_end, normalized_layer)
                ] = line

    return list(vertical_lines.values()), list(horizontal_lines.values())


def get_page_axis_lines(
    page: fitz.Page,
    pdf_path: str | None,
    cache_store: LineCacheStore,
    axis_tolerance: float,
    min_length: float,
    memory_cache: dict[int, tuple[list[AxisAlignedLine], list[AxisAlignedLine]]] | None = None,
    force_rebuild: bool = False,
) -> tuple[tuple[list[AxisAlignedLine], list[AxisAlignedLine]], str]:
    page_number_value = page.number
    if page_number_value is None:
        raise ValueError("无法确定当前页面编号。")
    page_number = int(page_number_value)
    normalized_min_length = normalize_line_cache_min_length(min_length)

    if memory_cache is not None:
        cached = memory_cache.get(page_number)
        if cached is not None:
            return cached, "memory"

    if not force_rebuild:
        disk_cached = cache_store.load(
            pdf_path,
            page_number,
            axis_tolerance,
            normalized_min_length,
        )
        if disk_cached is not None:
            if memory_cache is not None:
                memory_cache[page_number] = disk_cached
            logging.info(
                "第 %s 页矢量线已从缓存加载: 垂直=%s, 水平=%s",
                page_number + 1,
                len(disk_cached[0]),
                len(disk_cached[1]),
            )
            return disk_cached, "disk"

    started_at = time.perf_counter()
    built_lines = collect_page_axis_lines(
        page,
        axis_tolerance=axis_tolerance,
        min_length=normalized_min_length,
    )
    cache_store.save(
        pdf_path,
        page_number,
        axis_tolerance,
        normalized_min_length,
        built_lines[0],
        built_lines[1],
    )
    if memory_cache is not None:
        memory_cache[page_number] = built_lines

    elapsed = time.perf_counter() - started_at
    logging.info(
        "第 %s 页矢量线提取完成: 垂直=%s, 水平=%s, 耗时=%.2fs",
        page_number + 1,
        len(built_lines[0]),
        len(built_lines[1]),
        elapsed,
    )
    return built_lines, "built"


def build_pdf_line_cache(
    pdf_path: str,
    cache_dir: str,
    axis_tolerance: float,
    min_length: float,
    force_rebuild: bool = False,
) -> dict[str, int | float | str]:
    pdf_abspath = os.path.abspath(pdf_path)
    if not os.path.exists(pdf_abspath):
        raise FileNotFoundError(f"未找到 PDF 文件: {pdf_abspath}")
    if not os.path.isfile(pdf_abspath):
        raise ValueError(f"提供的 PDF 路径不是文件: {pdf_abspath}")

    cache_store = LineCacheStore(cache_dir=cache_dir, enabled=True)
    memory_cache: dict[int, tuple[list[AxisAlignedLine], list[AxisAlignedLine]]] = {}
    built_pages = 0
    disk_hit_pages = 0
    started_at = time.perf_counter()

    with fitz.open(pdf_abspath) as document:
        for page_index in range(len(document)):
            page = document.load_page(page_index)
            _, source = get_page_axis_lines(
                page,
                pdf_abspath,
                cache_store,
                axis_tolerance=axis_tolerance,
                min_length=min_length,
                memory_cache=memory_cache,
                force_rebuild=force_rebuild,
            )
            if source == "built":
                built_pages += 1
            elif source == "disk":
                disk_hit_pages += 1

    elapsed = time.perf_counter() - started_at
    return {
        "pdf_path": pdf_abspath,
        "pages": len(memory_cache),
        "built_pages": built_pages,
        "disk_hit_pages": disk_hit_pages,
        "elapsed_seconds": elapsed,
    }


def discover_pdf_files(pdf_dir: str) -> list[str]:
    root = Path(pdf_dir)
    if not root.exists():
        raise FileNotFoundError(f"未找到 PDF 目录: {root.resolve()}")
    if not root.is_dir():
        raise NotADirectoryError(f"PDF 路径不是目录: {root.resolve()}")
    return sorted(str(path) for path in root.rglob("*.pdf"))
