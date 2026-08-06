---
name: analytics-matomo
description: Read browser-side measurement from Matomo over its Reporting API: visits, unique visitors, page URLs and titles, entry and exit pages, referrer channels, campaigns, countries, devices, hour of day, ecommerce orders, abandoned carts, product SKUs, and the raw per-visit log. Use whenever a question concerns visitors, sessions, traffic sources, on-site behaviour or browser-measured conversions. Covers the single RPC endpoint and its parameters, the mandatory period/date pair, how Matomo describes its own 77 reports, segment syntax and operators, Live raw-visit access, the response shapes, and the errors that arrive with an HTTP 200.
---

Matomo measures the storefront from the browser. There is **no OpenAPI document
for it**, and it does not need one: it describes itself at runtime.

| variable | what it is |
|---|---|
| `$MATOMO_URL` | the base, e.g. `https://tracking.archipellabs.test` |
| `$MATOMO_SITE_ID` | the site to report on, an integer |
| `$MATOMO_AGENT_TOKEN` | the credential |
| `$COMPANY_CA` | the company's certificate authority, `company-ca.crt` in the working directory |

## The CA certificate, before anything else

The company answers on `.test` domains with certificates signed by its own CA.
A plain `curl` therefore fails with exit code 60, `curl failed to verify the
legitimacy of the server`, which reads exactly like an unreachable system.

Every command below passes `--cacert "$COMPANY_CA"`. Keep it.

Do **not** replace it with `-k` or `--insecure`. Trusting the company's CA is
what a real employee's machine does. Disabling verification is what somebody
does at 2am and never removes, and it hides the next certificate problem
instead of reporting it.

## Where the answers land

Every call below writes its body to `data/`, named for the API method it called,
and prints one line back: the status and the size.

```
curl -sS --cacert "$COMPANY_CA" -o data/matomo_METHOD.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
```

Keep the receipt. This API is the one that answers **HTTP 200 with an error
inside the body**, so the status line alone never tells you a call succeeded —
but a zero-byte or 40-byte response tells you at a glance that something is
wrong before you open anything.

## 1. Start here

Do these in order. The first three cost one request each and stop you from
guessing at method names that do not exist on this install.

**1. Confirm you can reach it and that the token works.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_api_getmatomoversion.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getMatomoVersion" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

A version string means the host, the CA and the token are all fine. Anything
else is answered in section 9.

**2. Learn what the site is.** Timezone and currency change how you read every
number that follows.

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=SitesManager.getSiteFromId" \
  -d "idSite=$MATOMO_SITE_ID" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_sitesmanager_getsitefromid.json | jq -c '{idsite, name, main_url, timezone, currency, ecommerce, ts_created}'
```

`ecommerce: 1` means order and cart reports exist. `ts_created` is the earliest
date that can possibly hold data.

**3. Make Matomo describe its own reports.** This is the contract. It is
generated from the plugins actually installed, so it cannot be out of date the
way a copied file would be.

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getReportMetadata" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=today" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_api_getreportmetadata.json | jq -r '.[] | "\(.module).\(.action)\t\(.category) / \(.name)\tdim=\(.dimension // "-")"'
```

This install returns about 77 reports. The full response is large. Always pipe
it through `jq` as above rather than reading it raw.

**4. Read the documentation of one report before calling it.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getReportMetadata" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=today" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_api_getreportmetadata_2.json | jq '.[] | select(.module=="Referrers" and .action=="getReferrerType")'
```

Each entry carries `metrics`, `processedMetrics`, `metricTypes` and a prose
`documentation` field written by Matomo itself.

**5. List the segment dimensions before writing a segment.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getSegmentsMetadata" \
  -d "idSites=$MATOMO_SITE_ID" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_api_getsegmentsmetadata.json | jq -r '.[] | "\(.category)\t\(.segment)\t\(.name)"'
```

**6. Then call the report.** Start with a small `filter_limit`, look at the
column names that come back, and only then widen.

## 2. The request shape

One endpoint, `index.php`, with everything in parameters. It is RPC over HTTP,
not REST: there are no resource paths to explore, and `module=API` is a literal
constant, not a placeholder.

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_visitssummary_get.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

POST rather than GET, so the token never lands in a log line or a shell history
entry. Matomo accepts every parameter identically in a POST body.

### Always present

| param | meaning |
|---|---|
| `module=API` | fixed. Selects the Reporting API front controller. |
| `method` | `Module.action`, e.g. `Actions.getPageUrls`. |
| `idSite` | `$MATOMO_SITE_ID`. Accepts a comma list or `all`. |
| `period` | `day`, `week`, `month`, `year` or `range`. |
| `date` | see section 3. Mandatory with `period`. |
| `format` | use `JSON`. |
| `token_auth` | `$MATOMO_AGENT_TOKEN`. |

### Shaping the result

| param | default | meaning |
|---|---|---|
| `filter_limit` | **100** | rows returned. `-1` returns all of them. |
| `filter_offset` | `0` | rows to skip. Paging, with `filter_limit`. |
| `filter_sort_column` | report default | e.g. `nb_visits`. |
| `filter_sort_order` | `desc` | `asc` or `desc`. |
| `filter_pattern` | none | regex kept against `filter_column`. |
| `filter_column` | `label` | which column `filter_pattern` tests. |
| `filter_truncate` | none | keep N rows, aggregate the rest into `Others`. |
| `flat` | `0` | `1` flattens a hierarchical report into full labels. |
| `expanded` | `0` | `1` returns first level plus every subtable inline. |
| `showColumns` | all | comma list. Everything else is dropped. |
| `hideColumns` | none | comma list to drop. |
| `segment` | none | see section 7. |
| `format_metrics` | `bc` | `0` for raw numbers, `1` for formatted strings. |
| `label` | none | fetch the single row with this exact label. |
| `idSubtable` | none | fetch one subtable, using an `idsubdatatable` from a parent row. |

`format` also accepts `XML`, `CSV`, `TSV`, `HTML` and `RSS`. If you use `CSV`,
pass `convertToUnicode=0` or you get UTF-16LE.

### flat and expanded

`Actions.getPageUrls` is a tree of path segments, not a list of pages. Without
`flat=1` the top rows are directory names:

```
diving      5867   idsubdatatable=124
products    2573   idsubdatatable=108
```

With `flat=1` they are the pages themselves:

```
/cart/   1117
/jobs     934
/          742
```

`flat=1` is almost always what you want for URLs, page titles and any other
tree. `expanded=1` returns the same data still nested, which is harder to read
and much larger. The same applies to `Actions.getPageTitles`,
`Actions.getEntryPageUrls` and `Actions.getExitPageUrls`.

## 3. period and date

They go **together, always**. Send one without the other and the request fails
with `HTTP 400` and a one-line body:

```json
{"result":"error","message":"Please specify a value for 'date'."}
```

Read that body. If you get a 400, suspect the parameter pair before suspecting
the system. Six consecutive requests once failed this way and the model driving
them concluded the analytics was broken rather than that its call was
malformed.

`period` is one of `day`, `week`, `month`, `year`, `range`.

`date` accepts:

| form | example | result |
|---|---|---|
| an ISO date | `date=2026-08-01` | that one period |
| `today`, `yesterday` | `date=yesterday` | that one period |
| `lastN` | `period=day&date=last30` | 30 periods **including today** |
| `previousN` | `period=day&date=previous30` | 30 periods **ending yesterday** |
| an explicit range | `period=range&date=2026-08-01,2026-08-02` | one aggregate over the window |
| `lastWeek`, `lastMonth`, `lastYear` | `period=range&date=lastMonth` | one aggregate |

`period=range` collapses the window into a **single** figure.
`period=day&date=last30` returns **thirty** figures, one per day, as an object
keyed by date:

```json
{"2026-07-28":15272,"2026-07-29":9953,"2026-07-30":11879}
```

That is a different response shape from a single-period call, and code that
reads one will not read the other. With `period=week`, the keys are
`start,end` pairs: `{"2026-07-27,2026-08-02":87445}`.

The last bucket of a `lastN` series is the current, incomplete period. A
part-day is not a low day.

## 4. Modules and methods

`API.getReportMetadata` is authoritative for this install. The table is the
subset that is nearly always present. Every method takes `idSite`, `period`,
`date`, `segment` and the shaping parameters from section 2.

### Volume

| method | returns |
|---|---|
| `VisitsSummary.get` | all core metrics at once: `nb_visits`, `nb_uniq_visitors`, `nb_users`, `nb_actions`, `nb_visits_converted`, `bounce_count`, `sum_visit_length`, `max_actions`, `bounce_rate`, `nb_actions_per_visit`, `avg_time_on_site` |
| `VisitsSummary.getVisits` | one number, or a keyed series over `lastN` |
| `VisitsSummary.getUniqueVisitors` | idem |
| `VisitsSummary.getActions` | idem |
| `VisitsSummary.getBounceCount` | idem |
| `VisitFrequency.get` | the same metrics restricted to returning visits, suffixed `_returning` |
| `API.get` | metrics from several plugins in one row. Pass `columns=nb_visits,nb_actions,revenue`. |

### Behaviour on the site

| method | dimension |
|---|---|
| `Actions.get` | totals: pageviews, unique pageviews, searches, downloads, outlinks |
| `Actions.getPageUrls` | page URL |
| `Actions.getPageTitles` | page title |
| `Actions.getEntryPageUrls` | first page of the visit |
| `Actions.getExitPageUrls` | last page of the visit |
| `Actions.getSiteSearchKeywords` | internal search terms |
| `Actions.getSiteSearchNoResultKeywords` | internal searches that returned nothing |
| `Actions.getOutlinks` | clicked links leaving the site |
| `Actions.getDownloads` | downloaded files |
| `Events.getCategory`, `Events.getAction`, `Events.getName` | tracked events |

### Where visitors came from

| method | dimension |
|---|---|
| `Referrers.get` | totals per channel |
| `Referrers.getReferrerType` | the six channels: `direct`, `search`, `website`, `social`, `campaign`, `ai` |
| `Referrers.getAll` | every referrer flattened across channels |
| `Referrers.getWebsites` | referring domain |
| `Referrers.getSearchEngines` | search engine |
| `Referrers.getKeywords` | keyword, mostly `Keyword not defined` on modern engines |
| `Referrers.getSocials` | social network |
| `Referrers.getCampaigns` | campaign name |

### Who they were

| method | dimension |
|---|---|
| `UserCountry.getCountry` | country |
| `UserCountry.getRegion`, `UserCountry.getCity`, `UserCountry.getContinent` | finer or coarser location |
| `DevicesDetection.getType` | desktop, smartphone, tablet |
| `DevicesDetection.getBrowsers`, `.getOsFamilies`, `.getBrand`, `.getModel` | client |
| `UserLanguage.getLanguage` | browser language |
| `Resolution.getResolution` | screen size |

### When

| method | dimension |
|---|---|
| `VisitTime.getVisitInformationPerServerTime` | hour of day in the **site's** timezone |
| `VisitTime.getVisitInformationPerLocalTime` | hour of day on the **visitor's** clock |
| `VisitTime.getByDayOfWeek` | day of week |
| `VisitorInterest.getNumberOfVisitsPerVisitDuration` | visit length buckets |
| `VisitorInterest.getNumberOfVisitsPerPage` | pages-per-visit buckets |
| `VisitorInterest.getNumberOfVisitsByDaysSinceLast` | recency buckets |

### Ecommerce and goals

| method | returns |
|---|---|
| `Goals.get` with `idGoal=ecommerceOrder` | orders as Matomo saw them |
| `Goals.get` with `idGoal=ecommerceAbandonedCart` | carts that never converted |
| `Goals.get` with `idGoal=<n>` | one configured goal |
| `Goals.get` with no `idGoal` | all goals combined |
| `Goals.getGoals` | the goal definitions, keyed by id. Takes `idSite` only, no `period`/`date`. |
| `Goals.getItemsName` | revenue and quantity by product name |
| `Goals.getItemsSku` | idem by SKU |
| `Goals.getItemsCategory` | idem by category |
| `Goals.getDaysToConversion` | days between first visit and conversion |
| `Goals.getVisitsUntilConversion` | number of visits before conversion |

The three `getItems*` methods take `abandonedCarts=1` to describe carts instead
of orders. The metric name changes with it: `orders` becomes
`abandoned_carts`.

### Metadata and plumbing

| method | use |
|---|---|
| `API.getReportMetadata` | the self-description. Section 1. |
| `API.getSegmentsMetadata` | every segment dimension. Section 7. |
| `API.getSuggestedValuesForSegment` | the values a dimension actually takes. Section 7. |
| `API.getProcessedReport` | one report plus its metadata, human-formatted. Section 8. |
| `API.getBulkRequest` | several calls in one HTTP round trip. Section 8. |
| `SitesManager.getSiteFromId` | timezone, currency, creation date. |

## 5. Worked commands

Each is complete. Substitute the dates.

**Visits per day over the last 30 days.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.getVisits" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=last30" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_visitssummary_getvisits.json | jq -r 'to_entries[] | "\(.key)\t\(.value)"'
```

**Every core metric for one day.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_visitssummary_get_2.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

**Every core metric over an arbitrary window, as one figure.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_visitssummary_get_3.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=range" -d "date=2026-08-01,2026-08-07" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

**Traffic by channel, with the conversions each channel carried.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Referrers.getReferrerType" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_referrers_getreferrertype.json | jq -r '.[] | "\(.label)\t\(.nb_visits)\t\(.nb_conversions)\t\(.revenue)\t\(.segment)"'
```

**Top 20 pages, flattened, with visits and hits.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Actions.getPageUrls" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "flat=1" -d "filter_limit=20" -d "filter_sort_column=nb_visits" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_actions_getpageurls.json | jq -r '.[] | "\(.nb_visits)\t\(.nb_hits)\t\(.label)"'
```

**One page in particular, by pattern.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_actions_getpageurls_2.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Actions.getPageUrls" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "flat=1" -d "filter_column=label" -d "filter_pattern=cart" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

**Ecommerce orders and revenue as Matomo measured them.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_goals_get.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Goals.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "idGoal=ecommerceOrder" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

Returns `nb_conversions`, `nb_visits_converted`, `revenue`,
`revenue_subtotal`, `revenue_tax`, `revenue_shipping`, `revenue_discount`,
`items`, `avg_order_revenue`, `conversion_rate`, each also broken down
`_new_visit` and `_returning_visit`.

**Abandoned carts.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_goals_get_2.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Goals.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "idGoal=ecommerceAbandonedCart" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

**Products, ordered and abandoned.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Goals.getItemsSku" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "filter_limit=20" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_goals_getitemssku.json | jq -r '.[] | "\(.label)\t\(.quantity)\t\(.orders)\t\(.revenue)"'

curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Goals.getItemsSku" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "abandonedCarts=1" -d "filter_limit=20" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_goals_getitemssku_2.json | jq -r '.[] | "\(.label)\t\(.quantity)\t\(.abandoned_carts)\t\(.revenue)"'
```

**Visits by hour of day, in the site's timezone.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitTime.getVisitInformationPerServerTime" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_visittime_getvisitinformationperservertime.json | jq -r '.[] | "\(.label)\t\(.nb_visits)\t\(.nb_conversions)\t\(.segment)"'
```

**Countries.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=UserCountry.getCountry" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "filter_limit=15" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_usercountry_getcountry.json | jq -r '.[] | "\(.label)\t\(.nb_visits)\t\(.segment)"'
```

**A report restricted to a segment.**

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_actions_getpageurls_3.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Actions.getPageUrls" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "segment=deviceType==smartphone;countryCode==us" \
  -d "flat=1" -d "filter_limit=20" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

## 6. Live: the raw visit log

`Live.*` reads the visit log directly instead of a precomputed archive. It is
the only part of the API that returns individual visits, and the only part that
answers any segment reliably (section 7).

**Individual visits, most recent first.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Live.getLastVisitsDetails" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "filter_limit=25" -d "doNotFetchActions=1" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_live_getlastvisitsdetails.json | jq -r '.[] | [.serverDatePretty, .serverTimePretty, .visitorId, .countryCode, .deviceType, .referrerType, .visitEcommerceStatus, .totalEcommerceRevenue, .actions] | @tsv'
```

Parameters worth knowing:

| param | effect |
|---|---|
| `filter_limit` | how many visits. Defaults to **100**, same as everywhere else. |
| `doNotFetchActions=1` | omit `actionDetails`. Cuts the response by an order of magnitude. |
| `minTimestamp` | Unix seconds. Only visits after this instant. |
| `segment` | works here even when it returns nothing on an archived report. |
| `period`/`date` | still mandatory unless you pass `minTimestamp`. |

Each visit record carries roughly 100 keys. The useful ones:

- identity and recurrence: `idVisit`, `visitorId`, `userId`, `visitorType`,
  `visitCount`, `daysSinceFirstVisit`, `daysSinceLastVisit`
- time: `serverTimestamp`, `serverDatePretty`, `serverTimePretty`,
  `firstActionTimestamp`, `lastActionTimestamp`, `visitDuration`,
  `visitServerHour`, `visitLocalHour`
- origin: `referrerType`, `referrerTypeName`, `referrerName`, `referrerUrl`,
  `referrerKeyword`, `campaignName`, `campaignSource`, `campaignMedium`
- client: `countryCode`, `city`, `region`, `deviceType`, `deviceBrand`,
  `browserName`, `operatingSystemName`, `resolution`, `language`
- outcome: `visitConverted`, `goalConversions`, `visitEcommerceStatus`,
  `totalEcommerceConversions`, `totalEcommerceRevenue`, `totalEcommerceItems`,
  `totalAbandonedCarts`, `totalAbandonedCartsRevenue`
- the click path: `actionDetails`, an array of
  `{type, url, pageTitle, timestamp, serverTimePretty, timeSpent, pageviewPosition}`

`visitEcommerceStatus` is one of `none`, `ordered`, `abandonedCart`,
`orderedThenAbandonedCart`.

A visit whose status is `abandonedCart` has `totalEcommerceRevenue` of `0`. Its
value is in `totalAbandonedCartsRevenue`. The two never hold the same money.

`visitorId`, `userId`, `visitIp` and `fingerprint` can be suppressed by the
privacy settings, in which case they come back as `false` rather than being
absent. That is a configuration of the install, not a missing visitor.

**The click path of one visit.**

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Live.getLastVisitsDetails" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "segment=visitEcommerceStatus==abandonedCart" -d "filter_limit=3" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_live_getlastvisitsdetails_2.json | jq -r '.[] | .idVisit as $v | .actionDetails[] | [$v, .serverTimePretty, .type, .url // .pageTitle] | @tsv'
```

**Counters over the last N minutes.** Does not take `period`/`date`.

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_live_getcounters.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Live.getCounters" \
  -d "idSite=$MATOMO_SITE_ID" -d "lastMinutes=60" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

Returns `[{"visits":…,"actions":…,"visitors":…,"visitsConverted":…}]`.

**Everything known about one visitor**, across all their visits:

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_live_getvisitorprofile.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Live.getVisitorProfile" \
  -d "idSite=$MATOMO_SITE_ID" -d "visitorId=<visitorId>" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

## 7. Segments

`segment=` restricts a report to a subset of visits.

### Operators

| operator | meaning |
|---|---|
| `==` | equals |
| `!=` | not equals |
| `<=` `<` `>=` `>` | numeric comparison |
| `=@` | contains |
| `!@` | does not contain |
| `=^` | starts with |
| `=$` | ends with |

### Combining

`;` is AND. `,` is OR. **OR binds tighter than AND**, so
`a==1,b==2;c==3` means `(a==1 OR b==2) AND c==3`.

```
segment=deviceType==smartphone;countryCode==us
segment=countryCode==us,countryCode==ca
segment=referrerType==search;visitEcommerceStatus==ordered
```

An empty value tests for absence: `referrerKeyword==` matches visits with no
keyword. `city!=` matches visits that have one.

### Encoding

The value after the operator must be URL encoded: `%20` for a space, `%2F` for
a slash. With `curl -d` the shell will not do this for you. Use
`--data-urlencode` when the value contains anything but letters and digits:

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_visitssummary_get_4.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  --data-urlencode "segment=pageUrl=@/checkout;referrerName==Google Search" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

Dimension names are case sensitive: `userId`, not `userid`.

### Do not compose segments by hand

Every row of a dimensional report carries the exact segment that selects it, in
a field called `segment`:

```json
{"label":"Search Engines","nb_visits":6946,"segment":"referrerType==search"}
{"label":"00","nb_visits":180,"segment":"visitStartServerHour==22"}
```

Copy that string. The second example shows why: the hour *label* is in the
site's timezone, and the hour *dimension* is not. A hand-written
`visitServerHour==0` does not select the row labelled `00`.

### Finding the values a dimension takes

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_api_getsuggestedvaluesforsegment.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getSuggestedValuesForSegment" \
  -d "idSite=$MATOMO_SITE_ID" -d "segmentName=referrerType" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

For `referrerType` this returns `["direct","website","search","social","ai","campaign"]`.

### Common dimensions

`visitorId`, `userId`, `visitorType` (`new`, `returning`, `returningCustomer`),
`visitCount`, `visitDuration`, `actions`, `daysSinceFirstVisit`,
`daysSinceLastVisit`, `visitConverted`, `visitConvertedGoalId`,
`visitEcommerceStatus`, `visitServerHour`, `visitStartServerHour`,
`visitLocalHour`, `countryCode`, `countryName`, `city`, `regionCode`,
`languageCode`, `deviceType`, `deviceBrand`, `deviceModel`, `browserName`,
`operatingSystemName`, `resolution`, `referrerType`, `referrerName`,
`referrerKeyword`, `referrerUrl`, `campaignName`, `campaignSource`,
`campaignMedium`, `pageUrl`, `pageTitle`, `entryPageUrl`, `exitPageUrl`,
`actionUrl`, `siteSearchKeyword`, `eventCategory`, `eventAction`, `eventName`,
`productName`, `productSku`, `productCategory`, `revenueOrder`.

Run `API.getSegmentsMetadata` for the list this install actually supports.

### The zero that is not a zero

An archived report can only answer for segments that have been archived. If a
segment has never been processed and the install does not allow archiving on
request, the report returns **valid, well-formed, zero**. It looks exactly like
"there were no such visits".

Distinguish the two by asking `Live`, which reads the raw log and needs no
archive:

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_live_getcounters_2.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=Live.getCounters" \
  -d "idSite=$MATOMO_SITE_ID" -d "lastMinutes=1440" \
  -d "segment=countryCode==us" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN"
```

If `Live` shows visits and the archived report shows zero, the segment is
valid and the archive simply does not cover it. That is a fact about the
install, not an answer about the visitors.

An unrecognised dimension is different again: it returns `HTTP 200` with
`{"result":"error","message":"Segment 'xyz' is not a supported segment."}`.
See section 9.

## 8. Response shapes

Three shapes come back, and they are not interchangeable.

**A single record**, from a `.get` on one period:

```json
{"nb_uniq_visitors":10682,"nb_visits":13263,"nb_actions":29958,"bounce_rate":"68%"}
```

**A keyed map**, from any method over `lastN`/`previousN`:

```json
{"2026-07-28":15272,"2026-07-29":9953}
```

**An array of rows**, from any dimensional report. Every row has `label`, the
metrics, and usually `segment`. Rows of a hierarchical report also have
`idsubdatatable`, which you pass back as `idSubtable` to open that branch.

Note that some metrics arrive as **strings**, not numbers: `bounce_rate` is
`"68%"`, and in a few reports `nb_actions` is `"495"`. Pass `format_metrics=0`
if you need raw numbers throughout.

Dimensional rows for a site with goals also carry a nested `goals` object,
keyed `idgoal=ecommerceOrder`, `idgoal=ecommerceAbandonedCart`, `idgoal=7`.
That is how you get conversions per referrer or per hour without a second call.

### Two other ways to ask

`API.getProcessedReport` returns the report **and** its metadata, with
human-formatted values (`"$12,560.80"`, `"00:01:52"`) and translated column
names:

```bash
curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getProcessedReport" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "apiModule=Referrers" -d "apiAction=getReferrerType" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  | tee data/matomo_api_getprocessedreport.json | jq '{columns, reportTotal, reportData}'
```

`API.getBulkRequest` sends several calls in one round trip. Each `urls[n]` is
an encoded query string, and the response is an array in the same order:

```bash
curl -sS --cacert "$COMPANY_CA" -o data/matomo_api_getbulkrequest.json -w 'HTTP %{http_code}  %{size_download} bytes\n' -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=API.getBulkRequest" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN" \
  --data-urlencode "urls[0]=method=VisitsSummary.get&idSite=$MATOMO_SITE_ID&period=day&date=2026-08-01" \
  --data-urlencode "urls[1]=method=Goals.get&idSite=$MATOMO_SITE_ID&period=day&date=2026-08-01&idGoal=ecommerceOrder"
```

## 9. Errors

An error is a JSON object with exactly two keys:

```json
{"result":"error","message":"Please specify a value for 'date'."}
```

| status | cause | body |
|---|---|---|
| `400` | `period` or `date` missing, or a malformed date | names the parameter |
| `401` | bad or missing `token_auth` | authentication failure |
| `404` | the module in `method` does not exist | `The plugin Nope was not found.` |
| `500` | the call reached Matomo and failed inside it | the exception message |
| **`200`** | **an unsupported segment, and other in-band failures** | `Segment 'xyz' is not a supported segment.` |

That last row is the one that bites. **A 200 is not proof of success.** Test
the body, not only the status code:

```bash
resp=$(curl -sS --cacert "$COMPANY_CA" -X POST "$MATOMO_URL/index.php" \
  -d "module=API" -d "method=VisitsSummary.get" \
  -d "idSite=$MATOMO_SITE_ID" -d "period=day" -d "date=2026-08-01" \
  -d "format=JSON" -d "token_auth=$MATOMO_AGENT_TOKEN")
echo "$resp" | jq -e 'if type=="object" and .result=="error" then error(.message) else . end'
```

`curl` exit code 60 is not a Matomo error at all. It is the CA: see the top of
this file.

## 10. Traps

**The certificate.** Without `--cacert "$COMPANY_CA"` every call fails at the
TLS layer and reads like an outage. Never work around it with `-k`.

**period and date travel together.** Neither is optional. A 400 here is your
request, not the system.

**`filter_limit` defaults to 100.** Silently. A report with 4000 page URLs
returns 100 rows and nothing tells you the other 3900 exist. Pass an explicit
`filter_limit`, and `-1` when you genuinely need all of it.

**The last bucket of a `lastN` series is incomplete.** It is the period in
progress. It is not a decline.

**A tree is not a list.** `Actions.getPageUrls` without `flat=1` returns
directory names, not pages. `/products/x` and `/products/y` are folded into one
row labelled `products`.

**An error can arrive as HTTP 200.** Check `.result == "error"` in the body.

**A segment can return a legitimate-looking zero.** Section 7 shows how to tell
that apart from an absence of visits, using `Live`.

**Hour labels and hour segments are in different timezones.** Copy the
`segment` field off the row rather than composing `visitServerHour==N`.

**A visit is attributed to the hour it started.** Someone arriving at 08:55 and
converting at 09:05 sits entirely in the 08 bucket, conversion included.

**A visit is a browser session, not a person and not a record.** One visitor may
return several times, and what the tracker counts is what the browser reported.
