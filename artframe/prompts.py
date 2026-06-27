"""Prompt templates ported from the Home Assistant automation.

The image prompt is the "GPT Image Generation" action, preserved verbatim with
`{condition}`, `{temperature}`, `{date}`, `{event}` placeholders swapped in for
the original Jinja `{{ }}` expressions.
"""
from __future__ import annotations

# --------------------------------------------------------------------------- #
# Step 1 — choose the day's event (ported from the enabled English generate_data)
# --------------------------------------------------------------------------- #
EVENT_SELECTION_PROMPT = """# Daily Event Generator Prompt

1. Find special events that happened on {date} in previous years, or relevant
and current events of global importance or national importance to the State of
Israel. Prefer a positive event, an international holiday, an event of global
historical significance, or an event in science, culture, or joyful current
affairs. If it is a major event, sports are also acceptable. The event should
have educational value and be inspiring. Avoid events that are war or violence
related, or events with negative subjects. Try to avoid events where the main
subject would be subject to copyright restrictions like Disney.

When several events qualify, gently favor ones that align with the viewer's
interests: {interests}.

Additionally:

2. Today's holiday context (may be empty):
{holiday_context}

3. If today is a *very important* holiday for the world or for Judaism, choose
it. Only include holidays that are relevant globally, to Israel, or to Judaism.
Exclude Muslim holidays and ignore holidays specific to other nations or
religions. Select Jewish holidays only if explicitly listed in section 2. If
there is no holiday, use the proposed historical event. Choose only one event
and write 15-25 words about it with no introduction—just a description of the
event."""

# --------------------------------------------------------------------------- #
# Step 2 — render the artwork (ported verbatim from the OpenAI image action)
# --------------------------------------------------------------------------- #
ARTWORK_PROMPT = """### Core Art Style & Composition:

A museum-quality abstract composition in the definitive style of Henri Matisse
*gouaches découpés*. The artwork must feel like it is made from **hand-cut
painted paper**, not digital shapes.

The composition should feel **instinctive, slightly unbalanced, and poetic**,
with a strong sense of rhythm between forms. Prioritize **visual harmony and
abstract expression over clarity or communication**.

---

### Colors & Shapes:

- Pure white background
- Deep matte black shapes only
- **No other colors allowed**
- Shapes must be **large, organic, irregular, and biomorphic**
- Edges must be **rough, torn, imperfect, visibly hand-cut**
- Subtle paper texture / screen-print feel
- No gradients, no shadows, no digital precision

Use **1-3 dominant black shapes** that feel fluid and ambiguous. Avoid symmetry
and avoid geometric forms.

---

### Abstraction Rule (Critical Override):

- **Legibility is intentionally degraded**
- Information should feel **hidden, dissolved, or partially lost**
- Elements must be **distorted, fragmented, stretched, rotated, and merged**
- The result should read as **abstract art first, information second**

If the viewer can instantly read everything → it is too literal.

---

### Crucially Integrated Dynamic Data (Dissolved Negative Space):

{data_block}

### 2. Event Symbol (Extremely Abstract):

- Source: "{event}"
- Translate into one single, ambiguous black silhouette (max two elements).
  Suggest the idea indirectly, keep it a primitive cut-out gesture, recognizable
  but not literal.

---

### Text & Signature (Detached Minimalism):

- Caption (bottom edge, outside shapes): 3-7 words, medium, bold, quiet,
  visually detached, noticeable on small low-resolution screens. Magazine-style
  copywriting. If it is a historical event, include the year.
- Signature: "{signature}" — bold, subtle, pen/brush handwritten, understated.

---

### Technical Constraints:

- Resolution: {resolution}
- Low detail, high contrast
- Focus on shape language, negative space, and tactile imperfection

### Final Intent:

A true paper collage by hand; a pure abstract composition with hidden structured
data embedded inside. Not a designed poster — an artwork where meaning is
discovered, not delivered."""

# --------------------------------------------------------------------------- #
# Step 3 — narration text (optional metadata shown in the app)
# --------------------------------------------------------------------------- #
NARRATION_EN_PROMPT = """Here is an event description:

{event}

Expand on it in 15-25 words in English. Give only an explanation of the event
with no introduction. If it is a historical event, mention the date it
happened. Important! Do not exceed 250 characters."""

NARRATION_HE_PROMPT = """יש פה פירוט על אירוע:

{event}

תרחיב עליו ב-25-45 מילים בעברית עבור תסריט לקריינות לקהל הצעיר. תן רק הסבר על
האירוע בלי הקדמה. אם זה אירוע היסטורי, תציין את התאריך שבו הוא קרה. חשוב! לא
לחרוג מ-250 תווים."""


def build_data_block(
    show_weather: bool, show_date: bool, condition: str, temperature: str, date_str: str
) -> str:
    """The dynamic-data directives injected into the artwork prompt.

    Reflects the device's show-date / show-weather toggles so the configuration
    visibly changes what the model is told to embed.
    """
    if not show_weather and not show_date:
        return ("Embed no text, numbers, or symbols at all. Keep the composition "
                "purely abstract with no readable information.")
    lines = [
        "The following must be carved out of the black shapes as negative space —",
        "warped unevenly, partially cropped, hand-cut, like a calligram dissolving",
        "into abstraction (abstract first, information second):",
    ]
    if show_weather:
        lines.append(f'- Weather: a naive, irregular icon for "{condition}", '
                     "stretched and bent to the shape.")
        lines.append(f'- Temperature: "{temperature}" — digits elongated, '
                     "compressed, or fused.")
    if show_date:
        lines.append(f'- Date: "{date_str}" — broken into uneven fragments, '
                     "curved along the inner contour.")
    return "\n".join(lines)


def format_holiday_context(jewish: list[str], israeli: list[str], glob: list[str]) -> str:
    """Build the section-2 holiday block; empty string when nothing applies."""
    lines: list[str] = []
    if jewish:
        lines.append("Jewish calendar today: " + "; ".join(jewish))
    if israeli:
        lines.append("Israeli holidays today: " + "; ".join(israeli))
    if glob:
        lines.append("Global holidays today: " + "; ".join(glob))
    return "\n".join(lines) if lines else "(no holiday today)"
