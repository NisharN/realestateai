
-- Dubai Real Estate AI Lead Gen Platform
-- Supabase PostgreSQL Schema

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- Brokers table
CREATE TABLE IF NOT EXISTS brokers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    specialization TEXT[] DEFAULT '{}',
    languages TEXT[] DEFAULT '{en}',
    active_leads INTEGER DEFAULT 0,
    max_leads INTEGER DEFAULT 20,
    performance_score DECIMAL(3,2) DEFAULT 0.00,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Properties table (scraped listings)
CREATE TABLE IF NOT EXISTS properties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL,
    source_id VARCHAR(100),
    source_url TEXT,
    title VARCHAR(255),
    description TEXT,
    price DECIMAL(15,2),
    price_per_sqft DECIMAL(10,2),
    area VARCHAR(100),
    property_type VARCHAR(50),
    bedrooms INTEGER,
    bathrooms INTEGER,
    size_sqft INTEGER,
    images TEXT[] DEFAULT '{}',
    video_url TEXT,
    floor_plan_url TEXT,
    map_lat DECIMAL(10,8),
    map_lng DECIMAL(11,8),
    amenities TEXT[] DEFAULT '{}',
    developer VARCHAR(100),
    completion_date DATE,
    is_active BOOLEAN DEFAULT TRUE,
    scraped_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    embedding VECTOR(768)
);

-- Leads table
CREATE TABLE IF NOT EXISTS leads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source VARCHAR(50) NOT NULL,
    source_id VARCHAR(100),
    first_name VARCHAR(100),
    last_name VARCHAR(100),
    phone VARCHAR(20),
    email VARCHAR(100),
    preferred_language VARCHAR(10) DEFAULT 'en',
    budget_min DECIMAL(15,2),
    budget_max DECIMAL(15,2),
    property_type VARCHAR(50),
    area_preference TEXT[] DEFAULT '{}',
    timeline VARCHAR(50) DEFAULT 'just_browsing',
    intent_score INTEGER DEFAULT 0 CHECK (intent_score >= 0 AND intent_score <= 100),
    status VARCHAR(50) DEFAULT 'new',
    assigned_broker UUID REFERENCES brokers(id),
    scraped_data JSONB DEFAULT '{}',
    conversation_history JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_contact_at TIMESTAMP WITH TIME ZONE
);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    agent_type VARCHAR(50) NOT NULL,
    channel VARCHAR(20) DEFAULT 'chat',
    messages JSONB DEFAULT '[]',
    sentiment VARCHAR(20),
    language VARCHAR(10) DEFAULT 'en',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Activities / Pipeline tracking
CREATE TABLE IF NOT EXISTS activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    activity_type VARCHAR(50) NOT NULL,
    description TEXT,
    performed_by VARCHAR(50) NOT NULL,
    scheduled_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    outcome VARCHAR(50),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Workspaces: one broker/agency's configuration (team, data sources,
-- channels). Added for the /configure workflow-builder POC. Note: leads,
-- properties, brokers, and conversations above are NOT yet scoped by
-- workspace_id — this table stores configuration only. Real multi-tenancy
-- would add a workspace_id column (+ index, + RLS policy) to each of those
-- tables and filter every query by it. See docs/poc_scope.md.
CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(150) NOT NULL,
    team JSONB DEFAULT '[]',
    data_sources JSONB DEFAULT '[]',
    channels JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'draft', -- 'draft' | 'live'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workspaces_status ON workspaces(status);

-- Lead-property matches
CREATE TABLE IF NOT EXISTS lead_property_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lead_id UUID REFERENCES leads(id) ON DELETE CASCADE,
    property_id UUID REFERENCES properties(id) ON DELETE CASCADE,
    match_score DECIMAL(5,2),
    is_viewed BOOLEAN DEFAULT FALSE,
    is_saved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(lead_id, property_id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_intent_score ON leads(intent_score DESC);
CREATE INDEX IF NOT EXISTS idx_leads_assigned_broker ON leads(assigned_broker);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_properties_area ON properties(area);
CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price);
CREATE INDEX IF NOT EXISTS idx_properties_type ON properties(property_type);
CREATE INDEX IF NOT EXISTS idx_properties_active ON properties(is_active);
CREATE INDEX IF NOT EXISTS idx_activities_lead ON activities(lead_id);
CREATE INDEX IF NOT EXISTS idx_conversations_lead ON conversations(lead_id);

-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_leads_updated_at ON leads;
CREATE TRIGGER update_leads_updated_at
    BEFORE UPDATE ON leads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Sample broker data
INSERT INTO brokers (name, email, phone, specialization, languages, max_leads)
VALUES 
    ('Ahmed Al-Rashid', 'ahmed@example.com', '+971501234567', '{"Downtown Dubai", "Dubai Marina"}', '{en, ar}', 25),
    ('Sarah Johnson', 'sarah@example.com', '+971502345678', '{"Palm Jumeirah", "JBR"}', '{en}', 20),
    ('Raj Patel', 'raj@example.com', '+971503456789', '{"Business Bay", "JLT"}', '{en, hi}', 20)
ON CONFLICT (email) DO NOTHING;
