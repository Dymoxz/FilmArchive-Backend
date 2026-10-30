from collections.abc import Sequence
from pathlib import Path
from PIL import Image, ImageOps

# Allow high-resolution drum/flatbed film scans without raising DecompressionBombError
Image.MAX_IMAGE_PIXELS = None

THUMB_MAX_SIZE = (600, 600)
THUMB_WEBP_QUALITY = 80

COVER_CANVAS_SIZE = (800, 800)
COVER_BG_COLOR = (18, 18, 18)  # #121212
COVER_GRID_TILE_SIZE = (390, 390)
COVER_GRID_GAP = 20
COVER_WEBP_QUALITY = 85


def _load_rgb_image(image_path: Path) -> Image.Image:
    with Image.open(image_path) as img:
        transposed = ImageOps.exif_transpose(img)
        if transposed.mode in ("RGBA", "LA") or (
            transposed.mode == "P" and "transparency" in transposed.info
        ):
            background = Image.new("RGB", transposed.size, COVER_BG_COLOR)
            rgba = transposed.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[3])
            return background
        if transposed.mode != "RGB":
            return transposed.convert("RGB")
        return transposed.copy()


def generate_thumbnail(source_path: Path, dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img = _load_rgb_image(source_path)
    img.thumbnail(THUMB_MAX_SIZE, Image.Resampling.LANCZOS)
    img.save(dest_path, format="WEBP", quality=THUMB_WEBP_QUALITY, method=4)
    return dest_path


def generate_cover_collage(image_paths: Sequence[Path], dest_path: Path) -> Path:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGB", COVER_CANVAS_SIZE, COVER_BG_COLOR)

    valid_paths = [p for p in image_paths if p and p.is_file()]

    if len(valid_paths) >= 4:
        selected = valid_paths[:4]
        tile_w, tile_h = COVER_GRID_TILE_SIZE
        positions = [
            (0, 0),
            (tile_w + COVER_GRID_GAP, 0),
            (0, tile_h + COVER_GRID_GAP),
            (tile_w + COVER_GRID_GAP, tile_h + COVER_GRID_GAP),
        ]
        for path, pos in zip(selected, positions):
            img = _load_rgb_image(path)
            cropped = ImageOps.fit(
                img,
                COVER_GRID_TILE_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            canvas.paste(cropped, pos)
    elif len(valid_paths) >= 1:
        img = _load_rgb_image(valid_paths[0])
        cropped = ImageOps.fit(
            img,
            COVER_CANVAS_SIZE,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        canvas.paste(cropped, (0, 0))

    canvas.save(dest_path, format="WEBP", quality=COVER_WEBP_QUALITY, method=4)
    return dest_path
