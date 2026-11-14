"""Select a small roster from recent, explicit team or distinctive player mentions."""
import re

from .core import Glossary


def mentions(text, value):
    return re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I) is not None


class MatchVocabulary:
    def __init__(self, catalog, glossary, title="", names=()):
        self.catalog, self.base = catalog, glossary
        self.manual = [name.strip() for name in names if name.strip()]
        self.active = {}
        self.teams = {team["name"]: team for team in catalog["teams"]}
        self.aliases = catalog["player_aliases"]
        self.ambiguous_players = {p.casefold() for p in catalog["ambiguous_players"]}
        self.ambiguous_teams = {p.casefold() for p in catalog["ambiguous_teams"]}
        self.cached_key = self.cached_glossary = None
        self.fixed = ()
        self.source = "speech"
        aliases = {alias.casefold(): name for name, team in self.teams.items()
                   for alias in [name, *team["aliases"]]}
        pattern = "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))
        fixture = re.compile(r"(?<!\w)(" + pattern + r")\s+(?:vs\.?|versus)\s+(?:team\s+)?(" + pattern + r")(?!\w)", re.I)
        parts = title.split(" | ")
        for index in range(len(parts) - 1, -1, -1):
            pairs = {tuple(aliases[match.casefold()] for match in pair) for pair in fixture.findall(parts[index])}
            if len(pairs) == 1:
                self.fixed = next(iter(pairs))
                self.active = dict.fromkeys(self.fixed, 0)
                self.source = "chapter" if index > 0 else "title"
                break
            if re.search(r"\b(?:vs|versus)\b", parts[index], re.I):
                break  # An ambiguous current chapter must not select an older title fixture.
        if not self.fixed and not re.search(r"\b(?:vs|versus)\b", title, re.I):
            self.observe(title, 0, title=True)
        if not self.fixed:
            self.observe(" ".join(self.manual), 0, title=True)
        manual_teams = [name for name in self.manual if name in self.teams]
        if not self.fixed and len(manual_teams) == 2:
            self.fixed = tuple(manual_teams)
            self.active = dict.fromkeys(self.fixed, 0)
            self.source = "manual"

    def observe(self, text, seconds, title=False):
        if self.fixed:
            self.active = dict.fromkeys(self.fixed, seconds)
            return list(self.active)
        detected = []
        for name, team in self.teams.items():
            found = any(mentions(text, alias) and (
                title or alias.casefold() not in self.ambiguous_teams or
                mentions(text, "team " + alias) or re.search(
                    r"(?:against|versus|vs\.?|for|from|on)\s+" + re.escape(alias) + r"(?!\w)", text, re.I))
                for alias in [name, *team["aliases"]])
            if not found:
                found = any(mentions(text, alias) for player in team["players"]
                            for alias in [player, *self.aliases.get(player, [])]
                            if len(alias) >= 4 and alias.casefold() not in self.ambiguous_players)
            if found:
                detected.append(name)
        for name in detected:
            self.active.pop(name, None)
            self.active[name] = seconds
        self.active = {name: seen for name, seen in self.active.items() if seconds - seen <= 180}
        self.active = dict(list(self.active.items())[-2:])
        return list(self.active)

    def glossary(self):
        key = tuple(sorted(self.active))
        if self.cached_key == key:
            return self.cached_glossary
        names = dict(self.base["names"])
        for name, team in self.teams.items():
            names[name] = team["aliases"]
            if name.casefold() in self.ambiguous_teams and name not in self.active:
                names.pop(name)
                names["Team " + name] = ["team " + name, *team["aliases"]]
        for name in self.active:
            for player in self.teams[name]["players"]:
                names[player] = self.aliases.get(player, [])
        for name in self.manual:
            names.setdefault(name, self.aliases.get(name, []))
        self.cached_key = key
        self.cached_glossary = Glossary(names, self.base["terms"], self.base.get("context_terms"))
        return self.cached_glossary

    def hints(self):
        glossary = self.glossary()
        selected = set(self.base["names"]) | set(self.active) | set(self.manual)
        selected.update(player for name in self.active for player in self.teams[name]["players"])
        hints = [alias for name, aliases in glossary.names.items() if name in selected
                 for alias in [name, *aliases]]
        return tuple(dict.fromkeys([*hints, *(hint.lower() for hint in hints)]))
