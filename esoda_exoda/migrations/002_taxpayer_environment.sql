-- Το περιβάλλον myDATA δένεται με τη βάση: αλλαγή του πάνω στα ίδια βιβλία θα ανακάτευε
-- MARK του sandbox με πραγματικά. Οι υπάρχουσες γραμμές ήρθαν από το παραγωγικό endpoint.
alter table taxpayer add column environment text;
update taxpayer set environment = 'production';
alter table taxpayer alter column environment set not null;
alter table taxpayer add constraint taxpayer_environment_check
  check (environment in ('dev', 'production'));
