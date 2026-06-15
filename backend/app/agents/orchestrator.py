"""LangGraph Multi-Agent Orchestrator for Dubai Real Estate AI.

State Machine:
[New Lead] → [Scoring] → [Qualifier] → [Research] → [Conversation] → [Follow-up/Handoff]
"""
from typing import TypedDict, Annotated, List, Dict, Any, Optional, Literal
from datetime import datetime
import json
import logging

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_groq import ChatGroq

from app.config import get_settings

logger = logging.getLogger(__name__)

# ───────────────────────────────────────────────
# STATE DEFINITION
# ───────────────────────────────────────────────

class AgentState(TypedDict):
    """Shared state across all agents in the graph."""
    # Lead info
    lead_id: Optional[str]
    lead_data: Dict[str, Any]

    # Conversation
    messages: Annotated[List[Any], add_messages]
    language: str  # 'en' or 'ar'

    # Agent outputs
    intent_score: int
    qualification: Dict[str, Any]
    matched_properties: List[Dict[str, Any]]
    conversation_complete: bool
    needs_human: bool
    handoff_reason: Optional[str]

    # Next action
    next_node: str

    # Metadata
    created_at: str
    error: Optional[str]


# ───────────────────────────────────────────────
# LLM SETUP (Groq - Free Tier)
# ───────────────────────────────────────────────

def get_llm(model_type: str = "quality"):
    """Get Groq LLM instance. 

    Args:
        model_type: 'quality' (70B, 1K RPD) or 'fast' (8B, 14.4K RPD)
    """
    settings = get_settings()
    model = settings.GROQ_MODEL if model_type == "quality" else settings.GROQ_MODEL_FAST

    return ChatGroq(
        api_key=settings.GROQ_API_KEY,
        model=model,
        temperature=0.3,
        max_tokens=2048,
    )


# ───────────────────────────────────────────────
# NODE 1: SCORING AGENT
# ───────────────────────────────────────────────

SCORING_PROMPT_EN = """You are a lead scoring expert for Dubai real estate.
Score this lead from 0-100 based on:
- Data completeness (name, phone, budget, timeline)
- Source quality (inbound form > social media > scraped)
- Intent signals (specific area, budget range, timeline mentioned)
- Language (English/Arabic both good for Dubai market)

Return ONLY a JSON object:
{
    "score": <0-100>,
    "reasoning": "brief explanation",
    "priority": "hot|warm|cold"
}"""

SCORING_PROMPT_AR = """أنت خبير في تقييم العملاء المحتملين للعقارات في دبي.
قيّم هذا العميل من 0-100 بناءً على:
- اكتمال البيانات (الاسم، الهاتف، الميزانية، الجدول الزمني)
- جودة المصدر (نموذج داخلي > وسائل التواصل الاجتماعي > مكشوف)
- إشارات النية (منطقة محددة، نطاق الميزانية، ذكر الجدول الزمني)

أعد JSON فقط:
{
    "score": <0-100>,
    "reasoning": "شرح موجز",
    "priority": "hot|warm|cold"
}"""

async def scoring_agent(state: AgentState) -> AgentState:
    """Score lead intent and quality."""
    try:
        llm = get_llm("fast")
        lead_data = state["lead_data"]
        lang = state.get("language", "en")

        prompt = SCORING_PROMPT_EN if lang == "en" else SCORING_PROMPT_AR

        messages = [
            SystemMessage(content=prompt),
            HumanMessage(content=f"Lead data: {json.dumps(lead_data, default=str)}")
        ]

        response = await llm.ainvoke(messages)

        # Parse JSON from response
        content = response.content
        # Extract JSON if wrapped in markdown
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content.strip())
        score = min(100, max(0, int(result.get("score", 0))))

        state["intent_score"] = score
        state["messages"] = state.get("messages", []) + [
            AIMessage(content=f"Lead scored: {score}/100 - {result.get('priority', 'warm').upper()}")
        ]

        # Route based on score
        if score >= 60:
            state["next_node"] = "qualifier"
        elif score >= 30:
            state["next_node"] = "nurture"
        else:
            state["next_node"] = "end"

        logger.info(f"Lead scored {score}/100, routing to {state['next_node']}")

    except Exception as e:
        logger.error(f"Scoring error: {e}")
        state["intent_score"] = 50  # Default to medium
        state["next_node"] = "qualifier"
        state["error"] = str(e)

    return state


# ───────────────────────────────────────────────
# NODE 2: QUALIFIER AGENT
# ───────────────────────────────────────────────

QUALIFIER_PROMPT_EN = """You are Ali, a friendly Dubai real estate assistant.
Your job: qualify the lead by asking ONE question at a time.

You already know: {known_info}
Missing info to collect: {missing_fields}

Rules:
- Ask ONE short question
- Be warm and professional
- If they mention budget/area/timeline, acknowledge it
- If they say "just looking", still try to get one key detail
- Respond in the same language as the user
- Keep under 2 sentences

Current conversation:
{conversation_history}"""

QUALIFIER_PROMPT_AR = """أنت علي، مساعد عقارات ودي في دبي.
مهمتك: تقييم العميل بطرح سؤال واحد في كل مرة.

ما تعرفه بالفعل: {known_info}
المعلومات المفقودة: {missing_fields}

القواعد:
- اطرح سؤالاً قصيراً واحداً
- كن دافئاً ومهنياً
- إذا ذكروا الميزانية/المنطقة/الجدول الزمني، أقر بذلك
- إذا قالوا "مجرد تصفح"، حاول الحصول على تفصيل واحد مهم
- رد بنفس لغة المستخدم
- اجعله أقل من جملتين"""

async def qualifier_agent(state: AgentState) -> AgentState:
    """Qualify lead through conversation."""
    try:
        llm = get_llm("quality")
        lead_data = state["lead_data"]
        lang = state.get("language", "en")
        messages_history = state.get("messages", [])

        # Determine what's known vs missing
        known = []
        missing = []
        fields = ["budget_min", "budget_max", "property_type", "area_preference", "timeline"]
        for field in fields:
            if lead_data.get(field):
                known.append(f"{field}: {lead_data[field]}")
            else:
                missing.append(field)

        if not missing:
            state["qualification"] = lead_data
            state["next_node"] = "research"
            return state

        prompt = QUALIFIER_PROMPT_EN if lang == "en" else QUALIFIER_PROMPT_AR

        conversation_text = "\n".join([
            f"{'User' if isinstance(m, HumanMessage) else 'Ali'}: {m.content}"
            for m in messages_history[-6:]  # Last 6 messages for context
        ])

        system_msg = prompt.format(
            known_info=", ".join(known) if known else "Nothing yet",
            missing_fields=", ".join(missing),
            conversation_history=conversation_text
        )

        response = await llm.ainvoke([
            SystemMessage(content=system_msg),
            *messages_history[-3:]  # Last 3 messages as context
        ])

        state["messages"] = messages_history + [AIMessage(content=response.content)]
        state["next_node"] = "conversation"  # Wait for user response

    except Exception as e:
        logger.error(f"Qualifier error: {e}")
        state["error"] = str(e)
        state["next_node"] = "conversation"

    return state


# ───────────────────────────────────────────────
# NODE 3: RESEARCH AGENT (Property Matching)
# ───────────────────────────────────────────────

RESEARCH_PROMPT_EN = """You are a Dubai property research expert.
Given lead preferences, find the best matching properties from this list:

Lead preferences:
{preferences}

Available properties:
{properties}

For each property, calculate a match score (0-100) and explain why.
Return ONLY a JSON array:
[
    {
        "property_id": "...",
        "match_score": <0-100>,
        "match_reason": "...",
        "highlight": "best feature for this lead"
    }
]"""

async def research_agent(state: AgentState) -> AgentState:
    """Match lead with properties."""
    try:
        # In production, this queries the database
        # For now, simulate with LLM reasoning
        llm = get_llm("quality")

        qualification = state.get("qualification", state["lead_data"])

        # Mock properties for demo - in production fetch from DB
        mock_properties = [
            {
                "id": "prop-1",
                "title": "Burj Vista Tower 1 - 2BR Apartment",
                "area": "Downtown Dubai",
                "price": 3200000,
                "bedrooms": 2,
                "size_sqft": 1200,
                "property_type": "apartment",
                "amenities": ["gym", "pool", "concierge"]
            },
            {
                "id": "prop-2", 
                "title": "Address Boulevard - 3BR Penthouse",
                "area": "Downtown Dubai",
                "price": 8500000,
                "bedrooms": 3,
                "size_sqft": 2500,
                "property_type": "penthouse",
                "amenities": ["private pool", "smart home", "valet"]
            },
            {
                "id": "prop-3",
                "title": "Marina Gate - 1BR with Sea View",
                "area": "Dubai Marina",
                "price": 1800000,
                "bedrooms": 1,
                "size_sqft": 800,
                "property_type": "apartment",
                "amenities": ["beach access", "gym", "parking"]
            }
        ]

        response = await llm.ainvoke([
            SystemMessage(content=RESEARCH_PROMPT_EN.format(
                preferences=json.dumps(qualification, default=str),
                properties=json.dumps(mock_properties, default=str)
            ))
        ])

        # Parse results
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        matches = json.loads(content.strip())
        # Sort by score
        matches.sort(key=lambda x: x.get("match_score", 0), reverse=True)

        state["matched_properties"] = matches[:5]  # Top 5
        state["messages"] = state.get("messages", []) + [
            AIMessage(content=f"Found {len(matches)} matching properties. Top match: {matches[0]['match_score']}/100")
        ]
        state["next_node"] = "conversation"

    except Exception as e:
        logger.error(f"Research error: {e}")
        state["matched_properties"] = []
        state["error"] = str(e)
        state["next_node"] = "conversation"

    return state


# ───────────────────────────────────────────────
# NODE 4: CONVERSATIONAL AGENT (Rich Responses)
# ───────────────────────────────────────────────

CONVERSATION_PROMPT_EN = """You are Ali, a professional Dubai real estate AI assistant.
You help clients find their perfect property in Dubai.

Your capabilities:
- Show property listings with images, videos, maps
- Schedule site visits
- Answer questions about areas, developers, market trends
- Connect clients with human brokers when ready

Current lead info: {lead_info}
Matched properties: {properties}

Respond naturally. If showing properties, include property IDs so the UI can render cards.
If the user wants to visit, set handoff flag.
If user asks in Arabic, respond in Arabic.

Previous messages:
{history}"""

CONVERSATION_PROMPT_AR = """أنت علي، مساعد ذكاء اصطناعي محترف للعقارات في دبي.
تساعد العملاء في العثور على العقار المثالي.

قدراتك:
- عرض قائمة العقارات مع الصور ومقاطع الفيديو والخرائط
- جدولة زيارات الموقع
- الإجابة على الأسئلة حول المناطق والمطورين واتجاهات السوق
- ربط العملاء بالوسطاء البشريين عند الجاهزية

معلومات العميل الحالية: {lead_info}
العقارات المطابقة: {properties}

رد بشكل طبيعي. إذا عرضت عقارات، ضمن معرفات العقارات حتى يمكن للواجهة عرض البطاقات.
إذا أراد المستخدم الزيارة، فعّل علامة التسليم.
إذا سأل المستخدم بالإنجليزية، رد بالإنجليزية."""

async def conversational_agent(state: AgentState) -> AgentState:
    """Handle ongoing conversation with rich responses."""
    try:
        llm = get_llm("quality")
        lang = state.get("language", "en")

        # Detect language from last user message
        messages = state.get("messages", [])
        if messages and isinstance(messages[-1], HumanMessage):
            # Simple detection - in production use langdetect
            user_text = messages[-1].content
            if any(ord(c) > 127 for c in user_text):  # Non-ASCII = likely Arabic
                lang = "ar"
                state["language"] = "ar"

        prompt = CONVERSATION_PROMPT_EN if lang == "en" else CONVERSATION_PROMPT_AR

        system_msg = prompt.format(
            lead_info=json.dumps(state.get("lead_data", {}), default=str),
            properties=json.dumps(state.get("matched_properties", [])[:3], default=str),
            history="\n".join([
                f"{'User' if isinstance(m, HumanMessage) else 'Ali'}: {m.content}"
                for m in messages[-8:]
            ])
        )

        response = await llm.ainvoke([
            SystemMessage(content=system_msg),
            *messages[-4:]
        ])

        # Check for handoff signals
        content = response.content.lower()
        handoff_signals = [
            "schedule a viewing", "book a visit", "site visit",
            "talk to a broker", "speak to an agent", "human agent",
            "زيارة", "موعد", "وسيط", "وسيط بشري"
        ]

        if any(signal in content for signal in handoff_signals):
            state["needs_human"] = True
            state["handoff_reason"] = "User requested site visit/broker meeting"
            state["next_node"] = "handoff"
        else:
            state["next_node"] = "end"  # Wait for next user message

        state["messages"] = messages + [AIMessage(content=response.content)]

    except Exception as e:
        logger.error(f"Conversation error: {e}")
        state["error"] = str(e)
        state["next_node"] = "end"

    return state


# ───────────────────────────────────────────────
# NODE 5: HANDOFF AGENT
# ───────────────────────────────────────────────

async def handoff_agent(state: AgentState) -> AgentState:
    """Prepare broker handoff with full context."""
    try:
        # Generate broker brief
        lead_data = state["lead_data"]
        qualification = state.get("qualification", {})
        properties = state.get("matched_properties", [])

        brief = {
            "lead_id": state.get("lead_id"),
            "lead_name": f"{lead_data.get('first_name', '')} {lead_data.get('last_name', '')}".strip(),
            "contact": {
                "phone": lead_data.get("phone"),
                "email": lead_data.get("email"),
                "preferred_language": state.get("language", "en")
            },
            "qualification": {
                "budget": f"AED {qualification.get('budget_min', 'N/A')} - {qualification.get('budget_max', 'N/A')}",
                "property_type": qualification.get("property_type", "Not specified"),
                "area_preference": qualification.get("area_preference", []),
                "timeline": qualification.get("timeline", "Not specified"),
                "intent_score": state.get("intent_score", 0)
            },
            "top_properties": [
                {
                    "id": p.get("property_id"),
                    "match_score": p.get("match_score"),
                    "highlight": p.get("highlight")
                }
                for p in properties[:3]
            ],
            "conversation_summary": "\n".join([
                f"{'User' if isinstance(m, HumanMessage) else 'AI'}: {m.content}"
                for m in state.get("messages", [])[-10:]
            ]),
            "handoff_reason": state.get("handoff_reason", "Qualified lead ready for broker"),
            "timestamp": datetime.utcnow().isoformat()
        }

        state["messages"] = state.get("messages", []) + [
            AIMessage(content="I\'ve connected you with our specialist. They\'ll contact you within 30 minutes!")
        ]
        state["conversation_complete"] = True
        state["next_node"] = "end"

        logger.info(f"Handoff prepared for lead {state.get('lead_id')}")

    except Exception as e:
        logger.error(f"Handoff error: {e}")
        state["error"] = str(e)
        state["next_node"] = "end"

    return state


# ───────────────────────────────────────────────
# NODE 6: NURTURE AGENT (Low-score leads)
# ───────────────────────────────────────────────

async def nurture_agent(state: AgentState) -> AgentState:
    """Handle low-intent leads with nurture sequence."""
    state["messages"] = state.get("messages", []) + [
        AIMessage(content="Thanks for your interest! I\'ll send you Dubai market updates weekly. Reply STOP to opt out.")
    ]
    state["conversation_complete"] = True
    state["next_node"] = "end"
    return state


# ───────────────────────────────────────────────
# ROUTING LOGIC
# ───────────────────────────────────────────────

def route_from_scoring(state: AgentState) -> str:
    return state.get("next_node", "qualifier")

def route_from_qualifier(state: AgentState) -> str:
    return state.get("next_node", "conversation")

def route_from_research(state: AgentState) -> str:
    return state.get("next_node", "conversation")

def route_from_conversation(state: AgentState) -> str:
    return state.get("next_node", "end")


# ───────────────────────────────────────────────
# BUILD THE GRAPH
# ───────────────────────────────────────────────

def build_agent_graph() -> StateGraph:
    """Build and compile the LangGraph state machine."""

    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("scoring", scoring_agent)
    workflow.add_node("qualifier", qualifier_agent)
    workflow.add_node("research", research_agent)
    workflow.add_node("conversation", conversational_agent)
    workflow.add_node("handoff", handoff_agent)
    workflow.add_node("nurture", nurture_agent)

    # Entry point
    workflow.set_entry_point("scoring")

    # Edges from scoring
    workflow.add_conditional_edges(
        "scoring",
        route_from_scoring,
        {
            "qualifier": "qualifier",
            "nurture": "nurture",
            "end": END
        }
    )

    # Edges from qualifier
    workflow.add_conditional_edges(
        "qualifier",
        route_from_qualifier,
        {
            "research": "research",
            "conversation": "conversation",
            "end": END
        }
    )

    # Edges from research
    workflow.add_conditional_edges(
        "research",
        route_from_research,
        {
            "conversation": "conversation",
            "end": END
        }
    )

    # Edges from conversation
    workflow.add_conditional_edges(
        "conversation",
        route_from_conversation,
        {
            "handoff": "handoff",
            "end": END
        }
    )

    # Terminal nodes
    workflow.add_edge("handoff", END)
    workflow.add_edge("nurture", END)

    return workflow.compile()


# Global compiled graph
agent_graph = build_agent_graph()
