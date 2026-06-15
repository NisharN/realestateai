#!/bin/bash
# Dubai Real Estate AI - Setup Script
# Run: chmod +x setup.sh && ./setup.sh

set -e

echo "🚀 Setting up Dubai Real Estate AI Platform..."

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi

if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found. Please install Node.js 18+"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "⚠️  Docker not found. Docker deployment will not be available."
fi

# Create project structure
echo "📁 Creating project structure..."
mkdir -p backend/app/{agents,api,database,models,scrapers,services,utils}
mkdir -p backend/tests
mkdir -p backend/models/piper
mkdir -p frontend/app
mkdir -p frontend/components/{chat,property-card,map,voice,dashboard}
mkdir -p frontend/lib
mkdir -p frontend/types
mkdir -p frontend/public
mkdir -p n8n-workflows
mkdir -p docs
mkdir -p scripts

# Backend setup
echo "🔧 Setting up backend..."
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Download Piper TTS models
mkdir -p models/piper
echo "📥 Downloading Piper TTS models..."
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx -O models/piper/en_US-lessac-medium.onnx || echo "⚠️  English model download failed"
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json -O models/piper/en_US-lessac-medium.onnx.json || echo "⚠️  English config download failed"

# Arabic model (if available)
wget -q https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/ar/ar_JO/kareem/medium/ar_JO-kareem-medium.onnx -O models/piper/ar_JO-kareem-medium.onnx || echo "⚠️  Arabic model download failed"

cd ..

# Frontend setup
echo "🎨 Setting up frontend..."
cd frontend

# Install dependencies
npm install

cd ..

# Environment setup
echo "📝 Creating environment files..."
if [ ! -f .env ]; then
    cp 02_env_example .env
    echo "⚠️  Please edit .env with your actual API keys"
fi

# Database setup instructions
echo ""
echo "📊 Database Setup Instructions:"
echo "1. Create a Supabase project at https://supabase.com"
echo "2. Run the SQL schema from 01_database_schema.sql in the SQL Editor"
echo "3. Copy your project URL and anon key to .env"
echo ""

# API keys setup
echo "🔑 API Keys Setup:"
echo "1. Groq: https://console.groq.com (Free tier: 1K requests/day)"
echo "2. OpenAI: https://platform.openai.com (For Whisper STT - $5 free credit)"
echo "3. Mapbox: https://account.mapbox.com (Free tier: 50K loads/month)"
echo "4. WhatsApp Business: https://business.facebook.com (Free tier: 1K conversations/month)"
echo ""

echo "✅ Setup complete!"
echo ""
echo "🚀 To start development:"
echo "  Backend: cd backend && source venv/bin/activate && uvicorn app.main:app --reload"
echo "  Frontend: cd frontend && npm run dev"
echo "  Docker: docker-compose up --build"
echo ""
echo "📖 Documentation: See docs/ folder for architecture and case studies"
