#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import requests
import json
import os
import yaml
from bs4 import BeautifulSoup

BASE = "https://slay-the-spire.fandom.com/wiki"

class SpireObject(object):
  def __repr__(self):
    return str(dict(vars(self)))

class Card(SpireObject):
  def __init__(self, name, description, card_type, category, rarity, cost):
    self.type = "Card"
    self.name = name.replace("\n", " ")
    self.description = description.replace("\n", " ")
    self.card_type = card_type
    self.category = category
    self.rarity = rarity
    self.cost = cost

class Relic(SpireObject):
  def __init__(self, name, description, category):
    self.type = "Relic"
    self.name = name.replace("\n", " ")
    self.description = description.replace("\n", " ")
    self.category = category

class Potion(SpireObject):
  def __init__(self, name, description, rarity):
    self.type = "Potion"
    self.name = name.replace("\n", " ")
    self.description = description.replace("\n", " ")
    self.rarity = rarity

class Event(SpireObject):
  def __init__(self, name, description, act):
    self.type = "Event"
    self.name = name
    self.description = description
    self.act = act

def Soup(url):
  return BeautifulSoup(requests.get(url).text, "html.parser")

def TableRows(url):
  soup = Soup(url)
  table = soup.find("table")
  for row in table.find_all("tr"):
    yield [cell.text.strip() for cell in row.find_all("td")]

def GatherPotions():
  potions = []
  for row in TableRows(BASE + "/Potions"):
    if len(row) == 4:
      _, name, rarity, description = row
      print("Found potion {0}".format(name))
      potions.append(Potion(name, description, rarity))
  return potions

def GatherEvents():
  events = []
  data = json.loads(open(os.path.join(os.path.dirname(__file__), "events.json"), "r").read())
  for act in data:
    for name in data[act]:
      print("Found event {0}".format(name))
      events.append(Event(name, data[act][name], act))
  return events

def GatherRelics():
  relics = []
  for row in TableRows(BASE + "/Relics"):
    if len(row) == 4:
      _, name, category, description = row
      print("Found relic {0}".format(name))
      relics.append(Relic(name, description, category))
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
    print("Gathering {0}".format(category))
    for row in TableRows(BASE + card_urls[category]):
      if category == "status":
        if len(row) == 4:
          name, _, card_type, description = row
          print("Found card {0}".format(name))
          cards.append(Card(name, description, card_type, category, None, None))

      elif category == "Curse":
        if len(row) == 4:
          name, _, description, _ = row
        elif len(row) == 3:
          name, _, description = row

        card_type = "Curse"
        print("Found card {0}".format(name))
        cards.append(Card(name, description, card_type, category, None, None))

      elif len(row) == 6:
        name, _, rarity, card_type, energy, description = row
        print("Found card {0}".format(name))
        cards.append(Card(name, description, card_type, category, rarity, energy))

  return cards

def main():
  cards = GatherCards()
  relics = GatherRelics()
  potions = GatherPotions()
  events = GatherEvents()
  
  open(os.path.join(os.path.dirname(__file__), "data.yml"), "w").write(yaml.dump([dict(vars(item)) for item in cards + relics + potions + events], default_flow_style = False))

if __name__ == "__main__":
  main()
