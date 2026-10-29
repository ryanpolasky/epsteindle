import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('audit', Path(__file__).with_name('audit-docket.py'))
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTest(unittest.TestCase):
    def test_exact_answer_is_accepted_outside_dictionary(self):
        data = {'paras': [['The ', {'w': 'ISLAND', 't': 'island'}, '.']]}
        self.assertEqual(audit.audit(data, set()), ([], 1, 1))
        self.assertEqual(audit.audit(data, {'island'}), ([], 1, 0))

    def test_empty_passage(self):
        self.assertIn('no guess targets', audit.audit({'paras': []}, set())[0])

    def test_invalid_targets_and_bar_boundaries(self):
        for target in [{'w': 'CAN’T', 't': 'can’t'}, {'w': 'ISLAND', 't': 'islands'}]:
            with self.subTest(target=target):
                self.assertTrue(audit.audit({'paras': [[target]]}, set())[0])
        for paragraph in [[{'doj': 1}, {'w': 'ISLAND', 't': 'island'}],
                          ['the', {'w': 'ISLAND', 't': 'island'}],
                          [{'w': 'ISLAND', 't': 'island'}, 'ers']]:
            self.assertTrue(audit.audit({'paras': [paragraph]}, set())[0])

    def test_spatial_order_and_missing_pdf(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            data = {'url': 'https://example.com/test.pdf', 'page': 1,
                    'paras': [['First line. Second line.']]}
            self.assertIn('source PDF unavailable', audit.layout_errors(data, cache)[0])
            with audit.redactions.pymupdf.open() as doc:
                page = doc.new_page()
                page.insert_text((50, 120), 'Second line.')
                page.insert_text((50, 100), 'First line.')
                doc.save(cache / 'test.pdf')
            self.assertEqual(audit.layout_errors(data, cache), [])
            data['paras'] = [['Second line. First line.']]
            self.assertIn('spatial PDF token order', audit.layout_errors(data, cache)[0])


if __name__ == '__main__':
    unittest.main()
