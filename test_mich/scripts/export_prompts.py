#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def load_manifest(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_style_map(manifest: dict) -> dict:
    styles = manifest.get("prompt_system", {}).get("style_blocks", [])
    return {style["id"]: style["prompt"] for style in styles if "id" in style and "prompt" in style}


def compose_prompt(style_text: str, subject_text: str) -> str:
    return f"{style_text}\nSUBJECT: {subject_text}"


def iter_asset_prompts(manifest: dict):
    style_map = build_style_map(manifest)
    negative = manifest.get("prompt_system", {}).get("global_negative_prompt")

    for asset in manifest.get("assets", []):
        asset_id = asset.get("id", "unknown_asset")

        # Single prompt asset
        prompt_parts = asset.get("prompt_parts")
        if isinstance(prompt_parts, dict):
            style_id = prompt_parts.get("style_id")
            style_text = style_map.get(style_id, "")

            subject = prompt_parts.get("subject_prompt")
            if subject:
                prompt = compose_prompt(style_text, subject)
                yield {
                    "asset_id": asset_id,
                    "variant": None,
                    "prompt": prompt,
                    "negative": negative,
                }

            template = prompt_parts.get("subject_prompt_template")
            if template:
                prompt = compose_prompt(style_text, template)
                yield {
                    "asset_id": asset_id,
                    "variant": "template",
                    "prompt": prompt,
                    "negative": negative,
                }

        # Multi-state asset
        series = asset.get("prompt_parts_series", [])
        if isinstance(series, list):
            for item in series:
                if not isinstance(item, dict):
                    continue
                style_id = item.get("style_id")
                style_text = style_map.get(style_id, "")
                subject = item.get("subject_prompt")
                if not subject:
                    continue
                variant = item.get("state")
                prompt = compose_prompt(style_text, subject)
                yield {
                    "asset_id": asset_id,
                    "variant": variant,
                    "prompt": prompt,
                    "negative": negative,
                }


def export_prompts(manifest_path: Path, output_path: Path) -> int:
    manifest = load_manifest(manifest_path)
    entries = list(iter_asset_prompts(manifest))

    lines = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(f"### Prompt {idx}")
        lines.append(f"asset_id: {entry['asset_id']}")
        if entry["variant"]:
            lines.append(f"variant: {entry['variant']}")
        lines.append("prompt:")
        lines.append(entry["prompt"])
        if entry["negative"]:
            lines.append("negative_prompt:")
            lines.append(entry["negative"])
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def parse_args():
    parser = argparse.ArgumentParser(description="Export all prompts from asset manifest to a text file.")
    parser.add_argument(
        "--manifest",
        default="asset_prompt_manifest.json",
        help="Path to manifest JSON file (default: asset_prompt_manifest.json)",
    )
    parser.add_argument(
        "--output",
        default="all_prompts.txt",
        help="Path to output text file (default: all_prompts.txt)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    manifest_path = Path(args.manifest)
    output_path = Path(args.output)

    count = export_prompts(manifest_path, output_path)
    print(f"Exported {count} prompts to {output_path}")


if __name__ == "__main__":
    main()
