---
name: shop-webservice
description: Read the storefront through the PrestaShop Webservice REST API: orders, order states and state history, order lines, carts, customers, addresses, products, stock, carriers, shipping zones and prices. The shop describes itself, so this covers the two calls that replace a contract file (the API root, which lists resources with per-verb permissions for your own key, and ?schema=synopsis, which lists a resource's fields with required/format/filterable flags), plus the CA certificate every call needs, Basic auth with the key as username, the JSON switch, display/filter/limit syntax, the date=1 rule, and the calls that fail by returning an empty list instead of an error.
---

The shop is a PrestaShop (server reports `PSWS-Version: 9.1.4`). It answers over
its Webservice REST API.

**There is no contract file, because the shop is its own contract.** Two calls
give you everything a specification would, and unlike a specification they
cannot go stale:

- the API root lists every resource **with a per-verb permission flag for your
  key**, so it tells you what *you* may read rather than what PrestaShop can do;
- `?schema=synopsis` on a resource returns its fields with `required`, a
  `format` such as `isUnsignedId`, `isDate` or `isPrice`, and flags for the
  fields that cannot be filtered or written.

Both are XML only. Adding `output_format=JSON` to the root returns HTTP 500 with
an empty body, and synopsis in JSON silently drops every scalar field and
returns only the associations.

An exported OpenAPI file used to ship here. It was dropped: it described every
resource PrestaShop can expose rather than the ones this key reaches, and it
named a host this deployment does not use. A generated document is a photograph
of a system. The calls below are the system.

## Every request needs these five things

1. `--cacert "$COMPANY_CA"`. The company runs on `.test` domains with
   certificates signed by its own internal CA. Without it curl exits 60
   ("unable to get local issuer certificate") and the shop looks down when it is
   not. `$COMPANY_CA` is a filename (`company-ca.crt`) in your working
   directory. Do **not** replace it with `-k` or `--insecure`. Trusting the
   company CA is what an employee's machine does. Turning verification off is
   what somebody does at 2am and never puts back.
2. `-g` (globoff). Nearly every useful parameter contains `[` and `]`, and curl
   reads those as glob ranges. Without `-g` you get `curl: (3) bad range in URL`
   and no request is sent.
3. `-u "$SHOP_API_KEY:"`. HTTP Basic, the key is the **username**, the password
   is **empty**. The trailing colon is what makes it empty. Sending the key as
   the password gives 401 code 17, "Authentication key is empty".
4. `output_format=JSON` on the query string. The default output is XML. The two
   self-description calls are the exception: they only work in XML.
5. `-o data/<name>` and `-w 'HTTP %{http_code}  %{size_download} bytes\n'`. The
   body goes to a file named for the call; what comes back to you is one line
   saying whether it worked and how much arrived. Every example below is written
   that way: a response you can reopen, slice and compute over is evidence, and
   a response that scrolled past once is a recollection. The receipt is also the
   only place the status code appears — with the body in a file, a `401` is
   otherwise invisible.

So the invariant prefix for everything below is:

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/NAME -w 'HTTP %{http_code}  %{size_download} bytes\n'
```

Two kinds of call in this file deliberately break that and let the body print:
one that pipes straight into `grep` or `jq` for a slice (those keep the whole
response with `tee` on the way past), and the two that provoke an error on
purpose, where the error message *is* the answer.

## Ask the shop what it is

This is the whole method. Ask the root what you may read, ask synopsis what a
resource holds, then query. Never assume a field name or a permission.

**Prove the connection and the credentials.** `200` is good. `401` means the key
was rejected or is not granted this resource. Curl exit 60 means no `--cacert`.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o /dev/null -w 'HTTP %{http_code}\n' "$SHOP_API_URL/orders?output_format=JSON"
```

**Ask the root what your key may do.** It lists only the resources granted to
your key, each with a flag per verb. There is nothing to infer: `get="true"` is
permission to read, `post="false"` is a write that will be refused.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_root.xml -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/"
```

Each entry looks like this, and carries a one-line `description` and links to
its two schemas:

```
<addresses xlink:href=".../api/addresses" get="true" put="false" post="false" patch="false" delete="false" head="true">
```

Distilled to a resource list:

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" "$SHOP_API_URL/" | tee data/shop_root.xml | grep -oE '^<[a-z_]+ xlink:href="[^"]+" get="[a-z]+"' | grep -v description | sed -E 's/ xlink:href="[^"]+"//; s/[<>]//g' | sort
```

A resource absent from that output is not missing from PrestaShop. It is out of
scope for your key, and calling it returns 401 code 26.

**Ask synopsis what a resource holds.** This is the field list, and more: which
fields are mandatory, what shape their values take, which ones you cannot filter
on, and which ones are computed rather than stored.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders_synopsis.xml -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?schema=synopsis"
```

Read the attributes on each element:

| Attribute | Means |
|---|---|
| `required="true"` | always present on a stored row |
| `format="isDate"`, `isPrice`, `isUnsignedId`, `isBool`, `isFloat` | the value's shape |
| `notFilterable="true"` | displayable but rejected in `filter[...]` |
| `read_only="true"` | computed or joined, not a stored column |
| `xlink:href=".../api/products/"` | this field is a foreign key, and to what |

Below the scalars, `<associations>` lists the nested collections that come back
with a single record or with `display=full`. On `orders` that is `order_rows`,
the order lines.

So to find what you cannot filter on before the filter fails:

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" "$SHOP_API_URL/products?schema=synopsis" | tee data/shop_products_synopsis.xml | grep notFilterable
```

`schema=blank` is the same list without the annotations. Prefer synopsis.

**Make the shop list its own fields by getting it wrong.** Every field-name
error returns the complete set of names it would have accepted, which is often
faster than reading the schema. `display` and `filter` answer with different
lists, and the difference is real: `date_add` is displayable always but
filterable only when `date=1` is present.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" "$SHOP_API_URL/orders?output_format=JSON&display=[nope]"
```

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" "$SHOP_API_URL/orders?output_format=JSON&date=1&filter[nope]=1"
```

**Read one record whole before querying many.** A single record shows the real
values, the id references and the nested lines.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_order_5324.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders/5324?output_format=JSON"
```

## Querying

A bare collection call returns ids and nothing else:
`{"orders":[{"id":6},{"id":7},...]}`.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_order_ids.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&limit=5"
```

| Parameter | Syntax | Notes |
|---|---|---|
| `output_format` | `JSON` or `XML` | XML is the default. Always pass `JSON`, except for the root and for `schema`. |
| `display` | `full` or `[f1,f2]` | Omit and you get ids only. `full` also returns the `associations` block. |
| `filter[field]` | see operators below | Repeatable, ANDed. |
| `date` | `1` | Unlocks `date_add` and `date_upd` as filterable. Nothing else does. |
| `limit` | `n` or `offset,n` | Zero-indexed. No total count is returned anywhere. |
| `language` | `1`, `[1\|2]`, `[1,2]` | Collapses multilingual fields. See below. |
| `schema` | `blank` or `synopsis` | Field templates. XML only in practice. |
| `id_shop` | shop id or `all` | Single-shop here, rarely needed. |
| `sort` | `[field_ASC]` | **Broken on this deployment. Do not use.** See below. |

**Pick fields.**

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&limit=20&display=[id,reference,date_add,total_paid,current_state,valid,id_carrier,id_customer]"
```

**Everything for a few rows.** `display=full` on a collection returns the
`associations` block too, so order lines come back inline. It is large: cap it.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders_full.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&limit=2&display=full"
```

**A time window.** Needs `date=1` *and* the bracket range. Spaces must be `%20`.
The values are shop-local time (`$SHOP_TIMEZONE`).

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders_day.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&date=1&filter[date_add]=[2026-08-03%2000:00:00,2026-08-03%2023:59:59]&display=[id,reference,date_add,total_paid,current_state]"
```

**Two filters.** Repeat `filter[...]`; they are ANDed.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders_day_valid.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&date=1&filter[date_add]=[2026-08-03%2000:00:00,2026-08-03%2023:59:59]&filter[valid]=1&display=[id,reference,current_state]"
```

**Paging.** `limit=offset,n`.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_orders_page11.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/orders?output_format=JSON&limit=1000,100&display=[id,date_add]"
```

### Filter operators

| Form | Meaning |
|---|---|
| `filter[valid]=1` | exact match, case-insensitive |
| `filter[id]=[6\|7]` | OR, a set of values |
| `filter[id]=[6,8]` | interval, inclusive, numeric or date |
| `filter[payment]=[Bank]%25` | begins with |
| `filter[payment]=%25[transfer]` | ends with |
| `filter[payment]=%25[Bank]%25` | contains |

The brackets are part of the wildcard syntax, not optional grouping.
`filter[payment]=%25Bank%25` without them matches nothing and returns `[]`.
Send the `%` of a wildcard as `%25`: a raw `%` is a percent-escape introducer,
and it survives here only because it always sits next to a `[`.

Only stored columns are filterable. A computed field refuses with code 34, `The
field "x" is dynamic. It is not possible to filter GET query with this field.`
`products.quantity` is one of these: displayable, not filterable, and marked
`notFilterable="true"` in the synopsis. The live number is in
`stock_availables`.

### Multilingual fields

`name`, `description` and similar come back as an array of one entry per
installed language (`1` is English, `2` is French; confirm with `/languages`):

```
"name": [{"id":1,"value":"Oak Log"},{"id":2,"value":"Bûche"}]
```

Adding `language=1` collapses them to a plain string. Do that unless you need
every translation, otherwise every string comparison has to unwrap a list.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_products.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/products?output_format=JSON&limit=5&language=1&display=[id,reference,name,price,active]"
```

## Resource map

**What this key reached at the time of writing. Confirm against the API root.**
The root is what decides, and its answer can change without this file changing.

| Resource | Holds | Joins by |
|---|---|---|
| `orders` | one row per placed order: `reference`, `date_add`, `total_paid`, `total_paid_real`, `total_products`, `total_shipping`, `current_state`, `valid`, `payment`, `module`, `conversion_rate`, `invoice_number`. `associations.order_rows` carries the lines. | `id_customer`, `id_cart`, `id_carrier`, `id_currency`, `id_address_delivery`, `id_address_invoice` |
| `order_states` | the state dictionary: `name`, plus flags `paid`, `shipped`, `logable`, `delivery`, `invoice`, `hidden` | `orders.current_state` |
| `order_histories` | every state transition with `date_add` and `id_employee` (0 = system) | `id_order`, `id_order_state` |
| `order_details` | order lines as a queryable collection: `product_name`, `product_quantity`, `product_reference`, `unit_price_tax_incl`, `total_price_tax_incl`. No date of its own. | `id_order`, `product_id` |
| `order_carriers` | the carrier actually attached to an order, with `shipping_cost_tax_incl`, `weight`, `tracking_number`, `date_add` | `id_order`, `id_carrier` |
| `carts` | baskets, placed or not: `date_add`, `date_upd`, `delivery_option`, `id_guest`, and `cart_rows`. A cart with no order is an abandoned one. | `id_customer`, `id_address_delivery`, `id_carrier` |
| `customers` | `email`, `firstname`, `lastname`, `date_add`, `newsletter`, `active`, `is_guest`, `deleted`, `id_default_group` | `id` |
| `addresses` | `city`, `postcode`, `address1`, `phone`, `deleted` | `id_customer`, `id_country`, `id_state` |
| `countries` | `iso_code`, `name`, `active`, `contains_states` | `id_zone` |
| `states` | sub-national regions: `iso_code`, `name`, `active` | `id_country`, `id_zone` |
| `zones` | shipping zones: `name`, `active` | referenced by `countries`, `states`, `deliveries` |
| `carriers` | `name`, `active`, `deleted`, `id_reference`, `shipping_method`, `range_behavior`, `max_weight`, `is_free`, `delay` | `id` |
| `deliveries` | the shipping price grid: `price` per (`id_carrier`, `id_zone`, `id_range_weight`, `id_range_price`) | `id_carrier`, `id_zone` |
| `price_ranges` | the price bands `deliveries` refers to: `delimiter1`, `delimiter2` | `id_carrier` |
| `products` | `reference`, `name`, `price`, `active`, `available_for_order`, `visibility`, `quantity` (read-only), `date_add` | `id_category_default`, `id_supplier`, `id_manufacturer` |
| `stock_availables` | `quantity`, `out_of_stock`, `depends_on_stock` per product (and per combination) | `id_product`, `id_product_attribute` |
| `categories`, `suppliers`, `currencies`, `languages`, `shops` | reference data | |

Absent from the root at the time of writing, so 401 rather than missing:
`order_payments`, `order_invoices`, `cart_rules`, `order_cart_rules`, `guests`,
`roles`, `configurations`, `taxes`, `stocks`, `warehouses`,
`weight_ranges`.

**Resolve a state id.** `current_state` on an order is an id into
`order_states`. That resource carries machine-readable flags, so a number never
has to be guessed at.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_order_states.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/order_states?output_format=JSON&language=1&display=[id,name,paid,shipped,logable,delivery,invoice,hidden]"
```

**How one order moved between states, with timestamps.**

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_order_histories.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/order_histories?output_format=JSON&filter[id_order]=5324&display=full"
```

**Carriers.** `deleted=1` rows are returned alongside live ones.

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_carriers.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/carriers?output_format=JSON&display=[id,name,active,deleted,id_reference,is_free,shipping_method,range_behavior]"
```

**What a carrier costs, per zone.** `deliveries` is the price grid: one row per
(carrier, zone, weight range, price range).

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_deliveries.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/deliveries?output_format=JSON&filter[id_carrier]=6&display=full"
```

**Stock for a product.**

```
curl -sS -g --cacert "$COMPANY_CA" -u "$SHOP_API_KEY:" -o data/shop_stock_availables.json -w 'HTTP %{http_code}  %{size_download} bytes\n' "$SHOP_API_URL/stock_availables?output_format=JSON&filter[id_product]=69&display=[id,id_product,id_product_attribute,quantity,out_of_stock]"
```

## Reading errors

Failures come back as a JSON `errors` array. Read `code` and `message`. Do not
read the HTTP status alone: this deployment emits PHP warnings (code 3) beside
real errors, and returns **500 for input problems that are logically 400**.

```
{"errors":[{"code":26,"message":"Resource of type \"order_payments\" is not allowed with this authentication key"}]}
```

| Status | Code | Means |
|---|---|---|
| 401 | 17 | key sent as the password instead of the username |
| 401 | 18 | key is not 32 characters of the expected alphabet |
| 401 | 20 / 21 | key is well formed but unknown or deactivated |
| 401 | 26 | this resource is not granted to this key |
| 404 | none | that id does not exist. **The body is empty**, in JSON and in XML |
| 405 | 25 | that verb is not granted to this key (every write, here) |
| 500 | 32 | that filter field does not exist, message lists the valid ones |
| 500 | 34 | that field is computed, not stored, so it cannot be filtered on |
| 500 | 35 | unknown `display` field, message lists the valid ones |
| 500 | 36 | malformed `display` syntax, message lists the valid ones |
| 500 | 38 | unknown `sort` field, message lists the valid ones |

401 means *this identity may not*. It never means *this does not exist*.

## Failures that look like answers

**`sort` is broken here.** Any `sort=[...]` returns HTTP 200 with a body of
`[]`, on every resource, with or without `date=1`. The generated ORDER BY is
invalid SQL and the failure is swallowed. An empty list is indistinguishable
from "no rows matched". Do not sort server-side. Fetch and sort in your own
code. A *misspelled* sort field is the only one that errors (code 38), so a
successful-looking empty answer is the failure mode.

**An empty result is `[]`, not `{"orders":[]}`.** The envelope key vanishes when
nothing matched. Code that does `response["orders"]` raises, and code that does
`response.get("orders", [])` silently reports zero. Check for the bare `[]`.

**A date filter without `date=1` is rejected, and the rejection reads as zero.**
`filter[date_add]` and `filter[date_upd]` are only accepted when `date=1` is
also present. Without it the response is an `errors` payload (code 32, "This
filter does not exist"), not an `orders` payload. A client that reaches for the
`orders` key and defaults to an empty list turns that error into "no orders".
Send `date=1` alongside any date filter, and check whether the body is an error
before reading it as data.

**An exact match on a datetime can never succeed.**
`filter[date_add]=2026-08-03` returns `[]` with HTTP 200, because no stored
value equals a date with no time component. Use the bracket range with explicit
times.

**Timestamps are shop-local, not UTC.** `date_add`, `date_upd`, `invoice_date`
are stored in `$SHOP_TIMEZONE`. A window computed in UTC returns a plausible,
non-empty, wrong set of rows, offset by the difference.

**There is no total count.** Not in the body, not in a header, not on HEAD. To
size a set, page with `limit=offset,n` until a short page comes back, or fetch
`display=[id]` and count client-side.

**Carriers are versioned by soft delete.** Editing a carrier in PrestaShop marks
the old row `deleted=1` and inserts a new one. `/carriers` returns both, and
`deleted=1` rows can still have `active=1`. Rows sharing an `id_reference` are
versions of the same carrier, and an order's `id_carrier` may point at a
`deleted=1` row that is still correct for that order. Filter on `deleted`
deliberately rather than by accident.

**Nested display syntax does not work.**
`display=[id,associations[order_rows]]` returns HTTP 500 with an empty body. To
get associations, fetch the single record by id or use `display=full`.

**`0000-00-00 00:00:00` is PrestaShop's null date.** It appears in
`delivery_date` and `invoice_date` and will crash most date parsers. Treat it as
absent.
