"""Read-only adapter for Vermont SOS static results. No campaign-finance data."""
from collections import defaultdict
from datetime import datetime, timezone
import json
from urllib.request import urlopen
from urllib.parse import urlparse

BASE = 'https://static.electionresults.vermont.gov'
TOWNS = set('ANDOVER|BALTIMORE|BARNARD|BETHEL|BRIDGEWATER|CAVENDISH|CHESTER|HARTFORD|HARTLAND|LUDLOW|NORWICH|PITTSFIELD|PLYMOUTH|POMFRET|READING|ROYALTON|SHARON|SPRINGFIELD|STOCKBRIDGE|THETFORD|WEATHERSFIELD|WEST WINDSOR|WESTON|WINDSOR|WOODSTOCK'.split('|'))

def fetch(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'static.electionresults.vermont.gov':
        raise ValueError('Only official SOS static feed URLs are allowed')
    with urlopen(url, timeout=20) as response:
        return json.load(response)

def feed_url(path):
    return BASE + '/' + path.replace('\\', '/').lstrip('/')

def normalize(senate, turnout):
    offices = [o for p in senate.get('d', []) for o in p.get('o', [])
               if o.get('dn', '').strip('_ ').upper() == 'WINDSOR']
    if len(offices) != 1:
        raise ValueError('Expected one Windsor Senate contest; feed schema needs review')
    office = offices[0]
    if office.get('vf') != 3:
        raise ValueError('Expected a vote-for-three Senate contest')
    rows = {}
    candidates = {}
    seen = set()
    for item in office.get('cs', []):
        if not item.get('tid'):  # district-wide summary must NEVER be added again
            continue
        town = item.get('tn', '').strip().upper()
        if town not in TOWNS:
            raise ValueError(f'Unexpected Windsor town: {town}')
        identity = (item['tid'], item.get('repd'), item.get('distCode'))
        if identity in seen:
            raise ValueError(f'Duplicate reporting split: {identity}')
        seen.add(identity)
        row = rows.setdefault(town, {'town': town, 'votes': {}, 'ballots': None, 'status': 'unreported', 'splits': []})
        row['splits'].append(item.get('repd', ''))
        for candidate in item.get('rc', []):
            if candidate.get('isWriteIn'):
                continue
            key = str(candidate['cid'])
            candidates[key] = {'key': key, 'name': candidate['cn'].title(), 'party': candidate.get('pn', '')}
            row['votes'][key] = row['votes'].get(key, 0) + int(candidate.get('vc') or 0)
    for item in turnout.get('d', []):
        town = item.get('tn', '').strip().upper()
        if town not in rows:
            continue
        row = rows[town]
        row['ballots'] = int(item.get('tvc') or 0)
        total, reported = int(item.get('tdis') or 0), int(item.get('tdisr') or 0)
        row['status'] = 'complete' if total > 0 and reported >= total else ('partial' if reported > 0 or row['ballots'] > 0 else 'unreported')
        if row['status'] == 'complete' and len(row['splits']) < total:
            row['status'] = 'partial'
    for row in rows.values():
        # Some result feeds precede turnout updates; show votes, never infer completeness.
        if row['status'] == 'unreported' and sum(row['votes'].values()) > 0:
            row['status'] = 'partial'
        b = row['ballots']
        if b is not None and b > 0 and (any(v > b for v in row['votes'].values()) or sum(row['votes'].values()) > 3*b):
            row['status'] = 'partial'
            row['warning'] = 'Vote and turnout feeds are not yet consistent; excluded from model'
    return {'rows': sorted(rows.values(), key=lambda r: r['town']), 'candidates': list(candidates.values())}

def pull(year=2026):
    elections = fetch(BASE + '/elections/elections.json')
    matches = [e for e in elections if e.get('electionYear') == year and e.get('electionTypeCode') == 'G' and e.get('electionCategoryCode') == 'S']
    if len(matches) != 1:
        raise ValueError(f'No unique {year} statewide general election is available from SOS yet')
    election = matches[0]
    manifest_url = BASE + '/elections/' + election['electionGuid'] + '.json'
    manifest = fetch(manifest_url)
    urls = [manifest_url]
    payloads = []
    for key in ('senate', 'turnOut'):
        config = manifest.get(key, {})
        if not config.get('isEnable') or not config.get('path'):
            raise ValueError(f'SOS has not published the {key} feed yet')
        url = feed_url(config['path'])
        urls.append(url)
        payloads.append(fetch(url))
    data = normalize(*payloads)
    data.update(year=year, election=election['electionName'], official=bool(election.get('isOfficial')),
                fetchedAt=datetime.now(timezone.utc).isoformat(),
                feedUpdated=manifest.get('lastUpdatedDate'), urls=urls)
    return data
