"""RSS payload-size regression tests; all fixture articles are invented.
No live orders or external model calls.
"""
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime,timezone,timedelta
from email.utils import format_datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from ai_research import MAX_BYTES,MAX_HEADLINES,ResearchUnavailable,fetch_headlines,approve_entry

class LargeNewsFeedTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,4,17,0,0,tzinfo=timezone.utc)
        self.rss=self._make_feed()
    def _make_feed(self,pad=1400):
        rss=ET.Element("rss")
        ch=ET.SubElement(rss,"channel")
        for i in range(100):
            item=ET.SubElement(ch,"item")
            ET.SubElement(item,"title").text=f"AMD market update {i:03d}"
            ET.SubElement(item,"source").text="Fixture Business News"
            ET.SubElement(item,"pubDate").text=format_datetime(self.now-timedelta(minutes=i))
            ET.SubElement(item,"link").text=f"https://news.google.com/rss/articles/fixture{i}"
            ET.SubElement(item,"description").text="safe neutral RSS description "+"x"*pad
        return ET.tostring(rss,encoding="utf-8",xml_declaration=True)
    def test_100_item_rss_above_old_128k_filters_to_only_six_headlines(self):
        self.assertGreater(len(self.rss),131072)
        self.assertLess(len(self.rss),MAX_BYTES)
        news=fetch_headlines("AMD",self.now,fetch=lambda _url:self.rss)
        self.assertEqual(len(news),MAX_HEADLINES)
        self.assertEqual(news[0]["title"],"AMD market update 000")
        self.assertEqual(news[-1]["title"],"AMD market update 005")
        self.assertEqual(set(news[0]),{"title","source","published_at","url"})
        self.assertNotIn("description",news[0])
    def test_successful_model_handoff_receives_only_six_bounded_public_headlines(self):
        invocations=[]
        def classifier(symbol,headlines):
            invocations.append((symbol,headlines))
            return {"ticker":symbol,"model":"fixture","sentiment":1,"impact":1,
                    "catalyst":"Fixture catalyst","downside_risk":"Fixture uncertainty"}
        approved,reason=approve_entry("AMD",self.now,
            get_headlines=lambda symbol,when:fetch_headlines(symbol,when,fetch=lambda _:self.rss),
            classifier=classifier)
        self.assertTrue(approved)
        self.assertEqual(len(invocations),1)
        self.assertEqual(invocations[0][0],"AMD")
        self.assertEqual(len(invocations[0][1]),MAX_HEADLINES)
        self.assertIn("AI news gate PASS",reason)
    def test_unbounded_rss_still_fails_closed_before_model_call(self):
        excessive=self._make_feed(pad=6000)
        self.assertGreater(len(excessive),MAX_BYTES)
        with self.assertRaisesRegex(ResearchUnavailable,"News feed exceeds size limit"):
            fetch_headlines("AMD",self.now,fetch=lambda _:excessive)
        invoked=[]
        def classifier(*args):
            invoked.append(True)
            raise AssertionError("Oversized feed must never be sent to model")
        approved,reason=approve_entry("AMD",self.now,
            get_headlines=lambda symbol,when:fetch_headlines(symbol,when,fetch=lambda _:excessive),
            classifier=classifier)
        self.assertFalse(approved)
        self.assertIn("News feed exceeds size limit",reason)
        self.assertFalse(invoked)
    def test_model_headline_limit_and_news_window_unchanged(self):
        self.assertEqual(MAX_HEADLINES,6)
        self.assertEqual(MAX_BYTES,524288)

if __name__=="__main__":unittest.main()
