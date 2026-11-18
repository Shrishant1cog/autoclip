"""Provider presets and the capability registry.

One place describing every provider AutoClip can talk to: which adapter
implements it, suggested models, default endpoint, and which capabilities
(text, JSON, long-context…) it can serve. Presets are data, not code — a new
OpenAI-compatible vendor is a dict entry, not a new adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderPreset:
    key: str                      # settings key & registry name
    label: str
    # adapters: openai | gemini | anthropic | ollama
    adapter: str
    requires_key: bool = True
    default_model: str = ""
    default_base_url: str | None = None
    suggested_models: list[str] = field(default_factory=list)
    capabilities: tuple[str, ...] = ("text", "json")
    is_local: bool = False


#: Capabilities the pipeline asks for. Task → required capability.
TASK_CAPABILITY = {
    "clip_analysis": "json",
    "metadata": "text",
    "caption_correction": "text",
    "classification": "json",
    "chat": "text",
}

#: All providers AutoClip knows about. OpenAI-compatible vendors share the
#: ``openai`` adapter with a different ``default_base_url``; they are presets,
#: not new code.
PRESETS: dict[str, ProviderPreset] = {
    "anthropic": ProviderPreset(
        key="anthropic",
        label="Anthropic",
        adapter="anthropic",
        default_model="claude-sonnet-5",
        suggested_models=["claude-sonnet-5", "claude-opus-5", "claude-haiku-5"],
        capabilities=("text", "json", "long_context", "vision"),
    ),
    "openai": ProviderPreset(
        key="openai",
        label="OpenAI",
        adapter="openai",
        default_model="gpt-4o",
        suggested_models=["gpt-4o", "gpt-4o-mini", "o4-mini"],
        capabilities=("text", "json", "long_context", "vision", "embeddings"),
    ),
    "gemini": ProviderPreset(
        key="gemini",
        label="Google Gemini",
        adapter="gemini",
        default_model="gemini-3.5-flash-lite",
        suggested_models=[
            "gemini-3.1-flash-lite",
            "gemini-3.5-flash-lite",
            "gemini-3.5-flash",
            "gemini-3.8-flash",
        ],
        capabilities=("text", "json", "long_context", "vision", "audio_understanding"),
    ),
    "openrouter": ProviderPreset(
        key="openrouter",
        label="OpenRouter",
        adapter="openai",
        default_model="openrouter/auto",
        default_base_url="https://openrouter.ai/api/v1",
        suggested_models=["openrouter/auto"],
        capabilities=("text", "json", "long_context", "vision"),
    ),
    "groq": ProviderPreset(
        key="groq",
        label="Groq",
        adapter="openai",
        default_model="llama-3.3-70b-versatile",
        default_base_url="https://api.groq.com/openai/v1",
        suggested_models=["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
        capabilities=("text", "json"),
    ),
    "cerebras": ProviderPreset(
        key="cerebras",
        label="Cerebras",
        adapter="openai",
        default_model="llama3.1-70b",
        default_base_url="https://api.cerebras.ai/v1",
        suggested_models=["llama3.1-70b", "llama3.1-8b"],
        capabilities=("text", "json"),
    ),
    "deepseek": ProviderPreset(
        key="deepseek",
        label="DeepSeek",
        adapter="openai",
        default_model="deepseek-chat",
        default_base_url="https://api.deepseek.com/v1",
        suggested_models=["deepseek-chat", "deepseek-reasoner"],
        capabilities=("text", "json", "long_context"),
    ),
    "mistral": ProviderPreset(
        key="mistral",
        label="Mistral",
        adapter="openai",
        default_model="mistral-large-latest",
        default_base_url="https://api.mistral.ai/v1",
        suggested_models=["mistral-large-latest", "mistral-small-latest"],
        capabilities=("text", "json"),
    ),
    "together": ProviderPreset(
        key="together",
        label="Together AI",
        adapter="openai",
        default_model="meta-llama/Llama-3.3-70B-Instruct-Turbo",
        default_base_url="https://api.together.xyz/v1",
        suggested_models=["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
        capabilities=("text", "json"),
    ),
    "freellmapi": ProviderPreset(
        key="freellmapi",
        label="FreeLLMAPI",
        adapter="openai",
        default_model="",
        default_base_url=None,   # user-configured; never hardcoded
        suggested_models=[],
        capabilities=("text", "json"),
    ),
    "huggingface": ProviderPreset(
        key="huggingface",
        label="Hugging Face",
        adapter="openai",
        default_model="meta-llama/Llama-3.1-8B-Instruct",
        default_base_url="https://router.huggingface.co/v1",
        suggested_models=["meta-llama/Llama-3.1-8B-Instruct"],
        capabilities=("text", "json"),
    ),
    "nvidia": ProviderPreset(
        key="nvidia",
        label="NVIDIA AI",
        adapter="openai",
        default_model="meta/llama-3.1-70b-instruct",
        default_base_url="https://integrate.api.nvidia.com/v1",
        suggested_models=["meta/llama-3.1-70b-instruct"],
        capabilities=("text", "json"),
    ),
    "lmstudio": ProviderPreset(
        key="lmstudio",
        label="LM Studio (local)",
        adapter="openai",
        default_model="",
        default_base_url="http://localhost:1234/v1",
        suggested_models=[],
        capabilities=("text", "json"),
        is_local=True,
        requires_key=False,
    ),
    "llamacpp": ProviderPreset(
        key="llamacpp",
        label="llama.cpp (local)",
        adapter="openai",
        default_model="",
        default_base_url="http://localhost:8080/v1",
        suggested_models=[],
        capabilities=("text", "json"),
        is_local=True,
        requires_key=False,
    ),
    "vllm": ProviderPreset(
        key="vllm",
        label="vLLM (local)",
        adapter="openai",
        default_model="",
        default_base_url="http://localhost:8001/v1",
        suggested_models=[],
        capabilities=("text", "json"),
        is_local=True,
        requires_key=False,
    ),
    "ollama": ProviderPreset(
        key="ollama",
        label="Ollama (local)",
        adapter="ollama",
        default_model="",
        default_base_url="http://localhost:11434",
        suggested_models=[],
        capabilities=("text", "json"),
        is_local=True,
        requires_key=False,
    ),
}


def get_preset(key: str) -> ProviderPreset | None:
    return PRESETS.get(key)


def presets_for_capability(capability: str) -> list[ProviderPreset]:
    return [p for p in PRESETS.values() if capability in p.capabilities]


__all__ = [
    "PRESETS",
    "ProviderPreset",
    "TASK_CAPABILITY",
    "get_preset",
    "presets_for_capability",
]
