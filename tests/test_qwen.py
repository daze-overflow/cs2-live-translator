from pathlib import Path
import unittest

from backend.core import Glossary
from backend.qwen import QwenTranslator


class TranslationTests(unittest.IsolatedAsyncioTestCase):
    def translator(self, outputs):
        payloads = []

        class Response:
            status = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def json(self):
                return {"choices": [{"message": {"content": outputs.pop(0)}}]}

        class Session:
            def post(self, _url, json):
                payloads.append(json)
                return Response()

        translator = QwenTranslator(Path('.'), '')
        translator.session = Session()
        return translator, payloads

    async def test_an_untranslated_final_gets_one_corrective_attempt(self):
        translator, payloads = self.translator(["yeah just individually mismatched", "是的，个人实力不匹配。"])
        result = await translator.translate("yeah just individually mismatched", None)
        self.assertEqual(result["zh"], "是的，个人实力不匹配。")
        self.assertEqual(len(payloads), 2)
        self.assertEqual(result["quality_retries"], 1)

    async def test_a_draft_does_not_spend_time_on_a_corrective_attempt(self):
        translator, payloads = self.translator(["yeah just individually mismatched"])
        await translator.translate("yeah just individually mismatched", None, repair=False)
        self.assertEqual(len(payloads), 1)

    async def test_preserved_player_map_weapon_names_do_not_trigger_repair(self):
        translator, payloads = self.translator(["Jame在Mirage用AWP击杀makazze。"])
        result = await translator.translate("Jame kills makazze with the AWP on Mirage.",
            Glossary({"Jame": [], "makazze": [], "AWP": [], "Mirage": []}, {}))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(result["quality_retries"], 0)

    async def test_an_all_name_output_is_not_mistaken_for_untranslated_prose(self):
        translator, payloads = self.translator(["Jame / makazze"])
        result = await translator.translate("Jame and makazze", Glossary({"Jame": [], "makazze": []}, {}))
        self.assertEqual(len(payloads), 1)
        self.assertFalse(result["untranslated"])

    async def test_two_uncertain_name_tokens_in_chinese_do_not_force_a_retranslation(self):
        translator, payloads = self.translator(["仍输给Mac Tec。"])
        await translator.translate("still loses out to the mac tec", None)
        self.assertEqual(len(payloads), 1)

    async def test_a_failed_repair_is_bounded_and_reported(self):
        translator, payloads = self.translator(["the smoke is gone", "the smoke is gone"])
        result = await translator.translate("the smoke is gone", None)
        self.assertEqual(len(payloads), 2)
        self.assertTrue(result["untranslated"])

    async def test_chinese_with_untranslated_ordinary_words_gets_repaired(self):
        translator, payloads = self.translator(["Jame previously held here这里。", "Jame之前守在这里。"])
        result = await translator.translate("Jame previously held here.", Glossary({"Jame": []}, {}))
        self.assertEqual(result["zh"], "Jame之前守在这里。")
        self.assertEqual(len(payloads), 2)

    async def test_a_short_fragment_does_not_import_the_previous_sentence(self):
        payloads = []

        class Response:
            status = 200
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                pass
            async def json(self):
                return {"choices": [{"message": {"content": "看看是否"}}]}

        class Session:
            def post(self, _url, json):
                payloads.append(json)
                return Response()

        translator = QwenTranslator(Path('.'), '')
        translator.session = Session()
        await translator.translate("see if the", None, "It is nice to have the crowd behind you")
        self.assertNotIn("crowd", payloads[0]["messages"][-1]["content"])

    async def test_an_isolated_name_is_retained_without_a_model_call(self):
        translator = QwenTranslator(Path('.'), '')
        result = await translator.translate("monesy", Glossary({"m0NESY": ["monesy"]}, {}), "prior sentence")
        self.assertEqual(result["zh"], "m0NESY")
        self.assertEqual(result["en"], "m0NESY")
