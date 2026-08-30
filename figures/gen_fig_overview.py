#!/usr/bin/env python3
"""Generate the README overview diagram (problem -> data recipe -> training -> exam)
via Gemini image generation (nano-banana). Needs GEMINI_API_KEY in the environment."""
import os
import sys
import time

from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY")
if not API_KEY:
    print("ERROR: Set GEMINI_API_KEY environment variable.")
    sys.exit(1)

MODELS = ["gemini-3-pro-image-preview", "gemini-2.5-flash-image"]
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
client = genai.Client(api_key=API_KEY)

PROMPT = """
Create an ultra-clean, modern technical overview diagram for a machine-learning
research README. Confident, spacious, authoritative — think Apple developer
documentation meets a Nature paper. It shows an end-to-end pipeline: teaching a
small open language model everything about one chip platform, then examining it
closed-book. Wide banner format, 16:9.

VISUAL STYLE — MODERN MINIMAL:
- Ultra-clean geometric shapes with crisp edges
- Four vertical section columns side by side, each a full-height rounded
  rectangle (12px corners) with a desaturated tinted fill
- Component boxes inside sections: white fill, 10px rounded corners, NO visible
  border — they float on the tinted section background with a subtle shadow
  (1px offset, 4px blur, rgba(0,0,0,0.06))
- ONE accent color per section, used only on the section header text and one
  key element in that section
- Arrows between sections: thin 1.5px, dark gray #6B7280, small filled circle
  at the source, clean open chevron at the target, with a small italic label
- Typography: Inter / system sans-serif, section headers in SMALL CAPS with
  letter-spacing, titles 600 weight, body 400 weight
- Labels INSIDE boxes, generous whitespace, at least 24px between elements
- NO decorative icons, NO illustrations — structure and typography only

COLOR PALETTE — NORD (use EXACTLY these colors):
- Main text: #2E3440
- Secondary text: #4C566A
- Section 1 fill: #EEF1F6 (blue tint), accent #5E81AC
- Section 2 fill: #EDF3ED (green tint), accent #4E7A4E
- Section 3 fill: #F5F2EA (sand tint), accent #B08C3E
- Section 4 fill: #F6EDEE (rose tint), accent #BF616A
- Component boxes: white #FFFFFF
- Arrows: #6B7280
- Page background: pure white #FFFFFF

LAYOUT — FOUR VERTICAL COLUMNS, LEFT TO RIGHT, EQUAL WIDTH:

COLUMN 1 — header "THE PROBLEM" in #5E81AC small caps, blue-tint section #EEF1F6:
- White box 1: title "Your chip's knowledge", subtitle "register maps - memory
  maps - drivers - build system - issue history"
- White box 2: title "In no pretraining corpus", subtitle "frontier LLMs know it
  only partially; a base 9B model barely at all"
- White box 3 (key element, thin #5E81AC left strip): title "Test bed: PULP
  Carfield SoC", subtitle "a real open RISC-V platform, 259 public repos"

COLUMN 2 — header "TRAINING DATA RECIPE" in #4E7A4E small caps, green-tint
section #EDF3ED:
- White box 1: title "Corpus - 31.2M tokens", subtitle "RTL - register hjson -
  C drivers - docs - issues"
- White box 2 (key element, thin #4E7A4E left strip, slightly taller): title
  "Knowledge-rewriting augmentation - 3.5M tokens", subtitle "every fact x 24
  paraphrase templates - 1/3 reversed forms - whole-table narrative docs"
- Small italic footnote text at the bottom of the section, in #4C566A:
  "raw corpus alone injects zero retrievable facts"

COLUMN 3 — header "TRAINING" in #B08C3E small caps, sand-tint section #F5F2EA:
- White box 1: title "Qwen3.5-9B-Base", subtitle "open weights"
- Downward thin gray arrow to:
- White box 2: title "Continued pretraining", subtitle "full-parameter - 77 min
  on 4x H100"
- Downward thin gray arrow to:
- White box 3 (key element, thin #B08C3E left strip): title
  "Qwen3.5-9B-PULP", subtitle "the chip expert"

COLUMN 4 — header "CLOSED-BOOK EXAM" in #BF616A small caps, rose-tint section
#F6EDEE:
- White box 1: title "1,776 auto-generated questions", subtitle "machine-checked,
  no retrieval, no context"
- White box 2, styled like a small exam card with a monospace feel: first line
  "Q: byte offset of the SECURITY_ISLAND_RST register in the carfield block?"
  second line "A: 0x2c" with "0x2c" in bold #BF616A
- White box 3 (key element, thin #BF616A left strip), a compact scoreboard of
  three rows, right-aligned numbers in 600 weight:
  row 1: "Qwen3.5-9B-PULP (ours)   81.6%" — this row's number in #BF616A
  row 2: "Claude Opus 5   72.2%"
  row 3: "Qwen3.5-9B-Base   41.2%"
  and below the rows, one small #4C566A line: "register offsets: 97% vs 28% vs 7%"

CONNECTIONS:
ARROW 1: from COLUMN 1 right edge to COLUMN 2 left edge, vertically centered.
- thin 1.5px, #6B7280, straight, filled dot at source, open chevron at target
- label above it in small italic #4C566A: "crawl + extract every fact"
ARROW 2: from COLUMN 2 right edge to COLUMN 3 left edge, vertically centered.
- same style, label: "corpus : augmentation : replay mix"
ARROW 3: from COLUMN 3 right edge to COLUMN 4 left edge, vertically centered.
- same style, label: "3-shot, greedy"

CONSTRAINTS:
- ZERO decoration — no icons, no illustrations, no ornaments, no logos
- NO visible borders on white boxes — subtle shadow only (left color strips on
  the three key boxes are the single exception)
- NO gradients, NO patterns, NO textures
- NO figure number, NO caption, NO watermark, NO title above the diagram
- Background pure white #FFFFFF
- Every text label spelled EXACTLY as written above; SPELL EXACTLY:
  "SECURITY_ISLAND_RST", "0x2c", "Qwen3.5-9B-PULP", "Carfield", "81.6%",
  "72.2%", "41.2%", "31.2M", "3.5M", "1,776"
- Whitespace is a design element; nothing cramped
"""


def generate_image(model, prompt_text, attempt_num):
    print(f"\n{'=' * 60}\n{model} — attempt {attempt_num}\n{'=' * 60}")
    try:
        cfg = dict(response_modalities=["IMAGE", "TEXT"])
        if "3-pro" in model:
            cfg["image_config"] = types.ImageConfig(aspect_ratio="16:9")
        response = client.models.generate_content(
            model=model,
            contents=prompt_text,
            config=types.GenerateContentConfig(**cfg),
        )
        output_path = os.path.join(OUTPUT_DIR, f"fig_overview_attempt{attempt_num}.png")
        for part in response.candidates[0].content.parts:
            if part.inline_data:
                with open(output_path, "wb") as f:
                    f.write(part.inline_data.data)
                print(f"Saved: {output_path} ({os.path.getsize(output_path):,} bytes)")
                return output_path
            elif part.text:
                print(f"Text: {part.text[:300]}")
        print("WARNING: No image in response")
        return None
    except Exception as e:
        print(f"ERROR: {e}")
        return None


def main():
    results = []
    for i in range(1, 4):
        if i > 1:
            time.sleep(2)
        for model in MODELS:
            path = generate_image(model, PROMPT, i)
            if path:
                results.append(path)
                break
    if not results:
        print("All attempts failed!")
        sys.exit(1)
    print(f"\nGenerated {len(results)} attempts. Review and pick the best.")


if __name__ == "__main__":
    main()
