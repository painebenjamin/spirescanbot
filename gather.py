#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json
import os
import re
import time
import yaml
from bs4 import BeautifulSoup

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
    "Watcher": "Watcher_Cards_(BETA)",
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

def GatherEvents():
  events = []
  data = json.loads(open(os.path.join(os.path.dirname(__file__), "events.json"), "r").read())
  for act in data:
    for name in data[act]:
      print("Found STS1 event {0}".format(name))
      events.append(Event(name, data[act][name], act, game="STS1"))
  return events


# =========================================================================
# STS2 Gathering (from sts2.untapped.gg)
# =========================================================================

def _sts2_extract_card_slugs():
  """Extract all card slugs from the STS2 cards page HTML."""
  resp = requests.get(STS2_BASE + "/en/cards", timeout=15)
  slugs = re.findall(r'/en/cards/([a-z0-9_]+)', resp.text)
  seen = set()
  unique = []
  for s in slugs:
    if s not in seen:
      seen.add(s)
      unique.append(s)
  return unique

def _sts2_parse_card_page(slug):
  """Fetch and parse a single STS2 card page."""
  url = STS2_BASE + "/en/cards/" + slug
  try:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
  except Exception as e:
    print("  Failed to fetch card {0}: {1}".format(slug, e))
    return None

  soup = BeautifulSoup(resp.text, "html.parser")

  title_tag = soup.find("title")
  if not title_tag:
    return None

  title_text = title_tag.text.strip()
  title_text = re.sub(r'\s*[–-]\s*Untapped\.gg\s*$', '', title_text)

  parts = title_text.split(" - ", 1)
  if len(parts) != 2:
    print("  Unexpected title format for {0}: {1}".format(slug, title_text))
    return None

  name = parts[0].strip()
  text = soup.get_text("\n", strip=True)
  lines = [l.strip() for l in text.split("\n") if l.strip()]

  description = ""
  category = None
  rarity = None
  card_type = None
  cost = None

  for line in lines:
    if line.startswith("Character"):
      category = line.replace("Character", "").strip()
    elif line.startswith("Type") and card_type is None:
      card_type = line.replace("Type", "").strip()
    elif line.startswith("Cost") and cost is None:
      cost = line.replace("Cost", "").strip()
    elif line.startswith("Rarity") and rarity is None:
      rarity = line.replace("Rarity", "").strip()

  found_name = False
  for line in lines:
    if name.lower() in line.lower() and not found_name:
      found_name = True
      continue
    if found_name and line not in [name] and not line.startswith("Character") \
        and not line.startswith("Type") and not line.startswith("Cost") \
        and not line.startswith("Rarity") and len(line) > 5 \
        and "untapped" not in line.lower() \
        and "UPGRADED" not in line \
        and not line.startswith("##") \
        and "Jorbs" not in line \
        and "twitch.tv" not in line \
        and "youtube" not in line \
        and "OTHER CARDS" not in line \
        and "STS 1" not in line and "STS 2" not in line:
      description = line
      break

  if not description:
    description = parts[1].strip() if len(parts) > 1 else ""

  return Card(
    name=name,
    description=description,
    card_type=card_type or "Unknown",
    category=category or "Unknown",
    rarity=rarity or "Unknown",
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

def _sts2_parse_list_page(url):
  """Parse a list page (relics/potions) from sts2.untapped.gg.
  
  Returns list of (name, meta_line, description) tuples.
  Pattern: Name, then ·CategoryRarity, then description.
  """
  resp = requests.get(url, timeout=15)
  resp.raise_for_status()
  soup = BeautifulSoup(resp.text, "html.parser")
  text = soup.get_text("\n", strip=True)
  lines = [l.strip() for l in text.split("\n") if l.strip()]

  items = []
  i = 0
  while i < len(lines):
    if i + 2 < len(lines) and lines[i + 1].startswith("·"):
      name = lines[i]
      meta = lines[i + 1].lstrip("·").strip()
      description = lines[i + 2]
      items.append((name, meta, description))
      i += 3
    else:
      i += 1
  return items

def GatherSTS2Relics():
  print("\nGathering STS2 Relics...")
  items = _sts2_parse_list_page(STS2_BASE + "/en/relics")
  relics = []
  for name, meta, description in items:
    category = "Colorless"
    for char_name in ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent"]:
      if meta.startswith(char_name):
        category = char_name
        break
    print("Found STS2 relic {0}".format(name))
    relics.append(Relic(name, description, category, game="STS2"))
  return relics

def GatherSTS2Potions():
  print("\nGathering STS2 Potions...")
  items = _sts2_parse_list_page(STS2_BASE + "/en/potions")
  potions = []
  for name, meta, description in items:
    rarity = "Common"
    for r in ["Rare", "Uncommon", "Common"]:
      if r in meta:
        rarity = r
        break
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
