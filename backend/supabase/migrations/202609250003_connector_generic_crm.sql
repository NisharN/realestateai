-- Allow the generic CRM pull connector on databases that already ran 202609250002.
alter table public.connectors drop constraint if exists connectors_type_check;
alter table public.connectors add constraint connectors_type_check
  check (type in ('csv_upload','webhook','google_sheets','portal_email','hubspot','zoho','salesforce','bitrix24','generic_crm','whatsapp','manual'));
