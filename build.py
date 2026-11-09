#!/usr/bin/env python3
"""Builds every table in this dataset from source/utility-rates.json.

source/utility-rates.json is the file behind the live pages, built by scripts/build-utility-rates-data.py from
EIA Form 826, EIA-861M, EIA-861 and BLS CPI. The frozen EIA extracts it starts from are in source/*.csv.gz.

  python3 build.py    writes the CSVs below, datapackage.json and the figures block of README.md
"""
import csv, json, os, re
HERE = os.path.dirname(os.path.abspath(__file__))
d = json.load(open(os.path.join(HERE, 'source', 'utility-rates.json')))
U = sorted(d['utilities'], key=lambda u: u['rank'])
PACK = []

def write(name, title, fields, rows):
    with open(os.path.join(HERE, name), 'w', newline='') as fh:
        w = csv.writer(fh, lineterminator='\n'); w.writerow([f[0] for f in fields]); w.writerows(rows)
    PACK.append({'name': name[:-4], 'path': name, 'format': 'csv', 'title': title, 'schema': {'fields': [{'name': f[0], 'type': f[1], 'description': f[2]} for f in fields]}})
    print(name, len(rows)); return len(rows)

def pct(a, b): return round((a / b - 1) * 100, 2) if a is not None and b else None
S, N, I = 'string', 'number', 'integer'
ID = ('utility', S, 'Slug of the utility, as in utilities.csv')

n = {}
n['utilities.csv'] = write('utilities.csv', 'The 40 utilities', [('rank', I, 'Rank by homes served, EIA-861 latest year'), ('utility', S, 'Slug'), ('name', S, 'Common name'), ('eia_name', S, 'Name on EIA returns'), ('eia_id', I, 'EIA utility number'), ('predecessor_ids', S, 'EIA numbers of merged predecessors whose months are added, separated by spaces'), ('states', S, 'States served'), ('ownership', S, 'EIA ownership type'), ('reports_monthly', I, '1 if the utility is in the EIA-861M monthly sample, 0 if only annual'), ('note', S, 'Note on the series')],
  [[u['rank'], u['slug'], u['brand'], u['eia_name'], u['eia_id'], ' '.join(str(p) for p in u['predecessors']), ' '.join(u['states']), u['ownership'], int(bool(u['monthly'])), u['note'] or ''] for u in U])
n['utility-electricity-prices-latest.csv'] = write('utility-electricity-prices-latest.csv', 'Latest 12 months for each utility', [ID, ('period_end', S, 'Last month of the window'), ('months_in_window', I, 'Months EIA published in the window'), ('price_cents_per_kwh', N, 'Revenue from homes divided by kWh sold to them'), ('prior_price_cents_per_kwh', N, 'Same for the 12 months before'), ('change_pct', N, 'Change on the 12 months before'), ('bill_usd_per_month', N, 'Average monthly bill'), ('kwh_per_month', N, 'Average monthly use'), ('price_rank', I, '1 = dearest of the 40'), ('homes_total', I, 'Homes on the wires, EIA-861'), ('homes_own_supply', I, 'Homes buying power from the utility'), ('homes_delivery_only', I, 'Homes buying power elsewhere'), ('delivery_only_cents_per_kwh', N, 'Wires-only revenue per kWh, EIA-861')],
  [[u['slug'], u['latest12']['end'], u['latest12']['months'], u['latest12']['price'], (u['prior12'] or {}).get('price'), pct(u['latest12']['price'], (u['prior12'] or {}).get('price')), u['latest12']['bill'], u['latest12']['kwh'], u['price_rank'], u['homes']['total'], u['homes']['own_supply'], u['homes']['delivery_only'], u['homes']['delivery_price']] for u in U])
n['utility-electricity-prices-monthly.csv'] = write('utility-electricity-prices-monthly.csv', 'Every month since 1990', [ID, ('month', S, 'YYYY-MM'), ('price_cents_per_kwh', N, 'Revenue divided by kWh, as EIA published'), ('kwh_per_customer', N, 'kWh per customer'), ('bill_usd_per_customer', N, 'Revenue per customer'), ('customers', I, 'Residential customers on own supply')],
  [[u['slug']] + r for u in U for r in u['months']])
n['utility-electricity-prices-annual.csv'] = write('utility-electricity-prices-annual.csv', 'Every year since 1990', [ID, ('year', I, 'Calendar year'), ('price_cents_per_kwh', N, 'Price'), ('kwh_per_month', N, 'Use'), ('bill_usd_per_month', N, 'Bill'), ('customers', I, 'Customers'), ('price_today_dollars', N, 'Price in latest dollars, BLS CPI-U all items'), ('source', S, 'm = sum of monthly returns, a = EIA-861 annual')],
  [[u['slug']] + r for u in U for r in u['annual']])
n['utility-prices-by-state.csv'] = write('utility-prices-by-state.csv', 'Latest 12 months, by state served', [ID, ('state', S, 'State'), ('price_cents_per_kwh', N, 'Price'), ('bill_usd_per_month', N, 'Bill'), ('kwh_per_month', N, 'Use'), ('customers', I, 'Customers'), ('months_in_window', I, 'Months published')],
  [[u['slug'], st, v['price'], v['bill'], v['kwh'], v['customers'], v['months']] for u in U for st, v in u['by_state'].items()])
n['utility-outages.csv'] = write('utility-outages.csv', 'Outages since 2013', [ID, ('year', I, 'Year'), ('standard', S, 'IEEE or Other, as reported'), ('saidi_minutes_all', N, 'Minutes without power per customer, all events'), ('saifi_all', N, 'Interruptions per customer, all events'), ('saidi_minutes_excl_major', N, 'Excluding major event days'), ('saifi_excl_major', N, 'Excluding major event days'), ('us_saidi_minutes_all', N, 'US customer-weighted average')],
  [[u['slug']] + r for u in U for r in u['reliability']])
n['utility-rooftop-solar.csv'] = write('utility-rooftop-solar.csv', 'Net-metered home solar since 2013', [ID, ('year', I, 'Year'), ('homes', I, 'Residential net-metered solar installations'), ('capacity_mw', N, 'Capacity')], [[u['slug']] + r for u in U for r in u['solar']])
n['utility-supply-split.csv'] = write('utility-supply-split.csv', 'Who supplies the homes', [ID, ('year', I, 'Year'), ('homes_own_supply', I, 'EIA-861 Parts A and D'), ('homes_delivery_only', I, 'EIA-861 Part C')], [[u['slug']] + r for u in U for r in u['supply_history']])
n['utility-service-counties.csv'] = write('utility-service-counties.csv', 'Counties served', [ID, ('state', S, 'State'), ('county', S, 'County; may be served in part')], [[u['slug'], st, c] for u in U for st, cs in u['counties'].items() for c in cs])
n['us-and-state-prices-annual.csv'] = write('us-and-state-prices-annual.csv', 'US and state yearly price', [('area', S, 'US or state'), ('year', I, 'Year'), ('price_cents_per_kwh', N, 'Residential price')], [['US'] + r[:2] for r in d['us_annual']] + [[st] + r[:2] for st, v in sorted(d['states_annual'].items()) for r in v])

json.dump({'name': 'us-utility-electricity-rates', 'title': 'US Utility Residential Electricity Prices, Monthly since 1990', 'licenses': [{'name': 'CC-BY-4.0', 'path': 'https://creativecommons.org/licenses/by/4.0/'}], 'homepage': 'https://greencalculus.com/data/utility-rates/', 'version': d['built'][:10].replace('-', '.'), 'resources': PACK}, open(os.path.join(HERE, 'datapackage.json'), 'w'), indent=1)

L = sorted(U, key=lambda u: -u['latest12']['price']); hi, lo = L[0], L[-1]
rows = ''.join('| %s | %s | %.1f¢ | $%.0f | %s |\n' % (u['rank'], u['brand'], u['latest12']['price'], u['latest12']['bill'], format(u['homes']['total'], ',')) for u in U[:10])
fig = f"""Data to **{d['latest']}** ({d['latest_status'].lower()}). Over the latest 12 months the 40 utilities ran from **{lo['latest12']['price']:.1f}¢** per kWh ({lo['brand']}) to **{hi['latest12']['price']:.1f}¢** ({hi['brand']}); the US average was **{d['us_12']:.1f}¢**.

| Rank by homes | Utility | Price per kWh | Bill a month | Homes served |
|---|---|---|---|---|
{rows}"""
files = ''.join('| `%s` | %s | %s |\n' % (k, format(v, ','), next(p['title'] for p in PACK if p['path'] == k)) for k, v in n.items())
p = os.path.join(HERE, 'README.md')
if os.path.exists(p):
    s = open(p, encoding='utf8').read()
    s = re.sub(r'(<!-- figures -->\n).*?(<!-- /figures -->)', lambda m: m.group(1) + fig + m.group(2), s, flags=re.S)
    s = re.sub(r'(<!-- files -->\n).*?(<!-- /files -->)', lambda m: m.group(1) + '| File | Rows | What it holds |\n|---|---|---|\n' + files + m.group(2), s, flags=re.S)
    open(p, 'w', encoding='utf8').write(s)
