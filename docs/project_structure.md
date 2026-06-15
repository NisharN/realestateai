dubai-real-estate-ai/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI entry point
│   │   ├── config.py               # Settings & env vars
│   │   ├── database.py             # Supabase client
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── lead.py
│   │   │   ├── property.py
│   │   │   ├── broker.py
│   │   │   └── conversation.py
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── orchestrator.py     # LangGraph state machine
│   │   │   ├── scoring_agent.py
│   │   │   ├── qualifier_agent.py
│   │   │   ├── research_agent.py
│   │   │   ├── conversational_agent.py
│   │   │   ├── followup_agent.py
│   │   │   └── handoff_agent.py
│   │   ├── scrapers/
│   │   │   ├── __init__.py
│   │   │   ├── base_scraper.py
│   │   │   ├── bayut_scraper.py
│   │   │   ├── propertyfinder_scraper.py
│   │   │   └── dubizzle_scraper.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── lead_service.py
│   │   │   ├── property_service.py
│   │   │   ├── voice_service.py
│   │   │   ├── whatsapp_service.py
│   │   │   └── crm_service.py
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── leads.py
│   │   │   ├── properties.py
│   │   │   ├── conversations.py
│   │   │   ├── webhooks.py
│   │   │   └── voice.py
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── embeddings.py
│   │       ├── validators.py
│   │       └── helpers.py
│   ├── models/                     # Piper TTS models (downloaded)
│   ├── tests/
│   └── Dockerfile
├── frontend/
│   ├── app/                        # Next.js 14 App Router
│   ├── components/
│   │   ├── chat/
│   │   ├── property-card/
│   │   ├── map/
│   │   ├── voice/
│   │   └── dashboard/
│   ├── lib/
│   ├── types/
│   └── public/
├── n8n-workflows/                  # Automation workflows
├── docs/
│   ├── architecture.md
│   └── case-studies.md
├── scripts/
│   ├── setup.sh
│   └── deploy.sh
├── .env
├── docker-compose.yml
└── README.md
