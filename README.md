# US Utility Residential Electricity Prices, Monthly since 1990

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24071582.svg)](https://doi.org/10.5281/zenodo.24071582)

What homes actually paid, all charges in, at the 40 biggest electric utilities in the United States: every month since January 1990, with the bill, the kWh, outages, rooftop solar, who supplies the homes and the counties served. Built from the returns each utility files with the US Energy Information Administration (EIA) and merged across corporate changes, so each utility is one continuous series under today's name. EIA publishes the raw numbers year by year, under whichever name a utility used at the time.

**Read it with charts, a bill check and a county finder:** <https://greencalculus.com/data/utility-rates/>

| Utility pages | |
|---|---|
| [All 40 compared](https://greencalculus.com/data/utility-rates/) | Sortable, with the next 60 utilities, price against outages and a state filter |
| [PG&E](https://greencalculus.com/data/pge-electricity-rates/) | California |
| [SCE](https://greencalculus.com/data/sce-electricity-rates/) | California |
| [Duke Energy Carolinas](https://greencalculus.com/data/duke-energy-carolinas-electricity-rates/) | North Carolina and South Carolina |

Related: [electricity rates by state](https://greencalculus.com/data/electricity-rates-by-state/) · [average electric bill by state](https://greencalculus.com/data/average-electric-bill-by-state/) ([dataset, DOI 10.5281/zenodo.24067456](https://doi.org/10.5281/zenodo.24067456))

## Known data issue: Eversource Massachusetts (NSTAR Electric, EIA ID 54913)

From January 2025 the residential price EIA publishes for NSTAR Electric does not match the company's filed rates. EIA shows 19.7¢ per kWh for the 12 months to August 2026; Eversource's filed rates from 1 September 2026 are 17.323¢ supply plus 18.635¢ delivery in eastern Massachusetts, 35.958¢ before a $10 monthly charge. In EIA-861 the gap between the Basic Service price and the delivery-only price fell from 13.6¢ in 2024 to 1.4¢ in 2025.

This archive keeps EIA's figures unedited. Do not use this utility's prices from 2025-01 onward as an all-in price. The affected range is listed in `data-quality-flags.csv`. Our reading is that reported Basic Service revenue stopped including supply; that is an inference and EIA has not confirmed it. Live page: https://greencalculus.com/data/utility-rates/

## Latest figures

<!-- figures -->
Data to **2026-08** (preliminary). Over the latest 12 months the 40 utilities ran from **12.3¢** per kWh (Entergy Louisiana) to **47.6¢** (SDG&E (San Diego Gas & Electric)); the US average was **18.0¢**.

| Rank by homes | Utility | Price per kWh | Bill a month | Homes served |
|---|---|---|---|---|
| 1 | FPL (Florida Power & Light) | 14.8¢ | $166 | 5,337,118 |
| 2 | PG&E (Pacific Gas and Electric) | 34.7¢ | $162 | 5,055,556 |
| 3 | Southern California Edison (SCE) | 31.6¢ | $179 | 4,627,247 |
| 4 | ComEd (Commonwealth Edison) | 19.3¢ | $112 | 3,753,924 |
| 5 | Con Edison | 38.5¢ | $148 | 3,088,999 |
| 6 | Duke Energy Carolinas | 14.0¢ | $142 | 2,543,170 |
| 7 | Dominion Energy (Virginia and North Carolina) | 17.1¢ | $179 | 2,517,958 |
| 8 | Georgia Power | 16.4¢ | $163 | 2,480,484 |
| 9 | DTE Energy (DTE Electric) | 22.0¢ | $137 | 2,078,328 |
| 10 | PSE&G (Public Service Electric and Gas) | 25.9¢ | $149 | 2,072,339 |
<!-- /figures -->

## Files

<!-- files -->
| File | Rows | What it holds |
|---|---|---|
| `utilities.csv` | 40 | The 40 utilities |
| `utility-electricity-prices-latest.csv` | 40 | Latest 12 months for each utility |
| `utility-electricity-prices-monthly.csv` | 16,596 | Every month since 1990 |
| `utility-electricity-prices-annual.csv` | 1,416 | Every year since 1990 |
| `utility-prices-by-state.csv` | 49 | Latest 12 months, by state served |
| `utility-outages.csv` | 491 | Outages since 2013 |
| `utility-rooftop-solar.csv` | 476 | Net-metered home solar since 2013 |
| `utility-supply-split.csv` | 998 | Who supplies the homes |
| `utility-service-counties.csv` | 1,502 | Counties served |
| `us-and-state-prices-annual.csv` | 1,872 | US and state yearly price |
<!-- /files -->

Also here: `source/utility-rates.json` (everything above, in one file), `source/tariffs-checked.json` (filed rates read from each utility's schedules, with the date checked), `source/*.csv.gz` (the frozen EIA extracts), `scripts/` (the code that made them), `datapackage.json` (field descriptions).

## How to read the price

- **Price = revenue from homes ÷ kWh sold to them.** It includes energy, delivery, fixed charges, riders and credits. It is not any single rate on a tariff, and no household pays exactly this.
- **It covers only homes buying power from the utility itself.** In retail-choice states and community choice areas, other homes pay the utility for delivery only. `utility-supply-split.csv` shows how many, and the delivery-only price is in the latest table. Compare with care.
- **12-month figures sum revenue and kWh** over the months EIA has published, and `months_in_window` says how many that is.
- **Months of the newest year are EIA preliminary figures** and can be revised. We never edit a month EIA published.

## Method and limits

- Monthly series: Form EIA-826 and its successor EIA-861M, residential sector, by utility and state. Excludes EIA's adjustment rows, state totals and behind-the-meter rows.
- Merged companies: a month is the utility's own row plus its predecessors' rows, in the states it serves today. `utilities.csv` lists the EIA numbers used.
- Yearly survey (EIA-861) fills years a utility was missing from the monthly sample (`source = a` in the annual table). SDG&E is absent from the monthly sample for 1993 to 2000.
- Reliant and TXU Energy, Texas retailers, appear only in the yearly data, from 2002. They have no monthly file.
- A one-month customer-count slip is blanked in the bill and kWh columns when it differs more than 40% from both neighbours, which agree with each other. Price is unaffected.
- Outages are as each utility reported them to EIA; utilities using other standards than IEEE 1366 are marked.
- County lists come from EIA-861 Service Territory. A listed county may be served only in part.
- Inflation adjustment: BLS CPI-U, all items, US city average.

## Rebuild

`python3 build.py` rebuilds every CSV and `datapackage.json` from `source/utility-rates.json`, with the Python standard library only. `scripts/build-utility-rates-data.py` builds that JSON from the frozen files plus EIA's current-year EIA-861M workbooks and BLS CPI; `scripts/freeze-history.py` and `scripts/freeze-annual.py` made the frozen files from EIA's published workbooks.

The live pages update each time EIA publishes a month. This archive is versioned, and each new version gets its own DOI.

## Cite

> Say, J. (2026). *US Utility Residential Electricity Prices, Monthly since 1990* (Version 2026.11.09.2) [Data set]. GreenCalculus. https://doi.org/10.5281/zenodo.24071582

Always-latest DOI: `10.5281/zenodo.24071582`. This exact version: `10.5281/zenodo.24072524`. See `CITATION.cff`.

## Licence

This compilation is licensed [CC BY 4.0](LICENSE): reuse it freely, with credit to GreenCalculus. The underlying EIA and BLS data are US government works in the public domain. Filed rates in `source/tariffs-checked.json` are facts from public filings; check the utility's own schedule before relying on one.
