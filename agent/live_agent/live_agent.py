import os
from datetime import datetime
import uuid
from typing import Any, Dict

from langchain.agents import create_agent

from agent.base_agent.base_agent import BaseAgent
from prompts.live_agent_prompt import get_live_agent_system_prompt
from tools.live_monitor import record_run_summary
from tools.live_alerts import notify_alert


class LiveAgent(BaseAgent):
    def _get_default_mcp_config(self) -> Dict[str, Dict[str, Any]]:
        return {
            "math": {
                "transport": "streamable_http",
                "url": f"http://localhost:{os.getenv('MATH_HTTP_PORT', '8000')}/mcp",
            },
            "search": {
                "transport": "streamable_http",
                "url": f"http://localhost:{os.getenv('SEARCH_HTTP_PORT', '8001')}/mcp",
            },
            "live_trade": {
                "transport": "streamable_http",
                "url": f"http://localhost:{os.getenv('LIVE_TRADE_HTTP_PORT', '8004')}/mcp",
            },
            "live_market": {
                "transport": "streamable_http",
                "url": f"http://localhost:{os.getenv('LIVE_MARKET_HTTP_PORT', '8005')}/mcp",
            },
        }

    async def run_trading_session(self, today_date: str) -> None:
        log_file = self._setup_logging(today_date)
        now_iso = datetime.utcnow().isoformat()
        run_id = str(uuid.uuid4())

        self.agent = create_agent(
            self.model,
            tools=self.tools,
            system_prompt=get_live_agent_system_prompt(now_iso),
        )

        user_query = [{"role": "user", "content": "Analyze current account and propose live trades."}]
        message = user_query.copy()
        self._log_message(log_file, user_query)

        current_step = 0
        status = "completed"
        error_details = None
        while current_step < self.max_steps:
            current_step += 1
            try:
                response = await self._ainvoke_with_retry(message)
                agent_response = self._extract_agent_response(response)

                if agent_response and "<FINISH_SIGNAL>" in agent_response:
                    self._log_message(log_file, [{"role": "assistant", "content": agent_response}])
                    break

                tool_msgs = self._extract_tool_messages(response)
                tool_response = "\n".join([self._tool_content(msg) for msg in tool_msgs])
                new_messages = [
                    {"role": "assistant", "content": agent_response},
                    {"role": "user", "content": f"Tool results: {tool_response}"},
                ]
                message.extend(new_messages)
                self._log_message(log_file, new_messages[0])
                self._log_message(log_file, new_messages[1])
            except Exception as exc:
                status = "error"
                error_details = {"error": str(exc)}
                self._log_message(log_file, [{"role": "assistant", "content": f"Error: {exc}"}])
                raise
        record_run_summary(run_id, self.signature, status, error_details)
        if status != "completed":
            notify_alert("live_run_error", {"run_id": run_id, "signature": self.signature, **(error_details or {})})

    async def run_date_range(self, init_date: str, end_date: str) -> None:
        today_date = datetime.utcnow().date().isoformat()
        await self.run_trading_session(today_date)

    def _extract_agent_response(self, response: Dict[str, Any]) -> str:
        from tools.general_tools import extract_conversation
        return extract_conversation(response, "final") or ""

    def _extract_tool_messages(self, response: Dict[str, Any]):
        from tools.general_tools import extract_tool_messages
        return extract_tool_messages(response)

    @staticmethod
    def _tool_content(msg: Any) -> str:
        if isinstance(msg, dict):
            return str(msg.get("content", ""))
        return str(getattr(msg, "content", ""))
