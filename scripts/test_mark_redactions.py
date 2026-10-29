import importlib.util
from pathlib import Path
import unittest

import numpy as np
import pymupdf

spec = importlib.util.spec_from_file_location('mark_redactions', Path(__file__).with_name('mark-redactions.py'))
marker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(marker)


class RedactionsTest(unittest.TestCase):
    def setUp(self):
        self.doc = pymupdf.open()
        self.page = self.doc.new_page()

    def tearDown(self):
        self.doc.close()

    def text(self, x, y, text):
        self.page.insert_text((x, y), text, fontname='cour', fontsize=10)

    def box(self, x0, y0, x1, y1):
        self.page.draw_rect(pymupdf.Rect(x0, y0, x1, y1), color=None, fill=(0, 0, 0))

    def test_spatial_order_and_target_preservation(self):
        self.text(50, 100, 'At first,')
        self.text(50, 114, 'It was')
        self.text(160, 100, 'quiet on the island.')
        self.text(100, 114, 'private.')
        self.box(110, 91, 150, 102)
        targets = [{'w': 'ISLAND', 't': 'island'}, {'w': 'PRIVATE', 't': 'private'}]
        paras = [['At first, It was quiet on the ', targets[0], '. ', targets[1], '.']]
        result, stats = marker.rebuild(self.page, paras)
        self.assertEqual(marker.passage_text(result), 'At first, ▮ quiet on the island. It was private.')
        self.assertEqual([c for p in result for c in p if isinstance(c, dict) and 't' in c], targets)
        self.assertEqual(stats['bars'], 1)

    def test_empty_boxes(self):
        self.text(50, 100, 'Nothing is missing.')
        paras = [['Nothing is missing.']]
        result, stats = marker.rebuild(self.page, paras)
        self.assertEqual(result, paras)
        self.assertEqual(stats['boxes'], 0)

    def test_bad_alignment(self):
        self.text(50, 100, 'Entirely different text.')
        with self.assertRaisesRegex(ValueError, 'alignment coverage'):
            marker.rebuild(self.page, [['No matching words here.']])

    def test_hidden_text_is_dropped_and_multiline_bars_merge(self):
        self.text(50, 100, 'January 2007.')
        self.text(145, 100, 'Hidden Name')
        self.box(140, 90, 230, 103)
        self.box(50, 106, 300, 117)
        self.box(50, 120, 300, 131)
        self.text(50, 148, 'They discussed the island.')
        paras = [['January 2007. They discussed the island.']]
        result, stats = marker.rebuild(self.page, paras)
        self.assertEqual(marker.passage_text(result), 'January 2007. ▮ They discussed the island.')
        self.assertEqual(stats['bars'], 1)
        self.assertGreaterEqual(stats['dropped'], 2)
        self.assertNotIn('Hidden', marker.passage_text(result))

    def test_existing_redaction_cannot_disappear(self):
        self.text(50, 100, 'Before and after.')
        with self.assertRaisesRegex(ValueError, 'existing redaction'):
            marker.rebuild(self.page, [['Before ', {'doj': 1}, ' and after.']])

    def test_scanned_image_box_and_hidden_text(self):
        self.box(100, 90, 170, 103)
        image = self.page.get_pixmap()
        page = self.doc.new_page()
        page.insert_image(page.rect, pixmap=image)
        page.insert_text((50, 100), 'Before', fontname='cour', fontsize=10, render_mode=3)
        page.insert_text((110, 100), 'Secret', fontname='cour', fontsize=10, render_mode=3)
        page.insert_text((180, 100), 'after.', fontname='cour', fontsize=10, render_mode=3)
        result, stats = marker.rebuild(page, [['Before after.']])
        self.assertEqual(marker.passage_text(result), 'Before ▮ after.')
        self.assertEqual(stats['dropped'], 1)

    def test_small_bbox_spillover_keeps_readable_word(self):
        dark = np.zeros((240, 400), dtype=bool)
        word = pymupdf.Rect(50, 90, 100, 102)
        box = pymupdf.Rect(99, 89, 140, 103)
        dark[178:206, 198:280] = True
        self.assertFalse(marker.hidden_word(word, [box], dark))

    def test_mostly_covered_word_is_hidden(self):
        dark = np.zeros((240, 400), dtype=bool)
        self.assertTrue(marker.hidden_word(pymupdf.Rect(50, 90, 100, 102), [pymupdf.Rect(65, 85, 105, 105)], dark))

    def test_center_in_box_is_hidden_even_below_half_coverage(self):
        dark = np.zeros((240, 400), dtype=bool)
        self.assertTrue(marker.hidden_word(pymupdf.Rect(50, 90, 100, 102), [pymupdf.Rect(70, 94, 80, 98)], dark))

    def test_raster_blackness_hides_word_without_detected_box(self):
        dark = np.zeros((240, 400), dtype=bool)
        dark[180:204, 100:165] = True
        self.assertTrue(marker.hidden_word(pymupdf.Rect(50, 90, 100, 102), [], dark))

    def test_existing_adjacent_bars_merge(self):
        self.text(50, 100, 'Before')
        self.box(100, 90, 170, 103)
        self.text(180, 100, 'after.')
        result, stats = marker.rebuild(self.page, [['Before ', {'doj': 1}, ' ', {'doj': 1}, ' after.']])
        self.assertEqual(marker.passage_text(result), 'Before ▮ after.')
        self.assertEqual(stats['bars'], 1)

    def test_safety_filters_check_newly_recovered_words(self):
        for word, label in [('naked', 'BLOCK'), ('someone@example.com', 'PII')]:
            with self.subTest(label=label):
                page = self.doc.new_page()
                page.insert_text((50, 100), f'We found {word} near the island.')
                with self.assertRaisesRegex(ValueError, label+' safety filter'):
                    marker.rebuild(page, [['We found near the island.']])

    def test_target_under_box_fails_closed(self):
        self.text(50, 100, 'They discussed the private island today.')
        self.box(163, 89, 207, 103)
        with self.assertRaisesRegex(ValueError, 'target missing'):
            marker.rebuild(self.page, [['They discussed the ', {'w': 'PRIVATE', 't': 'private'}, ' island today.']])

    def test_hidden_target_cannot_move_to_another_occurrence(self):
        self.text(50, 100, 'They discussed the private island today.')
        self.text(50, 114, 'The matter was private.')
        self.box(163, 89, 207, 103)
        with self.assertRaisesRegex(ValueError, 'target missing'):
            marker.rebuild(self.page, [['They discussed the ', {'w': 'PRIVATE', 't': 'private'}, ' island today. The matter was private.']])

    def test_target_order_change_fails_closed(self):
        self.text(50, 100, 'The island was private.')
        paras = [['The ', {'w': 'PRIVATE', 't': 'private'}, ' was ', {'w': 'ISLAND', 't': 'island'}, '.']]
        with self.assertRaisesRegex(ValueError, 'target order changed|alignment coverage'):
            marker.rebuild(self.page, paras)

    def test_vertical_gaps_preserve_paragraphs(self):
        self.text(50, 100, 'First passage.')
        self.text(50, 150, 'Second passage.')
        result, _ = marker.rebuild(self.page, [['First passage. Second passage.']])
        self.assertEqual(result, [['First passage.'], ['Second passage.']])

    def test_repeated_target_uses_original_occurrence_with_punctuation(self):
        self.text(50, 100, 'The ranch manager drove to the ranch, then left the ranch.')
        target = {'w': 'RANCH', 't': 'ranch'}
        result, _ = marker.rebuild(self.page, [['The ranch manager drove to the ', target, ', then left the ranch.']])
        self.assertEqual(result, [['The ranch manager drove to the ', target, ', then left the ranch.']])

    def test_ambiguous_target_fails_closed(self):
        sentence = 'We found the quiet island in the early morning. '
        self.text(50, 100, sentence)
        self.text(50, 114, sentence)
        target = {'w': 'ISLAND', 't': 'island'}
        paras = [['We found the quiet ', target, ' in the early morning. '+sentence]]
        with self.assertRaisesRegex(ValueError, 'ambiguous target context'):
            marker.rebuild(self.page, paras)

    def test_build_paragraph_length_style(self):
        sentence = 'The island was quiet and the weather was pleasant. '
        for i in range(10):
            self.text(50, 100+i*14, sentence)
        result, _ = marker.rebuild(self.page, [[sentence*10]])
        self.assertGreater(len(result), 1)
        self.assertTrue(all(len(marker.passage_text([p])) < 350 for p in result))


if __name__ == '__main__':
    unittest.main()
