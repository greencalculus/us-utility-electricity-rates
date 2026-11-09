#!/usr/bin/env python3
"""One-off (re-run once a year when EIA publishes a new EIA-861): freeze the annual utility files.

Input: a folder holding one sub-folder per year, u1990 .. uYYYY, each the unzipped EIA-861 annual zip
(https://www.eia.gov/electricity/data/eia861/; 1990-2011 are archive/zip/f861YY.zip, later f861YYYY.zip).
Needs xlrd + openpyxl (Mac only).

Output, in data/utility-rates/:
  eia861-annual-residential.csv.gz  year,utility_id,state,part,revenue_k,sales_mwh,customers
      part: A bundled, B energy-only, C delivery-only, D bundled by a retail power marketer (Texas).
      1990-2000 have no parts and are written as A.
  eia861-reliability.csv.gz         year,utility_id,state,standard,saidi_all,saifi_all,caidi_all,saidi_excl_major,saifi_excl_major,customers
      standard: IEEE (IEEE 1366) or Other, as the utility reported. From 2013.
  eia861-net-metering.csv.gz        year,utility_id,state,res_pv_installs,res_pv_mw
      Residential solar on net metering, summed over the utility's balancing-area rows. From 2013.

Exits non-zero when a year's file is missing or a layout gives too few rows.
Usage: python3 freeze-annual.py UNZIPPED_DIR
"""
import csv, glob, gzip, io, os, re, shutil, sys, tempfile, warnings
import xlrd, openpyxl

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'data', 'utility-rates')
SKIP_IDS = {0, 88888, 99999}


def sheets(path):
    """[(sheet name, rows)] for an .xls or .xlsx (some .xls are really xlsx)."""
    try:
        book = xlrd.open_workbook(path)
        return [(s.name, [s.row_values(r) for r in range(s.nrows)]) for s in book.sheets()]
    except xlrd.XLRDError:
        pass
    tmp = None
    if path.lower().endswith('.xls'):
        tmp = tempfile.mktemp(suffix='.xlsx')
        shutil.copy(path, tmp)
    try:
        book = openpyxl.load_workbook(tmp or path, read_only=True, data_only=True)
        return [(w.title, [list(r) for r in w.iter_rows(values_only=True)]) for w in book.worksheets]
    finally:
        if tmp:
            os.unlink(tmp)


def num(x):
    if x in (None, '', '.', '*'):
        return None
    try:
        return float(str(x).replace(',', ''))
    except ValueError:
        return None


def uid_of(x):
    try:
        u = int(float(x))
    except (TypeError, ValueError):
        return None
    return None if u in SKIP_IDS else u


def fmt(v):
    return '' if v is None else ('%d' % v if float(v).is_integer() else repr(round(v, 3)))


def find_header(rows, *names):
    for i, r in enumerate(rows[:15]):
        up = [str(c).strip().upper() if c is not None else '' for c in r]
        if all(n in up for n in names):
            return i, up
    return None, None


def one(year_dir, *patterns):
    for p in patterns:
        hits = [f for f in glob.glob(os.path.join(year_dir, '*')) if re.search(p, os.path.basename(f), re.I)]
        if hits:
            return sorted(hits)[0]
    return None


def sales_1990_98(y, d):
    rows = sheets(one(d, r'^F861TYP1\.xls$'))[0][1]
    h = rows[0]
    slots = [(i, m.group(1)) for i, n in enumerate(h) for m in [re.match(r'STCODE(\d+)_1$', str(n))] if m]
    ix = {n: i for i, n in enumerate(h)}
    for r in rows[1:]:
        u = uid_of(r[ix['UTILCODE']])
        if not u:
            continue
        for col, k in slots:
            st = str(r[col] or '').strip()
            if len(st) != 2:
                continue
            yield y, u, st, 'A', num(r[ix['REV%s_1' % k]]), num(r[ix['MWH%s_1' % k]]), num(r[ix['CONSUM%s_1' % k]])


def sales_1999_00(y, d):
    rows = sheets(one(d, r'^FILE2\.xls$'))[0][1]
    h = [str(c).strip().upper() for c in rows[0]]
    cust = 'RESCONS_' if 'RESCONS_' in h else 'RESCONS'
    for r in rows[1:]:
        u = uid_of(r[h.index('UTILCODE')])
        if u:
            yield y, u, str(r[h.index('STATE')]).strip(), 'A', num(r[h.index('RESREV')]), num(r[h.index('RESSALES')]), num(r[h.index(cust)])


def sales_2001_11(y, d):
    rows = sheets(one(d, r'^file2(_\d{4})?\.xls$'))[0][1]
    # Fixed order in every year: year, id, name, part, service, data type, state, owner, res rev, res sales, res cust.
    # Header wording changes and from 2008 sits on a second or third row, so rows are told by a numeric id in column 1.
    head = ' '.join(str(c).upper() for r in rows[:4] for c in r[:12])
    if 'PART' not in head or 'STATE' not in head:
        sys.exit('%d: file2 header not recognised' % y)
    for r in rows:
        if len(r) < 11 or not str(r[3]).strip() in ('A', 'B', 'C', 'D'):
            continue
        u = uid_of(r[1])
        if u:
            yield y, u, str(r[6]).strip(), str(r[3]).strip(), num(r[8]), num(r[9]), num(r[10])


def sales_2012_on(y, d):
    f = one(d, r'^Sales_Ult_Cust_\d{4}\.xlsx?$')
    rows = dict(sheets(f)).get('States') or sheets(f)[0][1]
    i, h = find_header(rows, 'UTILITY NUMBER', 'PART', 'STATE')
    if i is None:
        sys.exit('%d: sales header not found' % y)
    first = h.index('THOUSANDS DOLLARS') if 'THOUSANDS DOLLARS' in h else h.index('THOUSAND DOLLARS')
    for r in rows[i + 1:]:
        u = uid_of(r[h.index('UTILITY NUMBER')])
        part = str(r[h.index('PART')]).strip()
        own = str(r[h.index('OWNERSHIP')]).strip() if 'OWNERSHIP' in h else ''
        if u and part in ('A', 'B', 'C', 'D') and own != 'Behind the Meter':
            yield y, u, str(r[h.index('STATE')]).strip(), part, num(r[first]), num(r[first + 1]), num(r[first + 2])


def reliability(y, d):
    f = one(d, r'^Reliability_\d{4}\.xlsx?$')
    if not f:
        return
    rows = sheets(f)[0][1]
    i, h = find_header(rows, 'UTILITY NUMBER', 'STATE', 'OWNERSHIP')
    if i is None:
        sys.exit('%d: reliability header not found' % y)
    # Fixed order: 5-7 IEEE with major events, 8-10 IEEE without, 14 customers, 17-19 Other with, 20-22 Other without,
    # 23 Other customers (from 2020). 2019 alone has an extra "Short Form" column at 5, moving everything along by one.
    o = 1 if 'SHORT FORM' in h else 0
    for r in rows[i + 1:]:
        u = uid_of(r[1])
        if not u or len(r) < 23 + o:
            continue
        st = str(r[3]).strip()
        if num(r[5 + o]) is not None:
            yield y, u, st, 'IEEE', num(r[5 + o]), num(r[6 + o]), num(r[7 + o]), num(r[8 + o]), num(r[9 + o]), num(r[14 + o])
        elif num(r[17 + o]) is not None:
            cust = num(r[23 + o]) if len(r) > 23 + o and y >= 2020 else None
            yield y, u, st, 'Other', num(r[17 + o]), num(r[18 + o]), num(r[19 + o]), num(r[20 + o]), num(r[21 + o]), cust


def net_metering(y, d):
    f = one(d, r'^Net_Metering_\d{4}\.xlsx?$')
    if not f:
        return
    all_sheets = sheets(f)
    rows = dict(all_sheets).get('States') or all_sheets[0][1]
    i, h = find_header(rows, 'UTILITY NUMBER', 'STATE')
    if i is None:
        sys.exit('%d: net metering header not found' % y)
    res = [k for k, n in enumerate(h) if n == 'RESIDENTIAL']
    band = [str(c or '').upper() for c in rows[i - 1]]
    # Above the column names: "Capacity MW" over the first Residential, then "Installations" or "Customers".
    last, spans = '', {}
    for k in range(len(h)):
        last = band[k] or last
        spans[k] = last
    cap = next((k for k in res if 'CAPACITY' in spans[k]), None)
    cnt = next((k for k in res if ('INSTALL' in spans[k] or 'CUSTOMER' in spans[k])), None)
    if cap is None or cnt is None:
        sys.exit('%d: net metering residential columns not found: %r' % (y, sorted(set(band))))
    tot = {}
    for r in rows[i + 1:]:
        u = uid_of(r[h.index('UTILITY NUMBER')])
        if not u:
            continue
        key = (y, u, str(r[h.index('STATE')]).strip())
        a = tot.setdefault(key, [0.0, 0.0])
        a[0] += num(r[cnt]) or 0
        a[1] += num(r[cap]) or 0
    for (yy, u, st), (c, mw) in tot.items():
        if c or mw:
            yield yy, u, st, c, mw


def write(name, head, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(head)
    for r in sorted(rows, key=lambda x: tuple(str(c).zfill(8) if isinstance(c, int) else str(c) for c in x[:4])):
        w.writerow([c if isinstance(c, (int, str)) else fmt(c) for c in r])
    with gzip.GzipFile(os.path.join(OUT, name), 'wb', mtime=0) as g:
        g.write(buf.getvalue().encode())
    print('%s: %d rows' % (name, len(rows)), file=sys.stderr)


def main(root):
    years = sorted(int(m.group(1)) for m in (re.match(r'u(\d{4})$', x) for x in os.listdir(root)) if m)
    if years[0] != 1990 or years != list(range(1990, years[-1] + 1)):
        sys.exit('expected every year from 1990, got %r' % years)
    sales, rel, net = {}, [], []
    for y in years:
        d = os.path.join(root, 'u%d' % y)
        gen = sales_1990_98 if y <= 1998 else sales_1999_00 if y <= 2000 else sales_2001_11 if y <= 2011 else sales_2012_on
        n = 0
        for r in gen(y, d):
            if r[2] and any(v is not None for v in r[4:7]):
                key = r[:4]
                if key not in sales:
                    n += 1
                sales.setdefault(key, r)
        if n < 2000:  # from 2012 small utilities move to the short form, so counts fall to about 2,300
            sys.exit('%d: only %d sales rows, layout changed?' % (y, n))
        a = list(reliability(y, d)) if y >= 2013 else []
        b = list(net_metering(y, d)) if y >= 2013 else []
        if y >= 2013 and (len(a) < 200 or len(b) < 200):
            sys.exit('%d: reliability %d, net metering %d rows' % (y, len(a), len(b)))
        rel += a
        net += b
        print(y, 'sales', n, 'reliability', len(a), 'net metering', len(b), file=sys.stderr)
    write('eia861-annual-residential.csv.gz', ['year', 'utility_id', 'state', 'part', 'revenue_k', 'sales_mwh', 'customers'], list(sales.values()))
    write('eia861-reliability.csv.gz', ['year', 'utility_id', 'state', 'standard', 'saidi_all', 'saifi_all', 'caidi_all', 'saidi_excl_major', 'saifi_excl_major', 'customers'], rel)
    write('eia861-net-metering.csv.gz', ['year', 'utility_id', 'state', 'res_pv_installs', 'res_pv_mw'], net)


if __name__ == '__main__':
    main(sys.argv[1])
