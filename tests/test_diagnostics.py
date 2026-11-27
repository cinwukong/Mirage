"""The report you copy when asking for help (diagnostics.report): the facts and the errors, never what you said."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import diagnostics  # noqa: E402

HOME = r"C:\Users\Alex Svensson"
LOG = r"""[14:02:11] Listening on: Mikrofon (Yeti Stereo Microphon (Parakeet)
[14:02:15] Heard: 'mirage remind me to call grandma about the surgery'
[14:02:15] YOU: remind me to call grandma about the surgery
[14:02:16] MIRAGE: Okay, I'll remind you at 17:00.
[14:03:40] Brain tool: type_text {'text': 'my secret plans for the weekend'}
[14:03:41] Memory: noticed 'The user's sister is called Emma' (Emma)
[14:03:50] Speaking up: Don't forget, it's today: Emma's birthday.
[14:04:02] Asked 'Should I send that message?': yes ('yes send it')
[14:05:00] Brain: C:\Users\Alex Svensson\AppData\Local\Mirage\brain\llama\llama-server.exe -m model.gguf
[14:05:09] Speech failed to load:
Traceback (most recent call last):
  File "C:\Users\Alex Svensson\AppData\Local\Programs\Mirage\app\speech.py", line 557, in _load
RuntimeError: Failed to load model encoder.int8.onnx
[14:06:00] API error: Error code: 401 - invalid x-api-key sk-ant-api03-AbCdEf123456789
"""
INFO = {"Mirage": "3.0.2", "Windows": "Windows 11 (26300)", "Graphics": "NVIDIA GeForce RTX 4070 (12.0 GB)"}


class Report(unittest.TestCase):
    def setUp(self):
        self.text = diagnostics.report(INFO, LOG, home=HOME)

    def test_what_you_said_and_what_mirage_said_are_left_out(self):
        for private in ("grandma", "surgery", "17:00", "secret plans", "Emma", "send it", "birthday"):
            self.assertNotIn(private, self.text)

    def test_the_shape_of_the_conversation_stays(self):
        for kept in ("YOU:", "MIRAGE:", "Heard:", "Brain tool: type_text", "Asked"):
            self.assertIn(kept, self.text)

    def test_errors_and_tracebacks_are_kept(self):
        self.assertIn("RuntimeError: Failed to load model encoder.int8.onnx", self.text)
        self.assertIn('line 557, in _load', self.text)
        self.assertIn("Listening on: Mikrofon (Yeti Stereo Microphon (Parakeet)", self.text)

    def test_your_name_is_taken_out_of_paths(self):
        self.assertNotIn("Alex", self.text)
        self.assertNotIn("Svensson", self.text)
        self.assertIn(r"~\AppData\Local\Mirage\brain", self.text)

    def test_a_reply_over_several_lines_is_left_out_entirely(self):
        log = ("[10:00:00] MIRAGE: Here's your list:\nbuy flowers for Emma\ncall the clinic about the results\n"
               "[10:00:05] Speech failed to load:\nTraceback (most recent call last):\nRuntimeError: no model\n")
        text = diagnostics.report({}, log, home=HOME)
        self.assertNotIn("flowers", text)
        self.assertNotIn("clinic", text)
        self.assertIn("RuntimeError: no model", text)  # an error's traceback lines still come through

    def test_keys_are_hidden(self):
        self.assertNotIn("AbCdEf123456789", self.text)

    def test_the_facts_come_first(self):
        first = self.text.splitlines()[:6]
        self.assertTrue(any("NVIDIA GeForce RTX 4070" in line for line in first))
        self.assertTrue(any("3.0.2" in line for line in first))


if __name__ == "__main__":
    unittest.main()
