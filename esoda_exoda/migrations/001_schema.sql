-- Φάση 6: πηγή αλήθειας των βιβλίων. Κάθε πίνακας δεδομένων φέρει taxpayer_id.
create table schema_version (
  version integer primary key,
  applied_at timestamptz not null default now()
);

create table taxpayer (
  id serial primary key,
  afm text not null unique,
  name text not null default '',
  postal_code text not null default '',
  city text not null default ''
);

create table counterparty (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  vat text not null,
  country text not null default 'GR',
  name text not null default '',
  postal_code text not null default '',
  city text not null default '',
  notes text not null default '',
  separate_totals boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (taxpayer_id, country, vat)
);

create table classification_default (
  id serial primary key,
  counterparty_id integer not null references counterparty on delete cascade,
  direction text not null check (direction in ('income', 'expense')),
  category_code text not null,
  e3_code text not null,
  deductible boolean,
  inv_type text not null default '',
  unique (counterparty_id, direction)
);

create table mydata_fetch (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  method text not null,
  date_from date,
  date_to date,
  fetched_at timestamptz not null default now(),
  body text not null
);
create index mydata_fetch_lookup on mydata_fetch (taxpayer_id, method, fetched_at desc);

create table invoice (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  mark text not null,
  direction text not null check (direction in ('income', 'expense')),
  inv_type text not null default '',
  issue_date date not null,
  series text not null default '',
  aa text not null default '',
  issuer_vat text not null default '',
  issuer_name text not null default '',
  counterpart_vat text not null default '',
  counterparty_id integer references counterparty,
  net numeric(12,2) not null default 0,
  vat numeric(12,2) not null default 0,
  withheld numeric(12,2) not null default 0,
  gross numeric(12,2) not null default 0,
  other_taxes numeric(12,2) not null default 0,
  stamp_duty numeric(12,2) not null default 0,
  fees numeric(12,2) not null default 0,
  fuel_invoice boolean not null default false,
  in_book boolean not null default false,        -- ήρθε από RequestMyIncome/Expenses
  received boolean not null default false,       -- ήρθε από RequestDocs (έχει γραμμές)
  self_declared boolean not null default false,  -- αυτο-δηλωθέν από RequestTransmittedDocs
  uid text not null default '',
  cancelled_by_mark text not null default '',
  first_seen_fetch_id integer not null references mydata_fetch,
  last_seen_fetch_id integer not null references mydata_fetch,
  unique (taxpayer_id, mark)
);
create index invoice_by_date on invoice (taxpayer_id, issue_date);

create table invoice_line (
  id serial primary key,
  invoice_id integer not null references invoice on delete cascade,
  line_number integer not null,
  net numeric(12,2) not null default 0,
  vat_category integer not null default 0,
  vat_amount numeric(12,2) not null default 0,
  vat_exemption_category integer
);

create table classification_snapshot (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  mark text not null,
  source text not null check (source in ('transmitted_docs', 'e3_info', 'vat_info')),
  fetch_id integer not null references mydata_fetch,
  issue_date date,
  fetched_at timestamptz not null default now()
);
create index snapshot_current on classification_snapshot
  (taxpayer_id, mark, source, fetched_at desc, id desc);

create table classification_line (
  id serial primary key,
  snapshot_id integer not null references classification_snapshot on delete cascade,
  kind text not null check (kind in ('income', 'expense')),
  category text not null default '',
  e3_type text not null default '',
  value numeric(12,2)
);

create table vat_code_line (
  id serial primary key,
  snapshot_id integer not null references classification_snapshot on delete cascade,
  code text not null,
  value numeric(12,2) not null
);

create table invoice_submission (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  at timestamptz not null default now(),
  inv_type text not null default '',
  series text not null default '',
  aa text not null default '',
  issue_date date,
  net numeric(12,2) not null default 0,
  issuer_vat text not null default '',
  issuer_name text not null default '',
  counterparty_id integer references counterparty,
  mark text not null,
  uid text not null default '',
  status text not null default 'Success',
  request_xml text,
  response_xml text
);

create table classification_submission (
  id serial primary key,
  taxpayer_id integer not null references taxpayer,
  at timestamptz not null default now(),
  year integer,
  invoice_mark text not null default '',
  classification_mark text not null default '',
  status text not null,
  errors jsonb not null default '[]',
  per_invoice boolean,
  e3_type text not null default '',
  category text not null default '',
  amount numeric(12,2),
  request_xml text,
  response_xml text
);
