"""Read-only adapter for Vermont SOS static results. No campaign-finance data."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
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

def normalize_house(house, turnout):
    """Full House contests overlapping the Senate footprint, without district totals."""
    offices = [o for group in house.get('d', []) for o in group.get('o', [])]
    selected = [o for o in offices if any(item.get('tid') and item.get('tn', '').strip().upper() in TOWNS for item in o.get('cs', []))]
    if not selected:
        raise ValueError('No overlapping House contests found; prior House results retained')
    memberships = defaultdict(set)
    for office in offices:
        for item in office.get('cs', []):
            if item.get('tid'):
                memberships[item.get('tn', '').strip().upper()].add(office.get('dc'))
    turnout_by_town = {item.get('tn', '').strip().upper(): item for item in turnout.get('d', [])}
    races, contest_keys = [], set()
    def count(value):
        if value is None: return 0
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError('Invalid House vote count')
        return value
    for office in selected:
        key, seats = office.get('dc'), office.get('vf')
        if not isinstance(key, str) or not key or key in contest_keys or seats not in (1, 2):
            raise ValueError('Unexpected House district or seat count')
        contest_keys.add(key)
        candidates, rows, seen = {}, {}, set()
        for item in office.get('cs', []):
            if not item.get('tid'): continue
            town = item.get('tn', '').strip().upper()
            identity = (item['tid'], item.get('repd'), item.get('distCode'))
            if identity in seen: raise ValueError(f'Duplicate House reporting split: {key} {identity}')
            seen.add(identity)
            row = rows.setdefault(town, {'town': town, 'votes': {}, 'ballots': None, 'status': 'unreported', 'splits': [], 'otherWriteIns': 0, 'partialTown': len(memberships[town]) > 1})
            row['splits'].append(item.get('repd', ''))
            used_candidates = set()
            for candidate in [*item.get('rc', []), *item.get('wc', [])]:
                votes = count(candidate.get('vc'))
                if not candidate.get('cid'):
                    row['otherWriteIns'] += votes
                    continue
                cid = str(candidate['cid'])
                if cid in used_candidates: raise ValueError('Duplicate House candidate within a split')
                used_candidates.add(cid)
                candidates[cid] = {'key': cid, 'name': str(candidate.get('cn') or 'Unnamed candidate').title(), 'party': candidate.get('pn') or ('WRITE-IN' if candidate.get('isWriteIn') else ''), 'writeIn': bool(candidate.get('isWriteIn')), 'color': candidate.get('pco') or ''}
                row['votes'][cid] = row['votes'].get(cid, 0) + votes
        for row in rows.values():
            item = turnout_by_town.get(row['town'], {})
            total, reported = count(item.get('tdis')), count(item.get('tdisr'))
            town_ballots = count(item.get('tvc'))
            # Town-wide turnout is not a valid ballot denominator for part of Hartford.
            row['ballots'] = None if row['partialTown'] else town_ballots
            positive_votes = sum(row['votes'].values()) + row['otherWriteIns'] > 0
            row['status'] = 'complete' if total > 0 and reported >= total else ('partial' if positive_votes or (not row['partialTown'] and (reported > 0 or town_ballots > 0)) else 'unreported')
            if row['partialTown'] and reported > 0 and row['status'] != 'complete' and not positive_votes:
                row['warning'] = 'Town splits are reporting; this House contest has no positive counts yet'
            for cid in candidates: row['votes'].setdefault(cid, 0)
            b = row['ballots']
            if b and (any(v > b for v in row['votes'].values()) or sum(row['votes'].values()) + row['otherWriteIns'] > seats*b):
                row['status'] = 'partial'
                row['warning'] = 'House votes and town turnout are not yet synchronized'
        races.append({'key': key, 'name': str(office.get('dn') or key).title(), 'seats': seats, 'candidates': sorted(candidates.values(), key=lambda c: c['name']), 'rows': sorted(rows.values(), key=lambda r: r['town'])})
    return {'races': sorted(races, key=lambda race: (not race['key'].startswith('WDR '), race['key']))}


def pull(year=2026):
    elections = fetch(BASE + '/elections/elections.json')
    matches = [e for e in elections if e.get('electionYear') == year and e.get('electionTypeCode') == 'G' and e.get('electionCategoryCode') == 'S']
    if len(matches) != 1:
        raise ValueError(f'No unique {year} statewide general election is available from SOS yet')
    election = matches[0]
    manifest_url = BASE + '/elections/' + election['electionGuid'] + '.json'
    manifest = fetch(manifest_url)
    urls = [manifest_url]
    with ThreadPoolExecutor(max_workers=3) as executor:
        pending = {}
        for key in ('senate', 'turnOut', 'house'):
            config = manifest.get(key, {})
            if config.get('isEnable') and config.get('path'):
                url = feed_url(config['path']); urls.append(url)
                pending[key] = executor.submit(fetch, url)
            elif key != 'house':
                raise ValueError(f'SOS has not published the {key} feed yet')
        senate, turnout = pending['senate'].result(), pending['turnOut'].result()
        data = normalize(senate, turnout)
        try:
            if 'house' not in pending: raise ValueError('SOS has not published the House feed yet')
            data['house'] = normalize_house(pending['house'].result(), turnout)
        except Exception as exc:
            data['houseError'] = f'House refresh unavailable: {exc}'
    metadata = dict(year=year, election=election['electionName'], official=bool(election.get('isOfficial')),
                    fetchedAt=datetime.now(timezone.utc).isoformat(), feedUpdated=manifest.get('lastUpdatedDate'), urls=urls)
    data.update(metadata)
    if 'house' in data: data['house'].update(metadata)
    return data
