"""Conditional SOS release detection with result payloads cached by published version."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from hashlib import sha256
from statistics import median
from threading import RLock
from time import monotonic
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen
try:
    from .sos import BASE, fetch, feed_url, normalize, normalize_house
except ImportError:
    from sos import BASE, fetch, feed_url, normalize, normalize_house


def utc_now():
    return datetime.now(timezone.utc)


def manifest_request(url, etag=None, modified=None):
    headers = {'Cache-Control': 'no-cache', 'Accept': 'application/json'}
    if etag: headers['If-None-Match'] = etag
    if modified: headers['If-Modified-Since'] = modified
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response), dict(response.headers.items())
    except HTTPError as exc:
        if exc.code != 304: raise
        headers=dict(exc.headers.items());exc.close();return None, headers


class FeedMonitor:
    """One shared monitor per host; no result downloads until feed paths change."""
    def __init__(self, year=2026, fetch_json=fetch, read_manifest=manifest_request, now=utc_now, clock=monotonic):
        self.year, self.fetch_json, self.read_manifest = year, fetch_json, read_manifest
        self.now, self.clock, self.lock = now, clock, RLock()
        self.election = self.manifest = self.data = None
        self.election_at = self.check_at = float('-inf')
        self.headers, self.payloads, self.publications = {}, {}, []
        self.version = self.data_version = None
        self.last_checked = self.last_success = None

    def status(self, error=None):
        modified = self.headers.get('last-modified')
        try: published = parsedate_to_datetime(modified).astimezone(timezone.utc) if modified else None
        except (ValueError, TypeError): published = None
        intervals = [(b-a).total_seconds() for a,b in zip(self.publications, self.publications[1:])]
        near_five = [v for v in intervals if 240 <= v <= 360]
        seconds = round(median(near_five)) if len(near_five) >= 2 else 300
        cache = re.search(r'max-age=(\d+)', self.headers.get('cache-control', ''))
        return {'lastCheckedAt': self.last_checked, 'lastSuccessfulCheckAt': self.last_success,
                'publishedAt': published.isoformat() if published else None,
                'feedUpdated': (self.manifest or {}).get('lastUpdatedDate'),
                'estimatedNextAt': (published+timedelta(seconds=seconds)).isoformat() if published else None,
                'cadenceSeconds': seconds, 'cadenceBasis': 'observed recent releases' if len(near_five)>=2 else 'assumed five-minute cadence',
                'sourceCacheSeconds': int(cache.group(1)) if cache else None,
                'conditionalChecks': True, 'error': error}

    def _election(self):
        if self.election is None or self.clock()-self.election_at >= 3600:
            rows=self.fetch_json(BASE+'/elections/elections.json')
            matches=[e for e in rows if e.get('electionYear')==self.year and e.get('electionTypeCode')=='G' and e.get('electionCategoryCode')=='S']
            if len(matches)!=1: raise ValueError(f'No unique {self.year} statewide general election is available')
            election=matches[0]
            if self.election and self.election['electionGuid']!=election['electionGuid']:
                self.manifest=None;self.headers={};self.check_at=float('-inf');self.publications=[]
            self.election=election;self.election_at=self.clock()
        return BASE+'/elections/'+self.election['electionGuid']+'.json'

    def _download(self, url):
        if url not in self.payloads: self.payloads[url]=self.fetch_json(url)
        return self.payloads[url]

    def _results(self, manifest_url):
        urls=[manifest_url]
        with ThreadPoolExecutor(max_workers=3) as executor:
            pending={}
            for key in ('senate','turnOut','house'):
                config=self.manifest.get(key,{})
                if config.get('isEnable') and config.get('path'):
                    url=feed_url(config['path']);urls.append(url);pending[key]=executor.submit(self._download,url)
                elif key!='house': raise ValueError(f'SOS has not published the {key} feed yet')
            turnout=pending['turnOut'].result()
            data=normalize(pending['senate'].result(),turnout)
            try:
                if 'house' not in pending: raise ValueError('SOS has not published the House feed yet')
                data['house']=normalize_house(pending['house'].result(),turnout)
            except Exception as exc: data['houseError']=f'House refresh unavailable: {exc}'
        metadata=dict(year=self.year,election=self.election['electionName'],
                      official=bool(self.manifest.get('electionDetails',{}).get('isOfficial',self.election.get('isOfficial'))),
                      fetchedAt=self.now().isoformat(),feedUpdated=self.manifest.get('lastUpdatedDate'),urls=urls)
        data.update(metadata)
        if 'house' in data:data['house'].update(metadata)
        # Bound memory: keep only successful payloads from the current release.
        self.payloads={url:value for url,value in self.payloads.items() if url in urls}
        return data

    def check(self, known_version=None, force=False):
        with self.lock:
            try:
                manifest_url=self._election()
                if force or self.manifest is None or self.clock()-self.check_at>=5:
                    self.last_checked=self.now().isoformat()
                    manifest,headers=self.read_manifest(manifest_url,self.headers.get('etag'),self.headers.get('last-modified'))
                    self.headers.update({k.lower():v for k,v in headers.items()})
                    if manifest is not None:self.manifest=manifest
                    if self.manifest is None:raise ValueError('SOS returned no initial feed index')
                    self.last_success=self.now().isoformat();self.check_at=self.clock()
                    release={k:self.manifest.get(k,{}) for k in ('senate','turnOut','house')}
                    release['official']=self.manifest.get('electionDetails',{}).get('isOfficial',self.election.get('isOfficial'))
                    version=sha256(json.dumps(release,sort_keys=True).encode()).hexdigest()
                    if version!=self.version:
                        published=self.status().get('publishedAt')
                        if published:
                            stamp=datetime.fromisoformat(published)
                            if not self.publications or stamp>self.publications[-1]:self.publications=(self.publications+[stamp])[-8:]
                        self.version=version
                recovering=bool(self.data and self.data.get('houseError'))
                if self.data is None or self.data_version!=self.version or recovering:
                    data=self._results(manifest_url)
                    self.data,self.data_version=data,self.version
                unchanged=known_version==self.version and not force and not recovering and not self.data.get('houseError')
                return {'year':self.year,'version':self.version,'unchanged':unchanged,
                        'timing':self.status(), 'data':None if unchanged else self.data}
            except Exception:
                # Failed checks never replace the last successful result bundle.
                raise
