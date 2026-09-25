-- Listing intent (sale vs rent) so buy/invest searches never surface rental stock.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS listing_type text
  CHECK (listing_type IS NULL OR listing_type IN ('sale', 'rent'));
CREATE INDEX IF NOT EXISTS idx_properties_listing_type ON properties (workspace_id, listing_type, price);
