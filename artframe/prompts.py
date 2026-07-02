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

1. Pick ONE notable event that happened on {date} (this exact month and day) in a
past year. Apply these rules in priority order:

   (a) TOPIC — most important: the event's subject MUST relate to one of the
   viewer's interests: {interests}. Among events on {date}, choose the strongest
   one that fits an interest. Treat these interests as the category of the event
   (e.g. "music" → a famous concert, album, performance, or musician; "sports" →
   a famous match, record, championship, or athlete). Do NOT default to science,
   technology, or space unless those are listed as interests. Only if truly no
   event on {date} relates to ANY listed interest may you fall back to another
   notable {date} event.

   (b) DATE: it must have occurred on {date} — never pick an event from a
   different calendar date.

The event should be positive, inspiring, and educational. Avoid war, violence,
tragedy, or negative subjects, and avoid copyrighted characters (e.g. Disney).

Additionally:
2. Today might be a holiday. Today's holiday context (may be empty):

{holiday_context}

3. If today is a *very important* holiday for the world or for Judaism, choose
it. Only include holidays that are relevant globally, to Israel, or to Judaism.
Exclude Muslim holidays and ignore holidays specific to other nations or
religions. Select Jewish holidays only if they are explicitly mentioned in
section 2. If there is no holiday, use the proposed historical event. Choose
only one event and write 15-25 words about it with no introduction—just a
description of the event."""

# --------------------------------------------------------------------------- #
# Step 1b — fact-check the chosen event before drawing it.
# --------------------------------------------------------------------------- #
FACT_CHECK_PROMPT = """You are a careful fact-checker for a daily "on this day" artwork.

Target date: {date} (month and day).
Claim: "{event}"

Reply INACCURATE if EITHER is true:
- the claim is fabricated, false, or not a real event; or
- you are confident the event actually happened on a clearly different month/day
  than {date} (e.g. the claim is about Dec 8 but the target is June 29).

Otherwise — the event is real and plausibly tied to {date} — reply ACCURATE.
Do not reject a real event just because you are unsure of its exact date.
Answer with a single word on the first line: ACCURATE or INACCURATE."""

# Light check for the topic-forced path: only verify the event is real (not
# fabricated). We deliberately DON'T re-check the exact date here — the strict
# date check rejected real sports/music events and bounced selection to an
# off-interest fallback. Topic correctness matters more than an exact day.
REAL_EVENT_CHECK_PROMPT = """Is the following a real, actual event that genuinely
happened (not invented or fabricated)? Ignore the exact date — judge ONLY whether
the event itself is real.

Event: "{event}"

Reply with a single word: REAL or FAKE."""

# Web-search selection: ONE search returns several date-verified candidates; a
# cheap second (no-search) step curates the most iconic one. Returns a JSON array.
SEARCH_EVENT_PROMPT = """Use web search to find real, notable, positive events that
genuinely happened on {date} — this exact month and day — in past years, across these
topics:
{interests}

For EACH topic above, find 2-3 of the most significant events you can verify on
{date}. Verify every date with search before listing it.

Rules:
- Each event MUST have occurred on {date} (this month and day). Confirm via search.
- Tag each event with the topic it belongs to (exactly one of the topics listed).
- Favour genuinely significant, memorable moments — championships, world records,
  legendary performances, historic firsts, famous debuts, era-defining
  albums/films/concerts. AVOID routine, minor, or fan-only events (an ordinary
  album release, a regular tour concert, a minor premiere). Avoid war, violence,
  tragedy, and copyrighted characters.
- Pick the events purely on their own significance (above). Then, for each one,
  note in "now_tie" whether it happens to echo something in the world right now —
  an ongoing tournament or season, a country / team / artist / work in the news
  today, a milestone anniversary this year — or leave it empty. This is CONTEXT
  ONLY for the caption; it must NOT change which events you choose (keep the day
  diverse — don't over-pick one topic just because it's currently in the news).

Reply with ONLY a compact JSON array (no prose) of objects (aim for 2-3 per topic):
[{{"category": "<exactly one of the topics listed above>",
   "event": "<15-25 word description, including the year>",
   "verified_date": "<Month DD, YYYY>",
   "on_date": <true if it really happened on {date}, else false>,
   "now_tie": "<<=12 words: how this connects to something happening in the world
   right now (e.g. 'Paraguay faced Germany this week', 'Wimbledon is on now'), or
   \"\" if there is no current connection>",
   "iconic_visual": "<6-14 words: ONE concrete object or emblem whose SHAPE alone
   identifies this event as a bold black paper-cut silhouette — a distinctive
   trophy, uniform, instrument, vehicle, ball, landmark/monument, or signature
   object (e.g. the FIFA World Cup globe, an electric guitar, a chalkboard with
   E=mc2, a lunar module). If the event centers on a person, use their signature
   OBJECT or creation, NEVER their face, hair, body, or likeness — a silhouette
   cannot make a face look like a specific person; it just reads as a blob. Avoid
   faces, hairstyles, 'a player', 'a crowd', or 'team celebration'. Use \"\" (empty)
   if the event has no single instantly-recognizable object — never invent one.>"}}, ...]

If web search verifies no real event on {date} for any topic, reply: []"""

# Pooled curation across SEVERAL categories: candidates were gathered from a few
# different topics; pick the single most meaningful one, enforcing a real
# significance bar so a routine release never wins over a landmark moment.
POOL_CURATE_EVENT_PROMPT = """Below are real events that each happened on {date},
gathered across several topics. RANK them from most to least remarkable: #1 becomes
today's artwork, and the next few are shown to the user as "also on this day" — so
ordering the runners-up by real significance matters too, not just the winner.

Judge by genuine, lasting significance — a moment a wide audience would recognize
and find meaningful, not just something that merely occurred:
- STRONG (prefer these): a world record, an Olympic / World Cup / championship moment,
  a historic first, an era- or genre-defining album or film, a legendary performance,
  a landmark premiere, a defining scientific discovery or cultural milestone.
- WEAK (avoid unless nothing else): a routine album release, an ordinary concert
  date, a minor or fan-only premiere, an incremental or obscure event.

Choose the event with the widest, most lasting resonance AND a strong, instantly
recognizable visual. If several are comparably strong, pick the most visually
iconic. Judge purely on the event's own significance — do NOT factor in whether it
relates to current news (that is handled separately and must not bias the pick, so
the day stays diverse).

Candidates:
{candidates}

Reply with ONLY the candidate numbers separated by commas, most remarkable FIRST
(e.g. 4, 1, 7, 2). Rank every candidate exactly once; never reply 0."""

# Fallback when the chosen event has no iconic_visual (some providers omit it).
VISUAL_PROMPT = """Name the single most iconic, INSTANTLY recognizable image of this
event as ONE concrete object or emblem for a bold hand-cut paper silhouette (6-14
words).

Choose something whose SHAPE alone identifies the event in solid black — a
distinctive trophy, uniform, instrument, vehicle, ball, landmark/monument, or
signature object (e.g. the FIFA World Cup globe, the Wimbledon plate, an electric
guitar, a chalkboard with "E=mc2", a lunar module).

If the event centers on a PERSON, pick their signature OBJECT, creation, or emblem —
NEVER their face, hair, body, or likeness. A cut-paper silhouette cannot make a face
resemble a specific person; a face or "wild hair" just reads as a generic blob.

Avoid faces, portraits, hairstyles, "a player", "a crowd", "a team celebration", or
any vague gesture. Prefer one clean, unmistakable object.

If this event has NO single object that is instantly recognizable on its own — many
historic firsts, signings, abstract ideas, or announcements don't — reply exactly:
NONE. A clean abstract artwork is better than a forced, unrecognizable shape; do not
invent a symbol just to have one.

Reply with ONLY the phrase, or NONE (no quotes, no extra words).

Event: {event}"""

# Topic-forced selection: ask explicitly for ONE interest category, so the model
# can't default to its favourite topics (space/tech) and ignore the interests.
INTEREST_EVENT_PROMPT = """Name one real, well-known, positive event in the category
"{interest}" that happened on {date} — this exact month and day — in some past year.

Rules:
- It MUST have occurred on {date} (this month and day). Do not use other dates.
- It must clearly belong to "{interest}" (sports → a match, record, championship,
  or athlete; music → a concert, album, performance, composer, or musician;
  cinema → a film release, premiere, or filmmaker; and so on).
- Positive and inspiring. Avoid war, violence, tragedy, and copyrighted characters.

Write 15-25 words describing it, with no introduction. If you genuinely cannot
recall a real "{interest}" event on {date}, reply with exactly: NONE"""

# Fallback if the model's picks keep failing the fact-check.
GENERIC_EVENT_PROMPT = """Name one very well-known, indisputable event or fact
associated with {date} (for example a famous birth, a discovery, an invention,
or a widely recognized international holiday). Only choose something you are
certain is true and correctly dated. Avoid war or violence. Write 15-20 words
with no introduction—just the event."""

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

{data_block}

---

### Text & Signature (Detached Minimalism):

- Caption (bottom edge, outside shapes):
  → 3-7 words in **LARGE BOLD CAPITAL LETTERS** with wide letter-spacing —
    cap height at least 3% of the image height, so it stays clearly legible on a
    small 7.5-inch display. Never small, never thin, never subtle in size —
    quiet in placement, loud in weight.
  → If there is an event above, caption it in magazine-style copywriting (include
    the year for a historical event). If there is no event, omit the caption.
- Signature: "{signature}" — **bold, subtle, pen or brush handwritten,
  understated**

---

### Technical Constraints:

- Resolution: {resolution}
- High contrast
- Focus on **shape language, negative space, and tactile imperfection**

---

### Final Intent:

The piece should feel like:
- A **true paper collage by hand**
- A **pure abstract composition**
- With **hidden structured data embedded inside**

Not a designed poster — but an artwork where meaning is **discovered, not
delivered**."""

# --------------------------------------------------------------------------- #
# Step 3 — narration text (optional metadata shown in the app)
# --------------------------------------------------------------------------- #
NARRATION_EN_PROMPT = """Here is an event description:

{event}

Expand on it in 15-30 words in English. Give only an explanation of the event
with no introduction. If it is a historical event, mention the date it
happened. {connection}Important! Do not exceed 250 characters."""

NARRATION_HE_PROMPT = """יש פה פירוט על אירוע:

{event}

תרחיב עליו ב-25-45 מילים בעברית עבור תסריט לקריינות לקהל הצעיר. תן רק הסבר על
האירוע בלי הקדמה. אם זה אירוע היסטורי, תציין את התאריך שבו הוא קרה. {connection}חשוב! לא
לחרוג מ-250 תווים."""


def build_data_block(
    show_weather: bool, show_date: bool, condition: str, temperature: str,
    date_str: str, event: str = "", visual: str = "",
) -> str:
    """Assemble the two embedded sections of the artwork prompt, kept verbatim
    from the original. Section 1 (Weather & Date) is included only if the device
    wants the date and/or weather; section 2 (Event Symbol) only if there is an
    event. Either can be subtracted per the device's preferences.

    `visual` is the iconic image to depict (from the event finder); when given it
    is what the silhouette draws, while `event` is kept as context for the caption.
    """
    sections: list[str] = []

    if show_weather or show_date:
        # Only name the elements that are actually enabled, so weather/temperature
        # are never mentioned when the device has weather turned off.
        elems: list[str] = []
        if show_date:
            elems.append("date")
        if show_weather:
            elems += ["weather icon", "temperature"]
        if len(elems) == 1:
            phrase = f"The {elems[0]}"
        elif len(elems) == 2:
            phrase = f"The {elems[0]} and {elems[1]}"
        else:
            phrase = "The " + ", ".join(elems[:-1]) + f", and {elems[-1]}"
        title = " & ".join(t for t, on in (("Weather", show_weather), ("Date", show_date)) if on)
        intro = (
            "### Crucially Integrated Dynamic Data (Dissolved Negative Space):\n\n"
            f"{phrase} must be **carved out of the "
            "black shapes as negative space**, fully integrated into their form.\n\n"
            "They must:\n"
            "- Follow the **exact curvature and flow** of the shape\n"
            "- Be **warped unevenly** (non-linear scaling)\n"
            "- Be **partially cropped, overlapped, or fragmented**\n"
            "- Feel like they were **cut blindly by hand**, not typeset\n\n"
            "They should resemble a **calligram dissolving into abstraction**, not "
            "readable typography.\n\n"
            f"### 1. {title} (Embedded and Distorted):\n"
        )
        items: list[str] = []
        if show_weather:
            items.append(f'- Weather icon: "{condition}" → Render as a **naïve, '
                         "irregular, possibly incomplete symbol**, stretched and bent "
                         "to the shape")
            items.append(f'- Temperature: "{temperature}" → Reproduce this value and '
                         "its unit symbol **exactly as written** — do NOT convert it or "
                         "change the unit (if it says °C keep °C, if °F keep °F). Only the "
                         "**shape** may be distorted: digits **elongated, compressed, or "
                         "fused**, possibly sharing edges")
        if show_date:
            items.append(f'- Date: "{date_str}" → Break into **uneven fragments**, '
                         "scattered or curved along the inner contour")
        tail = ("\n\nAll must feel like they are **being absorbed into the black "
                "mass**, not sitting inside it.")
        sections.append(intro + "\n".join(items) + tail)

    if event and visual and visual.strip():
        # The event has a genuinely iconic, recognizable object — depict THAT.
        sections.append(
            "### 2. Event Symbol (Extremely Abstract):\n\n"
            f'- Iconic image to depict: "{visual.strip()}"\n'
            f'- It represents: "{event}"\n'
            "- Translate into **one single, ambiguous black silhouette** (max two elements)\n"
            "- Must:\n"
            "  - Suggest the idea **indirectly**, not depict it.\n"
            "  - Feel like a **primitive cut-out gesture**\n"
            "  - Avoid literal storytelling\n"
            "  - Keep the element recognizable and implicit to the subject\n"
            "  - Depict an **object or emblem only** — NEVER a person's face, head, "
            "hair, or body (a silhouette can't resemble a specific person; render "
            "their signature object instead)"
        )
    elif event:
        # No instantly-recognizable icon for this event — do NOT force a symbol
        # (that just produces a weird, unrecognizable shape). Stay abstract and let
        # the magazine-style caption text carry the meaning.
        sections.append(
            "### 2. Event (No Literal Symbol):\n\n"
            f'- Today\'s event is: "{event}"\n'
            "- This event has **no single instantly-recognizable image**, so do NOT "
            "invent or depict a specific object, scene, person, or symbol for it.\n"
            "- Keep the composition **purely abstract** — bold Matisse cut-paper "
            "shapes for their own rhythm and balance. The caption text alone conveys "
            "the event; the shapes must not try to illustrate it."
        )

    if not sections:
        return ("Embed no text, numbers, or symbols at all. Keep the composition "
                "purely abstract with no readable information.")
    return "\n\n---\n\n".join(sections)


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
