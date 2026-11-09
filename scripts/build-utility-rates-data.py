#!/usr/bin/env python3
"""Build the data file for the utility rate pages (build plan row 167). Standard library only: it runs on the jobs server.

Inputs:
  --data DIR         data/utility-rates from the repo: utilities.json and the frozen history files
                     (see freeze-history.py, freeze-annual.py).
  --monthly FILE...  EIA-861M sales_ult_cust_<YEAR>.xlsx for every year after the frozen history.
  --states FILE      EIA-861M sales_revenue.xlsx (state and US monthly since 2010).
  --territory FILE   EIA-861 Service_Territory_<YEAR>.xlsx (counties served).
  --cpi FILE         JSON {"CUUR0000SA0": {"2020-01": 257.97, ...}, "CUUR0000SEHF01": {...}}, months from 2020.

Output: <out>/utility-rates.json (schema gc-utility-rates/v1), <out>/csv/utilities/<slug>.csv and
<out>/csv/utility-rates-latest.csv.

Rules:
  One utility's month = its own row + every predecessor's row, in the states it serves today.
  EIA's months are kept as reported. Price = revenue / sales. Months with no revenue or sales stay gaps.
  A customer count is dropped only when one month alone is more than 40% away from both neighbours
  and those neighbours agree within 15% (a reporting slip: BGE July 2003 shows 106k homes among 1.06M).
  The 12-month figures: price = revenue over 12 months / sales over 12 months; bill and kWh per home use the
  median customer count of those months, so one bad count cannot move them.

Guards (non-zero exit, the last good file stays live): at least 34 of the monthly utilities carry the newest
month, the newest month never goes backwards, every 12-month price within 4-90 cents/kWh, no utility's
12-month price moving more than 20% between this file and the last one.
"""
import argparse, csv, datetime as dt, gzip, io, json, os, re, statistics, sys, zipfile
import xml.etree.ElementTree as ET

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
      'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
SKIP_IDS = {0, 88888, 99999}
SCHEMA = 'gc-utility-rates/v1'


def fail(msg):
    print('FAIL: ' + msg, file=sys.stderr)
    sys.exit(2)


def col_index(ref):
    n = 0
    for ch in re.match(r'[A-Z]+', ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_sheet(path, index=0, name=None):
    with zipfile.ZipFile(path) as z:
        shared = []
        if 'xl/sharedStrings.xml' in z.namelist():
            for si in ET.fromstring(z.read('xl/sharedStrings.xml')).findall('m:si', NS):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % NS['m'])))
        wb = ET.fromstring(z.read('xl/workbook.xml'))
        rels = {r.get('Id'): r.get('Target') for r in ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))}
        sheets = list(wb.find('m:sheets', NS))
        chosen = next((s for s in sheets if s.get('name') == name), None) if name else sheets[index]
        if chosen is None:
            fail('sheet %r not in %s' % (name, path))
        target = rels[chosen.get('{%s}id' % NS['r'])].lstrip('/')
        if not target.startswith('xl/'):
            target = 'xl/' + target
        out = []
        for _, el in ET.iterparse(io.BytesIO(z.read(target))):
            if el.tag != '{%s}row' % NS['m']:
                continue
            row = []
            for c in el.findall('m:c', NS):
                i = col_index(c.get('r'))
                while len(row) < i:
                    row.append(None)
                t, v = c.get('t'), c.find('m:v', NS)
                if t == 's' and v is not None:
                    val = shared[int(v.text)]
                elif t == 'inlineStr':
                    val = ''.join(x.text or '' for x in c.iter('{%s}t' % NS['m']))
                elif v is None or v.text is None:
                    val = None
                else:
                    try:
                        f = float(v.text)
                        val = int(f) if f.is_integer() else f
                    except ValueError:
                        val = v.text
                row.append(val)
            out.append(row)
            el.clear()
        return out


def fnum(s):
    if s in (None, '', '.'):
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def gz_rows(path):
    with gzip.open(path, 'rt') as f:
        yield from csv.DictReader(f)


def read_new_monthly(path):
    """Yield (uid, state, month, revenue_k, sales_mwh, customers, status) from a sales_ult_cust file."""
    rows = read_sheet(path)
    h = [str(c or '') for c in rows[2]]
    if h[:7] != ['Year', 'Month', 'Utility Number', 'Utility Name', 'State', 'Ownership', 'Data Status'] or rows[0][7] != 'RESIDENTIAL':
        fail('unexpected header in %s: %r' % (path, h[:9]))
    for r in rows[3:]:
        if len(r) < 8 or not isinstance(r[0], int) or not isinstance(r[1], int) or not isinstance(r[2], int):
            continue
        if r[2] in SKIP_IDS or r[5] == 'Behind the Meter' or re.search(r'adjust|state total', str(r[3]), re.I):
            continue
        g = lambda i: r[i] if len(r) > i and isinstance(r[i], (int, float)) else None
        yield r[2], r[4], '%04d-%02d' % (r[0], r[1]), g(7), g(8), g(9), r[6]


def rnd(x, n):
    return None if x is None else round(x, n)


def clean_customers(months, cust):
    """Blank a one-month reporting slip in the customer count. See the module docstring."""
    out = dict(cust)
    for i in range(1, len(months) - 1):
        a, b, c = out.get(months[i - 1]), cust.get(months[i]), cust.get(months[i + 1])  # a is the cleaned month, so a slip cannot flag its neighbour
        if a and b and c and abs(a / c - 1) <= 0.15 and abs(b / a - 1) > 0.40 and abs(b / c - 1) > 0.40:
            out[months[i]] = None
    return out


def add_month(ym, n):
    y, m = int(ym[:4]), int(ym[5:]) + n
    while m > 12:
        y, m = y + 1, m - 12
    while m < 1:
        y, m = y - 1, m + 12
    return '%04d-%02d' % (y, m)


def window(latest):
    return [add_month(latest, -i) for i in range(11, -1, -1)]


def twelve(month, cust, end):
    """12-month figures ending `end`, or None when fewer than 11 of the months have data."""
    ms = [m for m in window(end) if m in month]
    if len(ms) < 11:
        return None
    rev, mwh = sum(month[m][0] for m in ms), sum(month[m][1] for m in ms)
    cs = [cust[m] for m in ms if cust.get(m)]
    out = {'end': end, 'months': len(ms), 'gaps': [m for m in window(end) if m not in month],
           'price': round(rev / mwh * 100, 2), 'customers': None, 'kwh': None, 'bill': None}
    if len(cs) >= 6:
        c = statistics.median(cs)
        out.update(customers=int(c), kwh=round(mwh * 1000 / c / len(ms), 1), bill=round(rev * 1000 / c / len(ms), 2))
    return out


def load_states(path, data_dir):
    """Annual price per state and US, 1990 on; monthly 2010 on."""
    rows = read_sheet(path, name='Monthly-States')
    if [str(x or '') for x in rows[2][:4]] != ['Year', 'Month', 'State', 'Data Status'] or rows[0][4] != 'RESIDENTIAL':
        fail('unexpected header in sales_revenue: %r' % rows[2][:6])
    bym = {}
    for r in rows[3:]:
        if len(r) < 8 or not isinstance(r[0], int) or not isinstance(r[1], int) or not isinstance(r[4], (int, float)) or not isinstance(r[5], (int, float)) or not r[5]:
            continue
        ym = '%04d-%02d' % (r[0], r[1])
        bym.setdefault(r[2], {})[ym] = (r[4], r[5])
    if 'US' in bym:
        fail('sales_revenue now has a US row: check before summing the states')
    months = sorted(set.intersection(*[set(v) for v in bym.values()]))
    bym['US'] = {m: (sum(v[m][0] for v in bym.values()), sum(v[m][1] for v in bym.values())) for m in months}
    frozen = json.load(open(os.path.join(data_dir, 'state-annual-price-1990-2009.json')))['prices']
    annual, monthly, twelve_mo = {}, {}, {}
    for st, m in bym.items():
        last = sorted(m)[-12:]
        twelve_mo[st] = round(sum(m[k][0] for k in last) / sum(m[k][1] for k in last) * 100, 2)
        monthly[st] = [[k, round(m[k][0] / m[k][1] * 100, 2)] for k in sorted(m)]
        yrs = {}
        for k, v in m.items():
            a = yrs.setdefault(k[:4], [0.0, 0.0, 0])
            a[0] += v[0]; a[1] += v[1]; a[2] += 1
        ann = {y: frozen.get(st, {}).get(y) for y in frozen.get(st, {})}
        for y, a in yrs.items():
            if a[2] == 12:
                ann[y] = round(a[0] / a[1] * 100, 2)
        annual[st] = [[int(y), ann[y]] for y in sorted(ann)]
    return annual, monthly, twelve_mo


def load_cpi(data_dir, path):
    frozen = json.load(open(os.path.join(data_dir, 'cpi-1990-2019.json')))['series']
    new = json.load(open(path))
    out = {}
    for sid, key in (('CUUR0000SA0', 'all'), ('CUUR0000SEHF01', 'electricity')):
        s = dict(frozen[sid])
        s.update({k: float(v) for k, v in new[sid].items() if fnum(v) is not None})  # BLS has no October 2025 (shutdown): '-'
        if len(s) < 430:
            fail('CPI %s: only %d months' % (sid, len(s)))
        out[key] = s
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', required=True)
    ap.add_argument('--monthly', nargs='+', required=True)
    ap.add_argument('--states', required=True)
    ap.add_argument('--territory', required=True)
    ap.add_argument('--cpi', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--retrieved', default=dt.date.today().isoformat())
    a = ap.parse_args()

    utils = json.load(open(os.path.join(a.data, 'utilities.json')))['utilities']
    owner = {}
    for u in utils:
        for i in [u['eia_id']] + u['predecessors']:
            owner.setdefault(i, []).append(u)

    raw = {u['slug']: {} for u in utils}  # slug -> month -> [rev, mwh, cust, rows]
    by_state = {u['slug']: {} for u in utils}  # slug -> state -> month -> [rev, mwh, cust]

    def take(uid, st, ym, rev, mwh, cust):
        for u in owner.get(uid, ()):
            if st not in u['states'] or not rev or not mwh or rev <= 0 or mwh <= 0:
                continue
            m = raw[u['slug']].setdefault(ym, [0.0, 0.0, 0.0])
            m[0] += rev; m[1] += mwh; m[2] += cust or 0
            s = by_state[u['slug']].setdefault(st, {}).setdefault(ym, [0.0, 0.0, 0.0])
            s[0] += rev; s[1] += mwh; s[2] += cust or 0

    hist = [f for f in os.listdir(a.data) if re.match(r'eia861m-residential-1990-(\d{4})\.csv\.gz$', f)]
    if len(hist) != 1:
        fail('expected one frozen monthly file, found %r' % hist)
    frozen_to = int(hist[0][-11:-7])
    for r in gz_rows(os.path.join(a.data, hist[0])):
        take(int(r['utility_id']), r['state'], r['month'], fnum(r['revenue_k']), fnum(r['sales_mwh']), fnum(r['customers']))
    status = {}
    for path in a.monthly:
        for uid, st, ym, rev, mwh, cust, stat in read_new_monthly(path):
            if int(ym[:4]) <= frozen_to:
                continue
            status[ym] = stat
            take(uid, st, ym, rev, mwh, cust)

    latest = max(m for s in raw.values() for m in s)
    latest_y = int(latest[:4])

    # Annual tables
    parts = {u['slug']: {} for u in utils}  # year -> part -> [rev, mwh, cust]
    for r in gz_rows(os.path.join(a.data, 'eia861-annual-residential.csv.gz')):
        for u in owner.get(int(r['utility_id']), ()):
            if r['state'] not in u['states']:
                continue
            y = int(r['year'])
            p = parts[u['slug']].setdefault(y, {}).setdefault(r['part'], [0.0, 0.0, 0.0])
            p[0] += fnum(r['revenue_k']) or 0; p[1] += fnum(r['sales_mwh']) or 0; p[2] += fnum(r['customers']) or 0

    def weighted(acc, key, vals, w):
        a = acc.setdefault(key, [0.0] * (len(vals) + 1) + [[0.0] * len(vals)])
        for i, v in enumerate(vals):
            if v is not None:
                a[i] += v * w
                a[-1][i] += w

    rel, bench = {u['slug']: {} for u in utils}, {}
    for r in gz_rows(os.path.join(a.data, 'eia861-reliability.csv.gz')):
        y, st, std = int(r['year']), r['state'], r['standard']
        vals = [fnum(r['saidi_all']), fnum(r['saifi_all']), fnum(r['saidi_excl_major']), fnum(r['saifi_excl_major'])]
        w = fnum(r['customers']) or 1.0
        for u in owner.get(int(r['utility_id']), ()):
            if st in u['states']:
                weighted(rel[u['slug']], (y, std), vals, w)
        if std == 'IEEE' and fnum(r['customers']):
            weighted(bench, (y, 'US'), vals, w)
            weighted(bench, (y, st), vals, w)

    def done(acc):
        return [rnd(acc[i] / acc[-1][i], 3) if acc[-1][i] else None for i in range(4)]

    solar = {u['slug']: {} for u in utils}
    for r in gz_rows(os.path.join(a.data, 'eia861-net-metering.csv.gz')):
        for u in owner.get(int(r['utility_id']), ()):
            if r['state'] in u['states']:
                s = solar[u['slug']].setdefault(int(r['year']), [0.0, 0.0])
                s[0] += fnum(r['res_pv_installs']) or 0; s[1] += fnum(r['res_pv_mw']) or 0

    terr = read_sheet(a.territory, name='Counties_States')
    if [str(x or '') for x in terr[0][:6]] != ['Data Year', 'Utility Number', 'Utility Name', 'Short Form', 'State', 'County']:
        fail('unexpected Service_Territory header: %r' % terr[0][:6])
    terr_year = terr[1][0]
    counties = {}
    by_id = {u['eia_id']: u for u in utils}
    for r in terr[1:]:
        if len(r) > 5 and r[1] in by_id and r[4] and r[5]:
            counties.setdefault(by_id[r[1]]['slug'], {}).setdefault(r[4], set()).add(str(r[5]))

    st_annual, st_monthly, st_12 = load_states(a.states, a.data)
    cpi = load_cpi(a.data, a.cpi)
    cpi_end = max(cpi['all'])

    def cpi_year(y):
        v = [cpi['all'][k] for k in cpi['all'] if k[:4] == str(y)]
        return sum(v) / len(v) if len(v) >= 11 else None

    _w = [cpi['all'][m] for m in window(cpi_end) if m in cpi['all']]
    latest_cpi_12 = sum(_w) / len(_w)

    out_utils = []
    for u in utils:
        sl = u['slug']
        rec = {k: u[k] for k in ('rank', 'slug', 'brand', 'eia_name', 'eia_id', 'predecessors', 'states', 'ownership', 'monthly', 'note', 'tariff_url', 'tariff_checked')}
        pt = parts[sl]
        py = max(pt)
        lp = pt[py]
        g = lambda k, i: lp.get(k, [0, 0, 0])[i]
        homes = g('A', 2) + g('C', 2) + g('D', 2)
        rec['homes'] = {'year': py, 'total': int(homes), 'own_supply': int(g('A', 2) + g('D', 2)), 'delivery_only': int(g('C', 2)),
                        'own_supply_price': rnd((g('A', 0) + g('D', 0)) / (g('A', 1) + g('D', 1)) * 100, 2) if g('A', 1) + g('D', 1) else None,
                        'delivery_price': rnd(g('C', 0) / g('C', 1) * 100, 2) if g('C', 1) else None}
        rec['supply_history'] = [[y, int(pt[y].get('A', [0, 0, 0])[2] + pt[y].get('D', [0, 0, 0])[2]), int(pt[y].get('C', [0, 0, 0])[2])] for y in sorted(pt) if y >= 2001]

        months = sorted(raw[sl])
        cust_raw = {m: (raw[sl][m][2] or None) for m in months}
        cust = clean_customers(months, cust_raw)
        month_rows = []
        for m in months:
            r, w, _ = raw[sl][m]
            c = cust.get(m)
            month_rows.append([m, round(r / w * 100, 2), rnd(w * 1000 / c, 1) if c else None, rnd(r * 1000 / c, 2) if c else None, int(c) if c else None])
        rec['months'] = month_rows
        rec['flagged_customer_months'] = [m for m in months if cust_raw.get(m) and not cust.get(m)]

        # Annual: 12 reported months where we have them, otherwise the annual survey.
        ann = []
        for y in sorted(set(int(m[:4]) for m in months) | set(pt)):
            if y > latest_y or (y == latest_y and u['monthly']):
                continue
            ms = [m for m in months if m[:4] == str(y)]
            sv = pt.get(y, {})
            own = [sv.get('A', [0, 0, 0])[k] + sv.get('D', [0, 0, 0])[k] for k in range(3)]
            if len(ms) == 12:
                rv, mw = sum(raw[sl][m][0] for m in ms), sum(raw[sl][m][1] for m in ms)
                cs = [cust[m] for m in ms if cust.get(m)]
                c = statistics.median(cs) if len(cs) >= 6 else (own[2] or None)
                src = 'm'
            elif own[1] > 0 and own[0] > 0:
                rv, mw, c, src = own[0], own[1], own[2] or None, 'a'
            else:
                continue
            base = cpi_year(y)
            price = round(rv / mw * 100, 2)
            ann.append([y, price, rnd(mw * 1000 / c / 12, 1) if c else None, rnd(rv * 1000 / c / 12, 2) if c else None, int(c) if c else None,
                        rnd(price * latest_cpi_12 / base, 2) if base else None, src])
        rec['annual'] = ann

        if u['monthly']:
            end = months[-1]
            for back in (0, 1, 2):  # newest window with enough months
                now = twelve({m: raw[sl][m] for m in months}, cust, add_month(latest, -back))
                if now:
                    break
            if not now:
                fail('%s: no 12-month window near %s' % (sl, latest))
            prev = twelve({m: raw[sl][m] for m in months}, cust, add_month(now['end'], -12))
            rec['latest12'] = now
            rec['prior12'] = prev
            rec['has_latest_month'] = end == latest
            rec['by_state'] = {}
            for st, sm in by_state[sl].items():
                cs = {m: (v[2] or None) for m, v in sm.items()}
                t = twelve(sm, clean_customers(sorted(sm), cs), now['end'])
                if t:
                    rec['by_state'][st] = t
        else:
            y1, y0 = ann[-1], ann[-2]
            rec['latest12'] = {'end': '%d-12' % y1[0], 'months': 12, 'gaps': [], 'price': y1[1], 'customers': y1[4], 'kwh': y1[2], 'bill': y1[3]}
            rec['prior12'] = {'end': '%d-12' % y0[0], 'months': 12, 'gaps': [], 'price': y0[1], 'customers': y0[4], 'kwh': y0[2], 'bill': y0[3]}
            rec['has_latest_month'] = False
            rec['by_state'] = {}

        # Reliability: IEEE when any of it was reported that year; otherwise the utility's Other standard.
        rl = []
        for y in sorted({k[0] for k in rel[sl]}):
            std = 'IEEE' if (y, 'IEEE') in rel[sl] else 'Other'
            v = done(rel[sl][(y, std)])
            b = [rnd(bench[(y, 'US')][0] / bench[(y, 'US')][-1][0], 1)] if (y, 'US') in bench else [None]
            rl.append([y, std] + v + b)
        rec['reliability'] = rl
        rec['solar'] = [[y, int(v[0]), round(v[1], 1)] for y, v in sorted(solar[sl].items())]
        rec['counties'] = {st: sorted(c) for st, c in sorted(counties.get(sl, {}).items())}
        out_utils.append(rec)

    # Rank the 12-month price among the 40 (1 = highest)
    order = sorted(out_utils, key=lambda r: -r['latest12']['price'])
    for i, r in enumerate(order, 1):
        r['price_rank'] = i

    d = {
        'schema': SCHEMA,
        'built': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'latest': latest,
        'latest_status': status.get(latest, 'Final'),
        'frozen_to': frozen_to,
        'territory_year': terr_year,
        'source': {'retrieved': a.retrieved},
        'fields': {'months': ['month', 'price_cents_per_kwh', 'kwh_per_home', 'bill_usd_per_home', 'homes_on_own_supply'],
                   'annual': ['year', 'price_cents_per_kwh', 'kwh_per_home_month', 'bill_usd_per_home_month', 'homes_on_own_supply', 'price_in_latest_dollars', 'source_m_monthly_a_annual'],
                   'reliability': ['year', 'standard', 'saidi_all_minutes', 'saifi_all', 'saidi_excl_major_minutes', 'saifi_excl_major', 'us_saidi_all_minutes'],
                   'solar': ['year', 'home_solar_installs', 'home_solar_mw'],
                   'supply_history': ['year', 'homes_on_own_supply', 'homes_delivery_only']},
        'us_12': st_12['US'],
        'states_12': {k: v for k, v in st_12.items() if k != 'US'},
        'us_annual': st_annual['US'],
        'states_annual': {k: v for k, v in st_annual.items() if k != 'US'},
        'us_monthly': st_monthly['US'],
        'states_monthly': {k: v for k, v in st_monthly.items() if k != 'US'},
        'cpi': {'end': cpi_end, 'all_12mo_mean': round(latest_cpi_12, 3),
                'all_annual': [[y, round(cpi_year(y), 3)] for y in range(1990, 2100) if cpi_year(y)],
                'electricity_annual': [[y, round(sum(v) / len(v), 3)] for y in range(1990, 2100) for v in [[cpi['electricity'][k] for k in cpi['electricity'] if k[:4] == str(y)]] if len(v) >= 11]},
        'utilities': out_utils,
    }

    # Guards
    path = os.path.join(a.out, 'utility-rates.json')
    prev = None
    if os.path.exists(path):
        try:
            prev = json.load(open(path))
        except ValueError:
            prev = None
    monthly = [r for r in out_utils if r['monthly']]
    have = sum(1 for r in monthly if r['has_latest_month'])
    if have < 34:
        fail('only %d of %d monthly utilities have the newest month %s' % (have, len(monthly), latest))
    for r in out_utils:
        if not 4 <= r['latest12']['price'] <= 90:
            fail('%s: 12-month price %s outside 4-90 c/kWh' % (r['slug'], r['latest12']['price']))
    if prev and prev.get('schema') == SCHEMA:
        if prev['latest'] > latest:
            fail('newest month %s is older than the last file (%s)' % (latest, prev['latest']))
        old = {r['slug']: r['latest12']['price'] for r in prev['utilities']}
        for r in out_utils:
            if r['slug'] in old and abs(r['latest12']['price'] / old[r['slug']] - 1) > 0.20:
                fail('%s: 12-month price moved from %s to %s' % (r['slug'], old[r['slug']], r['latest12']['price']))

    os.makedirs(os.path.join(a.out, 'csv', 'utilities'), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(d, f, separators=(',', ':'))
    os.replace(tmp, path)
    for r in out_utils:
        with open(os.path.join(a.out, 'csv', 'utilities', r['slug'] + '.csv'), 'w', newline='') as f:
            w = csv.writer(f)
            if r['monthly']:
                w.writerow(['month', 'residential_price_cents_per_kwh', 'kwh_per_home', 'bill_usd_per_home', 'homes_on_own_supply'])
                w.writerows(r['months'])
            else:
                w.writerow(['year', 'residential_price_cents_per_kwh', 'kwh_per_home_month', 'bill_usd_per_home_month', 'homes', 'price_in_latest_dollars', 'source'])
                w.writerows(r['annual'])
    with open(os.path.join(a.out, 'csv', 'utility-rates-latest.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rank_by_homes', 'utility', 'eia_utility_id', 'states', 'homes_total', 'homes_on_own_supply', '12_months_to', 'price_cents_per_kwh', 'bill_usd_per_month', 'kwh_per_month', 'prior_year_price', 'delivery_only_price'])
        for r in sorted(out_utils, key=lambda x: x['rank']):
            n, p = r['latest12'], r['prior12'] or {}
            w.writerow([r['rank'], r['brand'], r['eia_id'], ' '.join(r['states']), r['homes']['total'], r['homes']['own_supply'], n['end'], n['price'], n['bill'], n['kwh'], p.get('price', ''), r['homes']['delivery_price'] or ''])
    print('OK latest=%s (%s) utilities=%d with_newest=%d/%d' % (latest, d['latest_status'], len(out_utils), have, len(monthly)))


if __name__ == '__main__':
    main()
