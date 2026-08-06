---
name: logs-loki
description: Read what the running services actually wrote, by querying Grafana Loki over HTTP. Use whenever a question needs evidence from service logs: the storefront, the gateway, Matomo, or the ERP file drop. Covers label discovery, the endpoints, LogQL (line filters, label filters, parsers, formatting, metric queries), time bounds in Unix nanoseconds, the response JSON shape, the limits and the error codes.
---

Loki holds what the services write to stdout. Grafana publishes **no OpenAPI
document** for Loki, so this file is the contract.

`$LOKI_URL` is the base. No auth header is needed. Every path below is appended
to it.

## Where the answers land

Every call below writes its body to `data/`, named for the endpoint, and prints
one line back: the status and the size. The ones that pipe into `jq` for a slice
still keep the whole response, with `tee` on the way past.

```
curl -sS -G -o data/NAME -w 'HTTP %{http_code}  %{size_download} bytes\n' "$LOKI_URL/..."
```

This matters more here than anywhere else, because a log query answers with far
more than fits on a screen and the interesting part is usually a count, a first
and last timestamp, or a set of distinct values — none of which you get by
scrolling.

## 1. Start here

Do these in order. Steps 1 and 2 cost nothing and stop you from querying a label
that does not exist.

**1. List the labels.**

```bash
curl -sS -o data/loki_labels.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$LOKI_URL/loki/api/v1/labels"
```

**2. List the values of the label you intend to select on.**

```bash
curl -sS -o data/loki_label_service_values.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$LOKI_URL/loki/api/v1/label/service/values"
```

**3. Confirm the streams that actually exist.**

```bash
curl -sS -G -o data/loki_series.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$LOKI_URL/loki/api/v1/series" \
  --data-urlencode 'match[]={job="company"}'
```

**4. Pull a small sample first, with a narrow window and a small limit.** Look at
the shape of the lines before you write a real filter.

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query={service="prestashop"}' \
  --data-urlencode 'since=15m' \
  --data-urlencode 'limit=5' \
  --data-urlencode 'direction=backward' \
  | tee data/loki_query_range.json | jq -r '.data.result[].values[][1]'
```

**5. Then narrow with a line filter and only then widen the window.**

## 2. The labels in this deployment

Three labels: `job`, `service`, `service_name`. **There is no `container` label.**
A selector on `container` returns an empty result, which looks identical to a
service that logged nothing.

`service` and `service_name` are duplicates. Use `service`.

`{job="company"}` selects everything at once.

**The values of `service` are not listed here, deliberately.** Ask for them — step
2 above returns them, and it is the only source that cannot be out of date. A
company acquires systems; a list written into a document does not. This section
used to carry that list, and by the time anyone noticed it was missing three
services, several investigations had hand-written a selector from it and never
queried what it omitted.

A service you did not select is indistinguishable, in the result, from a service
that stayed silent. So enumerate first, then narrow — never the reverse.

### detected_level

Query results also carry a `detected_level` key inside the `stream` object. It is
structured metadata added by Loki, not an index label: it does not appear in
`/loki/api/v1/labels` and `/loki/api/v1/label/detected_level/values` returns
nothing. It is still usable as a label filter after the selector:

```
{service="gateway"} | detected_level="error"
```

In this deployment it is `unknown` on effectively every line, because the
services do not emit a level Loki recognises. Do not filter on it and do not read
meaning into it.

## 3. The endpoints

| path | what it does |
|---|---|
| `/loki/api/v1/query_range` | logs or metrics over a time window. The one you want. |
| `/loki/api/v1/query` | a single instant. Only useful for metric queries. |
| `/loki/api/v1/labels` | which labels exist |
| `/loki/api/v1/label/<name>/values` | which values a label takes |
| `/loki/api/v1/series` | which streams match a selector |
| `/loki/api/v1/tail` | a websocket. Not usable from a script. |

### query_range parameters

| param | meaning | default |
|---|---|---|
| `query` | the LogQL query. Required. | none |
| `since` | window length relative to `end`, e.g. `30m`, `6h`, `2d` | none |
| `start` | window start, **Unix nanoseconds** | 1 hour ago |
| `end` | window end, **Unix nanoseconds** | now |
| `limit` | max lines returned, log queries only | `100` |
| `direction` | `backward` (newest first) or `forward` | `backward` |
| `step` | resolution of a metric query, e.g. `300` or `5m` | dynamic |
| `interval` | minimum gap between returned log lines | none |

`start` is inclusive, `end` is exclusive. An explicit `start` supersedes `since`.

`/loki/api/v1/labels`, `/label/<name>/values` and `/series` accept `start`, `end`
and `since` too. Their window defaults to the **last 6 hours**, so a label that
only appeared yesterday will not be listed unless you pass `since=48h`.

## 4. Time bounds

`start` and `end` are **Unix nanoseconds**, not seconds. Off by a factor of a
billion, the query silently covers a window in 1970 and returns nothing. There is
no error.

The simplest way to avoid the mistake is to not compute timestamps at all. Use
`since`:

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query={service="gateway"} |= "500"' \
  --data-urlencode 'since=2h' \
  --data-urlencode 'limit=100' \
  --data-urlencode 'direction=backward' \
  | tee data/loki_query_range_2.json | jq -r '.data.result[].values[] | [.[0], .[1]] | @tsv'
```

When you need an explicit window, build it from seconds and multiply. This is
portable across macOS and Linux:

```bash
NOW_NS=$(( $(date -u +%s) * 1000000000 ))
START_NS=$(( NOW_NS - 3600 * 1000000000 ))   # one hour back

curl -sS -G -o data/loki_query_range_3.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query={service="prestashop"} |= "carrier"' \
  --data-urlencode "start=$START_NS" \
  --data-urlencode "end=$NOW_NS" \
  --data-urlencode 'limit=200' \
  --data-urlencode 'direction=backward'
```

RFC3339 is also accepted in `start` and `end`, e.g.
`start=2026-08-03T18:00:00Z`. That form cannot be off by 10^9.

`direction=backward` returns the most recent first. That is what you want when
you do not know how much there is: the `limit` then truncates the old end, not
the recent end.

### How far back this instance holds anything

Ask it. Walk forward from a wide window and read the oldest timestamp returned:

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query={job="company"}' \
  --data-urlencode 'since=720h' \
  --data-urlencode 'limit=1' \
  --data-urlencode 'direction=forward' \
  | tee data/loki_query_range_4.json | jq -r '.data.result[].values[][0]'
```

Divide by 10^9 for seconds. Anything older than that line is gone.

## 5. The response shape

### Log queries: resultType `streams`

```json
{
  "status": "success",
  "data": {
    "resultType": "streams",
    "result": [
      {
        "stream": { "job": "company", "service": "gateway", "service_name": "gateway", "detected_level": "unknown" },
        "values": [
          ["1785786534841318879", "the log line as a string"]
        ]
      }
    ],
    "stats": { }
  }
}
```

Each entry in `values` is a two-element array. Element 0 is the timestamp as a
**string of Unix nanoseconds**. Element 1 is the raw log line. Lines are grouped
by stream, so a query over several services returns several `result` objects and
the lines are **not globally sorted** across them.

### Metric queries over a range: resultType `matrix`

```json
{
  "status": "success",
  "data": {
    "resultType": "matrix",
    "result": [
      { "metric": { "service": "gateway" }, "values": [[1785782700, "1022"], [1785783000, "967"]] }
    ]
  }
}
```

Here the timestamp is **seconds**, a number, not nanoseconds. The value is a
string.

### Metric queries at an instant: resultType `vector`

```json
{
  "status": "success",
  "data": {
    "resultType": "vector",
    "result": [
      { "metric": { "service": "gateway" }, "value": [1785786601.077, "623"] }
    ]
  }
}
```

Singular `value`, not `values`.

### Always pipe through jq

Every response carries a large `stats` object: cache counters, chunk counters,
bytes processed. It is several times the size of a small result and it tells you
nothing. Never dump a raw response.

```bash
# lines only
| jq -r '.data.result[].values[][1]'

# timestamp and line, tab separated
| jq -r '.data.result[].values[] | [.[0], .[1]] | @tsv'

# readable timestamp, service, line
| jq -r '.data.result[] as $s | $s.values[] | [((.[0]|tonumber)/1e9|todate), $s.stream.service, .[1]] | @tsv'

# metric series
| jq -r '.data.result[] | "\(.metric) \(.values[-1][1])"'
```

## 6. LogQL

A query is a **stream selector in braces**, then an optional pipeline of stages
separated by `|`. The selector is mandatory. You cannot search all logs without
one.

Loki evaluates the pipeline left to right. Put the cheap stages first: selector,
then line filters, then parsers, then label filters. A parser placed before a
line filter has to parse every line in the stream instead of the few that
survived the filter.

### Stream selector

```
{service="prestashop"}          exact
{service!="matomo"}             not equal
{service=~"prestashop|gateway"} regex, fully anchored
{service!~"matomo|erpfile"}     negative regex, fully anchored
{job="company"}                 everything
```

Selector regexes are anchored: `service=~"presta"` matches nothing,
`service=~"presta.*"` matches.

### Line filter expressions

Operate on the raw line. These are the fastest stage available.

```
{service="prestashop"} |= "carrier"          line contains
{service="prestashop"} != "healthcheck"      line does not contain
{service="gateway"}    |~ "status\":5[0-9]{2}"   line matches regex, not anchored
{service="gateway"}    !~ "/(health|metrics)"    line does not match regex
```

They chain, and chaining is an AND:

```
{service="gateway"} |= "POST" |= "/api" != "200"
```

`| decolorize` strips ANSI escape codes from a line.

Use backticks for the string when it contains backslashes or double quotes. LogQL
treats a backtick-quoted string as raw, so no double escaping:

```
{service="prestashop"} |~ `"(GET|POST) /order`
```

### Parser expressions

A parser turns the line into labels you can then filter and format on.

- `json` : JSON lines. Nested fields flatten with `_`.
- `logfmt` : `key=value` lines. Flags `--strict` and `--keep-empty`.
- `pattern "..."` : fixed-shape text. `<name>` captures, `<_>` skips a field.
- `regexp "..."` : anything else. Go RE2, named captures only.
- `unpack` : JSON where an `_entry` field holds the real line.

```
{service="gateway"} | json
{service="gateway"} | json code="status", route="uri"
{service="erpfile"} | logfmt
{service="prestashop"} | pattern `<ip> - <user> [<ts>] "<method> <uri> <proto>" <status> <size> "<referer>" "<ua>"`
{service="erpfile"} | regexp `(?P<event>Accepted|Failed) (?P<method>\w+) for (?P<user>\w+)` | event != ""
```

Give `json` an explicit field list when you can. Bare `| json` extracts every key
in the line, which is fine for a log query but explodes a metric query. See
section 9.

A parser that fails on a line sets `__error__` on that line rather than dropping
it, and leaves its captures empty. `| event != ""` above drops the lines the
regexp did not match. Without it you get blank output lines. See section 9.

### Label filter expressions

Run after a parser, on the extracted labels. They are typed.

```
| status >= 400                      number
| status == 200
| duration > 1s                      Go duration
| bytes_sent > 20KB                  bytes
| method = "POST"                    string
| user =~ "5ZX.*"                    string regex
```

Chain with `and`, `or`, or a comma, and group with parentheses:

```
{service="gateway"} | json | status >= 400 and method != "GET"
{service="gateway"} | json | (status == 401 or status == 403)
```

### Formatting

`| line_format` rewrites the output line with a Go template. This is how you cut
a wide line down to the fields you care about, which directly cuts how much of
the response you have to read.

```
{service="gateway"} | json | line_format "{{.status}} {{.method}} {{.uri}} {{.duration}}"
```

`__line__` is the original line and `__timestamp__` the entry time inside a
template.

`| label_format` renames or computes a label:

```
| label_format endpoint=uri
| label_format summary="{{.method}} {{.uri}}"
```

`| drop` and `| keep` prune labels:

```
| drop ua, referer
| keep method, uri, status
```

### Metric queries

Wrap a log query in a range aggregation with a range interval in brackets. These
return `matrix` from `query_range` and `vector` from `query`. They are the way to
answer "how much" and "when did it change" without pulling the lines themselves.

Log range aggregations:

- `count_over_time({...}[5m])` : number of entries per stream per interval
- `rate({...}[5m])` : entries per second
- `bytes_over_time({...}[5m])`, `bytes_rate({...}[5m])`
- `absent_over_time({...}[5m])` : 1 when the stream produced nothing

Aggregate across streams with `sum`, `avg`, `min`, `max`, `count`, `topk`,
`bottomk`, grouped with `by (...)` or `without (...)`:

```
sum by (service) (count_over_time({job="company"}[5m]))
topk(5, sum by (service) (rate({job="company"}[5m])))
```

Unwrapped aggregations turn an extracted label into a number instead of counting
lines:

- `avg_over_time`, `max_over_time`, `min_over_time`, `sum_over_time`,
  `stddev_over_time`
- `quantile_over_time(0.95, ...)`
- conversions: `unwrap duration_seconds(field)`, `unwrap bytes(field)`

Scope the parser and group the result, or the query dies on the series cap:

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query=quantile_over_time(0.95, {service="gateway"} | json duration="duration", route="uri" | __error__="" | unwrap duration [5m]) by (route)' \
  --data-urlencode 'since=1h' \
  --data-urlencode 'step=300' \
  | tee data/loki_query_range_5.json | jq -r '.data.result[] | .metric.route + " " + .values[-1][1]'
```

`without ()` collapses everything into one series when you want a single number
per step:

```
avg_over_time({service="gateway"} | json duration="duration" | __error__="" | unwrap duration [5m]) without ()
```

Volume per service over the last 6 hours:

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query=sum by (service) (count_over_time({job="company"}[5m]))' \
  --data-urlencode 'since=6h' \
  --data-urlencode 'step=300' \
  | tee data/loki_query_range_6.json | jq -r '.data.result[] | .metric.service + " " + (.values | map(.[1]) | join(","))'
```

Gateway responses broken down by HTTP status:

```bash
curl -sS -G "$LOKI_URL/loki/api/v1/query_range" \
  --data-urlencode 'query=sum by (status) (count_over_time({service="gateway"} | json | __error__="" [10m]))' \
  --data-urlencode 'since=3h' \
  --data-urlencode 'step=600' \
  | tee data/loki_query_range_7.json | jq -r '.data.result[] | .metric.status + " " + (.values | map(.[1]) | join(","))'
```

`step` controls how many points come back. `since=6h` with `step=300` is 72
points per series. A small `step` over a long window returns a wall of numbers.

`offset` shifts a range vector and must sit immediately after the brackets:
`count_over_time({job="company"}[5m] offset 1h)`.

## 7. What each service writes

The line format decides which parser applies. **This list is partial**: it covers
the services these notes happened to be written against, not every service the
enumeration in §1 step 2 will return. Sample any service with `limit=3` before building
on it — including, and especially, one that is not described below.

- `gateway` : one JSON object per line. Parse with `json`.
- `prestashop` : nginx/Apache combined access log. Parse with `pattern`.
- `matomo` : nginx/Apache combined access log. Parse with `pattern`.
- `erpfile` : plain sshd text, no structure. Use line filters, or `regexp`.

A caution on that last one, because it has been misread: `erpfile` is the **file
drop's SSH daemon**. It records who connected, not what the data did. Reading it
end to end tells you that sessions opened and closed and nothing whatever about
the contents of the drop or what any system made of them.

That distinction generalises. A service's log tells you what *that process* did.
Where two systems meet, the record of the meeting belongs to whatever sits
between them — which is its own service, with its own name, and it will not be
the name of either system it connects.

The gateway JSON has these keys: `time`, `client`, `xff`, `method`, `uri`,
`status`, `bytes`, `duration`, `upstream`, `upstream_time`, `referer`, `ua`,
`sim`.

In the combined access log format, the third field is `-` for anonymous traffic
and carries the API key for authenticated webservice calls.

## 8. Limits and status codes

- `limit` defaults to **100**. If you do not pass it, you get 100 lines and no
  warning that there were more.
- `limit` is capped at **5000** in this deployment. Above it the request fails
  with `400` and the body
  `max entries limit per query exceeded, limit > max_entries_limit (99999 > 5000)`.
- `limit` applies to log queries only. It does nothing to a metric query.
- A metric query is capped at **500 series**. Over it the request fails with
  `400` and the body `maximum of series (500) reached for a single query`.

| code | meaning |
|---|---|
| `200` | success. Check `data.result` is non-empty: a valid query with no matches is also a 200. |
| `400` | bad LogQL (`parse error at line 1, col 1: ...`), bad timestamp, or a limit over the cap. The body says which. |
| `404` | wrong path. Check the `/loki/api/v1/` prefix. |
| `429` | rate limited. Wait, then narrow the query. |
| `500` | Loki failed the query, usually because it was too large. Narrow the window. |

On any non-200, read the response body. It is a plain string and it names the
problem exactly.

## 9. Traps

**Nanoseconds.** `start` and `end` are nanoseconds. Seconds gives you 1970 and an
empty result, silently. Prefer `since`.

**`container` does not exist.** The labels are `job`, `service`, `service_name`.
Nothing else. A selector on a non-existent label is not an error, it is an empty
result.

**An empty result is not an answer.** A `200` with `"result": []` means one of
four things: it did not happen, it happened outside the window, it happened
before retention dropped it, or the query is wrong. Rule out the last three
before believing the first. Re-run without the line filter to check the stream
has anything at all in that window.

**Logs expire.** A line is kept for a while and then it is gone. An empty result
means *not found in what is retained*, never *did not happen*. Section 4 shows
how to find the oldest line the instance still holds.

**A parser error is a 400 on metric queries.** If any line in range fails to
parse, a log query tags it with `__error__` and carries on, but a metric query
aborts with `400 pipeline error: 'JSONParserErr' for series: ...`. Not every
gateway line is valid JSON. Add `| __error__=""` after the parser in any metric
query:

```
sum by (status) (count_over_time({service="gateway"} | json | __error__="" [10m]))
```

**Bare `| json` blows up a metric query.** Each extracted field becomes a label,
and each combination of labels becomes a series. On the gateway, `uri`, `ua` and
`time` are near-unique per line, so `avg_over_time({service="gateway"} | json |
unwrap duration [5m])` fails with `400 maximum of series (500) reached for a
single query`. Two fixes, use both: name only the fields you need
(`| json duration="duration"`), and group the result (`by (route)` or
`without ()`). This does not affect log queries, where bare `| json` is fine.

**A parser that does not match does not drop the line.** It leaves the captures
empty, so `line_format` prints blanks. Add a label filter on a capture
(`| event != ""`) to keep only the lines that parsed.

**The `stats` block dwarfs small results.** Always pipe through `jq` and select
the fields you need. Section 5 has the recipes.

**Anchored where you do not expect it.** Label matchers (`=~` inside the braces
and in label filters) are fully anchored. Line filters (`|~`, `!~`) are not.

**Narrow beats broad.** `limit` caps what comes back and Loki refuses queries
that scan too much, but neither protects you from reading 3000 lines of routine
traffic to find one. An unfiltered query over a busy service returns thousands of
lines and the line that mattered is somewhere inside. More log is not more
evidence: a run that pulled everything spent its whole context on gateway noise
and never reached the line it needed, while a narrower query found it
immediately. Add a line filter, cut the window, and use `line_format` to drop the
fields you are not reading.
