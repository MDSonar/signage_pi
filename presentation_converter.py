#!/usr/bin/env python3
"""
Presentation conversion utilities
- Converts PPTX/PDF presentations to cached PNG slides
- Uses LibreOffice for PPTX->PDF and ImageMagick for PDF->PNG
"""

import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class PresentationConverter:
    """Handles PPTX and PDF to PNG conversion"""

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_cache_path(self, presentation_file: Path) -> Path:
        cache_name = presentation_file.stem
        return self.cache_dir / cache_name

    def is_cached(self, presentation_file: Path) -> bool:
        cache_path = self.get_cache_path(presentation_file)
        if not cache_path.exists():
            return False
        png_files = list(cache_path.glob("slide_*.png"))
        return len(png_files) > 0

    def convert_pptx_to_pdf(self, pptx_file: Path, output_dir: Path) -> Path:
        logger.info("  Converting PPTX to PDF...")
        cmd = ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(pptx_file)]
        subprocess.run(cmd, check=True, timeout=180)
        generated_pdf = output_dir / f"{pptx_file.stem}.pdf"
        if not generated_pdf.exists():
            raise FileNotFoundError(f"PDF not generated for {pptx_file.name}")
        return generated_pdf

    def convert_pdf_to_png(self, pdf_file: Path, output_dir: Path):
        logger.info("  Converting PDF pages to PNG...")
        cmd = ["convert", "-density", "150", "-quality", "90", str(pdf_file), str(output_dir / "slide_%03d.png")]
        subprocess.run(cmd, check=True, timeout=300)
        png_files = sorted(output_dir.glob("slide_*.png"))
        if not png_files:
            raise FileNotFoundError(f"No PNG files generated from {pdf_file.name}")
        return png_files

    def convert_pptx(self, pptx_file: Path):
        cache_path = self.get_cache_path(pptx_file)
        cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Converting PPTX: {pptx_file.name}")
        try:
            pdf_file = self.convert_pptx_to_pdf(pptx_file, cache_path)
            png_files = self.convert_pdf_to_png(pdf_file, cache_path)
            try:
                pdf_file.unlink()
            except Exception:
                pass
            logger.info(f"✓ Converted {pptx_file.name}: {len(png_files)} slides")
            return png_files
        except Exception as e:
            logger.error(f"Failed to convert {pptx_file.name}: {e}")
            return []

    def convert_pdf(self, pdf_file: Path):
        cache_path = self.get_cache_path(pdf_file)
        cache_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Converting PDF: {pdf_file.name}")
        try:
            png_files = self.convert_pdf_to_png(pdf_file, cache_path)
            logger.info(f"✓ Converted {pdf_file.name}: {len(png_files)} slides")
            return png_files
        except Exception as e:
            logger.error(f"Failed to convert {pdf_file.name}: {e}")
            return []

    def convert_presentation(self, presentation_file: Path):
        ext = presentation_file.suffix.lower()
        if ext in ('.pptx', '.ppt'):
            return self.convert_pptx(presentation_file)
        elif ext in ('.pdf',):
            return self.convert_pdf(presentation_file)
        else:
            logger.error(f"Unsupported format: {ext}")
            return []
