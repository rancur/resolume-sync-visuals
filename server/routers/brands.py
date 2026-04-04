"""
Brand configuration CRUD — read/write brand YAML files.
Includes style transfer reference image management.
"""
import base64
import hashlib
import logging
import shutil
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/brands", tags=["brands"])

_BRANDS_DIR = Path(__file__).parent.parent.parent / "config" / "brands"
_REFERENCES_DIR = _BRANDS_DIR / "_references"


def _brand_path(name: str) -> Path:
    return _BRANDS_DIR / f"{name}.yaml"


@router.get("")
def list_brands():
    brands = []
    for f in sorted(_BRANDS_DIR.glob("*.yaml")):
        if f.stem.startswith("TEMPLATE"):
            continue
        with open(f) as fh:
            data = yaml.safe_load(fh) or {}
        brands.append({
            "name": f.stem,
            "display_name": data.get("name", f.stem),
            "description": data.get("description", ""),
        })
    return {"brands": brands}


@router.get("/{name}")
def get_brand(name: str):
    path = _brand_path(name)
    if not path.exists():
        raise HTTPException(404, f"Brand '{name}' not found")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data


class BrandUpdateRequest(BaseModel):
    yaml_content: str | None = None
    # Also accept raw JSON object for structured editing
    data: dict | None = None


@router.put("/{name}")
def update_brand(name: str, req: BrandUpdateRequest):
    path = _brand_path(name)

    if req.yaml_content:
        # Direct YAML string
        try:
            data = yaml.safe_load(req.yaml_content)
        except yaml.YAMLError as e:
            raise HTTPException(400, f"Invalid YAML: {e}")
        if not isinstance(data, dict):
            raise HTTPException(400, "YAML must be a mapping")
        content = req.yaml_content
    elif req.data:
        # JSON object — serialize to YAML
        content = yaml.dump(req.data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    else:
        raise HTTPException(400, "Provide either yaml_content or data")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return {"updated": True, "name": name}


class PreviewPromptRequest(BaseModel):
    section: str = "drop"
    mood_quadrant: str = "euphoric"
    genre: str = ""
    style_override: str = ""


@router.post("/{name}/preview-prompt")
def preview_prompt(name: str, req: PreviewPromptRequest):
    path = _brand_path(name)
    if not path.exists():
        raise HTTPException(404, f"Brand '{name}' not found")
    with open(path) as f:
        brand = yaml.safe_load(f) or {}

    sections = brand.get("sections", {})
    section = sections.get(req.section, sections.get("drop", {}))
    base_prompt = section.get("prompt", brand.get("style", {}).get("base", ""))

    mood_mods = brand.get("mood_modifiers", {}).get(req.mood_quadrant, {})
    genre_mods = brand.get("genre_modifiers", {}).get(req.genre.lower(), {})

    parts = [base_prompt]
    if mood_mods.get("colors"):
        parts.append(mood_mods["colors"])
    if mood_mods.get("atmosphere"):
        parts.append(mood_mods["atmosphere"])
    if genre_mods.get("extra"):
        parts.append(genre_mods["extra"])
    if req.style_override:
        parts.append(req.style_override)

    prompt = ", ".join(p for p in parts if p)
    motion = section.get("motion", "smooth continuous motion")

    return {
        "prompt": prompt,
        "motion_prompt": motion,
        "section": req.section,
        "mood_quadrant": req.mood_quadrant,
    }


# ── Style Transfer Reference Images ──


@router.post("/{name}/reference-image")
async def upload_reference_image(name: str, file: UploadFile = File(...)):
    """Upload a reference image for style transfer.

    The image is stored alongside the brand config and referenced in the YAML.
    Supported formats: PNG, JPEG, WebP.
    Max size: 10MB.
    """
    path = _brand_path(name)
    if not path.exists():
        raise HTTPException(404, f"Brand '{name}' not found")

    # Validate file type
    allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(
            400,
            f"Unsupported image type: {file.content_type}. "
            f"Allowed: {', '.join(allowed_types)}"
        )

    # Read and validate size
    content = await file.read()
    max_size = 10 * 1024 * 1024  # 10MB
    if len(content) > max_size:
        raise HTTPException(400, f"Image too large ({len(content)} bytes). Max: {max_size}")

    # Generate filename from content hash
    content_hash = hashlib.sha256(content).hexdigest()[:12]
    ext = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
    }.get(file.content_type, ".png")
    filename = f"{name}_{content_hash}{ext}"

    # Save the file
    ref_dir = _REFERENCES_DIR
    ref_dir.mkdir(parents=True, exist_ok=True)
    ref_path = ref_dir / filename
    ref_path.write_bytes(content)

    # Update brand YAML to include reference
    with open(path) as f:
        brand_data = yaml.safe_load(f) or {}

    if "style_references" not in brand_data:
        brand_data["style_references"] = []

    # Avoid duplicate entries
    ref_entry = {
        "filename": filename,
        "hash": content_hash,
        "original_name": file.filename or "reference",
        "content_type": file.content_type,
        "size_bytes": len(content),
    }
    existing_hashes = [r.get("hash") for r in brand_data["style_references"]]
    if content_hash not in existing_hashes:
        brand_data["style_references"].append(ref_entry)
        content_yaml = yaml.dump(
            brand_data, default_flow_style=False,
            allow_unicode=True, sort_keys=False,
        )
        path.write_text(content_yaml)

    return {
        "uploaded": True,
        "filename": filename,
        "hash": content_hash,
        "size_bytes": len(content),
        "brand": name,
        "total_references": len(brand_data["style_references"]),
    }


@router.get("/{name}/reference-images")
def list_reference_images(name: str):
    """List all reference images for a brand."""
    path = _brand_path(name)
    if not path.exists():
        raise HTTPException(404, f"Brand '{name}' not found")

    with open(path) as f:
        brand_data = yaml.safe_load(f) or {}

    refs = brand_data.get("style_references", [])

    # Check which files actually exist
    result = []
    for ref in refs:
        filename = ref.get("filename", "")
        file_path = _REFERENCES_DIR / filename
        result.append({
            **ref,
            "exists": file_path.exists(),
            "url": f"/api/brands/{name}/reference-images/{filename}" if file_path.exists() else None,
        })

    return {"brand": name, "references": result}


@router.get("/{name}/reference-images/{filename}")
def get_reference_image(name: str, filename: str):
    """Serve a reference image file."""
    from fastapi.responses import FileResponse

    file_path = _REFERENCES_DIR / filename
    if not file_path.exists():
        raise HTTPException(404, f"Reference image not found: {filename}")

    # Determine media type
    ext = file_path.suffix.lower()
    media_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    media_type = media_types.get(ext, "application/octet-stream")

    return FileResponse(str(file_path), media_type=media_type)


@router.delete("/{name}/reference-images/{ref_hash}")
def delete_reference_image(name: str, ref_hash: str):
    """Remove a reference image from a brand by its hash."""
    path = _brand_path(name)
    if not path.exists():
        raise HTTPException(404, f"Brand '{name}' not found")

    with open(path) as f:
        brand_data = yaml.safe_load(f) or {}

    refs = brand_data.get("style_references", [])
    new_refs = [r for r in refs if r.get("hash") != ref_hash]

    if len(new_refs) == len(refs):
        raise HTTPException(404, f"Reference image with hash '{ref_hash}' not found")

    # Delete the file
    for ref in refs:
        if ref.get("hash") == ref_hash:
            file_path = _REFERENCES_DIR / ref.get("filename", "")
            file_path.unlink(missing_ok=True)

    brand_data["style_references"] = new_refs
    content_yaml = yaml.dump(
        brand_data, default_flow_style=False,
        allow_unicode=True, sort_keys=False,
    )
    path.write_text(content_yaml)

    return {"deleted": True, "hash": ref_hash, "remaining": len(new_refs)}
