import asyncio
import unittest

from backend.core import Glossary, LatestTranslator


class GlossaryTests(unittest.TestCase):
    def setUp(self):
        self.glossary = Glossary({"NiKo": ["niko"], "m0NESY": ["monesy"],
                                  "NAVI": ["natus vincere"]}, {"opening kill": "首杀"})

    def test_names_are_retained_when_the_model_omits_them(self):
        translated = self.glossary.preserve("Niko and monesy against Natus Vincere", "译文")["zh"]
        for name in ("NiKo", "m0NESY", "NAVI"):
            self.assertIn(name, translated)

    def test_required_game_information_is_retained_when_omitted(self):
        self.assertIn("首杀", self.glossary.preserve("opening kill", "译文")["zh"])

    def test_matches_are_whole_words_and_do_not_replace_other_names(self):
        self.assertEqual(self.glossary.hints("Nikola"), [])

    def test_ordinary_player_names_are_opt_in(self):
        self.assertEqual(self.glossary.hints("rain"), [])
        self.glossary.add_names(["rain"])
        self.assertEqual(self.glossary.preserve("rain", "雨")["zh"], "雨（rain）")

    def test_close_long_ids_are_corrected_without_turning_money_into_monesy(self):
        glossary = Glossary({"Magisk": [], "m0NESY": ["monesy"]}, {})
        text, changes = glossary.canonicalize("magiski gets the kill and they need money")
        self.assertEqual(text, "Magisk gets the kill and they need money")
        self.assertEqual(changes[0]["source"], "magiski")

    def test_common_phrases_remain_ordinary_even_with_an_active_roster(self):
        glossary = Glossary({"b1t": ["bit"], "w0nderful": ["wonderful"], "Zero": [], "rain": [], "device": []}, {})
        text = "a bit late, a wonderful shot, zero chance, rain delay and device failure"
        self.assertEqual(glossary.canonicalize(text)[0], text)
        self.assertEqual(glossary.hints(text), [])
        self.assertEqual(glossary.canonicalize("bit and wonderful hold B")[0], "b1t and w0nderful hold B")


class LatestTests(unittest.IsolatedAsyncioTestCase):
    async def test_reading_interval_starts_after_display_not_before_inference(self):
        started, release = asyncio.Event(), asyncio.Event()
        emitted = []

        async def translate(job):
            if job["text"] == "first":
                started.set()
                await release.wait()
            return job

        def emit(job):
            emitted.append((job["text"], asyncio.get_running_loop().time()))

        scheduler = LatestTranslator(translate, emit, interval=.08)
        task = asyncio.create_task(scheduler.run())
        scheduler.submit({"text": "first", "utterance": 0})
        await started.wait()
        await asyncio.sleep(.1)  # Slow inference already consumed the old start-to-start limit.
        scheduler.submit({"text": "first with more words", "utterance": 0})
        release.set()
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual(len(emitted), 2)
        self.assertGreaterEqual(emitted[1][1] - emitted[0][1], .07)

    async def test_word_fragments_wait_but_short_finals_are_kept(self):
        results = []

        async def translate(job):
            return job

        scheduler = LatestTranslator(translate, results.append, interval=0, min_draft_words=4)
        task = asyncio.create_task(scheduler.run())
        for text in ("Jame", "Jame has", "Jame has no"):
            scheduler.submit({"text": text, "utterance": 0})
            await asyncio.sleep(0)
        scheduler.submit({"text": "no kit", "utterance": 0, "final": True})
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual([r["text"] for r in results], ["no kit"])

    async def test_a_seek_discards_old_final_and_pending_context(self):
        started, release = asyncio.Event(), asyncio.Event()
        results = []

        async def translate(job):
            if job["text"] == "before seek":
                started.set()
                await release.wait()
            return job

        scheduler = LatestTranslator(translate, results.append, interval=0)
        task = asyncio.create_task(scheduler.run())
        scheduler.submit({"text": "before seek", "utterance": 0, "final": True})
        await started.wait()
        scheduler.submit({"text": "queued old words", "utterance": 1})
        scheduler.clear()
        scheduler.submit({"text": "after seek", "utterance": 2})
        release.set()
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual([r["text"] for r in results], ["after seek"])

    async def test_pending_final_survives_the_next_utterance(self):
        started, release = asyncio.Event(), asyncio.Event()
        results = []

        async def translate(job):
            if job["text"] == "draft":
                started.set()
                await release.wait()
            return job

        scheduler = LatestTranslator(translate, results.append, interval=0)
        task = asyncio.create_task(scheduler.run())
        scheduler.submit({"text": "draft", "utterance": 0})
        await started.wait()
        scheduler.submit({"text": "final", "utterance": 0, "final": True})
        scheduler.submit({"text": "next", "utterance": 1})
        release.set()
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual([r["text"] for r in results], ["final", "next"])
        self.assertEqual(scheduler.missed_finals, 0)

    async def test_a_valid_short_prefix_is_shown_while_more_speech_arrives(self):
        started, release = asyncio.Event(), asyncio.Event()
        results = []

        async def translate(job):
            if job["text"] == "Niko":
                started.set()
                await release.wait()
            return {**job, "zh": job["text"]}

        scheduler = LatestTranslator(translate, lambda result: results.append(result), interval=0)
        task = asyncio.create_task(scheduler.run())
        scheduler.submit({"text": "Niko", "utterance": 0})
        await started.wait()
        scheduler.submit({"text": "Niko gets the kill", "utterance": 0})
        release.set()
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual([r["zh"] for r in results], ["Niko", "Niko gets the kill"])

    async def test_an_old_translation_cannot_overwrite_a_new_revision(self):
        started = asyncio.Event()
        release = asyncio.Event()
        results = []
        calls = []

        async def translate(job):
            calls.append(job["text"])
            if job["text"] == "old":
                started.set()
                await release.wait()
            return {**job, "zh": job["text"]}

        scheduler = LatestTranslator(translate, lambda result: results.append(result), interval=0)
        task = asyncio.create_task(scheduler.run())
        scheduler.submit({"text": "old", "utterance": 0})
        await started.wait()
        scheduler.submit({"text": "middle", "utterance": 0})
        scheduler.submit({"text": "new", "utterance": 0})
        release.set()
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual(calls, ["old", "new"])
        self.assertEqual([result["zh"] for result in results], ["new"])


if __name__ == "__main__":
    unittest.main()
