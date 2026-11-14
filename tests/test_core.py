import asyncio
import unittest

from backend.core import CaptionPacer, Glossary, LatestTranslator


class CaptionPacerTests(unittest.TestCase):
    def test_incomplete_team_name_at_the_end_of_a_short_draft_is_held(self):
        pacer = CaptionPacer()
        self.assertEqual(pacer.push("for NAVI and Fal", False), [])
        self.assertEqual(pacer.push("for NAVI and Fal", False), [])
        self.assertEqual(pacer.push("for NAVI and Falcons walk", False), [])
        final, = pacer.push("for NAVI and Falcons walk right down", True)
        self.assertEqual(final["text"], "for NAVI and Falcons walk right down")

    def test_draft_waits_for_agreement_and_is_replaced_only_by_final(self):
        pacer = CaptionPacer()
        self.assertEqual(pacer.push("NAVI are saving their rifles inside", False), [])
        draft, = pacer.push("NAVI are saving their rifles behind", False)
        self.assertEqual(draft["text"], "NAVI are saving their rifles")
        self.assertFalse(draft["final"])
        self.assertEqual(pacer.push("NAVI are saving their rifles behind the smoke", False), [])
        final, = pacer.push("NAVI are saving their rifles behind the smoke", True)
        self.assertTrue(final["final"])
        self.assertEqual(final["utterance"], draft["utterance"])
        self.assertEqual(final["text"], "NAVI are saving their rifles behind the smoke")

    def test_an_unfinished_draft_stops_before_an_open_phrase(self):
        pacer = CaptionPacer()
        pacer.push("Jame takes the opening kill with the", False)
        draft, = pacer.push("Jame takes the opening kill with the AWP", False)
        self.assertEqual(draft["text"], "Jame takes the opening kill")

    def test_continuous_speech_keeps_earlier_cues_and_translates_the_tail(self):
        pacer = CaptionPacer()
        first = "Jame has a smoke and a flash for the retake"
        next_clause = "but NAVI still have both players on the site"
        pacer.push(first, False)
        draft, = pacer.push(first + " but NAVI", False)
        self.assertEqual(draft["text"], first)
        self.assertEqual(pacer.push(first + " but NAVI still", False), [])
        committed, = pacer.push(first + " " + next_clause, False)
        self.assertTrue(committed["final"])
        self.assertEqual(committed["text"], first)
        self.assertEqual(committed["utterance"], draft["utterance"])
        tail, = pacer.push(first.lower() + " " + next_clause, True)
        self.assertEqual(tail["utterance"], committed["utterance"] + 1)
        self.assertEqual(tail["text"], next_clause)
        self.assertEqual(tail["prefix"], first.lower())

    def test_sentence_boundary_and_very_short_final_are_not_lost(self):
        pacer = CaptionPacer()
        text = "Jame takes the opening kill. No kit."
        self.assertEqual(pacer.push(text, False), [])
        first, second = pacer.push(text, True)
        self.assertEqual(first["text"], "Jame takes the opening kill.")
        self.assertEqual(second["text"], "No kit.")
        self.assertTrue(first["final"] and second["final"])

    def test_reset_clears_the_word_offset_and_draft_state(self):
        pacer = CaptionPacer()
        pacer.push("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen", False)
        pacer.push("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen", False)
        pacer.reset()
        final, = pacer.push("No kit", True)
        self.assertEqual(final["text"], "No kit")
        self.assertEqual(final["prefix"], "")

    def test_a_word_inserted_before_a_committed_cue_does_not_repeat_its_tail(self):
        pacer = CaptionPacer()
        first = "Jame has a smoke and a flash for the retake."
        pacer.push(first + " NAVI are ready", False)
        committed, = pacer.push(first + " NAVI are ready to fight", False)
        self.assertTrue(committed["final"])
        tail, = pacer.push("Jame still has a smoke and a flash for the retake. NAVI are ready to fight", True)
        self.assertEqual(tail["text"], "NAVI are ready to fight")


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

    async def test_clauses_from_one_endpoint_are_translated_in_order(self):
        results = []

        async def translate(job):
            return job

        scheduler = LatestTranslator(translate, results.append, interval=0)
        for index, text in enumerate(("first clause", "second clause", "no kit")):
            scheduler.submit({"text": text, "utterance": index, "final": True})
        task = asyncio.create_task(scheduler.run())
        await scheduler.idle()
        scheduler.close()
        await task
        self.assertEqual([r["text"] for r in results], ["first clause", "second clause", "no kit"])
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
