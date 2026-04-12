from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from PIL import Image
from pptx.presentation import Presentation as PptxPresentation

from ..pptx_extraction import open_presentation, presentation_digest
from ..pptx_functions import PptxEditor
from ..reward_models import RenderedPresentation, RenderedSlideImage


class PptxRenderService:
    def __init__(
        self,
        *,
        work_root: str | None = None,
        density_dpi: int = 200,
        soffice_binary: str = "soffice",
        magick_binary: str = "magick",
        timeout_seconds: int = 120,
    ):
        if density_dpi < 72:
            raise ValueError("density_dpi must be at least 72")
        if timeout_seconds < 1:
            raise ValueError("timeout_seconds must be at least 1")
        self.work_root = Path(work_root) if work_root else None
        self.density_dpi = density_dpi
        self.soffice_binary = soffice_binary
        self.magick_binary = magick_binary
        self.timeout_seconds = timeout_seconds

    def render_presentation(
        self,
        presentation: PptxEditor | PptxPresentation | str,
    ) -> RenderedPresentation:
        opened = open_presentation(presentation)
        deck_digest = presentation_digest(opened.presentation)
        work_dir = self._resolve_work_dir(deck_digest)
        pptx_path = work_dir / "presentation.pptx"
        pdf_path = work_dir / "presentation.pdf"
        slides_dir = work_dir / "slides"
        slides_dir.mkdir(parents=True, exist_ok=True)

        self._export_pptx(
            opened.presentation, pptx_path, source_path=opened.source_path
        )
        soffice_diagnostics = self._convert_pptx_to_pdf(pptx_path, pdf_path)
        magick_diagnostics = self._convert_pdf_to_pngs(pdf_path, slides_dir)
        slide_images = self._collect_slide_images(slides_dir)
        if not slide_images:
            raise ValueError("rendering produced no slide images")

        return RenderedPresentation(
            slide_images=slide_images,
            pptx_path=str(pptx_path),
            pdf_path=str(pdf_path),
            backend="soffice+magick",
            metadata={
                "presentation_digest": deck_digest,
                "inspection_mode": opened.inspection_mode,
                "source_path": opened.source_path,
                "density_dpi": self.density_dpi,
                "work_dir": str(work_dir),
                "slide_count": len(slide_images),
                "conversion": {
                    "soffice": soffice_diagnostics,
                    "magick": magick_diagnostics,
                },
            },
        )

    def _resolve_work_dir(self, deck_digest: str) -> Path:
        if self.work_root is not None:
            work_dir = self.work_root / deck_digest
            work_dir.mkdir(parents=True, exist_ok=True)
            return work_dir
        return Path(tempfile.mkdtemp(prefix=f"ppt-render-{deck_digest[:12]}-"))

    def _export_pptx(
        self,
        presentation: PptxPresentation,
        pptx_path: Path,
        *,
        source_path: str | None,
    ) -> None:
        if source_path:
            source = Path(source_path)
            if source.suffix.lower() == ".pptx" and source.exists():
                if source.resolve() != pptx_path.resolve():
                    shutil.copy2(source, pptx_path)
                return
        presentation.save(str(pptx_path))

    def _convert_pptx_to_pdf(self, pptx_path: Path, pdf_path: Path) -> dict[str, Any]:
        command = [
            self.soffice_binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(pdf_path.parent),
            str(pptx_path),
        ]
        started_at = time.time()
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        duration_seconds = time.time() - started_at
        if result.returncode != 0:
            raise ValueError(
                "soffice pptx->pdf conversion failed with exit code "
                f"{result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
            )
        if not pdf_path.exists():
            raise ValueError(
                "soffice reported success but did not create the expected PDF at "
                f"{pdf_path}"
            )
        return {
            "command": command,
            "duration_seconds": duration_seconds,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "pdf_path": str(pdf_path),
        }

    def _convert_pdf_to_pngs(self, pdf_path: Path, slides_dir: Path) -> dict[str, Any]:
        existing_outputs = list(slides_dir.glob("slide_*.png"))
        for path in existing_outputs:
            path.unlink()

        output_pattern = slides_dir / "slide_%03d.png"
        command = [
            self.magick_binary,
            "-density",
            str(self.density_dpi),
            str(pdf_path),
            "-background",
            "white",
            "-alpha",
            "remove",
            "-alpha",
            "off",
            str(output_pattern),
        ]
        started_at = time.time()
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        duration_seconds = time.time() - started_at
        if result.returncode != 0:
            raise ValueError(
                "magick pdf->png conversion failed with exit code "
                f"{result.returncode}: {result.stderr.strip() or result.stdout.strip()}"
            )
        outputs = sorted(slides_dir.glob("slide_*.png"))
        if not outputs:
            raise ValueError(
                f"magick reported success but produced no PNG files in {slides_dir}"
            )
        return {
            "command": command,
            "duration_seconds": duration_seconds,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "png_count": len(outputs),
            "slides_dir": str(slides_dir),
        }

    def _collect_slide_images(self, slides_dir: Path) -> list[RenderedSlideImage]:
        slide_images: list[RenderedSlideImage] = []
        for slide_index, path in enumerate(
            sorted(slides_dir.glob("slide_*.png")), start=1
        ):
            with Image.open(path) as image:
                width_px, height_px = image.size
            slide_images.append(
                RenderedSlideImage(
                    slide_index=slide_index,
                    image_path=str(path),
                    width_px=width_px,
                    height_px=height_px,
                    content_hash=self._file_sha256(path),
                    metadata={"filename": path.name},
                )
            )
        return slide_images

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()


__all__ = ["PptxRenderService"]
