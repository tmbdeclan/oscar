import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sos import normalize

class AdapterTests(unittest.TestCase):
    def test_splits_and_district_summary(self):
        def split(n,v):
            return {'tid':104,'tn':'HARTFORD','repd':n,'distCode':'WDR 1','rc':[{'cid':1,'cn':'CANDIDATE','vc':v}]}
        payload={'d':[{'o':[{'dn':'WINDSOR_','vf':3,'cs':[split('A',20),split('B',30),{'tid':0,'tn':'District Wide','rc':[{'cid':1,'cn':'CANDIDATE','vc':50}]}]}]}]}
        turnout={'d':[{'tn':'HARTFORD','tvc':100,'tdis':2,'tdisr':2}]}
        result=normalize(payload,turnout)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['votes']['1'],50)
        self.assertEqual(result['rows'][0]['status'],'complete')
        payload['d'][0]['o'][0]['cs'].append(split('B',30))
        with self.assertRaisesRegex(ValueError,'Duplicate'):
            normalize(payload,turnout)

    def test_missing_turnout_does_not_imply_complete(self):
        payload={'d':[{'o':[{'dn':'WINDSOR_','vf':3,'cs':[{'tid':104,'tn':'HARTFORD','repd':'A','rc':[{'cid':1,'cn':'C','vc':1}]}]}]}]}
        self.assertEqual(normalize(payload,{'d':[]})['rows'][0]['status'],'partial')


class HouseAdapterTests(unittest.TestCase):
    def make_office(self, code='WDR 1', towns=('WINDSOR',), seats=2):
        return {'dc':code,'dn':code,'vf':seats,'cs':[{'tid':i+10,'tn':town,'repd':code,'distCode':code,'rc':[{'cid':1,'cn':'A','vc':20,'pn':'D'},{'cid':2,'cn':'B','vc':15,'pn':'R'},{'cid':3,'cn':'C','vc':10,'pn':'I'}],'wc':[{'cid':9,'cn':'NAMED WRITE-IN','vc':3,'isWriteIn':True},{'cid':0,'cn':'OTHER WRITEIN','vc':100}]} for i,town in enumerate(towns)]}
    def test_house_full_contest_and_writeins(self):
        from sos import normalize_house
        o=self.make_office(towns=('WINDSOR','HANCOCK'))
        o['cs'].append({'tid':0,'tn':'DISTRICT TOTAL','rc':[{'cid':1,'cn':'A','vc':9999}]})
        bundle=normalize_house({'d':[{'o':[o]}]},{'d':[{'tn':t,'tvc':1000,'tdis':1,'tdisr':1} for t in ('WINDSOR','HANCOCK')]})
        race=bundle['races'][0]
        self.assertEqual(len(race['rows']),2)
        self.assertEqual(sum(r['votes']['1'] for r in race['rows']),40)
        self.assertEqual(len(race['candidates']),4)
        self.assertEqual(race['rows'][0]['otherWriteIns'],100)
        self.assertTrue(all(r['status']=='complete' for r in race['rows']))
    def test_split_house_town_and_duplicates(self):
        from sos import normalize_house
        a,b=self.make_office('WDR 4',('HARTFORD',),1),self.make_office('WDR 6',('HARTFORD',),2)
        t={'d':[{'tn':'HARTFORD','tvc':100,'tdis':2,'tdisr':1}]}
        races=normalize_house({'d':[{'o':[a,b]}]},t)['races']
        self.assertTrue(all(r['rows'][0]['status']=='partial' for r in races))
        self.assertTrue(all(r['rows'][0]['ballots'] is None and r['rows'][0]['partialTown'] for r in races))
        a['cs'].append(a['cs'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate'):normalize_house({'d':[{'o':[a,b]}]},t)
    def test_house_failure_retains_senate(self):
        from unittest.mock import patch
        from sos import pull,BASE
        elections=[{'electionYear':2026,'electionTypeCode':'G','electionCategoryCode':'S','electionGuid':'test','electionName':'TEST','isOfficial':False}]
        manifest={k:{'isEnable':True,'path':k+'.json'} for k in ('senate','turnOut','house')}
        senate={'d':[{'o':[{'dn':'WINDSOR','vf':3,'cs':[{'tid':1,'tn':'WINDSOR','repd':'WDR 1','rc':[{'cid':1,'cn':'A','vc':20}]}]}]}]}
        def fake(url):
            if url.endswith('elections.json'):return elections
            if url.endswith('test.json'):return manifest
            if url.endswith('senate.json'):return senate
            if url.endswith('turnOut.json'):return {'d':[]}
            raise ValueError('House feed unavailable')
        with patch('sos.fetch',side_effect=fake):
            result=pull();self.assertEqual(result['rows'][0]['votes']['1'],20);self.assertIn('houseError',result)

if __name__=='__main__':unittest.main()
