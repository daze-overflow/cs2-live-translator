import json
from pathlib import Path
import unittest

from backend.catalog import MatchVocabulary
from backend.stream import EndpointStream

ROOT = Path(__file__).resolve().parents[1]


class VocabularyTests(unittest.TestCase):
    def vocabulary(self, title="", names=()):
        return MatchVocabulary(json.loads((ROOT / "backend/catalog.json").read_text(encoding="utf-8")),
                               json.loads((ROOT / "backend/glossary.json").read_text(encoding="utf-8")), title, names)

    def test_fixture_title_injects_only_the_two_teams(self):
        vocabulary = self.vocabulary("Team Falcons vs. Natus Vincere - IEM Beijing")
        self.assertEqual(set(vocabulary.active), {"Falcons", "NAVI"})
        glossary = vocabulary.glossary()
        self.assertIn("m0NESY", glossary.names)
        self.assertIn("makazze", glossary.names)
        self.assertNotIn("ZywOo", glossary.names)
        self.assertEqual(glossary.canonicalize("monesy and bit need money")[0], "m0NESY and b1t need money")
        self.assertEqual(glossary.canonicalize("monzi needs money")[0], "m0NESY needs money")

    def test_native_hints_do_not_boost_unrelated_teams(self):
        vocabulary = self.vocabulary("Team Liquid vs. TYLOO - Map 1")
        hints = vocabulary.hints()
        self.assertIn("JamYoung", hints)
        self.assertIn("NAF", hints)
        self.assertNotIn("DENDELE", hints)
        self.assertNotIn("Nexus", hints)
        self.assertNotIn("gafolo", hints)

    def test_current_chapter_takes_precedence_over_the_video_title(self):
        vocabulary = self.vocabulary("Liquid vs TYLOO | FURIA vs Vitality - Map 2", names=["ChildKing"])
        self.assertEqual(set(vocabulary.active), {"FURIA", "Vitality"})
        self.assertIn("ChildKing", vocabulary.glossary().names)

    def test_live_pvision_title_injects_rosters_before_any_speech(self):
        vocabulary = self.vocabulary("PVISION vs. Natus Vincere - IEM Beijing 2026 - Quarterfinal")
        self.assertEqual(vocabulary.fixed, ("PARIVISION", "NAVI"))
        self.assertIn("Jame", vocabulary.hints())
        self.assertIn("makazze", vocabulary.hints())
        self.assertNotIn("NiKo", vocabulary.hints())

    def test_supplementary_names_do_not_override_a_clear_current_fixture(self):
        vocabulary = self.vocabulary("FURIA vs Vitality", names=["Liquid", "G2", "jL"])
        self.assertEqual(vocabulary.fixed, ("FURIA", "Vitality"))
        self.assertIn("jL", vocabulary.glossary().names)
        self.assertNotIn("NAF", vocabulary.hints())

    def test_fixture_uses_opponents_around_vs_instead_of_other_mentions(self):
        vocabulary = self.vocabulary("NAVI vs PARIVISION - winner plays G2")
        self.assertEqual(vocabulary.fixed, ("NAVI", "PARIVISION"))

    def test_a_multi_match_title_waits_for_evidence_instead_of_pinning_arbitrary_teams(self):
        vocabulary = self.vocabulary("Liquid vs G2 / NAVI vs PARIVISION")
        self.assertFalse(vocabulary.fixed)
        vocabulary.observe("Jame and makazze", 1)
        self.assertEqual(set(vocabulary.active), {"NAVI", "PARIVISION"})

    def test_explicit_fixture_does_not_drift_to_sponsor_or_ordinary_words(self):
        vocabulary = self.vocabulary("Team Liquid vs. TYLOO - Map 1")
        vocabulary.observe("a little more pain, go nexus gg, heroic on the Glock", 20)
        vocabulary.observe("DENDELE is there", 25)
        self.assertEqual(set(vocabulary.active), {"Liquid", "TYLOO"})
        self.assertNotIn("paiN", vocabulary.glossary().names)

    def test_pain_and_sponsor_nexus_are_not_team_evidence(self):
        vocabulary = self.vocabulary()
        vocabulary.observe("that is a pain, go nexus gg", 10)
        self.assertEqual(vocabulary.active, {})

    def test_player_mention_switches_and_old_teams_expire(self):
        vocabulary = self.vocabulary()
        vocabulary.observe("JamYoung against Liquid", 10)
        self.assertEqual(set(vocabulary.active), {"TYLOO", "Liquid"})
        vocabulary.observe("torzsi has the AWP for MOUZ", 15)
        self.assertEqual(len(vocabulary.active), 2)
        self.assertIn("MOUZ", vocabulary.active)
        vocabulary.observe("a tactical timeout", 196)
        self.assertEqual(vocabulary.active, {})
        self.assertNotIn("torzsi", vocabulary.hints())

    def test_common_words_do_not_activate_rosters_or_force_soft_terms(self):
        vocabulary = self.vocabulary()
        vocabulary.observe("rain on the device with zero money, frozen, it is big magic", 5)
        self.assertEqual(vocabulary.active, {})
        self.assertEqual(vocabulary.glossary().hints("rain device zero money big magic"), [])
        self.assertEqual(vocabulary.glossary().preserve("default position", "默认站位")["zh"], "默认站位")
        self.assertEqual(vocabulary.glossary().preserve("ADR", "场均伤害")["zh"], "场均伤害")
        vocabulary.observe("100 Thieves", 6)
        self.assertIn("rain", vocabulary.glossary().names)
        self.assertIn("device", vocabulary.hints())

    def test_manual_names_survive_expiry_for_historical_replays(self):
        vocabulary = self.vocabulary(names=["Magisk", "jL"])
        vocabulary.observe("nothing more", 400)
        self.assertIn("Magisk", vocabulary.glossary().names)
        self.assertIn("jL", vocabulary.hints())

    def test_major_terms_and_furia_asr_aliases_are_handled_safely(self):
        vocabulary = self.vocabulary("Spirit vs FURIA")
        glossary = vocabulary.glossary()
        text, _ = glossary.canonicalize("caserato yakinder and molodoid win the major")
        self.assertEqual(text, "KSCERATO YEKINDAR and molodoy win the major")
        self.assertIn("Major", glossary.preserve("Vitality win the major", "Vitality赢得大赛")["zh"])
        self.assertEqual(glossary.preserve("a major mistake", "一个重大失误")["zh"], "一个重大失误")
        self.assertEqual(glossary.preserve("visit refrag dot gg", "访问refrag.gg")["zh"], "访问refrag.gg")


class EndpointTests(unittest.TestCase):
    def test_hint_refresh_preserves_undecoded_audio_and_absolute_word_times(self):
        class Stream:
            def __init__(self, event):
                self.event, self.packets, self.closed = event, [], False

            def push(self, pcm):
                self.packets.append(pcm)
                result, self.event = self.event, []
                return result

            def close(self):
                self.closed = True

        class Recognizer:
            def __init__(self):
                self.streams = []

            def stream(self, hints):
                events = [{"text": "Falcons", "final": True, "audio_processed": .8, "words": []}] if not self.streams else []
                stream = Stream(events)
                self.streams.append(stream)
                return stream

        recognizer = Recognizer()
        stream = EndpointStream(recognizer, ("Falcons",))
        audio = bytes(25600) + bytes([1, 2]) * 3200
        stream.push(audio)
        stream.refresh(("Falcons", "m0NESY"))
        self.assertTrue(recognizer.streams[0].closed)
        self.assertEqual(recognizer.streams[1].packets, [audio[25600:]])
        recognizer.streams[1].event = [{"text": "monesy", "final": False, "audio_processed": .4,
                                       "words": [{"text": "monesy", "start_ms": 100, "end_ms": 300}]}]
        events = stream.push(bytes(6400))
        self.assertAlmostEqual(events[0]["audio_processed"], 1.2)
        self.assertEqual(events[0]["words"][0]["start_ms"], 900)
        self.assertEqual(events[0]["words"][0]["end_ms"], 1100)
        stream.refresh(("NAVI",))  # Never discard an unfinished utterance.
        self.assertEqual(len(recognizer.streams), 2)


if __name__ == "__main__":
    unittest.main()
