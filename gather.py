#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json
import os
import re
import time
import yaml
import html as html_module
from difflib import SequenceMatcher

# --- STS1 sources (MediaWiki API — Cloudflare blocks HTML scraping now) ---
STS1_API = "https://slay-the-spire.fandom.com/api.php"

# --- STS2 sources ---
STS2_BASE = "https://sts2.untapped.gg"

# --- Data classes ---

class SpireObject(object):
  def __repr__(self):
    return str(dict(vars(self)))

class Card(SpireObject):
  def __init__(self, name, description, card_type, category, rarity, cost,
               game="STS1", star_cost=None):
    self.type = "Card"
    self.game = game
    self.name = name.replace("\n", " ").strip()
    self.description = description.replace("\n", " ").strip()
    self.card_type = card_type
    self.category = category
    self.rarity = rarity
    self.cost = cost
    if star_cost is not None:
      self.star_cost = star_cost

class Relic(SpireObject):
  def __init__(self, name, description, category, game="STS1"):
    self.type = "Relic"
    self.game = game
    self.name = name.replace("\n", " ").strip()
    self.description = description.replace("\n", " ").strip()
    self.category = category

class Potion(SpireObject):
  def __init__(self, name, description, rarity, game="STS1"):
    self.type = "Potion"
    self.game = game
    self.name = name.replace("\n", " ").strip()
    self.description = description.replace("\n", " ").strip()
    self.rarity = rarity

class Event(SpireObject):
  def __init__(self, name, description, act, game="STS1"):
    self.type = "Event"
    self.game = game
    self.name = name.strip()
    self.description = description.strip()
    self.act = act


# =========================================================================
# Wikitext parsing helpers
# =========================================================================

def _clean_wikitext(text):
  """Strip wikitext markup to plain text."""
  # Remove {{KW|...}} and {{C|...}} templates -> just the first arg
  text = re.sub(r'\{\{KW\|([^}|]+)(?:\|[^}]*)?\}\}', r'\1', text)
  text = re.sub(r'\{\{C\|([^}|]+)(?:\|[^}]*)?\}\}', r'\1', text)
  # Remove other templates
  text = re.sub(r'\{\{[^}]*\}\}', '', text)
  # Remove [[File:...]]
  text = re.sub(r'\[\[File:[^\]]*\]\]', '', text)
  # Convert [[Page|Display]] -> Display, [[Page]] -> Page
  text = re.sub(r'\[\[([^]|]*)\|([^\]]*)\]\]', r'\2', text)
  text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text)
  # Remove bold/italic markup
  text = re.sub(r"'{2,5}", '', text)
  # Remove any remaining HTML tags
  text = re.sub(r'<[^>]+>', '', text)
  # Clean up whitespace
  text = re.sub(r'\s+', ' ', text).strip()
  return text

def _get_wikitext(page):
  """Fetch wikitext for a page from the Fandom MediaWiki API."""
  resp = requests.get(STS1_API, params={
    "action": "parse",
    "page": page,
    "prop": "wikitext",
    "format": "json",
  }, timeout=15)
  resp.raise_for_status()
  data = resp.json()
  return data["parse"]["wikitext"]["*"]

def _parse_wiki_table_rows(wikitext):
  """Parse rows from a wikitext table.

  Yields lists of cell values (cleaned) for each row.
  Rows start with |- and cells start with |.
  """
  in_table = False
  current_row = []

  for line in wikitext.split("\n"):
    line = line.strip()
    if line.startswith("{|"):
      in_table = True
      continue
    if line.startswith("|}"):
      if current_row:
        yield current_row
      in_table = False
      current_row = []
      continue
    if not in_table:
      continue
    if line.startswith("!"):
      continue  # Header row
    if line.startswith("|-"):
      if current_row:
        yield current_row
      current_row = []
      continue
    if line.startswith("|"):
      cell = line[1:].strip()
      current_row.append(_clean_wikitext(cell))

  if current_row:
    yield current_row


# =========================================================================
# STS1 Gathering (via MediaWiki API)
# =========================================================================

def GatherCards():
  card_pages = {
    "Ironclad": "Ironclad_Cards",
    "Silent": "Silent_Cards",
    "Defect": "Defect_Cards",
    "Watcher": "Watcher_Cards",
    "Colorless": "Colorless_Cards",
    "Status": "Status",
    "Curse": "Curse",
  }

  cards = []

  for category, page in card_pages.items():
    print("Gathering STS1 {0}".format(category))
    try:
      wikitext = _get_wikitext(page)
    except Exception as e:
      print("  Failed to fetch {0}: {1}".format(page, e))
      continue

    for row in _parse_wiki_table_rows(wikitext):
      if category == "Status":
        if len(row) >= 4:
          name, _, card_type, description = row[0], row[1], row[2], row[3]
          print("Found STS1 card {0}".format(name))
          cards.append(Card(name, description, card_type, category, None, None, game="STS1"))

      elif category == "Curse":
        if len(row) >= 3:
          name = row[0]
          description = row[2] if len(row) >= 3 else row[-1]
          print("Found STS1 card {0}".format(name))
          cards.append(Card(name, description, "Curse", category, None, None, game="STS1"))

      elif len(row) >= 6:
        # Standard card: Name, Picture, Rarity, Type, Energy, Description
        name, _, rarity, card_type, energy, description = row[0], row[1], row[2], row[3], row[4], row[5]
        print("Found STS1 card {0}".format(name))
        cards.append(Card(name, description, card_type, category, rarity, energy, game="STS1"))

  return cards

def GatherRelics():
  relics = []
  print("Gathering STS1 Relics")
  try:
    wikitext = _get_wikitext("Relics")
  except Exception as e:
    print("  Failed to fetch Relics: {0}".format(e))
    return relics

  for row in _parse_wiki_table_rows(wikitext):
    if len(row) >= 4:
      _, name, category, description = row[0], row[1], row[2], row[3]
      # Skip junk rows (CSS style strings parsed as data)
      if name.startswith("style=") or "border" in name or len(name) > 100:
        continue
      print("Found STS1 relic {0}".format(name))
      relics.append(Relic(name, description, category, game="STS1"))

  return relics

def GatherPotions():
  potions = []
  print("Gathering STS1 Potions")
  try:
    wikitext = _get_wikitext("Potions")
  except Exception as e:
    print("  Failed to fetch Potions: {0}".format(e))
    return potions

  for row in _parse_wiki_table_rows(wikitext):
    if len(row) >= 4:
      _, name, rarity, description = row[0], row[1], row[2], row[3]
      print("Found STS1 potion {0}".format(name))
      potions.append(Potion(name, description, rarity, game="STS1"))

  return potions

def _get_event_description(event_name):
  """Fetch an event's description from its wiki page via API."""
  page_title = event_name.replace(" ", "_")
  try:
    wikitext = _get_wikitext(page_title)
  except Exception:
    try:
      wikitext = _get_wikitext(page_title + "_(Event)")
    except Exception:
      return ""

  lines = wikitext.split("\n")
  for line in lines:
    line = line.strip()
    if not line or line.startswith("[[File:") or line.startswith("[[Category"):
      continue
    if line.startswith("{") or line.startswith("=") or line.startswith("__"):
      continue
    if line.startswith("*") or line.startswith("#") or line.startswith("|") or line.startswith("!"):
      continue
    cleaned = _clean_wikitext(line)
    if len(cleaned) > 20:
      return cleaned

  return ""

def GatherEvents():
  """Gather STS1 events from the Events wiki page."""
  events = []
  print("Gathering STS1 Events")

  events_json = os.path.join(os.path.dirname(__file__), "events.json")
  if os.path.exists(events_json):
    data = json.loads(open(events_json, "r").read())
    for act in data:
      for name in data[act]:
        print("Found STS1 event {0} (from events.json)".format(name))
        events.append(Event(name, data[act][name], act, game="STS1"))
    if events:
      return events

  try:
    wikitext = _get_wikitext("Events")
  except Exception as e:
    print("  Failed to fetch Events: {0}".format(e))
    return events

  section_map = {
    "common_events": "Common",
    "act1_events": "Act 1 (The Exordium)",
    "act2_events": "Act 2 (The City)",
    "act3_events": "Act 3 (The Beyond)",
  }

  sections = re.split(r'<div id="(\w+_events)"', wikitext)

  for i in range(1, len(sections), 2):
    section_id = sections[i]
    section_text = sections[i + 1] if i + 1 < len(sections) else ""
    act_name = section_map.get(section_id, section_id)

    names = re.findall(r'\{\{ficon\|[^|]+\|([^|]+)\|', section_text)
    link_names = re.findall(r'\[\[([^|\]]+?)(?:\s*\(Event\))?\|([^\]]+)\]\]', section_text)
    for page, display in link_names:
      if display not in names and "Act" not in display and "File:" not in display:
        names.append(display)

    for name in names:
      if len(name) < 3 or "|" in name or "px" in name or name in ["first", "three", "two"]:
        continue
      print("Found STS1 event {0} ({1})".format(name, act_name))
      description = _get_event_description(name)
      events.append(Event(name, description, act_name, game="STS1"))
      time.sleep(0.2)

  return events


# =========================================================================
# STS2 HTML parsing helpers
# =========================================================================

def _unescape_html(text):
  """Unescape HTML entities: &#x27; -> ', &amp; -> &, etc."""
  return html_module.unescape(text)

def _extract_description_from_html(html_fragment):
  """Extract card description text from an HTML fragment (foreignObject content).

  Handles:
  - <img alt="Regent Star Energy"> -> star marker (counted)
  - <img alt="X Energy"> -> energy marker (counted)
  - <span class="...mechanic">keyword</span> -> keyword text
  - <br/> -> sentence separator
  """
  # Replace star energy images with placeholder
  text = re.sub(r'<img[^>]*alt="[^"]*Star Energy"[^>]*/?\s*>', '\x01S\x01', html_fragment)
  # Replace regular energy images with placeholder
  text = re.sub(r'<img[^>]*alt="[^"]*Energy"[^>]*/?\s*>', '\x01E\x01', text)
  # Replace <br/> with sentence separator
  text = re.sub(r'<br\s*/?>', ' ', text)
  # Strip all remaining HTML tags
  text = re.sub(r'<[^>]+>', '', text)
  # Unescape HTML entities
  text = _unescape_html(text)
  # Clean up whitespace
  text = re.sub(r'\s+', ' ', text).strip()

  # Normalize energy/star sequences:
  # 1. Number followed by energy icon(s) (with optional space): "4\x01E\x01" -> "4 Energy"
  def _replace_numbered_energy(m):
    return m.group(1) + ' Energy'
  text = re.sub(r'(\d)\s*(\x01E\x01)+', _replace_numbered_energy, text)

  # 2. Standalone energy icons: "\x01E\x01\x01E\x01" -> "2 Energy"
  def _replace_energy(m):
    count = m.group(0).count('\x01E\x01')
    return '{0} Energy'.format(count)
  text = re.sub(r'(\x01E\x01)+', _replace_energy, text)

  # 3. Number followed by star icon(s) (with optional space)
  def _replace_numbered_stars(m):
    return m.group(1) + ' Stars'
  text = re.sub(r'(\d)\s*(\x01S\x01)+', _replace_numbered_stars, text)

  # 4. Standalone star icons: "\x01S\x01\x01S\x01\x01S\x01" -> "3 Stars"
  def _replace_stars(m):
    count = m.group(0).count('\x01S\x01')
    return '{0} Stars'.format(count)
  text = re.sub(r'(\x01S\x01)+', _replace_stars, text)

  # Fix missing spaces where word runs into number: "Gain3" -> "Gain 3"
  text = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', text)
  # Fix stray spaces before punctuation: "something ." -> "something."
  text = re.sub(r'\s+([.,;:!?])', r'\1', text)
  # Clean up multiple spaces
  text = re.sub(r'\s+', ' ', text)

  return text.strip()

def _compute_upgrade_diff(base_text, upgrade_text):
  """Compute a parenthesized diff between base and upgraded card text.

  Examples:
    "Deal 6 damage." + "Deal 9 damage." -> "Deal 6(9) damage."
    "Gain 2 Stars." + "Gain 3 Stars." -> "Gain 2(3) Stars."
    "Draw 1 card." + "Draw 2 cards." -> "Draw 1(2) card(s)."
  """
  if not base_text or not upgrade_text:
    return base_text or ""
  if base_text == upgrade_text:
    return base_text

  base_words = base_text.split()
  upg_words = upgrade_text.split()

  # Use SequenceMatcher for alignment
  matcher = SequenceMatcher(None, base_words, upg_words)
  result = []

  for op, i1, i2, j1, j2 in matcher.get_opcodes():
    if op == 'equal':
      result.extend(base_words[i1:i2])
    elif op == 'replace':
      base_chunk = base_words[i1:i2]
      upg_chunk = upg_words[j1:j2]
      if len(base_chunk) == len(upg_chunk):
        # Word-by-word replacement
        for bw, uw in zip(base_chunk, upg_chunk):
          result.append(_diff_word(bw, uw))
      elif len(base_chunk) == 1 and len(upg_chunk) == 1:
        result.append(_diff_word(base_chunk[0], upg_chunk[0]))
      else:
        # Multi-word replacement — show inline
        result.append('{0}({1})'.format(
          ' '.join(base_chunk), ' '.join(upg_chunk)
        ))
    elif op == 'insert':
      # Words added in upgrade
      added = ' '.join(upg_words[j1:j2])
      result.append('({0})'.format(added))
    elif op == 'delete':
      # Words removed in upgrade — show with strikethrough notation
      removed = ' '.join(base_words[i1:i2])
      result.append(removed)

  return ' '.join(result)


def _diff_word(base_word, upg_word):
  """Diff a single word pair, handling numbers, pluralization, punctuation."""
  if base_word == upg_word:
    return base_word

  # Strip trailing punctuation for comparison
  base_stripped = base_word.rstrip('.,;:!?')
  upg_stripped = upg_word.rstrip('.,;:!?')
  base_punct = base_word[len(base_stripped):]
  upg_punct = upg_word[len(upg_stripped):]
  # Use base punctuation (usually same)
  punct = base_punct or upg_punct

  if base_stripped == upg_stripped:
    return base_word  # Only punctuation differs

  # Check if both are numbers
  if _is_number(base_stripped) and _is_number(upg_stripped):
    return '{0}({1}){2}'.format(base_stripped, upg_stripped, punct)

  # Check pluralization: "card" -> "cards", "time" -> "times"
  if upg_stripped == base_stripped + 's' or upg_stripped == base_stripped + 'es':
    return base_stripped + '(s)' + punct

  # Check "a" -> "ALL", "random" -> "not random" etc.
  # For simple word changes, parenthesize
  return '{0}({1}){2}'.format(base_stripped, upg_stripped, punct)


def _is_number(s):
  """Check if string is a number (int or X for variable cost)."""
  try:
    int(s)
    return True
  except ValueError:
    return s == 'X'


def _extract_upgrade_cost(page_html):
  """Extract upgrade cost change from the upgradeDetails section.

  Returns (base_cost, upgrade_cost) if cost changes, else (None, None).
  Pattern: "Cost changes from 3 to 2"
  """
  upg_match = re.search(
    r'upgradeDetails[^>]*>(.*?)</div>\s*</div>\s*</div>',
    page_html, re.DOTALL
  )
  if not upg_match:
    return None, None

  raw = upg_match.group(1)
  # Strip tags
  text = re.sub(r'<[^>]+>', ' ', raw)
  text = re.sub(r'\s+', ' ', text).strip()

  cost_match = re.search(r'Cost changes from (\d+) to (\d+)', text)
  if cost_match:
    return cost_match.group(1), cost_match.group(2)

  return None, None


# =========================================================================
# STS2 Gathering (from sts2.untapped.gg)
# =========================================================================

def _sts2_extract_card_slugs():
  """Extract all card slugs from STS2 per-character card pages.

  The main /en/cards page only loads ~90 slugs (JS lazy-loads the rest).
  Per-character pages have all slugs for that character in the HTML.
  """
  characters = ["ironclad", "silent", "defect", "necrobinder", "regent", "colorless"]
  seen = set()
  unique = []

  for char in characters:
    url = STS2_BASE + "/en/tier-list/cards/" + char
    try:
      resp = requests.get(url, timeout=15)
      slugs = re.findall(r'/en/cards/([a-z0-9_]+)', resp.text)
      for s in slugs:
        if s not in seen:
          seen.add(s)
          unique.append(s)
    except Exception as e:
      print("  Failed to fetch {0} cards: {1}".format(char, e))

  # Also check the main cards page for any we missed
  try:
    resp = requests.get(STS2_BASE + "/en/cards", timeout=15)
    for s in re.findall(r'/en/cards/([a-z0-9_]+)', resp.text):
      if s not in seen:
        seen.add(s)
        unique.append(s)
  except Exception:
    pass

  return unique

def _sts2_parse_card_page(slug):
  """Fetch and parse a single STS2 card page.

  Uses:
  - Meta tags for structured data (name, category, rarity, type, cost)
  - foreignObject elements for accurate base + upgrade descriptions
  - starCost SVG for Regent star costs
  - upgradeDetails for cost-only upgrades
  """
  url = STS2_BASE + "/en/cards/" + slug
  try:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
  except Exception as e:
    print("  Failed to fetch card {0}: {1}".format(slug, e))
    return None

  page_html = resp.text

  # --- Parse structured info from meta tags ---
  title_match = re.search(r'<title>([^<]+)</title>', page_html)
  if not title_match:
    return None
  title = title_match.group(1).strip()
  title = _unescape_html(title)
  title = re.sub(r'\s*[\u2013-]\s*Untapped\.gg\s*$', '', title)
  title = re.sub(r'\s*[\u2013-]\s*Slay the Spire 2\s*$', '', title)

  parts = title.split(" - ", 1)
  name = parts[0].strip()

  desc_match = re.search(
    r'<meta[^>]*name="description"[^>]*content="([^"]+)"', page_html
  )
  if not desc_match:
    desc_match = re.search(
      r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', page_html
    )

  cost = None
  rarity = None
  card_type = None
  category = None

  if desc_match:
    meta_desc = _unescape_html(desc_match.group(1))
    # Handle X-Cost cards: "X-Cost" in meta
    info_match = re.match(
      r'.+? is an? ([\dX]+)-Cost\s+(?:(Common|Uncommon|Rare|Basic)\s+)?'
      r'(Attack|Skill|Power|Status|Curse)\s+card in the (\w+) pool:\s*(.+)',
      meta_desc
    )
    if info_match:
      cost = info_match.group(1)
      rarity = info_match.group(2) or "Basic"
      card_type = info_match.group(3)
      category = info_match.group(4)

  # Fallback category/rarity from title parts
  if len(parts) > 1 and (not category or not rarity):
    info = parts[1].strip()
    tokens = info.split()
    if not category and tokens:
      category = tokens[0]
    for t in tokens:
      if t in ("Common", "Uncommon", "Rare", "Basic") and not rarity:
        rarity = t
      if t in ("Attack", "Skill", "Power", "Status", "Curse") and not card_type:
        card_type = t

  # --- Parse descriptions from foreignObject elements ---
  # First foreignObject = base card, second = upgraded card (in display:none div)
  foreign_objects = re.findall(
    r'<foreignObject[^>]*>(.*?)</foreignObject>',
    page_html, re.DOTALL
  )

  base_desc = ""
  upgrade_desc = ""

  if len(foreign_objects) >= 1:
    base_desc = _extract_description_from_html(foreign_objects[0])
  if len(foreign_objects) >= 2:
    upgrade_desc = _extract_description_from_html(foreign_objects[1])

  # --- Parse star cost from SVG (only from the main card, not OTHER CARDS) ---
  star_cost = None
  # The main card is before the "otherCards" or "upgradeDetails" sections
  # Find the first starCost SVG that appears before the OTHER CARDS section
  other_cards_pos = page_html.find('otherCards')
  search_region = page_html[:other_cards_pos] if other_cards_pos > 0 else page_html
  star_match = re.search(
    r'starCost[^>]*>.*?<text[^>]*>(\d+)</text>',
    search_region, re.DOTALL
  )
  if star_match:
    star_cost = star_match.group(1)

  # --- Compute upgrade diff ---
  description = base_desc
  if upgrade_desc and upgrade_desc != base_desc:
    description = _compute_upgrade_diff(base_desc, upgrade_desc)

  # --- Check for cost-only upgrades ---
  old_cost, new_cost = _extract_upgrade_cost(page_html)
  if old_cost and new_cost and old_cost != new_cost:
    cost = '{0}({1})'.format(old_cost, new_cost)

  # Unescape name
  name = _unescape_html(name)

  return Card(
    name=name,
    description=description,
    card_type=card_type or "Unknown",
    category=category or "Unknown",
    rarity=rarity or "Basic",
    cost=cost,
    game="STS2",
    star_cost=star_cost,
  )

def GatherSTS2Cards():
  print("\nGathering STS2 Cards...")
  slugs = _sts2_extract_card_slugs()
  print("Found {0} card slugs".format(len(slugs)))

  cards = []
  for i, slug in enumerate(slugs):
    card = _sts2_parse_card_page(slug)
    if card:
      print("Found STS2 card {0} ({1}/{2})".format(card.name, i + 1, len(slugs)))
      cards.append(card)
    if (i + 1) % 10 == 0:
      time.sleep(0.5)

  return cards

def _sts2_parse_rsc_list(url):
  """Parse a list page (relics/potions) from sts2.untapped.gg by extracting
  React Server Component (RSC) data from self.__next_f.push() script blocks.

  Returns list of (name, character, rarity, description) tuples.
  """
  resp = requests.get(url, timeout=15)
  resp.raise_for_status()
  text = resp.text

  # Collect all RSC push payloads and unescape them
  rsc_chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', text, re.DOTALL)
  rsc_text = "\n".join(rsc_chunks)
  rsc_text = rsc_text.replace('\\"', '"').replace('\\n', '\n')

  # Build a map of deferred ref IDs -> description text
  ref_map = {}
  desc_ref_pattern = re.compile(
    r'([0-9a-f]+):\["\$","span",null,\{"className":"\$undefined","children":'
    r'\[(\[.*?\])\]\}]',
    re.DOTALL
  )
  for m in desc_ref_pattern.finditer(rsc_text):
    ref_id = m.group(1)
    children_str = m.group(2)
    # Extract text from children, handling energy/star alt text
    text_parts = re.findall(r'"children":"([^"]*)"', children_str)
    # Also look for energy image alt texts
    alt_parts = re.findall(r'"alt":"([^"]*Energy)"', children_str)
    full_text = "".join(text_parts).strip()
    if full_text:
      ref_map[ref_id] = _unescape_html(full_text)

  # Find each item entry by its UPPER_CASE key in a div with __relic className
  item_pattern = re.compile(
    r'\["\$","div","([A-Z][A-Z0-9_\'!? ]*)",\{"className":"[^"]*__relic"'
  )

  items = []
  seen_keys = set()
  item_keys = [(m.group(1), m.start()) for m in item_pattern.finditer(rsc_text)]

  for idx, (key, start_pos) in enumerate(item_keys):
    if key in seen_keys:
      continue
    seen_keys.add(key)

    end_pos = item_keys[idx + 1][1] if idx + 1 < len(item_keys) else start_pos + 2000
    slice_text = rsc_text[start_pos:end_pos]

    h2_match = re.search(r'\["\$","h2",null,\{"children":"([^"]+)"\}]', slice_text)
    if not h2_match:
      continue
    item_name = _unescape_html(h2_match.group(1))

    detail_match = re.search(
      r'"children":"\xb7"\}]'
      r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]'
      r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]',
      slice_text, re.DOTALL
    )
    if not detail_match:
      # Try with escaped middot
      detail_match = re.search(
        r'"children":"\\u00b7"\}]'
        r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]'
        r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]',
        slice_text, re.DOTALL
      )
    character = detail_match.group(1) if detail_match else "Colorless"
    rarity = detail_match.group(2) if detail_match else "Unknown"

    desc_ref_match = re.search(r'description","children":"\$L([0-9a-f]+)"', slice_text)
    description = ""
    if desc_ref_match:
      ref_id = desc_ref_match.group(1)
      description = ref_map.get(ref_id, "")

    items.append((item_name, character, rarity, _unescape_html(description)))

  return items

def GatherSTS2Relics():
  print("\nGathering STS2 Relics...")
  items = _sts2_parse_rsc_list(STS2_BASE + "/en/relics")
  relics = []
  seen_names = set()
  for name, character, rarity, description in items:
    if name in seen_names:
      continue
    seen_names.add(name)
    category = character if character != "Colorless" else rarity
    if category in ("Common", "Uncommon", "Rare", "Starter", "Boss", "Event",
                     "Shop", "Ancient", "Basic", "Unknown"):
      category = character
    print("Found STS2 relic {0}".format(name))
    relics.append(Relic(name, description, category, game="STS2"))
  return relics

def GatherSTS2Potions():
  print("\nGathering STS2 Potions...")
  items = _sts2_parse_rsc_list(STS2_BASE + "/en/potions")
  potions = []
  seen_names = set()
  for name, character, rarity, description in items:
    if name in seen_names:
      continue
    seen_names.add(name)
    print("Found STS2 potion {0}".format(name))
    potions.append(Potion(name, description, rarity, game="STS2"))
  return potions


# =========================================================================
# Main
# =========================================================================

def main():
  # STS1 (via MediaWiki API)
  cards = GatherCards()
  relics = GatherRelics()
  potions = GatherPotions()
  events = GatherEvents()

  # STS2
  sts2_cards = GatherSTS2Cards()
  sts2_relics = GatherSTS2Relics()
  sts2_potions = GatherSTS2Potions()

  all_items = cards + relics + potions + events + sts2_cards + sts2_relics + sts2_potions

  print("\n=== Summary ===")
  print("STS1: {0} cards, {1} relics, {2} potions, {3} events".format(
    len(cards), len(relics), len(potions), len(events)))
  print("STS2: {0} cards, {1} relics, {2} potions".format(
    len(sts2_cards), len(sts2_relics), len(sts2_potions)))
  print("Total: {0} items".format(len(all_items)))

  open(os.path.join(os.path.dirname(__file__), "data.yml"), "w").write(
    yaml.dump([dict(vars(item)) for item in all_items], default_flow_style=False)
  )

if __name__ == "__main__":
  main()
