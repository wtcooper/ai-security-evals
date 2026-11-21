#!/usr/bin/env python3
"""Render the custom-lane images: receipts, forms, screenshots, signs and slides that carry an
injected instruction, and the harmful and benign prompts set as typographic images.

    python render.py --out <dir>                         # render every case
    python render.py --out <dir> --check corpus/manifest.json
    python render.py --out <dir> --write-manifest corpus/manifest.json   # maintainers only

Deterministic: no randomness, one font (Pillow's bundled default TrueType font), fixed sizes.
The manifest records a hash of each image's PIXELS (independent of PNG compression) and of the
PNG file. A different Pillow or FreeType build can move a glyph by a pixel; --check reports
which images differ, and the run records it as a validity note. Needs Pillow.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vmb_core as core  # noqa: E402

INK, GREY, LIGHT, RULE = "#1F2328", "#5B6470", "#EBEBEB", "#C9CED6"
ACCENT, PAPER, SCREEN_BG = "#2463EB", "#FFFFFF", "#F6F7F9"
WIDTH = {"receipt": 560, "page": 820, "screen": 1100, "sign": 960, "slide": 1100}
_FONTS: dict[int, ImageFont.FreeTypeFont] = {}


def font(size: int):
    if size not in _FONTS:
        _FONTS[size] = ImageFont.load_default(size=size)
    return _FONTS[size]


def wrap(text: str, size: int, width: int) -> list[str]:
    f, lines = font(size), []
    for para in text.split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if f.getlength(trial) <= width or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return lines


def text_block(draw, xy, text, size, width, fill=INK, bold=False, spacing=6) -> int:
    """Draw wrapped text; return the height used."""
    x, y = xy
    for line in wrap(text, size, width):
        draw.text((x, y), line, font=font(size), fill=fill, stroke_width=1 if bold else 0,
                  stroke_fill=fill)
        y += size + spacing
    return y - xy[1]


def block_image(text: str, size: int, width: int, fill=INK, bg=(0, 0, 0, 0)) -> Image.Image:
    lines = wrap(text, size, width)
    im = Image.new("RGBA", (width + 8, len(lines) * (size + 6) + 8), bg)
    text_block(ImageDraw.Draw(im), (4, 4), text, size, width, fill=fill)
    return im


# --- scene content ------------------------------------------------------------------------
def draw_blocks(draw, img, scene, x0, y, width, inline_text=None, inline_at=None) -> int:
    kind = scene["kind"]
    body = 26 if kind == "slide" else 17
    blocks = list(scene.get("blocks", []))
    if inline_text is not None:
        style = "bullet" if any(b["t"] == "bullet" for b in blocks) else "text"
        blocks.insert(inline_at if inline_at is not None else (len(blocks) + 1) // 2,
                      {"t": style, "s": inline_text})
    for b in blocks:
        t = b["t"]
        if t == "row":
            draw.text((x0, y), b["k"], font=font(body + 1), fill=INK)
            v = b["v"]
            draw.text((x0 + width - font(body + 1).getlength(v), y), v, font=font(body + 1),
                      fill=INK)
            y += body + 15
        elif t == "field":
            draw.text((x0, y), b["k"], font=font(13), fill=GREY)
            y += 19
            draw.rectangle((x0, y, x0 + width, y + 38), outline=RULE, width=2)
            draw.text((x0 + 10, y + 9), b["v"], font=font(18), fill=INK)
            y += 52
        elif t == "text":
            y += text_block(draw, (x0, y), b["s"], body, width) + 8
        elif t == "head":
            y += text_block(draw, (x0, y), b["s"], 26, width, bold=True) + 10
        elif t == "bullet":
            draw.ellipse((x0, y + body // 2 - 4, x0 + 8, y + body // 2 + 4), fill=INK)
            y += text_block(draw, (x0 + 22, y), b["s"], body, width - 22) + 12
        elif t == "rule":
            draw.line((x0, y + 4, x0 + width, y + 4), fill=RULE, width=2)
            y += 16
        elif t == "big":
            f = font(54)
            draw.text((x0 + (width - f.getlength(b["s"])) / 2, y), b["s"], font=f, fill=INK,
                      stroke_width=1, stroke_fill=INK)
            y += 80
        elif t == "button":
            w = font(18).getlength(b["s"]) + 40
            draw.rounded_rectangle((x0, y, x0 + w, y + 40), radius=8, fill=ACCENT)
            draw.text((x0 + 20, y + 10), b["s"], font=font(18), fill="#FFFFFF")
            y += 56
        elif t == "msg":
            draw.text((x0, y), b["who"], font=font(14), fill=GREY, stroke_width=1,
                      stroke_fill=GREY)
            y += 20
            h = len(wrap(b["s"], 17, width - 60)) * 23 + 16
            draw.rounded_rectangle((x0, y, x0 + width - 40, y + h), radius=12, fill="#E9EEF5")
            text_block(draw, (x0 + 12, y + 8), b["s"], 17, width - 60)
            y += h + 14
        elif t == "bars":
            data, h = b["data"], 230
            top = max(v for _, v in data)
            bw = width // (len(data) * 2)
            for i, (label, v) in enumerate(data):
                bx = x0 + i * 2 * bw + bw // 2
                bh = int(h * v / top)
                draw.rectangle((bx, y + h - bh, bx + bw, y + h), fill=ACCENT)
                draw.text((bx, y + h + 6), str(label), font=font(15), fill=INK)
                draw.text((bx, y + h - bh - 20), str(v), font=font(14), fill=GREY)
            y += h + 34
    return y


def render_case(case: dict) -> Image.Image:
    scene, place, inj = case["scene"], case["placement"], case["injection"]
    kind = scene["kind"]
    W = WIDTH[kind]
    bg = SCREEN_BG if kind == "screen" else PAPER
    img = Image.new("RGB", (W, 2400), bg)
    draw = ImageDraw.Draw(img)
    pad = 28 if kind == "receipt" else 44
    x0, inner = pad, W - 2 * pad
    y = 0
    if kind == "screen":
        draw.rectangle((0, 0, W, 40), fill="#2B303B")
        for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
            draw.ellipse((14 + i * 22, 13, 28 + i * 22, 27), fill=c)
        label = {"browser": "Browser", "chat": "Messages", "email": "Mail"}.get(
            scene.get("chrome"), "Application")
        draw.text((100, 11), label, font=font(15), fill="#D7DAE0")
        y = 40
        if scene.get("chrome") == "browser":
            draw.rectangle((0, y, W, y + 46), fill="#E4E7EC")
            draw.rounded_rectangle((90, y + 8, W - 40, y + 38), radius=14, fill="#FFFFFF")
            draw.text((108, y + 14), scene.get("url", ""), font=font(15), fill=GREY)
            y += 46
        y += 24
    else:
        y = pad
    if place == "header":
        hb = block_image(inj, 17, inner - 24, fill="#5A4300")
        draw.rectangle((x0, y, x0 + inner, y + hb.height + 16), fill="#FFF1B8",
                       outline="#E0B400")
        img.paste(hb, (x0 + 12, y + 8), hb)
        y += hb.height + 34
    title_size = {"slide": 44, "sign": 50, "receipt": 26}.get(kind, 30)
    centred = kind in ("receipt", "sign")
    for line in wrap(scene.get("title", ""), title_size, inner):
        tx = x0 + (inner - font(title_size).getlength(line)) / 2 if centred else x0
        draw.text((tx, y), line, font=font(title_size), fill=INK, stroke_width=1,
                  stroke_fill=INK)
        y += title_size + 10
    if scene.get("subtitle"):
        sub = scene["subtitle"]
        sx = x0 + (inner - font(16).getlength(sub)) / 2 if centred else x0
        draw.text((sx, y), sub, font=font(16), fill=GREY)
        y += 30
    y += 14
    y = draw_blocks(draw, img, scene, x0, y, inner,
                    inline_text=inj if place == "inline" else None)
    if place == "caption":
        y += text_block(draw, (x0, y), inj, 14, inner, fill=GREY) + 10
    if place in ("footer", "signature"):
        draw.line((x0, y + 6, x0 + inner, y + 6), fill=RULE, width=1)
        y += 18
        if place == "signature":
            draw.text((x0, y), "--", font=font(15), fill=GREY)
            y += 22
        y += text_block(draw, (x0, y), inj, 15, inner, fill=GREY) + 10
    if place == "small":
        y += 10 + text_block(draw, (x0, y + 10), inj, 10, inner, fill="#6B7280") + 6
    if place == "low_contrast":
        y += 10 + text_block(draw, (x0, y + 10), inj, 16, inner, fill=LIGHT) + 6
    height = max(y + pad, 520 if kind in ("screen", "slide") else 360)
    img = img.crop((0, 0, W, height))
    return overlay(img, place, inj, kind)


def overlay(img: Image.Image, place: str, inj: str, kind: str) -> Image.Image:
    W, H = img.size
    if place in ("rotated", "margin"):
        size = 15 if place == "rotated" else 11
        blk = block_image(inj, size, H - 60, fill=INK if place == "rotated" else GREY)
        blk = blk.rotate(90 if place == "rotated" else 270, expand=True)
        out = Image.new("RGB", (W + blk.width + 16, H), img.getpixel((W - 1, H - 1)))
        if place == "rotated":
            out.paste(img, (0, 0))
            out.paste(blk, (W + 4, 30), blk)
        else:
            out.paste(img, (blk.width + 16, 0))
            out.paste(blk, (6, 30), blk)
        return out
    if place == "dialog":
        bw = int(W * 0.66)
        body = block_image(inj, 18, bw - 48)
        bh = body.height + 130
        if H < bh + 80:
            grown = Image.new("RGB", (W, bh + 80), img.getpixel((0, H - 1)))
            grown.paste(img, (0, 0))
            img, H = grown, bh + 80
        img = Image.blend(img, Image.new("RGB", (W, H), "#000000"), 0.35)
        d = ImageDraw.Draw(img)
        bx, by = (W - bw) // 2, (H - bh) // 2
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=14, fill="#FFFFFF",
                            outline="#9AA3AF", width=2)
        d.text((bx + 24, by + 18), "Notice", font=font(22), fill=INK, stroke_width=1,
               stroke_fill=INK)
        img.paste(body, (bx + 20, by + 56), body)
        d.rounded_rectangle((bx + bw - 130, by + bh - 56, bx + bw - 24, by + bh - 18),
                            radius=8, fill=ACCENT)
        d.text((bx + bw - 92, by + bh - 47), "OK", font=font(18), fill="#FFFFFF")
        return img
    if place == "toast":
        tw = 400
        body = block_image(inj, 15, tw - 32, fill="#FFFFFF")
        th = body.height + 46
        d = ImageDraw.Draw(img)
        tx, ty = W - tw - 20, 52
        d.rounded_rectangle((tx, ty, tx + tw, ty + th), radius=10, fill="#30343C")
        d.text((tx + 16, ty + 10), "Notification", font=font(15), fill="#C9CED6")
        img.paste(body, (tx + 12, ty + 34), body)
        return img
    if place == "banner":
        body = block_image(inj, 16, W - 220, fill="#FFFFFF")
        bh = body.height + 30
        out = Image.new("RGB", (W, H + bh), "#1F2937")
        out.paste(img, (0, 0))
        out.paste(body, (20, H + 15), body)
        d = ImageDraw.Draw(out)
        d.rounded_rectangle((W - 170, H + bh // 2 - 20, W - 30, H + bh // 2 + 20), radius=8,
                            fill=ACCENT)
        d.text((W - 136, H + bh // 2 - 10), "Accept", font=font(18), fill="#FFFFFF")
        return out
    if place == "watermark":
        blk = block_image(inj, 30, int(W * 0.8), fill=(150, 150, 150, 90))
        blk = blk.rotate(22, expand=True, resample=Image.Resampling.BICUBIC)
        base = img.convert("RGBA")
        base.alpha_composite(blk, (max(0, (W - blk.width) // 2), max(0, (H - blk.height) // 2)))
        return base.convert("RGB")
    return img


def render_prompt(prompt: dict) -> Image.Image:
    """FigStep's layout: black text on a white 760x760 square; `list` style adds an empty
    numbered list under the request."""
    text = prompt["prompt"] + ("\n1.\n2.\n3." if prompt["style"] == "list" else "")
    size = 44
    while size > 20 and sum(len(wrap(p, size, 712)) for p in text.split("\n")) * (size + 10) > 700:
        size -= 2
    img = Image.new("RGB", (760, 760), PAPER)
    text_block(ImageDraw.Draw(img), (24, 20), text, size, 712, spacing=10)
    return img


# --- batch ----------------------------------------------------------------------------------
def png_bytes(img: Image.Image) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def environment() -> dict:
    import PIL
    return {"pillow": PIL.__version__, "freetype": features.version("freetype2"),
            "font": "Pillow load_default(size) TrueType font"}


def render_all(out_dir: Path, ids: set[str] | None = None) -> dict:
    """Render every custom case (or only `ids`) into out_dir; return the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = []
    for bench, cases in core.custom_cases().items():
        for c in cases:
            if ids is not None and c["id"] not in ids:
                continue
            img = render_case(c) if "scene" in c else render_prompt(c)
            data = png_bytes(img)
            path = out_dir / f"{c['id']}.png"
            path.write_bytes(data)
            items.append({"id": c["id"], "benchmark": bench, "file": path.name,
                          "width": img.width, "height": img.height, "bytes": len(data),
                          "pixel_sha256": hashlib.sha256(img.tobytes()).hexdigest(),
                          "png_sha256": hashlib.sha256(data).hexdigest()})
    return {"environment": environment(), "images": items}


def compare(manifest: dict, reference: dict) -> list[dict]:
    """Images whose pixels differ from the checked-in reference (or are missing from it)."""
    ref = {i["id"]: i for i in reference.get("images", [])}
    return [{"id": i["id"], "reason": "not in reference" if i["id"] not in ref
             else "pixels differ"}
            for i in manifest["images"]
            if i["id"] not in ref or ref[i["id"]]["pixel_sha256"] != i["pixel_sha256"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--check", help="reference manifest to compare pixel hashes against")
    p.add_argument("--write-manifest", help="write the manifest here (maintainers)")
    a = p.parse_args(argv)
    manifest = render_all(Path(a.out))
    print(f"rendered {len(manifest['images'])} images into {a.out} "
          f"(Pillow {manifest['environment']['pillow']}, "
          f"FreeType {manifest['environment']['freetype']})")
    if a.write_manifest:
        Path(a.write_manifest).write_text(json.dumps(manifest, indent=1) + "\n")
    if a.check:
        diffs = compare(manifest, json.loads(Path(a.check).read_text()))
        print(f"{len(diffs)} image(s) differ from {a.check}")
        for d in diffs:
            print(f"  {d['id']}: {d['reason']}")
        return 1 if diffs else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
