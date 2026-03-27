"""
PiClaw OS – Security Tools
Includes the Emergency Shutdown feature and other network security integrations.
"""

import logging
from piclaw.llm.base import ToolDefinition

log = logging.getLogger("piclaw.tools.network_security")

TOOL_DEFS = [
    ToolDefinition(
        name="emergency_network_off",
        description=(
            "Initiates an emergency shutdown of the internet connection (modem/router) "
            "by turning off the smart plug. IMPORTANT: If you detect a threat or want to use this, "
            "you MUST first ask the user 'Disconnect network? [Yes/No]' and call this tool "
            "with confirm=True ONLY AFTER they say 'Yes'."
        ),
        parameters={
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "The reason for the emergency shutdown.",
                },
                "entity_id": {
                    "type": "string",
                    "description": "The Home Assistant entity ID of the modem smart plug (e.g. switch.modem).",
                    "default": "switch.modem",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be set to True ONLY IF the user explicitly replied 'Yes' to the confirmation prompt.",
                    "default": False,
                },
            },
            "required": ["reason"],
        },
    ),
]


def build_handlers(ha_client=None, notify_fn=None) -> dict:
    async def emergency_network_off(
        reason: str, entity_id: str = "switch.modem", confirm: bool = False, **_
    ) -> str:
        if not ha_client:
            return (
                "❌ Home Assistant is not configured. Cannot turn off the modem/router."
            )

        if not confirm:
            # If not confirmed, instruct the LLM to ask the user.
            return (
                f"🚨 EMERGENCY SHUTDOWN PENDING 🚨\n"
                f"Reason: {reason}\n"
                f"Action required: Ask the user exactly 'Disconnect network? [Yes/No]'. "
                f"Do NOT execute the shutdown until the user replies 'Yes'."
            )

        # The user has confirmed. Proceed with shutdown.
        try:
            # Call the Home Assistant API directly to turn off the plug
            await ha_client.call_service(
                domain=entity_id.split(".")[0],
                service="turn_off",
                service_data={"entity_id": entity_id},
            )
            return f"✅ Emergency shutdown confirmed. Turned off {entity_id}."
        except Exception as e:
            log.error("Failed to disable network via HA: %s", e)
            return f"❌ Failed to disable network via HA: {e}"

    return {
        "emergency_network_off": emergency_network_off,
    }
