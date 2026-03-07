#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json
import os
import re
import time
import yaml
from bs4 import BeautifulSoup

# --- STS1 sources ---
STS1_BASE = "https://slay-the-spire.fandom.com/wiki"

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
# STS1 Gathering (unchanged from original)
# =========================================================================

def Soup(url):
  return BeautifulSoup(requests.get(url).text, "html.parser")

def TableRows(url):
  soup = Soup(url)
  table = soup.find("table")
  for row in table.find_all("tr"):
    yield [cell.text.strip() for cell in row.find_all("td")]

def GatherPotions():
  potions = []
  for row in TableRows(STS1_BASE + "/Potions"):
    if len(row) == 4:
      _, name, rarity, description = row
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

def GatherRelics():
  relics = []
  for row in TableRows(STS1_BASE + "/Relics"):
    if len(row) == 4:
      _, name, category, description = row
      print("Found STS1 relic {0}".format(name))
      relics.append(Relic(name, description, category, game="STS1"))
  return relics

def GatherCards():
  card_urls = {
    "Ironclad": "/Ironclad_Cards",
    "Silent": "/Silent_Cards",
    "Defect": "/Defect_Cards",
    "Watcher": "/Watcher_Cards_(BETA)",
    "Colorless": "/Colorless_Cards",
    "Status": "/Status",
    "Curse": "/Curse"
  }
  
  cards = []
  
  for category in card_urls:
    print("Gathering STS1 {0}".format(category))
    for row in TableRows(STS1_BASE + card_urls[category]):
      if category == "status":
        if len(row) == 4:
          name, _, card_type, description = row
          print("Found STS1 card {0}".format(name))
          cards.append(Card(name, description, card_type, category, None, None, game="STS1"))

      elif category == "Curse":
        if len(row) == 4:
          name, _, description, _ = row
        elif len(row) == 3:
          name, _, description = row

        card_type = "Curse"
        print("Found STS1 card {0}".format(name))
        cards.append(Card(name, description, card_type, category, None, None, game="STS1"))

      elif len(row) == 6:
        name, _, rarity, card_type, energy, description = row
        print("Found STS1 card {0}".format(name))
        cards.append(Card(name, description, card_type, category, rarity, energy, game="STS1"))

  return cards


# =========================================================================
# STS2 Gathering (from sts2.untapped.gg)
# =========================================================================

def _sts2_fetch(path):
  """Fetch a page from sts2.untapped.gg and return BeautifulSoup."""
  url = STS2_BASE + path
  resp = requests.get(url, timeout=15)
  resp.raise_for_status()
  return BeautifulSoup(resp.text, "html.parser")

def _sts2_parse_section_list(soup):
  """Parse the untapped.gg list pages (relics, potions).

  These pages use a repeated pattern of:
    ## Name
    ·CategoryRarity
    Description text
  """
  items = []
  # The readable content has ## headings for each item
  text = soup.get_text("\n", strip=True)
  return text

def _sts2_extract_card_slugs():
  """Extract all card slugs from the STS2 cards page HTML."""
  resp = requests.get(STS2_BASE + "/en/cards", timeout=15)
  # Find all /en/cards/<slug> links in the raw HTML
  slugs = re.findall(r'/en/cards/([a-z0-9_]+)', resp.text)
  # Deduplicate while preserving order
  seen = set()
  unique = []
  for s in slugs:
    if s not in seen:
      seen.add(s)
      unique.append(s)
  return unique

def _sts2_parse_card_page(slug):
  """Fetch and parse a single STS2 card page.
  
  Returns a Card object or None if parsing fails.
  Page structure:
    <title>Name - Category Rarity Type</title>
    Body: description, then Character/Type/Cost/Rarity fields
  """
  url = STS2_BASE + "/en/cards/" + slug
  try:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
  except Exception as e:
    print("  Failed to fetch card {0}: {1}".format(slug, e))
    return None

  soup = BeautifulSoup(resp.text, "html.parser")
  
  # Parse from <title>: "Name - Category Rarity Type"
  title_tag = soup.find("title")
  if not title_tag:
    return None

  title_text = title_tag.text.strip()
  # Remove trailing " – Untapped.gg" or similar
  title_text = re.sub(r'\s*[–-]\s*Untapped\.gg\s*$', '', title_text)
  
  # Split: "Anger - Ironclad Common Attack"
  parts = title_text.split(" - ", 1)
  if len(parts) != 2:
    print("  Unexpected title format for {0}: {1}".format(slug, title_text))
    return None

  name = parts[0].strip()
  meta = parts[1].strip()  # e.g. "Ironclad Common Attack"

  # Extract readable text for description and metadata
  text = soup.get_text("\n", strip=True)
  lines = [l.strip() for l in text.split("\n") if l.strip()]

  # Find description — it's the first substantial line of text content
  # Look for lines before the metadata fields
  description = ""
  category = None
  rarity = None
  card_type = None
  cost = None

  for line in lines:
    if line.startswith("Character"):
      category = line.replace("Character", "").strip()
    elif line.startswith("Type"):
      card_type = line.replace("Type", "").strip()
    elif line.startswith("Cost"):
      cost = line.replace("Cost", "").strip()
    elif line.startswith("Rarity"):
      rarity = line.replace("Rarity", "").strip()

  # Description is typically the first content line that isn't the title or nav
  # Find it by looking for text after the card name but before metadata
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
    # Fallback: use meta string
    description = meta

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
  """Gather all STS2 cards by fetching individual card pages."""
  print("\nGathering STS2 Cards...")
  slugs = _sts2_extract_card_slugs()
  print("Found {0} card slugs".format(len(slugs)))

  cards = []
  for i, slug in enumerate(slugs):
    card = _sts2_parse_card_page(slug)
    if card:
      print("Found STS2 card {0} ({1}/{2})".format(card.name, i + 1, len(slugs)))
      cards.append(card)
    # Be polite
    if (i + 1) % 10 == 0:
      time.sleep(0.5)

  return cards

def GatherSTS2Relics():
  """Gather STS2 relics from the relics listing page."""
  print("\nGathering STS2 Relics...")
  resp = requests.get(STS2_BASE + "/en/relics", timeout=15)
  resp.raise_for_status()
  soup = BeautifulSoup(resp.text, "html.parser")

  text = soup.get_text("\n", strip=True)
  lines = [l.strip() for l in text.split("\n") if l.strip()]

  relics = []
  i = 0
  while i < len(lines):
    line = lines[i]
    # Relic entries follow the pattern from the markdown extraction:
    # Name line, then ·CategoryRarity line, then description
    if i + 2 < len(lines) and lines[i + 1].startswith("·"):
      name = line
      meta = lines[i + 1].lstrip("·").strip()
      description = lines[i + 2] if i + 2 < len(lines) else ""

      # Parse category from meta: e.g. "ColorlessUncommon", "IroncladRare"
      # Category is character name, rarity is the rest
      category = "Colorless"
      for char_name in ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent", "Colorless"]:
        if meta.startswith(char_name):
          category = char_name
          break

      print("Found STS2 relic {0}".format(name))
      relics.append(Relic(name, description, category, game="STS2"))
      i += 3
    else:
      i += 1

  return relics

def GatherSTS2Potions():
  """Gather STS2 potions from the potions listing page."""
  print("\nGathering STS2 Potions...")
  resp = requests.get(STS2_BASE + "/en/potions", timeout=15)
  resp.raise_for_status()
  soup = BeautifulSoup(resp.text, "html.parser")

  text = soup.get_text("\n", strip=True)
  lines = [l.strip() for l in text.split("\n") if l.strip()]

  potions = []
  i = 0
  while i < len(lines):
    line = lines[i]
    if i + 2 < len(lines) and lines[i + 1].startswith("·"):
      name = line
      meta = lines[i + 1].lstrip("·").strip()
      description = lines[i + 2] if i + 2 < len(lines) else ""

      # Parse rarity from meta: e.g. "ColorlessCommon", "IroncladUncommon"
      rarity = "Common"
      for r in ["Rare", "Uncommon", "Common"]:
        if r in meta:
          rarity = r
          break

      print("Found STS2 potion {0}".format(name))
      potions.append(Potion(name, description, rarity, game="STS2"))
      i += 3
    else:
      i += 1

  return potions


# =========================================================================
# Main
# =========================================================================

def main():
  # STS1
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
