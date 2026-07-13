"""
Base Agent Class for Ottobiz
All agents inherit from this base class which provides common functionality.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import logfire
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from backend.config import config

logfire.configure(
    token=os.getenv("LOGFIRE_TOKEN"),
    send_to_logfire="if-token-present",
)
logfire.instrument_pydantic_ai()

logger = logging.getLogger(__name__)

# OpenRouter prompt caching — cuts repeat latency on multi-turn sessions
_OPENROUTER_SETTINGS = OpenRouterModelSettings(
    openrouter_cache_instructions=True,
    openrouter_cache_tool_definitions=True,
    timeout=180.0,
)


@dataclass
class AgentDependencies:
    """Dependencies that can be passed to agents"""

    user_id: Optional[str] = None
    business_id: Optional[str] = None
    logistic_id: Optional[str] = None
    session_id: Optional[str] = None
    api_key: Optional[str] = None
    extra_data: Optional[Dict[str, Any]] = None


class BaseAgent:
    """
    Base agent class that all other agents inherit from.
    Provides model initialization and common agent functionality.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        api_key: Optional[str] = None,
        system_prompt: Optional[str] = None,
        instructions: Optional[str] = None,
        deps_type: Optional[type] = None,
        output_type: Optional[type] = None,
        tools: Optional[List[Any]] = None,
        model_settings: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize base agent with model selection.

        Args:
            model_name: Model name to use (defaults to config.MODEL_NAME)
            api_key: API key for the model (defaults per provider / MODEL_API_KEY)
            system_prompt: System prompt for the agent
            instructions: Instructions for the agent
            deps_type: Type for dependencies
            output_type: Type for structured output (Pydantic model)
        """
        self.model_name = model_name or config.MODEL_NAME
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.instructions = instructions

        # Initialize model
        self.model = self._select_model(self.model_name, self.api_key)

        # Create agent with optional system prompt/instructions
        agent_kwargs = {}
        if system_prompt:
            agent_kwargs["system_prompt"] = system_prompt
        if instructions:
            agent_kwargs["instructions"] = instructions
        if deps_type:
            agent_kwargs["deps_type"] = deps_type
        if output_type:
            agent_kwargs["output_type"] = output_type
        if tools:
            agent_kwargs["tools"] = tools
        if model_settings:
            agent_kwargs["model_settings"] = model_settings
        self.agent = Agent(self.model, **agent_kwargs)

    def _select_model(self, model_name: Optional[str] = None, api_key: Optional[str] = None):
        """
        Route model names to the correct pydantic-ai provider.

        Rules:
          - Slugs with ``/`` (e.g. ``google/gemma-4-31b-it``, ``meta-llama/...``) → OpenRouter
          - ``gemini*`` without slash → Google
          - ``claude*`` → Anthropic
          - ``gpt*`` / ``openai*`` → OpenAI
          - Everything else → OpenRouter (where credits usually live)
        """
        name = (model_name or config.MODEL_NAME).strip()
        lower = name.lower()

        # Vendor/model slugs — always OpenRouter, never native Google API
        if "/" in lower:
            key = api_key or config.OPENROUTER_API_KEY
            logger.info("OpenRouter model: %s", name)
            return OpenRouterModel(
                name,
                provider=OpenRouterProvider(api_key=key),
                settings=_OPENROUTER_SETTINGS,
            )

        if lower.startswith("gemini"):
            key = api_key or config.GOOGLE_API_KEY
            return GoogleModel(name, provider=GoogleProvider(api_key=key))

        if "claude" in lower:
            key = api_key or config.MODEL_API_KEY
            return AnthropicModel(name, provider=AnthropicProvider(api_key=key))

        if "gpt" in lower:
            key = api_key or config.OPENAI_API_KEY
            return OpenAIChatModel(name, provider=OpenAIProvider(api_key=key))

        key = api_key or config.OPENROUTER_API_KEY
        logger.info("Routing unknown model via OpenRouter: %s", name)
        return OpenRouterModel(
            name,
            provider=OpenRouterProvider(api_key=key),
            settings=_OPENROUTER_SETTINGS,
        )

    async def run(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs,
    ):
        """
        Run the agent with a prompt.

        Args:
            prompt: User prompt or list of prompt parts
            deps: Dependencies to pass to the agent
            message_history: Previous message history
            **kwargs: Additional arguments

        Returns:
            Agent result
        """
        return await self.agent.run(
            prompt, deps=deps, message_history=message_history, **kwargs
        )

    def run_sync(
        self,
        prompt: str | List[Any],
        deps: Optional[Any] = None,
        message_history: Optional[List] = None,
        **kwargs,
    ):
        """
        Run the agent synchronously with a prompt.

        Args:
            prompt: User prompt or list of prompt parts
            deps: Dependencies to pass to the agent
            message_history: Previous message history
            **kwargs: Additional arguments

        Returns:
            Agent result
        """
        return self.agent.run_sync(
            prompt, deps=deps, message_history=message_history, **kwargs
        )
