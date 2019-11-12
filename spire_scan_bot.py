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

def wiki_url(title):
  return "http://slay-the-spire.wikia.com/wiki/{0}".format(url_encode(title))

def format_relic(relic_dict):
  return """[{name:s}]({url:s}) {title:s}

{description:s}""".format(
    name = relic_dict["name"],
    url = wiki_url(relic_dict["name"]),
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
  return """[{name:s}]({url:s}) {title:s}

{description:s}""".format(
    name = potion_dict["name"],
    url = wiki_url(potion_dict["name"]),
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
  return """[{name:s}]({url:s}) {title:s}

{description:s}""".format(
    name = event_dict["name"],
    url = wiki_url(event_dict["name"]),
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
  category = card_dict["category"]
  def format_card_title():
    if category in ["Curse", "Status"]:
      if card_dict["rarity"] == "Special":
        return "Special {0}".format(category)
      return category
    else:
      return "{category:s} {rarity:s} {type:s}".format(
        category = category,
        rarity = card_dict["rarity"],
        type = card_dict["card_type"]
      )
  return """[{name:s}]({url:s}) {title:s}

{cost:s} | {description:s}""".format(
    name = card_dict["name"],
    url = wiki_url(card_dict["name"]),
    title = format_card_title(),
    cost = "Unplayable" if card_dict["cost"] is None else "{0} Energy".format(card_dict["cost"]),
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
    "retained"
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
  title = escape(title)
  items = [
    (
      item,
      distance.get_jaro_distance(escape(item["name"]), title, winkler = True, scaling = 0.1)
    )
    for item in data
  ]
  items.sort(key = lambda item: item[1])
  items.reverse()
  if minimum_likeness is not None:
    if items[0][1] < minimum_likeness:
      return None
  return items[0][0]

def search_text(text):
  return [
    escape(word)
    for word in word_finder.findall(text)
  ]

def format_comment(text):
  results = [
    find_by_title(word)
    for word in search_text(text)
  ]
  
  result_lines = [
    format_item(result).splitlines()
    for result in results
    if result is not None
  ]

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

    ^Call ^me ^with ^up ^to ^10 ^([[ name ]].) ^Data ^accurate ^as ^of ^({1}.) ^Some ^legacy ^cards ^with ^new ^beta ^effects ^might ^not ^be ^shown ^correctly. ^[Questions?](https://www.reddit.com/message/compose/?to=ehmohteeoh&subject=SpireScan%20Inquiry)""".format(reply, data_date)

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
