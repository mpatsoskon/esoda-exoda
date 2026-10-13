-- Πηγή αλήθειας των βιβλίων, σε SQLite. Κάθε πίνακας δεδομένων φέρει taxpayer_id.
-- Τύποι: date και timestamptz είναι κείμενο ISO-8601 (timestamptz πάντα σε UTC, με «Z»),
-- boolean είναι 0/1· το db.py τα μετατρέπει από τον δηλωμένο τύπο της στήλης.
-- ΠΟΣΑ: κάθε στήλη ποσού είναι integer σε ΛΕΠΤΑ (12,34 € → 1234), ώστε εγγραφές και sum()
-- να είναι ακριβή. Μετατροπή μόνο μέσω db.to_cents / db.from_cents.
-- Τα id είναι autoincrement: δεν ξαναχρησιμοποιούνται, άρα η σειρά των fetches κρίνεται από
-- το id.
create table schema_version (
  version integer primary key,
  applied_at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- Το περιβάλλον myDATA δένεται με τη βάση: αλλαγή του πάνω στα ίδια βιβλία θα ανακάτευε
-- MARK του sandbox με πραγματικά.
create table taxpayer (
  id integer primary key autoincrement,
  afm text not null unique,
  name text not null default '',
  postal_code text not null default '',
  city text not null default '',
  environment text not null check (environment in ('dev', 'production'))
);

create table counterparty (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  vat text not null,
  country text not null default 'GR',
  name text not null default '',
  postal_code text not null default '',
  city text not null default '',
  notes text not null default '',
  separate_totals boolean not null default 0,
  created_at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  unique (taxpayer_id, country, vat)
);

create table classification_default (
  id integer primary key autoincrement,
  counterparty_id integer not null references counterparty (id) on delete cascade,
  direction text not null check (direction in ('income', 'expense')),
  category_code text not null,
  e3_code text not null,
  deductible boolean,
  inv_type text not null default '',
  unique (counterparty_id, direction)
);

create table mydata_fetch (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  method text not null,
  date_from date,
  date_to date,
  fetched_at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  body text not null
);
create index mydata_fetch_lookup on mydata_fetch (taxpayer_id, method, id);

create table invoice (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  mark text not null,
  direction text not null check (direction in ('income', 'expense')),
  inv_type text not null default '',
  issue_date date not null,
  series text not null default '',
  aa text not null default '',
  issuer_vat text not null default '',
  issuer_name text not null default '',
  counterpart_vat text not null default '',
  counterparty_id integer references counterparty (id),
  net integer not null default 0,          -- λεπτά
  vat integer not null default 0,          -- λεπτά
  withheld integer not null default 0,     -- λεπτά
  gross integer not null default 0,        -- λεπτά
  other_taxes integer not null default 0,  -- λεπτά
  stamp_duty integer not null default 0,   -- λεπτά
  fees integer not null default 0,         -- λεπτά
  fuel_invoice boolean not null default 0,
  in_book boolean not null default 0,        -- ήρθε από RequestMyIncome/Expenses
  received boolean not null default 0,       -- ήρθε από RequestDocs (έχει γραμμές)
  self_declared boolean not null default 0,  -- αυτο-δηλωθέν από RequestTransmittedDocs
  uid text not null default '',
  cancelled_by_mark text not null default '',
  first_seen_fetch_id integer not null references mydata_fetch (id),
  last_seen_fetch_id integer not null references mydata_fetch (id),
  unique (taxpayer_id, mark)
);
create index invoice_by_date on invoice (taxpayer_id, issue_date);

create table invoice_line (
  id integer primary key autoincrement,
  invoice_id integer not null references invoice (id) on delete cascade,
  line_number integer not null,
  net integer not null default 0,         -- λεπτά
  vat_category integer not null default 0,
  vat_amount integer not null default 0,  -- λεπτά
  vat_exemption_category integer
);

create table classification_snapshot (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  mark text not null,
  source text not null check (source in ('transmitted_docs', 'e3_info', 'vat_info')),
  fetch_id integer not null references mydata_fetch (id),
  issue_date date,
  fetched_at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
create index snapshot_current on classification_snapshot (taxpayer_id, mark, source, fetch_id, id);

create table classification_line (
  id integer primary key autoincrement,
  snapshot_id integer not null references classification_snapshot (id) on delete cascade,
  kind text not null check (kind in ('income', 'expense')),
  category text not null default '',
  e3_type text not null default '',
  value integer  -- λεπτά
);

create table vat_code_line (
  id integer primary key autoincrement,
  snapshot_id integer not null references classification_snapshot (id) on delete cascade,
  code text not null,
  value integer not null  -- λεπτά
);

create table invoice_submission (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  inv_type text not null default '',
  series text not null default '',
  aa text not null default '',
  issue_date date,
  net integer not null default 0,  -- λεπτά
  issuer_vat text not null default '',
  issuer_name text not null default '',
  counterparty_id integer references counterparty (id),
  mark text not null,
  uid text not null default '',
  status text not null default 'Success',
  request_xml text,
  response_xml text
);

create table classification_submission (
  id integer primary key autoincrement,
  taxpayer_id integer not null references taxpayer (id),
  at timestamptz not null default (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  year integer,
  invoice_mark text not null default '',
  classification_mark text not null default '',
  status text not null,
  errors text not null default '[]',  -- JSON
  per_invoice boolean,
  e3_type text not null default '',
  category text not null default '',
  amount integer,  -- λεπτά
  request_xml text,
  response_xml text
);
