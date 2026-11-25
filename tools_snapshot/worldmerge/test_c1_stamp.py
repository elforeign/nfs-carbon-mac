"""World builder stamps its converter revision; a world without it or with another one is refused.

Synthetic, runs bare. Old code (no stamp written or checked): the missing-stamp world is accepted.
New code: current stamp accepted; missing, wrong and absent proof.json refused (3/3), 1/1 accepted.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
import c1_world as w
from formats import FormatError


class Stamp(unittest.TestCase):
    def world(self, proof):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        if proof is not None:
            (Path(d.name)/'proof.json').write_text(json.dumps(proof))
        return d.name

    def test_current_accepted(self):
        w.require_current(self.world({'converter': w.converter_stamp()}))

    def test_stale_or_missing_refused(self):
        for proof in ({'records': 1433}, {'converter': '0'*64}, None):
            with self.assertRaises(FormatError, msg=str(proof)):
                w.require_current(self.world(proof))

    def test_stamp_follows_sources(self):
        self.assertEqual(len(w.converter_stamp()), 64)
        self.assertEqual(w.converter_stamp(), w.converter_stamp())


if __name__ == '__main__':
    unittest.main()
