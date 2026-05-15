import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    def generate(self, system: str, prompt: str, temperature: float = 0.2) -> str:
        try:
            if settings.llm_provider == "groq":
                return self._groq(system, prompt, temperature)

            if settings.llm_provider == "openai":
                return self._openai(system, prompt, temperature)

            if settings.llm_provider == "gemini":
                return self._gemini(system, prompt, temperature)

            return self._local_answer()

        except Exception as error:
            logger.exception("LLM generation failed: %s", error)
            return (
                "I could not generate a response right now because the language model service failed. "
                "Please try again in a moment."
            )

    def _groq(self, system: str, prompt: str, temperature: float) -> str:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            timeout=30,
        )

        return response.choices[0].message.content or ""

    def _openai(self, system: str, prompt: str, temperature: float) -> str:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            timeout=30,
        )

        return response.choices[0].message.content or ""

    def _gemini(self, system: str, prompt: str, temperature: float) -> str:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(
            settings.gemini_model,
            system_instruction=system,
        )

        response = model.generate_content(
            prompt,
            generation_config={
                "temperature": temperature,
            },
        )

        return response.text or ""

    def _local_answer(self) -> str:
        return (
            "No language model provider is currently configured. "
            "Please configure GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in the backend environment."
        )