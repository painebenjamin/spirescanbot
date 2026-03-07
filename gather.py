#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json
import os
import re
import time
import yaml
# No longer need BeautifulSoup - using meta tags + RSC parsing

# --- STS1 sources (MediaWiki API — Cloudflare blocks HTML scraping now) ---
STS1_API = "https://slay-the-spire.fandom.com/api.php"

# --- STS2 sources ---
STS2_BASE = "https://sts2.untapped.gg"

# --- Data classes ---

class SpireObject(object):
  def __repr__(self):
    return str(dict(vars(self)))

class Card(SpireObject):
  def __init__(self, name, description, card_type, category, rarity, cost, game="STS1"):
    self.type = "Card"
    self.game = game
    self.name = name.replace("\n", " ").strip()
    self.description = description.replace("\n", " ").strip()
    self.card_type = card_type
    self.category = category
    self.rarity = rarity
    self.cost = cost

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
  # Remove {{KW|...}} and {{C|...}} templates → just the first arg
  text = re.sub(r'\{\{KW\|([^}|]+)(?:\|[^}]*)?\}\}', r'\1', text)
  text = re.sub(r'\{\{C\|([^}|]+)(?:\|[^}]*)?\}\}', r'\1', text)
  # Remove other templates
  text = re.sub(r'\{\{[^}]*\}\}', '', text)
  # Remove [[File:...]] 
  text = re.sub(r'\[\[File:[^\]]*\]\]', '', text)
  # Convert [[Page|Display]] → Display, [[Page]] → Page
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
  # Convert name to wiki page title
  page_title = event_name.replace(" ", "_")
  try:
    wikitext = _get_wikitext(page_title)
  except Exception:
    # Some events have "(Event)" suffix
    try:
      wikitext = _get_wikitext(page_title + "_(Event)")
    except Exception:
      return ""

  # Find first real text paragraph (skip images, templates, sections, categories)
  lines = wikitext.split("\n")
  for line in lines:
    line = line.strip()
    # Skip empty, images, templates, sections, categories, TOC
    if not line or line.startswith("[[File:") or line.startswith("[[Category"):
      continue
    if line.startswith("{") or line.startswith("=") or line.startswith("__"):
      continue
    if line.startswith("*") or line.startswith("#") or line.startswith("|") or line.startswith("!"):
      continue
    # This looks like a description line
    cleaned = _clean_wikitext(line)
    if len(cleaned) > 20:
      return cleaned

  return ""

def GatherEvents():
  """Gather STS1 events from the Events wiki page."""
  events = []
  print("Gathering STS1 Events")

  # First try the events.json fallback if it exists
  events_json = os.path.join(os.path.dirname(__file__), "events.json")
  if os.path.exists(events_json):
    data = json.loads(open(events_json, "r").read())
    for act in data:
      for name in data[act]:
        print("Found STS1 event {0} (from events.json)".format(name))
        events.append(Event(name, data[act][name], act, game="STS1"))
    if events:
      return events

  # Fallback: scrape from wiki API
  try:
    wikitext = _get_wikitext("Events")
  except Exception as e:
    print("  Failed to fetch Events: {0}".format(e))
    return events

  # Split by section divs
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

    # Extract event names from {{ficon|Icon.png|Name|100px}} templates
    names = re.findall(r'\{\{ficon\|[^|]+\|([^|]+)\|', section_text)
    # Also from [[Page (Event)|Display Name]] links
    link_names = re.findall(r'\[\[([^|\]]+?)(?:\s*\(Event\))?\|([^\]]+)\]\]', section_text)
    for page, display in link_names:
      if display not in names and "Act" not in display and "File:" not in display:
        names.append(display)

    for name in names:
      # Skip junk entries (fragments from wikitext parsing)
      if len(name) < 3 or "|" in name or "px" in name or name in ["first", "three", "two"]:
        continue
      print("Found STS1 event {0} ({1})".format(name, act_name))
      description = _get_event_description(name)
      events.append(Event(name, description, act_name, game="STS1"))
      time.sleep(0.2)  # Be polite to the API

  return events


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
  """Fetch and parse a single STS2 card page using meta tags.

  Meta description format:
    "Name is a Cost-Cost Rarity Type card in the Character pool: Description."
  Title format:
    "Name - Character Rarity Type - Slay the Spire 2 – Untapped.gg"
  """
  url = STS2_BASE + "/en/cards/" + slug
  try:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
  except Exception as e:
    print("  Failed to fetch card {0}: {1}".format(slug, e))
    return None

  text = resp.text

  # Parse title: "Name - Character Rarity Type - Slay the Spire 2 – Untapped.gg"
  title_match = re.search(r'<title>([^<]+)</title>', text)
  if not title_match:
    return None
  title = title_match.group(1).strip()
  title = re.sub(r'\s*[–-]\s*Untapped\.gg\s*$', '', title)
  title = re.sub(r'\s*[–-]\s*Slay the Spire 2\s*$', '', title)

  # Split: "Name - Character Rarity Type"
  parts = title.split(" - ", 1)
  name = parts[0].strip()

  # Parse meta description: structured card info
  desc_match = re.search(
    r'<meta[^>]*name="description"[^>]*content="([^"]+)"', text
  )
  if not desc_match:
    desc_match = re.search(
      r'<meta[^>]*property="og:description"[^>]*content="([^"]+)"', text
    )

  description = ""
  cost = None
  rarity = None
  card_type = None
  category = None

  if desc_match:
    meta_desc = desc_match.group(1)
    # Pattern: "Name is a 2-Cost Rare Attack card in the Ironclad pool: Deal 8 damage."
    # Or: "Name is a 0-Cost Attack card in the Ironclad pool: ..." (no rarity)
    info_match = re.match(
      r'.+? is a (\d+)-Cost\s+(?:(Common|Uncommon|Rare)\s+)?'
      r'(Attack|Skill|Power|Status|Curse)\s+card in the (\w+) pool:\s*(.+)',
      meta_desc
    )
    if info_match:
      cost = info_match.group(1)
      rarity = info_match.group(2) or "Basic"
      card_type = info_match.group(3)
      category = info_match.group(4)
      description = info_match.group(5).strip().rstrip('.')
    else:
      # Fallback: grab everything after the colon
      colon_idx = meta_desc.find(": ")
      if colon_idx > 0:
        description = meta_desc[colon_idx + 2:].strip()

  # Fallback category/rarity from title parts
  if len(parts) > 1 and (not category or not rarity):
    info = parts[1].strip()
    tokens = info.split()
    if not category and tokens:
      category = tokens[0]
    for t in tokens:
      if t in ("Common", "Uncommon", "Rare") and not rarity:
        rarity = t
      if t in ("Attack", "Skill", "Power", "Status", "Curse") and not card_type:
        card_type = t

  return Card(
    name=name,
    description=description,
    card_type=card_type or "Unknown",
    category=category or "Unknown",
    rarity=rarity or "Basic",
    cost=cost,
    game="STS2",
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

  # Build a map of deferred ref IDs → description text
  # Pattern: hex_id:["$","span",null,{"className":"$undefined","children":[[...spans...]]}]
  ref_map = {}
  desc_ref_pattern = re.compile(
    r'([0-9a-f]+):\["\$","span",null,\{"className":"\$undefined","children":'
    r'\[(\[.*?\])\]\}]',
    re.DOTALL
  )
  for m in desc_ref_pattern.finditer(rsc_text):
    ref_id = m.group(1)
    children_str = m.group(2)
    text_parts = re.findall(r'"children":"([^"]*)"', children_str)
    full_text = "".join(text_parts).strip()
    if full_text:
      ref_map[ref_id] = full_text

  # Find each item entry by its UPPER_CASE key in a div with __relic className
  # The CSS module hash varies per page, so match any hash pattern
  item_pattern = re.compile(
    r'\["\$","div","([A-Z][A-Z0-9_\'!? ]*)",\{"className":"[^"]*__relic"'
  )

  items = []
  seen_keys = set()
  item_keys = [(m.group(1), m.start()) for m in item_pattern.finditer(rsc_text)]

  for idx, (key, start_pos) in enumerate(item_keys):
    # Skip duplicates (page may render items twice)
    if key in seen_keys:
      continue
    seen_keys.add(key)

    # Get the text slice for this item (until next item or +2000 chars)
    end_pos = item_keys[idx + 1][1] if idx + 1 < len(item_keys) else start_pos + 2000
    slice_text = rsc_text[start_pos:end_pos]

    # Extract name from h2
    h2_match = re.search(r'\["\$","h2",null,\{"children":"([^"]+)"\}]', slice_text)
    if not h2_match:
      continue
    name = h2_match.group(1)

    # Extract character and rarity from detail spans (after spacer ·)
    detail_match = re.search(
      r'"children":"·"\}]'
      r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]'
      r'.*?\["\$","span",null,\{"children":"([^"]+)"\}]',
      slice_text, re.DOTALL
    )
    character = detail_match.group(1) if detail_match else "Colorless"
    rarity = detail_match.group(2) if detail_match else "Unknown"

    # Extract description via deferred ref: "children":"$L<hex>"
    desc_ref_match = re.search(r'description","children":"\$L([0-9a-f]+)"', slice_text)
    description = ""
    if desc_ref_match:
      ref_id = desc_ref_match.group(1)
      description = ref_map.get(ref_id, "")

    items.append((name, character, rarity, description))

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
    # Character from the RSC data is the class affinity
    category = character if character != "Colorless" else rarity
    # If rarity is actually a class name, fix up
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
