import os
import smtplib
from email.mime.text import MIMEText
from typing import TypedDict, Optional
from dotenv import load_dotenv 
from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

# 1. LOAD THE KEYS
load_dotenv() 

class AgentState(TypedDict):
    prompt: str
    tone: str
    recipient: str
    recipient_email: Optional[str]
    draft: str
    is_approved: Optional[bool]
    feedback: Optional[str]
    usage: Optional[dict] 
    is_mock: Optional[bool]

# 2. Setup Resilient Model
primary_llm = ChatOpenAI(model="gpt-4o", temperature=0.7).with_retry(stop_after_attempt=2)
fallback_llm = ChatAnthropic(model="claude-3-5-sonnet-20240620", temperature=0.7)
smart_model = primary_llm.with_fallbacks([fallback_llm])

# --- SMTP HELPER FUNCTIONS ---

def test_smtp_connection():
    load_dotenv(override=True) # Forces reload of .env file
    sender = os.getenv("SENDER_EMAIL")
    # .strip() removes any hidden spaces or newline characters
    password = os.getenv("EMAIL_PASSWORD").strip() if os.getenv("EMAIL_PASSWORD") else None
    
    server_host = "smtp.gmail.com"
    port = 587

    try:
        server = smtplib.SMTP(server_host, port)
        server.starttls()
        server.login(sender, password)
        server.quit()
        return True, "Connection Successful! ✅"
    except Exception as e:
        return False, f"Connection Failed: {str(e)} ❌"


def send_real_email(recipient_email, subject, body):
    sender = os.getenv("SENDER_EMAIL")
    password = os.getenv("EMAIL_PASSWORD") 
    
    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls() 
            server.login(sender, password)
            server.sendmail(sender, recipient_email, msg.as_string())
        return True, "Success"
    except Exception as e:
        return False, str(e)


def send_real_email(recipient_email, subject, body):
    """Sends an email using SMTP."""
    sender = os.getenv("SENDER_EMAIL")
    password = os.getenv("EMAIL_PASSWORD") 
    
    if not sender or not password:
        return False, "SMTP Credentials missing in .env"

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient_email

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls() 
            server.login(sender, password)
            server.sendmail(sender, recipient_email, msg.as_string())
        return True, "Success"
    except Exception as e:
        return False, str(e)

# --- AGENT NODES ---

def draft_writer_agent(state: AgentState):
    if state.get("is_mock"):
        mock_content = (
            f"Subject: Application for position - {state['prompt']}\n\n"
            f"Dear {state['recipient']},\n\n"
            f"This is a [MOCK MODE] draft generated for testing purposes.\n\n"
            "Best regards,\nMailMind User"
        )
        return {"draft": mock_content, "usage": {"input": 0, "output": 0}}

    full_prompt = f"Recipient: {state['recipient']}\nGoal: {state['prompt']}\nTone: {state['tone']}\nWrite a professional email."
    response = smart_model.invoke([HumanMessage(content=full_prompt)])
    
    usage_data = response.response_metadata.get('token_usage') or response.response_metadata.get('usage') or {}
    return {
        "draft": response.content,
        "usage": {
            "input": usage_data.get('prompt_tokens', 0) or usage_data.get('input_tokens', 0),
            "output": usage_data.get('completion_tokens', 0) or usage_data.get('output_tokens', 0)
        }
    }

def review_validator_agent(state: AgentState):
    """Adds the validation signature."""
    suffix = "Validated by MailMind Review Agent ✅"
    if state.get("is_mock"):
        suffix = "Validated by MailMind (Mock Mode) ✅"
    return {"draft": state["draft"] + f"\n\n---\n{suffix}"}

def final_send_node(state: AgentState):
    """Terminal node after approval."""
    return {"is_approved": True}

# --- GRAPH CONSTRUCTION ---

def build_mailmind_graph():
    builder = StateGraph(AgentState)
    builder.add_node("writer", draft_writer_agent)
    builder.add_node("validator", review_validator_agent)
    builder.add_node("final_send", final_send_node)
    
    builder.add_edge(START, "writer")
    builder.add_edge("writer", "validator")
    builder.add_edge("validator", "final_send")
    builder.add_edge("final_send", END)
    
    memory = MemorySaver()
    # Pauses BEFORE 'validator' node so user sees/edits 'writer' output
    return builder.compile(checkpointer=memory, interrupt_before=["validator"])

mailmind_app = build_mailmind_graph()
