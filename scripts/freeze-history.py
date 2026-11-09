#!/usr/bin/env python3
"""One-off: freeze EIA's monthly utility files (Form 826 to 2007, EIA-861M after) for
1990..LAST_FINAL into one compact file. The monthly job then reads only the years after it.

Inputs (download from https://www.eia.gov/electricity/data/eia861m/ into one folder):
  f826YYYY.xls (1990-2016; some are xlsx under an .xls name), retail_sales_YYYY.xlsx (2017-2020),
  sales_ult_cust_YYYY.xlsx (2021-).
Needs xlrd + openpyxl (Mac only; the jobs server reads the newer xlsx with the stdlib).

Output: data/utility-rates/eia861m-residential-1990-<LAST_FINAL>.csv.gz
  utility_id,state,month,revenue_k,sales_mwh,customers
  One row per utility, state and month, residential sector only, as EIA reports it.
  Left out: state adjustment rows (id 0 / 99999 / names with "adjust"), state totals (88888),
  and behind-the-meter sellers (rooftop solar firms, ownership "Behind the Meter").
  When a file repeats a utility-state-month (2005-2007 name typos), the first row is kept;
  the duplicates are identical in every number.
Plus data/utility-rates/utility-names.json: id -> every name EIA used, with first and last month.

Usage: python3 freeze-history.py RAW_DIR LAST_FINAL
"""
import csv, gzip, io, json, os, re, shutil, sys, tempfile, warnings
import xlrd, openpyxl

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '..', '..', 'data', 'utility-rates')
SKIP_IDS = {0, 88888, 99999}


def sheet_rows(path):
    try:
        book = xlrd.open_workbook(path)
        sh = book.sheet_by_index(0)
        for r in range(sh.nrows):
            yield sh.row_values(r)
    except xlrd.XLRDError:  # an xlsx saved under an .xls name
        tmp = tempfile.mktemp(suffix='.xlsx')
        shutil.copy(path, tmp)
        try:
            book = openpyxl.load_workbook(tmp, read_only=True, data_only=True)
            for row in book.worksheets[0].iter_rows(values_only=True):
                yield list(row)
        finally:
            os.unlink(tmp)


def num(x):
    if x in (None, '', '.', '*'):
        return None
    try:
        return float(str(x).replace(',', ''))
    except ValueError:
        return None


def read(path):
    """Yield (uid, name, state, 'YYYY-MM', revenue_k, sales_mwh, customers, ownership)."""
    hdr = None
    for row in sheet_rows(path):
        cells = ['' if c is None else str(c).strip() for c in row]
        up = [c.upper() for c in cells]
        if hdr is None:
            if up and up[0] in ('UTILITYID', 'UTILITY_ID'):
                hdr = ('A', up)  # 1990-2012: one header row, residential columns 5-7
            elif 'UTILITY NUMBER' in up:
                hdr = ('B', up)  # 2013-: three header rows, this is the last
            continue
        kind, h = hdr
        if kind == 'A':
            uid, name, st, yr, mo = cells[:5]
            rev, sales = num(row[5]), num(row[6])
            has_cust = len(h) > 7 and ('RES_CONS' in h[7] or 'RESIDENTIAL CUSTOMERS' in h[7])
            cust = num(row[7]) if has_cust else None
            own = ''
        else:
            ix = {k: h.index(k) for k in ('YEAR', 'MONTH', 'UTILITY NUMBER', 'UTILITY NAME', 'STATE')}
            first = h.index('THOUSANDS DOLLARS')  # residential is the first sector block
            uid, name, st = cells[ix['UTILITY NUMBER']], cells[ix['UTILITY NAME']], cells[ix['STATE']]
            yr, mo = cells[ix['YEAR']], cells[ix['MONTH']]
            rev, sales, cust = num(row[first]), num(row[first + 1]), num(row[first + 2])
            own = cells[h.index('OWNERSHIP')] if 'OWNERSHIP' in h else ''
        my, mm = re.match(r'(\d+)', yr or ''), re.match(r'(\d+)', mo or '')
        if not my or not mm or not uid:
            continue
        y = int(my.group(1))
        y = y + 1900 if y < 100 else y  # two-digit years to 1997
        try:
            uid = int(float(uid))
        except ValueError:
            continue
        if uid in SKIP_IDS or re.search(r'adjust|state total', name, re.I) or own == 'Behind the Meter':
            continue
        yield uid, name, st, f'{y}-{int(mm.group(1)):02d}', rev, sales, cust, own


def year_of(fname):
    m = re.search(r'(\d{4})\.xlsx?$', fname)
    return int(m.group(1)) if m else None


def main(raw, last_final):
    files = sorted(f for f in os.listdir(raw) if year_of(f) and year_of(f) <= last_final)
    years = sorted(year_of(f) for f in files)
    missing = [y for y in range(1990, last_final + 1) if y not in years]
    if missing:
        sys.exit(f'missing years: {missing}')
    seen, names = {}, {}
    for f in files:
        n = 0
        for r in read(os.path.join(raw, f)):
            key = (r[0], r[2], r[3])
            if key in seen:
                continue
            seen[key] = r
            n += 1
            rec = names.setdefault(str(r[0]), {})
            span = rec.setdefault(r[1], [r[3], r[3]])
            span[0], span[1] = min(span[0], r[3]), max(span[1], r[3])
        if n < 2000:
            sys.exit(f'{f}: only {n} rows, layout changed?')
        print(f'{f}: {n}', file=sys.stderr)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'eia861m-residential-1990-{last_final}.csv.gz')
    def fmt(v):
        return '' if v is None else ('%d' % v if float(v).is_integer() else repr(round(v, 3)))
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(['utility_id', 'state', 'month', 'revenue_k', 'sales_mwh', 'customers'])
    for k in sorted(seen):
        r = seen[k]
        w.writerow([r[0], r[2], r[3], fmt(r[4]), fmt(r[5]), fmt(r[6])])
    with gzip.GzipFile(path, 'wb', mtime=0) as g:  # mtime 0: same input, same bytes
        g.write(buf.getvalue().encode())
    with open(os.path.join(OUT, 'utility-names.json'), 'w') as fh:
        json.dump(names, fh, indent=0, sort_keys=True)
    print(f'{len(seen)} rows -> {path}', file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]))
