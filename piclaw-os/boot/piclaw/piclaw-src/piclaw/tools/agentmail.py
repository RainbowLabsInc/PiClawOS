"""
PiClaw OS – AgentMail Integration
Provides email capabilities for AI agents using the AgentMail service.
"""

import logging
import asyncio
from typing import Optional, List

from piclaw.config import AgentMailConfig
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.agentmail")

TOOL_DEFS = [
    ToolDefinition(
        name="agentmail_create_inbox",
        description="Creates a new dedicated email inbox for the agent. Returns the inbox details including the email address.",
        parameters={
            "type": "object",
            "properties": {
                "display_name": {"type": "string", "description": "Optional name to display on sent emails."},
                "username": {"type": "string", "description": "Preferred username (e.g. 'my-agent' for my-agent@agentmail.to)."},
            },
        },
    ),
    ToolDefinition(
        name="agentmail_list_inboxes",
        description="Lists all active AgentMail inboxes managed by this API key.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="agentmail_send_email",
        description="Sends an email from a specific AgentMail inbox.",
        parameters={
            "type": "object",
            "properties": {
                "inbox_id": {"type": "string", "description": "The ID or email address of the sending inbox."},
                "to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email address(es)."},
                "subject": {"type": "string", "description": "The subject line of the email."},
                "text": {"type": "string", "description": "Plain text body of the email."},
                "html": {"type": "string", "description": "Optional HTML version of the email body."},
            },
            "required": ["inbox_id", "to", "subject", "text"],
        },
    ),
    ToolDefinition(
        name="agentmail_list_messages",
        description="Retrieves a list of emails received in a specific inbox.",
        parameters={
            "type": "object",
            "properties": {
                "inbox_id": {"type": "string", "description": "The ID or email address of the inbox to check."},
                "limit": {"type": "integer", "description": "Maximum number of messages to return (default: 10).", "default": 10},
            },
            "required": ["inbox_id"],
        },
    ),
]


async def _get_client(cfg: AgentMailConfig):
    """Lazy imports and initializes the AsyncAgentMail client."""
    if not cfg.api_key:
        raise ValueError("AgentMail API key is not configured. Ask the user to set 'agentmail.api_key'.")

    try:
        from agentmail import AsyncAgentMail
        return AsyncAgentMail(api_key=cfg.api_key)
    except ImportError:
        raise ImportError("The 'agentmail' library is not installed. Please run 'pip install agentmail'.")


async def agentmail_create_inbox(cfg: AgentMailConfig, display_name: str = None, username: str = None) -> str:
    try:
        client = await _get_client(cfg)
        inbox = await client.inboxes.create(
            display_name=display_name,
            username=username
        )
        return (
            f"✅ Inbox created successfully.\n"
            f"  Email: {inbox.email_address}\n"
            f"  ID:    {inbox.inbox_id}"
        )
    except Exception as e:
        log.error("AgentMail create_inbox error: %s", e)
        return f"❌ Error creating inbox: {e}"


async def agentmail_list_inboxes(cfg: AgentMailConfig) -> str:
    try:
        client = await _get_client(cfg)
        inboxes_res = await client.inboxes.list()
        if not inboxes_res.inboxes:
            return "No inboxes found."

        lines = ["Active Inboxes:"]
        for ib in inboxes_res.inboxes:
            lines.append(f"- {ib.email_address} (ID: {ib.inbox_id})")
        return "\n".join(lines)
    except Exception as e:
        log.error("AgentMail list_inboxes error: %s", e)
        return f"❌ Error listing inboxes: {e}"


async def agentmail_send_email(
    cfg: AgentMailConfig, inbox_id: str, to: List[str], subject: str, text: str, html: str = None
) -> str:
    try:
        client = await _get_client(cfg)
        # Handle single string if passed by mistake
        if isinstance(to, str):
            to = [to]

        await client.inboxes.messages.send(
            inbox_id=inbox_id,
            to=to,
            subject=subject,
            text=text,
            html=html
        )
        return f"✅ Email sent successfully from {inbox_id} to {', '.join(to)}."
    except Exception as e:
        log.error("AgentMail send_email error: %s", e)
        return f"❌ Error sending email: {e}"


async def agentmail_list_messages(cfg: AgentMailConfig, inbox_id: str, limit: int = 10) -> str:
    try:
        client = await _get_client(cfg)
        msgs_res = await client.inboxes.messages.list(inbox_id=inbox_id, limit=limit)

        if not msgs_res.messages:
            return f"No messages found in inbox {inbox_id}."

        lines = [f"Recent messages for {inbox_id}:"]
        for m in msgs_res.messages:
            date_str = getattr(m, "created_at", "unknown date")
            lines.append(
                f"[{date_str}] From: {m.from_address}\n"
                f"       Subject: {m.subject}\n"
                f"       Preview: {m.extracted_text[:100] if hasattr(m, 'extracted_text') and m.extracted_text else m.text[:100]}..."
            )
        return "\n\n".join(lines)
    except Exception as e:
        log.error("AgentMail list_messages error: %s", e)
        return f"❌ Error listing messages: {e}"


def build_handlers(cfg: AgentMailConfig) -> dict:
    return {
        "agentmail_create_inbox": lambda **kw: agentmail_create_inbox(cfg=cfg, **kw),
        "agentmail_list_inboxes": lambda **kw: agentmail_list_inboxes(cfg=cfg, **kw),
        "agentmail_send_email":   lambda **kw: agentmail_send_email(cfg=cfg, **kw),
        "agentmail_list_messages": lambda **kw: agentmail_list_messages(cfg=cfg, **kw),
    }
