#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import unicode_literals, print_function

import requests
import json
import os
import sys
import re
import logging
import traceback
import time
import yaml

from pyjarowinkler import distance

from dundergifflin.reddit import RedditCrawler
from dundergifflin.config import Configuration
from dundergifflin.util import url_encode, flatten

configuration = Configuration(os.path.join(os.path.expanduser("~"), "dundergifflin", "spire_config"))
data_date = configuration.SPIRE_DATA_DATE
data = yaml.load(open(configuration.SPIRE_DATA, "r"))

word_finder = re.compile(r"\[\[.+?\]\]")

# --- URL helpers ---

STS1_WIKI = "http://slay-the-spire.wikia.com/wiki"
STS2_WIKI = "https://sts2.untapped.gg/en"

def wiki_url(title, game="STS1"):
  if game == "STS2":
    slug = re.sub(r'[^a-z0-9]+', '_', title.lower()).strip('_')
    return "{0}/cards/{1}".format(STS2_WIKI, slug)
  # STS1 and BOTH both link to the STS1 wiki
  return "{0}/{1}".format(STS1_WIKI, url_encode(title))

def escape(string):
  return re.sub(r"\W", "", string.replace("(BETA)", "").lower())

def levenshtein(a, b):
  if len(a) == 0:
    return len(b)
  if len(b) == 0:
    return len(a)

  matrix = [
    [
      0
      for i in range(len(a) + 1)
    ]
    for j in range(len(b) + 1)
  ]

  for i in range(len(b) + 1):
    matrix[i][0] = i

  for i in range(len(a) + 1):
    matrix[0][i] = i

  for i in range(1, len(b) + 1):
    for j in range(1, len(a) + 1):
      if b[i-1] == a[j-1]:
        matrix[i][j] = matrix[i-1][j-1]
      else:
        matrix[i][j] = min([
          matrix[i-1][j-1] + 1,
          matrix[i][j-1] + 1,
          matrix[i-1][j] + 1
        ])
  return matrix[len(b)][len(a)]

# --- Formatting ---

def game_tag(item_or_tag=None):
  """Return a superscript game tag using bold serif roman numerals.

  Accepts an item dict, a game string, or a pre-built tag string.
  """
  if isinstance(item_or_tag, dict):
    game = item_or_tag.get("game", "STS1")
  elif item_or_tag is not None:
    game = item_or_tag
  else:
    game = "STS1"

  if game == "BOTH":
    return "^(\U0001d408, \U0001d408\U0001d408)"  # ^(𝐈, 𝐈𝐈)
  elif game == "STS2":
    return "^\U0001d408\U0001d408"  # ^𝐈𝐈
  else:
    return "^\U0001d408"  # ^𝐈

def format_relic(relic_dict):
  game = relic_dict.get("game", "STS1")
  return """[{name:s}]({url:s}) {tag:s} {title:s}

{description:s}""".format(
    name = relic_dict["name"],
    url = wiki_url(relic_dict["name"], game),
    tag = game_tag(relic_dict),
    title = "{0} Relic".format(
      relic_dict["category"]
    ),
    description = replace_energy(
      highlight_key_words(
        relic_dict["description"]
      )
    )
  )

def format_potion(potion_dict):
  game = potion_dict.get("game", "STS1")
  return """[{name:s}]({url:s}) {tag:s} {title:s}

{description:s}""".format(
    name = potion_dict["name"],
    url = wiki_url(potion_dict["name"], game),
    tag = game_tag(potion_dict),
    title = "{0} Potion".format(
      potion_dict["rarity"]
    ),
    description = replace_energy(
      highlight_key_words(
        potion_dict["description"]
      )
    )
  )

def format_event(event_dict):
  game = event_dict.get("game", "STS1")
  return """[{name:s}]({url:s}) {tag:s} {title:s}

{description:s}""".format(
    name = event_dict["name"],
    url = wiki_url(event_dict["name"], game),
    tag = game_tag(event_dict),
    title = "Event - {0}".format(
      event_dict["act"]
    ),
    description = replace_energy(
      highlight_key_words(
        event_dict["description"]
      )
    )
  )

def format_card(card_dict):
  game = card_dict.get("game", "STS1")
  category = card_dict["category"]
  def format_card_title():
    if category in ["Curse", "Status"]:
      if card_dict["rarity"] == "Special":
        return "Special {0}".format(category)
      return category
    else:
      return "{category:s} {rarity:s} {type:s}".format(
        category = category,
        rarity = card_dict["rarity"] or "?",
        type = card_dict["card_type"] or "?"
      )

  # Format cost string, including star cost for Regent cards
  cost_str = "Unplayable"
  if card_dict["cost"] is not None:
    cost_str = "{0} Energy".format(card_dict["cost"])
  star_cost = card_dict.get("star_cost")
  if star_cost:
    star_display = "\u2b50" * int(star_cost)  # star emoji x N
    if card_dict["cost"] is not None:
      cost_str = "{0} Energy {1}".format(card_dict["cost"], star_display)
    else:
      cost_str = star_display

  return """[{name:s}]({url:s}) {tag:s} {title:s}

{cost:s} | {description:s}""".format(
    name = card_dict["name"],
    url = wiki_url(card_dict["name"], game),
    tag = game_tag(card_dict),
    title = format_card_title(),
    cost = cost_str,
    description = replace_energy(
      highlight_key_words(card_dict["description"])
    )
  )

def format_item(item):
  if item["type"] == "Relic":
    return format_relic(item)
  elif item["type"] == "Card":
    return format_card(item)
  elif item["type"] == "Potion":
    return format_potion(item)
  elif item["type"] == "Event":
    return format_event(item)

def highlight_key_words(string):
  KEYWORDS = [
    "artifact",
    "exhaust",
    "ethereal",
    "block",
    "vulnerable",
    "strength",
    "weak",
    "intangible",
    "exhausted",
    "wound",
    "wounds",
    "dazed",
    "poison",
    "shiv",
    "shivs",
    "dexterity",
    "frail",
    "unplayable",
    "channel",
    "evoke",
    "channeled",
    "evoked",
    "lightning",
    "frost",
    "dark",
    "void",
    "innate",
    "lock-on",
    "focus",
    "burn",
    "plasma",
    "scry",
    "wrath",
    "calm",
    "mantra",
    "divinity",
    "stance",
    "stances",
    "retain",
    "retained",
    # STS2 keywords
    "vigor",
    "enchant",
    "swift",
    "summon",
    "conjure",
    "decree",
    "soot",
    "sly",
    "forge",
    "soul",
    "souls",
    "debris",
    "fuel",
    "fatal",
    "eternal",
    "osty",
    "frost",
    "plating",
    "doom",
    "replay",
    "glass",
    "stars",
    "star",
  ]

  return " ".join([
    "**{0}**".format(word)
    if escape(word) in KEYWORDS
    else word
    for word in string.split()
  ])

def replace_energy(string):
  return string.replace("[G]", "[E]").replace("[W]", "[E]").replace("[R]", "◼").replace("[B]", "◼").replace("[E]", "[E]")

def find_by_title(title, minimum_likeness = 0.85):
  """Find all matching items across both games.
  
  Returns a list of matching items. If the same name appears in both
  STS1 and STS2, both are returned.
  """
  title_escaped = escape(title)

  # Score all items
  scored = [
    (
      item,
      distance.get_jaro_distance(escape(item["name"]), title_escaped, winkler = True, scaling = 0.1)
    )
    for item in data
  ]
  scored.sort(key = lambda item: item[1], reverse=True)

  if not scored or scored[0][1] < minimum_likeness:
    return []

  best_score = scored[0][1]
  best_name = escape(scored[0][0]["name"])

  # Collect all items with the same name (could be in both STS1 and STS2)
  results = []
  for item, score in scored:
    if escape(item["name"]) == best_name:
      results.append(item)
    elif score >= minimum_likeness and abs(score - best_score) < 0.01:
      # Also include very close matches (e.g. slightly different names)
      results.append(item)
    else:
      break

  return results

def search_text(text):
  return [
    escape(word)
    for word in word_finder.findall(text)
  ]

def _normalize_rarity(r):
  """Normalize rarity labels across games (STS1 'Starter' == STS2 'Basic')."""
  if r in ("Starter", "Basic"):
    return "Basic"
  return r

def _items_identical_for_display(a, b):
  """Check if two items from different games are identical for display.

  If so, we show them as a single entry with ^(𝐈, 𝐈𝐈) tag.
  Name comparison is case-insensitive; Starter==Basic for rarity.
  """
  if a["type"] != b["type"]:
    return False
  if a["name"].lower() != b["name"].lower():
    return False
  if a["type"] == "Card":
    return (a.get("description") == b.get("description") and
            a.get("card_type") == b.get("card_type") and
            a.get("category") == b.get("category") and
            _normalize_rarity(a.get("rarity")) == _normalize_rarity(b.get("rarity")) and
            a.get("cost") == b.get("cost") and
            a.get("star_cost") == b.get("star_cost"))
  elif a["type"] == "Relic":
    return (a.get("description") == b.get("description") and
            a.get("category") == b.get("category"))
  elif a["type"] == "Potion":
    return (a.get("description") == b.get("description") and
            _normalize_rarity(a.get("rarity")) == _normalize_rarity(b.get("rarity")))
  elif a["type"] == "Event":
    return (a.get("description") == b.get("description") and
            a.get("act") == b.get("act"))
  return False

def _deduplicate_results(items):
  """Deduplicate items that are identical across STS1 and STS2.

  Returns a list of items where identical cross-game pairs are merged
  into a single item with game="BOTH".
  """
  if len(items) < 2:
    return items

  sts1 = [i for i in items if i.get("game") == "STS1"]
  sts2 = [i for i in items if i.get("game") == "STS2"]
  other = [i for i in items if i.get("game") not in ("STS1", "STS2")]

  merged = []
  used_sts2 = set()

  for item1 in sts1:
    found_match = False
    for j, item2 in enumerate(sts2):
      if j not in used_sts2 and _items_identical_for_display(item1, item2):
        # Merge: use STS2 item data (more modern labels) but mark as BOTH
        combined = dict(item2)
        combined["game"] = "BOTH"
        merged.append(combined)
        used_sts2.add(j)
        found_match = True
        break
    if not found_match:
      merged.append(item1)

  for j, item2 in enumerate(sts2):
    if j not in used_sts2:
      merged.append(item2)

  merged.extend(other)
  return merged

def format_comment(text):
  search_results = [
    find_by_title(word)
    for word in search_text(text)
  ]

  result_lines = []
  for items in search_results:
    if not items:
      continue
    deduped = _deduplicate_results(items)
    for item in deduped:
      formatted = format_item(item)
      if formatted:
        result_lines.append(formatted.splitlines())

  return "\r\n".join([
    "\r\n".join(
      [
        "+ {0}".format(result[0])
      ] + [
        "    {0}".format(line)
        for line in result[1:]
      ]
    )
    for result in result_lines[:10]
  ])

def test(text):
  reply = format_comment(text)
  if reply:
    print(reply)

def main(conn = None, logger = None):
  if logger is None:
    logger = logging.getLogger("dunder-gifflin")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler(sys.stdout))

  def comment_function(comment):
    if conn is not None:
      conn.send("comment_evaluated")
    reply = format_comment(comment.body.replace("\\[", "[").replace("\\]", "]"))
    if reply:
      if conn is not None:
        conn.send("comment_replied")
      return """{0}

    ^Call ^me ^with ^up ^to ^10 ^([[ name ]].) ^Data ^accurate ^as ^of ^({1}.) ^[Questions?](https://www.reddit.com/message/compose/?to=ehmohteeoh&subject=SpireScan%20Inquiry)""".format(reply, data_date)

  try:
    with RedditCrawler(
      configuration.REDDIT_CLIENT_ID,
      configuration.REDDIT_CLIENT_SECRET,
      configuration.REDDIT_USERNAME,
      configuration.REDDIT_PASSWORD,
      configuration.REDDIT_USER_AGENT,
      comment_function = comment_function,
      crawled_subreddits = [subreddit for subreddit in configuration.REDDIT_CRAWLED_SUBREDDITS.split(",") if subreddit]
    ) as crawler:

      while True:
        time.sleep(60)

  except Exception as ex:
    logger.error("Received an exception during normal operation.\n\n{0}(): {1}\n\n{2}".format(
      type(ex).__name__,
      str(ex),
      traceback.format_exc(ex)
    ))

if __name__ == "__main__":
  #main(*sys.argv[1:])
  test(" ".join(sys.argv[1:]))
