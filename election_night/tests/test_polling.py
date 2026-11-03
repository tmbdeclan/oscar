import unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from email.utils import format_datetime
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from polling import FeedMonitor

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tick=0;self.calls=[];self.requests=[];self.release=0;self.fail_index=False;self.fail_house=False
        self.start=datetime(2026,11,4,0,0,tzinfo=timezone.utc)
        self.manifest={'lastUpdatedDate':'SOS timestamp','electionDetails':{'isOfficial':False},**{k:{'isEnable':True,'path':k+'-v0.json'} for k in ('senate','turnOut','house')}}
        def fetch(url):
            self.calls.append(url)
            if url.endswith('elections.json'):return [{'electionYear':2026,'electionTypeCode':'G','electionCategoryCode':'S','electionGuid':'test','electionName':'TEST'}]
            if self.fail_house and '/house-' in url:raise RuntimeError('House temporarily unavailable')
            return {'url':url}
        def read(url,etag,modified):
            self.requests.append((url,etag,modified))
            if self.fail_index:raise RuntimeError('Index unavailable')
            headers={'ETag':'v'+str(self.release),'Last-Modified':format_datetime(self.start+timedelta(seconds=self.release*300),usegmt=True),'Cache-Control':'public, max-age=60'}
            return (None if etag==headers['ETag'] else self.manifest.copy()),headers
        self.monitor=FeedMonitor(fetch_json=fetch,read_manifest=read,now=lambda:self.start+timedelta(seconds=self.tick),clock=lambda:self.tick)
        self.senate=patch('polling.normalize',side_effect=lambda *args:{'rows':[],'candidates':[]});self.senate.start()
        self.house=patch('polling.normalize_house',side_effect=lambda *args:{'races':[]});self.house.start()
        self.addCleanup(patch.stopall)
    def advance(self,seconds=15):self.tick+=seconds
    def new_release(self):
        self.release+=1;self.tick=self.release*300
        self.manifest={**self.manifest,**{k:{'isEnable':True,'path':k+f'-v{self.release}.json'} for k in ('senate','turnOut','house')}}
    def test_conditional_index_and_no_redundant_result_downloads(self):
        first=self.monitor.check();self.assertEqual(len(self.calls),4);self.assertIsNotNone(first['data'])
        self.advance();second=self.monitor.check(first['version'])
        self.assertTrue(second['unchanged']);self.assertIsNone(second['data']);self.assertEqual(len(self.calls),4)
        self.assertEqual(self.requests[-1][1],'v0');self.assertEqual(second['timing']['sourceCacheSeconds'],60)
        self.advance(1);self.monitor.check(first['version']);self.assertEqual(len(self.requests),2)
        manual=self.monitor.check(first['version'],force=True);self.assertIsNotNone(manual['data']);self.assertEqual(len(self.calls),4)
    def test_new_release_downloads_immediately_and_learns_estimate(self):
        first=self.monitor.check();self.new_release();second=self.monitor.check(first['version'])
        self.assertNotEqual(first['version'],second['version']);self.assertEqual(len(self.calls),7)
        self.assertEqual(second['timing']['cadenceBasis'],'assumed five-minute cadence')
        self.new_release();third=self.monitor.check(second['version'])
        self.assertEqual(third['timing']['cadenceBasis'],'observed recent releases');self.assertEqual(third['timing']['cadenceSeconds'],300)
        self.assertEqual(third['timing']['estimatedNextAt'],(self.start+timedelta(seconds=900)).isoformat())
    def test_failed_index_retains_last_success(self):
        first=self.monitor.check();saved=self.monitor.data;self.advance();self.fail_index=True
        with self.assertRaisesRegex(RuntimeError,'Index unavailable'):self.monitor.check(first['version'])
        self.assertIs(self.monitor.data,saved);self.assertEqual(len(self.calls),4)
        self.assertEqual(self.monitor.status('failed')['error'],'failed')
    def test_house_recovery_does_not_redownload_successful_feeds(self):
        self.fail_house=True;first=self.monitor.check();self.assertIn('houseError',first['data']);self.advance();self.fail_house=False
        second=self.monitor.check(first['version']);self.assertNotIn('houseError',second['data']);self.assertFalse(second['unchanged'])
        self.assertEqual(sum('/senate-' in u for u in self.calls),1);self.assertEqual(sum('/turnOut-' in u for u in self.calls),1);self.assertEqual(sum('/house-' in u for u in self.calls),2)
    def test_only_changed_feed_downloaded(self):
        first=self.monitor.check();self.release=1;self.advance();self.manifest={**self.manifest,'house':{'isEnable':True,'path':'house-v1.json'}}
        self.monitor.check(first['version']);self.assertEqual(len(self.calls),5)


class ConditionalRequestTests(unittest.TestCase):
    def test_sends_revalidation_headers_and_accepts_304(self):
        from polling import manifest_request
        from urllib.error import HTTPError
        from email.message import Message
        headers=Message();headers['ETag']='same';headers['Cache-Control']='public, max-age=60'
        def unchanged(request,timeout):
            self.assertEqual(request.get_header('If-none-match'),'same')
            self.assertEqual(request.get_header('If-modified-since'),'Mon, 02 Nov 2026 23:00:00 GMT')
            self.assertEqual(request.get_header('Cache-control'),'no-cache')
            raise HTTPError(request.full_url,304,'Not Modified',headers,None)
        with patch('polling.urlopen',side_effect=unchanged):
            body,returned=manifest_request('https://static.electionresults.vermont.gov/elections/test.json','same','Mon, 02 Nov 2026 23:00:00 GMT')
        self.assertIsNone(body);self.assertEqual(returned['ETag'],'same')

if __name__=='__main__':unittest.main()
