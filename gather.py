#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gather Slay the Spire 1 & 2 data from slaythespire.wiki.gg.

Both games' content is stored as Lua return-table modules accessible through
MediaWiki's parse API. We fetch the wikitext for each module, parse the table,
and render each entry's text into the upgrade-diff display style used by the
Reddit bot (e.g. "Deal 6(9) damage.").
"""
import requests
import os
import re
import time
import yaml
import html as html_module
from difflib import SequenceMatcher

WIKI_API = "https://slaythespire.wiki.gg/api.php"


# =========================================================================
# Data classes
# =========================================================================

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
# MediaWiki fetch
# =========================================================================

_HEADERS = {"User-Agent": "SpireScanBot/2.0 (+https://github.com/ehmohteeoh/spirescanbot)"}

def _get_module_wikitext(page, max_retries=3):
  """Fetch the raw wikitext for a Module: page via the MediaWiki parse API."""
  delay = 1.0
  for attempt in range(max_retries):
    resp = requests.get(WIKI_API, params={
      "action": "parse",
      "page": page,
      "prop": "wikitext",
      "format": "json",
    }, headers=_HEADERS, timeout=20)
    if resp.status_code == 429:
      time.sleep(delay)
      delay *= 2
      continue
    resp.raise_for_status()
    time.sleep(0.3)
    return resp.json()["parse"]["wikitext"]["*"]
  resp.raise_for_status()
  return resp.json()["parse"]["wikitext"]["*"]


# =========================================================================
# Lua return-table parser
# =========================================================================

_LUA_STRING_ESCAPES = {
  "n": "\n", "t": "\t", "r": "\r", '"': '"', "'": "'", "\\": "\\",
}

def _strip_lua_comments(text):
  """Remove Lua line comments (-- ...) but only outside string literals."""
  out = []
  i = 0
  n = len(text)
  while i < n:
    ch = text[i]
    if ch == '"':
      j = i + 1
      while j < n and text[j] != '"':
        if text[j] == '\\' and j + 1 < n:
          j += 2
        else:
          j += 1
      out.append(text[i:j + 1])
      i = j + 1
    elif ch == '-' and i + 1 < n and text[i + 1] == '-':
      while i < n and text[i] != '\n':
        i += 1
    else:
      out.append(ch)
      i += 1
  return "".join(out)


def _read_lua_string(text, i):
  """Read a Lua double-quoted string starting at text[i] == '"'.

  Returns (decoded_value, index_after_closing_quote).
  """
  assert text[i] == '"'
  i += 1
  out = []
  n = len(text)
  while i < n:
    ch = text[i]
    if ch == '"':
      return "".join(out), i + 1
    if ch == '\\' and i + 1 < n:
      nxt = text[i + 1]
      if nxt in _LUA_STRING_ESCAPES:
        out.append(_LUA_STRING_ESCAPES[nxt])
        i += 2
        continue
      if nxt == 'u' and i + 2 < n and text[i + 2] == '{':
        end = text.find('}', i + 3)
        if end != -1:
          try:
            out.append(chr(int(text[i + 3:end], 16)))
            i = end + 1
            continue
          except ValueError:
            pass
      out.append(nxt)
      i += 2
    else:
      out.append(ch)
      i += 1
  return "".join(out), i


def _read_lua_value(text, i):
  """Read a Lua value (string, number, bool, nil, or { ... }) at text[i].

  Returns (value, index_after_value). For tables we capture the raw inner
  text, since we never need to deeply traverse Traits/Requirement/etc.
  """
  n = len(text)
  while i < n and text[i] in " \t\r\n":
    i += 1
  if i >= n:
    return None, i

  ch = text[i]
  if ch == '"':
    return _read_lua_string(text, i)
  if ch == '{':
    depth = 1
    j = i + 1
    while j < n and depth > 0:
      cj = text[j]
      if cj == '"':
        _, j = _read_lua_string(text, j)
        continue
      if cj == '{':
        depth += 1
      elif cj == '}':
        depth -= 1
      j += 1
    inner = text[i + 1:j - 1]
    return {"__raw__": inner}, j
  m = re.match(r'(-?\d+(?:\.\d+)?)', text[i:])
  if m:
    raw = m.group(1)
    try:
      val = int(raw)
    except ValueError:
      val = float(raw)
    return val, i + len(raw)
  m = re.match(r'(true|false|nil)\b', text[i:])
  if m:
    raw = m.group(1)
    val = {"true": True, "false": False, "nil": None}[raw]
    return val, i + len(raw)
  return None, i + 1


def _parse_lua_object_body(body):
  """Parse the inner body of a Lua table literal into a dict of fields."""
  result = {}
  i = 0
  n = len(body)
  while i < n:
    while i < n and body[i] in " \t\r\n,;":
      i += 1
    if i >= n:
      break

    if body[i] == '[':
      end = body.find(']', i)
      if end == -1:
        break
      key_expr = body[i + 1:end].strip()
      if key_expr.startswith('"') and key_expr.endswith('"'):
        key, _ = _read_lua_string(key_expr, 0)
      else:
        key = key_expr
      i = end + 1
    else:
      m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)', body[i:])
      if not m:
        i += 1
        continue
      key = m.group(1)
      i += len(key)

    while i < n and body[i] in " \t\r\n":
      i += 1
    if i >= n or body[i] != '=':
      continue
    i += 1
    value, i = _read_lua_value(body, i)
    result[key] = value

  return result


def _parse_lua_table(text):
  """Parse a Lua return-table module into a dict of {name: {field: value}}.

  Top-level entries are expected to be of the form `["Name"] = { ... }`.
  Returns an ordered dict-like list-preserving dict.
  """
  text = _strip_lua_comments(text)
  m = re.search(r'\breturn\s*\{', text)
  if not m:
    return {}
  start = m.end()
  depth = 1
  i = start
  n = len(text)
  while i < n and depth > 0:
    ch = text[i]
    if ch == '"':
      _, i = _read_lua_string(text, i)
      continue
    if ch == '{':
      depth += 1
    elif ch == '}':
      depth -= 1
      if depth == 0:
        break
    i += 1
  body = text[start:i]

  entries = {}
  j = 0
  m_len = len(body)
  while j < m_len:
    while j < m_len and body[j] in " \t\r\n,;":
      j += 1
    if j >= m_len:
      break
    if body[j] != '[':
      j += 1
      continue
    end = body.find(']', j)
    if end == -1:
      break
    key_expr = body[j + 1:end].strip()
    if key_expr.startswith('"'):
      key, _ = _read_lua_string(key_expr, 0)
    else:
      key = key_expr
    k = end + 1
    while k < m_len and body[k] in " \t\r\n":
      k += 1
    if k >= m_len or body[k] != '=':
      j = end + 1
      continue
    k += 1
    value, k = _read_lua_value(body, k)
    if isinstance(value, dict) and "__raw__" in value:
      entries[key] = _parse_lua_object_body(value["__raw__"])
    else:
      entries[key] = value
    j = k

  return entries


# =========================================================================
# Wiki text -> display text rendering
# =========================================================================

def _strip_templates(text):
  """Replace MediaWiki templates with reasonable display text.

  - {{C|X}} / {{C|X|Y}} / {{C|X|Y|2}} -> last non-empty (and non-numeric) arg
  - {{R|Name||2}}                     -> Name
  - {{KW|kw|Display|2}}               -> Display (or kw if no display)
  - {{QueryLink|page|filter|Display}} -> Display
  - any other {{...}}                 -> stripped
  """
  def _resolve(args):
    """Return the most readable arg from a template's pipe-split args."""
    cleaned = [a.strip() for a in args]
    while cleaned and (not cleaned[-1] or cleaned[-1].isdigit()):
      cleaned.pop()
    return cleaned[-1] if cleaned else ""

  def _replace(match):
    inner = match.group(1)
    parts = inner.split('|')
    name = parts[0].strip()
    args = parts[1:]
    if name in ("C", "R", "KW"):
      return _resolve(args) or name
    if name == "QueryLink":
      return _resolve(args)
    return ""

  for _ in range(5):
    new_text = re.sub(r'\{\{([^{}]*)\}\}', _replace, text)
    if new_text == text:
      break
    text = new_text
  return text


def _replace_keyword_dollar(text):
  """Replace $Keyword references with plain text.

  Keywords are TitleCase words, optionally a second TitleCase word
  (e.g. $Lock On, $Plated Armor).
  """
  return re.sub(
    r'\$([A-Z][A-Za-z]*)((?:\s+[A-Z][A-Za-z]*)?)',
    lambda m: m.group(1) + m.group(2),
    text,
  )


# All character/colorless energy icon codes used across both games.
_ENERGY_TOKEN_RE = re.compile(
  r'@(RE|GE|BE|PE|IE|SE|DE|NE|CE|RegE)'
)
_STAR_TOKEN_RE = re.compile(r'@ST')


def _collapse_energy_and_stars(text):
  """Convert sequences of energy/star icons into "N Energy" / "N Stars".

  Examples:
    "Gain @RE @RE."          -> "Gain 2 Energy."
    "Costs 1 less @BE for"   -> "Costs 1 less Energy for"   (single = 1 Energy collapsed)
    "Gain @ST@ST@ST."        -> "Gain 3 Stars."
  """
  marker_e = '\x01E\x01'
  marker_s = '\x01S\x01'
  text = _ENERGY_TOKEN_RE.sub(marker_e, text)
  text = _STAR_TOKEN_RE.sub(marker_s, text)

  def _repl_numbered_energy(m):
    return m.group(1) + ' Energy'
  text = re.sub(r'(\d)\s*' + marker_e + r'(?:\s*' + marker_e + r')*',
                _repl_numbered_energy, text)

  def _repl_energy(m):
    n = m.group(0).count(marker_e)
    return ('Energy' if n == 1 else '{0} Energy'.format(n))
  text = re.sub(marker_e + r'(?:\s*' + marker_e + r')*', _repl_energy, text)

  def _repl_numbered_stars(m):
    return m.group(1) + ' Stars'
  text = re.sub(r'(\d)\s*' + marker_s + r'(?:\s*' + marker_s + r')*',
                _repl_numbered_stars, text)

  def _repl_stars(m):
    n = m.group(0).count(marker_s)
    return ('1 Star' if n == 1 else '{0} Stars'.format(n))
  text = re.sub(marker_s + r'(?:\s*' + marker_s + r')*', _repl_stars, text)

  # Remaining @-prefixed icon tokens (e.g. @Gold) -> the bare word.
  text = re.sub(r'@([A-Z][A-Za-z]*)', r'\1', text)

  return text


def _expand_upgrade_brackets(text, opener, closer, separator):
  """Expand inline upgrade brackets into base/upgrade text pairs.

  STS1 cards / STS2 cards use [base|upgrade].
  STS1 potions use <base:upgrade>.

  We walk left-to-right collecting two parallel strings (base, upgraded).
  """
  base = []
  upg = []
  i = 0
  n = len(text)
  while i < n:
    ch = text[i]
    if ch == opener:
      end = text.find(closer, i + 1)
      if end == -1:
        base.append(ch)
        upg.append(ch)
        i += 1
        continue
      inside = text[i + 1:end]
      sep_pos = inside.find(separator)
      if sep_pos == -1:
        base.append(opener + inside + closer)
        upg.append(opener + inside + closer)
      else:
        b = inside[:sep_pos]
        u = inside[sep_pos + 1:]
        # When one side is empty, add a separating space so it doesn't
        # collide with adjacent words from outside the bracket
        # (e.g. "add<:two copies>" should expand to "add" / "add two copies").
        if not b and u:
          u = ' ' + u
        if not u and b:
          b = ' ' + b
        base.append(b)
        upg.append(u)
      i = end + 1
    else:
      base.append(ch)
      upg.append(ch)
      i += 1
  return "".join(base), "".join(upg)


def _normalize_whitespace(text):
  text = html_module.unescape(text)
  text = re.sub(r'<br\s*/?>', ' ', text, flags=re.IGNORECASE)
  text = re.sub(r'<[^>]+>', ' ', text)
  text = re.sub(r'\s+([.,;:!?])', r'\1', text)
  text = re.sub(r'\s+', ' ', text)
  return text.strip()


_WIKILINK_RE = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]')

def _strip_wikilinks(text):
  """Replace [[Page|Display]] -> Display, [[Page]] -> Page."""
  return _WIKILINK_RE.sub(lambda m: m.group(2) or m.group(1), text)


def _render_text(raw, upgrade_syntax="square"):
  """Render a wiki-formatted card/relic/potion/event description string.

  upgrade_syntax: "square" for [base|upgrade], "angle" for <base:upgrade>,
  or "none" to skip upgrade expansion entirely.
  """
  if not raw:
    return ""
  raw = _strip_wikilinks(raw)
  if upgrade_syntax == "square":
    base_raw, upg_raw = _expand_upgrade_brackets(raw, '[', ']', '|')
  elif upgrade_syntax == "angle":
    base_raw, upg_raw = _expand_upgrade_brackets(raw, '<', '>', ':')
  else:
    base_raw = raw
    upg_raw = raw

  def _post(s):
    s = _strip_templates(s)
    s = _replace_keyword_dollar(s)
    s = _collapse_energy_and_stars(s)
    s = _normalize_whitespace(s)
    return s

  base = _post(base_raw)
  upg = _post(upg_raw)
  if upgrade_syntax == "none" or base == upg:
    return base
  return _compute_upgrade_diff(base, upg)


# =========================================================================
# Upgrade diff (base text vs upgraded text)
# =========================================================================

def _compute_upgrade_diff(base_text, upgrade_text):
  """Compute a parenthesized diff between base and upgraded card text."""
  if not base_text or not upgrade_text:
    return base_text or upgrade_text or ""
  if base_text == upgrade_text:
    return base_text

  base_words = base_text.split()
  upg_words = upgrade_text.split()
  matcher = SequenceMatcher(None, base_words, upg_words)
  result = []

  for op, i1, i2, j1, j2 in matcher.get_opcodes():
    if op == 'equal':
      result.extend(base_words[i1:i2])
    elif op == 'replace':
      base_chunk = base_words[i1:i2]
      upg_chunk = upg_words[j1:j2]
      if len(base_chunk) == len(upg_chunk):
        for bw, uw in zip(base_chunk, upg_chunk):
          result.append(_diff_word(bw, uw))
      elif len(base_chunk) == 1 and len(upg_chunk) == 1:
        result.append(_diff_word(base_chunk[0], upg_chunk[0]))
      else:
        result.append('{0}({1})'.format(
          ' '.join(base_chunk), ' '.join(upg_chunk)
        ))
    elif op == 'insert':
      added = ' '.join(upg_words[j1:j2])
      result.append('({0})'.format(added))
    elif op == 'delete':
      removed = ' '.join(base_words[i1:i2])
      result.append(removed)

  return ' '.join(result)


def _diff_word(base_word, upg_word):
  """Diff a single word pair, handling numbers, pluralization, punctuation."""
  if base_word == upg_word:
    return base_word

  base_stripped = base_word.rstrip('.,;:!?')
  upg_stripped = upg_word.rstrip('.,;:!?')
  base_punct = base_word[len(base_stripped):]
  upg_punct = upg_word[len(upg_stripped):]
  punct = base_punct or upg_punct

  if base_stripped == upg_stripped:
    return base_word

  if _is_number(base_stripped) and _is_number(upg_stripped):
    return '{0}({1}){2}'.format(base_stripped, upg_stripped, punct)

  if upg_stripped == base_stripped + 's' or upg_stripped == base_stripped + 'es':
    return base_stripped + '(s)' + punct

  return '{0}({1}){2}'.format(base_stripped, upg_stripped, punct)


def _is_number(s):
  try:
    int(s)
    return True
  except ValueError:
    return s == 'X'


# =========================================================================
# Cost rendering
# =========================================================================

def _format_cost(cost, cost_plus=None):
  """Return display string for a cost, or None for unplayable.

  Cost == -2 -> Unplayable (None)
  Cost == -1 -> X
  Otherwise int. CostPlus, if different, is rendered as "a(b)".
  """
  if cost is None or cost == -2:
    return None
  if cost == -1:
    base = "X"
  else:
    base = str(cost)
  if cost_plus is not None and cost_plus != cost:
    if cost_plus == -1:
      upg = "X"
    elif cost_plus == -2:
      upg = "Unplayable"
    else:
      upg = str(cost_plus)
    return "{0}({1})".format(base, upg)
  return base


# =========================================================================
# STS1 gathering (Module:Cards/data, Module:Relics/data, etc.)
# =========================================================================

_STS1_COLOR_TO_CATEGORY = {
  "Red": "Ironclad",
  "Green": "Silent",
  "Blue": "Defect",
  "Purple": "Watcher",
  "Colorless": "Colorless",
}

def GatherCards():
  print("Gathering STS1 Cards")
  cards = []
  try:
    wikitext = _get_module_wikitext("Module:Cards/data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return cards

  for name, data in _parse_lua_table(wikitext).items():
    if name == "nodata_fallback":
      continue
    color = data.get("Color", "Colorless")
    card_type = data.get("Type", "Skill")
    rarity = data.get("Rarity", "Basic")
    category = _STS1_COLOR_TO_CATEGORY.get(color, color)
    if card_type in ("Status", "Curse"):
      category = card_type
    cost = _format_cost(data.get("Cost"), data.get("CostPlus"))
    description = _render_text(data.get("Text", ""), upgrade_syntax="square")
    print("Found STS1 card {0}".format(name))
    cards.append(Card(
      name=name,
      description=description,
      card_type=card_type,
      category=category,
      rarity=rarity,
      cost=cost,
      game="STS1",
    ))
  return cards


def GatherRelics():
  print("Gathering STS1 Relics")
  relics = []
  try:
    wikitext = _get_module_wikitext("Module:Relics/data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return relics

  for name, data in _parse_lua_table(wikitext).items():
    description = _render_text(data.get("Description", ""), upgrade_syntax="none")
    rarity = data.get("Rarity", "Common")
    print("Found STS1 relic {0}".format(name))
    relics.append(Relic(name, description, rarity, game="STS1"))
  return relics


def GatherPotions():
  print("Gathering STS1 Potions")
  potions = []
  try:
    wikitext = _get_module_wikitext("Module:Potions/data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return potions

  for name, data in _parse_lua_table(wikitext).items():
    raw = data.get("Text") or data.get("Description") or ""
    description = _render_text(raw, upgrade_syntax="angle")
    rarity = data.get("Rarity", "Common")
    print("Found STS1 potion {0}".format(name))
    potions.append(Potion(name, description, rarity, game="STS1"))
  return potions


def GatherEvents():
  print("Gathering STS1 Events")
  events = []
  try:
    wikitext = _get_module_wikitext("Module:Events/data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return events

  for name, data in _parse_lua_table(wikitext).items():
    description = _render_text(data.get("Description", ""), upgrade_syntax="none")
    description = re.sub(r"'{2,}", "", description)
    act = data.get("Act") or "Unknown"
    if isinstance(act, dict):
      act = "Multiple"
    print("Found STS1 event {0}".format(name))
    events.append(Event(name, description, act, game="STS1"))
  return events


# =========================================================================
# STS2 gathering
# =========================================================================

_STS2_CARD_MODULES = [
  "Module:Cards/StS2 data/Ironclad",
  "Module:Cards/StS2 data/Silent",
  "Module:Cards/StS2 data/Defect",
  "Module:Cards/StS2 data/Necrobinder",
  "Module:Cards/StS2 data/Regent",
  "Module:Cards/StS2 data/Colorless",
]

def GatherSTS2Cards():
  print("\nGathering STS2 Cards")
  cards = []
  for module in _STS2_CARD_MODULES:
    try:
      wikitext = _get_module_wikitext(module)
    except Exception as e:
      print("  Failed to fetch {0}: {1}".format(module, e))
      continue

    for name, data in _parse_lua_table(wikitext).items():
      color = data.get("Color", "Colorless")
      card_type = data.get("Type", "Skill")
      rarity = data.get("Rarity", "Basic")
      category = color
      if card_type in ("Status", "Curse"):
        category = card_type
      cost = _format_cost(data.get("Cost"), data.get("CostPlus"))
      star_cost = data.get("StarCost")
      if star_cost is not None:
        star_cost = str(star_cost)
      description = _render_text(data.get("Text", ""), upgrade_syntax="square")
      print("Found STS2 card {0}".format(name))
      cards.append(Card(
        name=name,
        description=description,
        card_type=card_type,
        category=category,
        rarity=rarity,
        cost=cost,
        game="STS2",
        star_cost=star_cost,
      ))
    time.sleep(0.2)
  return cards


def GatherSTS2Relics():
  print("\nGathering STS2 Relics")
  relics = []
  try:
    wikitext = _get_module_wikitext("Module:Relics/StS2 data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return relics

  for name, data in _parse_lua_table(wikitext).items():
    description = _render_text(data.get("Description", ""), upgrade_syntax="none")
    category = data.get("Character") or data.get("Rarity") or "Common"
    print("Found STS2 relic {0}".format(name))
    relics.append(Relic(name, description, category, game="STS2"))
  return relics


def GatherSTS2Potions():
  print("\nGathering STS2 Potions")
  potions = []
  try:
    wikitext = _get_module_wikitext("Module:Potions/StS2 data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return potions

  for name, data in _parse_lua_table(wikitext).items():
    raw = data.get("Text") or data.get("Description") or ""
    description = _render_text(raw, upgrade_syntax="none")
    rarity = data.get("Rarity", "Common")
    print("Found STS2 potion {0}".format(name))
    potions.append(Potion(name, description, rarity, game="STS2"))
  return potions


def GatherSTS2Events():
  print("\nGathering STS2 Events")
  events = []
  try:
    wikitext = _get_module_wikitext("Module:Events/StS2 data")
  except Exception as e:
    print("  Failed: {0}".format(e))
    return events

  for name, data in _parse_lua_table(wikitext).items():
    description = _render_text(data.get("Description", ""), upgrade_syntax="none")
    description = re.sub(r"'{2,}", "", description)
    act_field = data.get("Act") or "Unknown"
    if isinstance(act_field, dict) and "__raw__" in act_field:
      raw = act_field["__raw__"]
      parts = re.findall(r'"([^"]*)"', raw)
      act = ", ".join(parts) if parts else "Unknown"
    elif isinstance(act_field, dict):
      act = "Unknown"
    else:
      act = act_field
    print("Found STS2 event {0}".format(name))
    events.append(Event(name, description, act, game="STS2"))
  return events


# =========================================================================
# Main
# =========================================================================

def main():
  cards = GatherCards()
  relics = GatherRelics()
  potions = GatherPotions()
  events = GatherEvents()

  sts2_cards = GatherSTS2Cards()
  sts2_relics = GatherSTS2Relics()
  sts2_potions = GatherSTS2Potions()
  sts2_events = GatherSTS2Events()

  all_items = (cards + relics + potions + events
               + sts2_cards + sts2_relics + sts2_potions + sts2_events)

  print("\n=== Summary ===")
  print("STS1: {0} cards, {1} relics, {2} potions, {3} events".format(
    len(cards), len(relics), len(potions), len(events)))
  print("STS2: {0} cards, {1} relics, {2} potions, {3} events".format(
    len(sts2_cards), len(sts2_relics), len(sts2_potions), len(sts2_events)))
  print("Total: {0} items".format(len(all_items)))

  open(os.path.join(os.path.dirname(__file__), "data.yml"), "w").write(
    yaml.dump([dict(vars(item)) for item in all_items], default_flow_style=False)
  )

if __name__ == "__main__":
  main()
