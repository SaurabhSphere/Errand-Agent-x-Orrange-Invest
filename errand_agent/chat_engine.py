"""Intelligent Chat Support Engine powered by LangChain/OpenAI LLM and dynamic context."""

import os
import re
from typing import Any
from dotenv import load_dotenv

from mcp_server.provider_api import MockProviderAPI
from mcp_server.data import PROVIDERS_DATA
from errand_agent.memory import MemoryManager
from errand_agent.sanitizer import Sanitizer
from errand_agent.state import ErrandState

load_dotenv()


class ChatSupportEngine:
    """Intelligent conversational chat support engine.
    
    Provides rich context-aware answers to user inquiries (availability,
    slot queries, booking status, pricing policies, provider attributes, and reviews)
    using OpenAI LLM when configured, with a deterministic fallback for offline/test environments.
    """

    def __init__(
        self,
        api: MockProviderAPI,
        memory_manager: MemoryManager | None = None,
        sanitizer: Sanitizer | None = None,
    ):
        self.api = api
        self.memory = memory_manager
        self.sanitizer = sanitizer or Sanitizer()
        self.llm = self._init_llm()

    def _init_llm(self) -> Any:
        """Initialize ChatOpenAI if API key is present and not explicitly offline."""
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        offline_mode = os.getenv("ERRAND_AGENT_OFFLINE", "0").strip() == "1"
        if not api_key or offline_mode:
            return None

        try:
            from langchain_openai import ChatOpenAI
            model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            return ChatOpenAI(
                model=model_name,
                temperature=0.1,
                openai_api_key=api_key,
                timeout=10,
            )
        except Exception:
            return None

    def is_llm_active(self) -> bool:
        """Return True if a live LLM is configured and operational."""
        return self.llm is not None

    def build_system_context(self, state: ErrandState, user_id: str = "user_default") -> str:
        """Compile live system context including bookings, providers, slots, memory, and sanitized reviews."""
        lines = ["=== CURRENT SYSTEM CONTEXT ==="]

        # 1. Active User Bookings
        bookings = self.api.list_bookings(user_id=user_id)
        lines.append("ACTIVE USER BOOKINGS:")
        if not bookings:
            lines.append("  (No existing bookings)")
        else:
            for b in bookings:
                lines.append(
                    f"  - Booking ID: {b.get('booking_id')}, Provider: {b.get('provider_name')} "
                    f"({b.get('provider_id')}), Service: {b.get('service')}, Slot: {b.get('slot')}, "
                    f"Price: ₹{b.get('price')}, Status: {b.get('status')}"
                )

        # 2. Currently Presented or Matching Providers
        active_providers = state.get("providers") or PROVIDERS_DATA
        lines.append("\nAVAILABLE SERVICE PROVIDERS:")
        for p in active_providers:
            attrs = p.get("attributes", {})
            spec = attrs.get("specialty", "General")
            exp = attrs.get("experience_years", "N/A")
            badge = attrs.get("badge", "Verified")
            slots = ", ".join(p.get("free_slots", []))
            lines.append(
                f"  - {p.get('name')} (ID: {p.get('id')}, Service: {p.get('service')}, Area: {p.get('area')}): "
                f"Rate: ₹{p.get('price')}, Rating: {p.get('rating')}★ [{badge}], "
                f"Exp: {exp} yrs, Specialty: '{spec}', Free Slots: [{slots}]"
            )

        # 3. User Memory Preferences
        if self.memory:
            facts = self.memory.view_all(user_id)
            if facts:
                lines.append("\nUSER STORED PREFERENCES:")
                for f in facts:
                    lines.append(f"  - {f['key']}: {f['value']} (Source: {f['source']})")

        # 4. Sanitized Reviews Sample
        lines.append("\nCUSTOMER REVIEWS (SANITIZED):")
        for p in active_providers[:3]:
            try:
                raw_reviews = self.api.get_reviews(p["id"])
                for r in raw_reviews:
                    sanitized_text = self.sanitizer.sanitize_prompt(r.get("text", ""))
                    lines.append(f"  - [{p.get('name')}] {r.get('user')}: {sanitized_text} ({r.get('rating')}★)")
            except Exception:
                pass

        return "\n".join(lines)

    def route_and_reason(
        self,
        user_query: str,
        state: ErrandState,
        user_id: str = "user_default",
    ) -> dict[str, Any] | None:
        """Use LLM to perform deep intent classification, contradiction detection, and slot extraction."""
        if not self.llm:
            return None

        # Build context
        context_str = self.build_system_context(state, user_id=user_id)
        current_providers = state.get("providers", [])
        opt_summary = [
            f"Option {i+1}: {p.get('name')} (ID: {p.get('id')}, Price: ₹{p.get('price')}, Rating: {p.get('rating')}★)"
            for i, p in enumerate(current_providers)
        ] if current_providers else ["None currently shown"]

        system_instruction = (
            "You are the intelligent intent router and reasoning engine for Orange Invest Home Services assistant.\n"
            "Supported services: plumbing, electrician, ac_servicing, cleaning.\n\n"
            "INTENT CLASSIFICATION RULES:\n"
            "1. 'clarification': The user's requested trade contradicts the described task (e.g. asking for a plumber to fix light bulbs/switches/wiring, or electrician for leaking pipes/taps/toilets). Provide clarifying 'answer' asking if they want the correct trade.\n"
            "2. 'search': The user expresses a need, desire, or request to find, book, hire, or arrange a home service (e.g. 'i need a plumber', 'find electrician in Koramangala', 'book ac servicing', 'looking for someone to fix shower'). Extract 'service' ('plumbing'|'electrician'|'ac_servicing'|'cleaning') and 'area'.\n"
            "3. 'select_option': The user chooses an option number or provider name from presented options (e.g. '1', '2', 'Option 1', 'first one', 'book Rajesh', 'Anil'). Provide 1-based 'selected_option_index'.\n"
            "4. 'inquiry': The user is asking a question or requesting information about a provider's price, rating, reviews, specialty, experience, slot availability, or policies (e.g. 'rating of anil', 'price of anil', 'is rajesh available at 9am?'). Provide helpful conversational 'answer'.\n"
            "5. 'list_bookings': User asks to view active or past bookings ('my bookings', 'show bookings').\n"
            "6. 'cancel': User wants to cancel an existing booking.\n"
            "7. 'reschedule': User wants to reschedule or move an existing booking.\n"
            "8. 'memory_view': User asks to see stored preferences ('my memory', 'show preferences').\n"
            "9. 'memory_forget': User asks to forget a preference ('forget <key>').\n\n"
            "Output a valid JSON object with the following keys:\n"
            "- intent: 'clarification' | 'search' | 'select_option' | 'inquiry' | 'cancel' | 'reschedule' | 'list_bookings' | 'memory_view' | 'memory_forget'\n"
            "- contradiction: boolean\n"
            "- service: 'plumbing' | 'electrician' | 'ac_servicing' | 'cleaning' | null\n"
            "- area: string or null (e.g. koramangala, indiranagar, etc.)\n"
            "- budget_max: number or null\n"
            "- time_preference: string or null\n"
            "- selected_option_index: number or null\n"
            "- answer: string or null (if intent is inquiry or clarification, provide a direct helpful conversational answer)\n\n"
            f"Current options presented: {', '.join(opt_summary)}\n"
            f"{context_str}"
        )

        try:
            import json
            from langchain_core.messages import SystemMessage, HumanMessage
            response = self.llm.invoke([
                SystemMessage(content=system_instruction),
                HumanMessage(content=f"User Input: '{user_query}'"),
            ])
            content = response.content if hasattr(response, "content") else str(response)
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
        except Exception:
            return None
        return None

    def answer_inquiry(
        self,
        user_query: str,
        state: ErrandState,
        user_id: str = "user_default",
    ) -> str:
        """Answer user's question conversationally with live context."""
        context_str = self.build_system_context(state, user_id=user_id)

        # Attempt LLM reasoning first if online
        if self.llm:
            try:
                system_instruction = (
                    "You are the intelligent chat support assistant for Orange Invest's Home Services platform.\n"
                    "You have access to live provider schedules, active bookings, customer reviews, and pricing data.\n"
                    "Your job is to answer user inquiries accurately, naturally, and helpfully based on the context.\n\n"
                    "Rules:\n"
                    "1. AVAILABILITY & EXISTING BOOKING CROSS-CHECK:\n"
                    "   If the user asks whether a provider is available at a particular date/time (e.g. 'is rajesh available at 2026-11-02T09:00'):\n"
                    "   - Check if the provider lists that slot in their free slots.\n"
                    "   - CRITICAL: Check the user's ACTIVE USER BOOKINGS! If the user already has a booking with that provider at that exact slot, "
                    "clearly explain that the provider has that slot, but the user ALREADY has a confirmed booking for that exact time (cite the Booking ID)!\n"
                    "   - Offer helpful next steps (e.g., keep it, reschedule to another slot, or book another provider).\n"
                    "2. PRICING & NEGOTIATION:\n"
                    "   Explain that platform partner quotes are fixed, standardized rates backed by warranty, but suggest cheaper alternative providers if they want budget options.\n"
                    "3. ATTRIBUTES & REVIEWS:\n"
                    "   If asked about experience, specialty, rating, or reviews, provide specific verified details from the context.\n"
                    "4. SAFETY & INTEGRITY:\n"
                    "   Never bypass code approval gates in text. You cannot confirm or finalize a booking purely in chat text without the code approval flow.\n"
                    "5. Keep responses concise, polite, and to the point (2 to 4 sentences).\n\n"
                    f"{context_str}"
                )

                response = self.llm.invoke([
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_query},
                ])
                content = response.content if hasattr(response, "content") else str(response)
                return content.strip()
            except Exception:
                # On timeout or error, fall through to deterministic response
                pass

        # Deterministic semantic response (Offline fallback & evaluation mode)
        return self._deterministic_answer(user_query, state, user_id)

    def _deterministic_answer(
        self,
        query: str,
        state: ErrandState,
        user_id: str,
    ) -> str:
        """Deterministic, rule-backed intelligent answer generator for offline/test environments."""
        text = query.lower()
        active_providers = state.get("providers") or PROVIDERS_DATA
        bookings = self.api.list_bookings(user_id=user_id)

        # 0a. Check for Platform Capabilities / What services do you offer?
        if any(phrase in text for phrase in ["what services", "which services", "services you offer", "supported services", "what can you do", "help me with what"]):
            return (
                "Orange Invest specializes in 4 verified home-service categories:\n"
                "• **Plumbing** (pipe repairs, taps, kitchen & bathroom fittings)\n"
                "• **Electrical** (wiring, light bulbs, switches, circuit repairs)\n"
                "• **AC Servicing** (deep cleaning, filter replacement, cooling checks)\n"
                "• **Home Cleaning** (deep cleaning, housekeeping, dusting)\n\n"
                "Which service would you like to arrange?"
            )

        # 0b. Check for Unsupported / Out-of-Scope Services
        unsupported_trades = {
            "car drivers or transportation services": ["driver", "car driver", "chauffeur", "cab", "taxi", "car drive"],
            "carpentry or woodwork services": ["carpenter", "carpentry", "woodwork", "furniture repair"],
            "painting services": ["painter", "painting", "whitewash"],
            "pest control services": ["pest control", "termites", "bedbugs", "cockroach"],
            "gardening or landscaping services": ["gardener", "gardening", "landscaping", "lawn care"],
            "cooking or chef services": ["cook", "chef", "cooking maid"],
            "childcare or babysitting services": ["babysitter", "baby sitter", "childcare", "nanny"],
            "appliance repairs outside AC servicing": ["refrigerator", "fridge repair", "washing machine", "tv repair", "microwave"],
            "automotive or mechanic services": ["car repair", "car mechanic", "bike repair", "car wash"],
        }
        for desc, keywords in unsupported_trades.items():
            if any(kw in text for kw in keywords):
                return (
                    f"I apologize, but Orange Invest currently does not offer {desc}. "
                    "We specialize in verified home services for **plumbing**, **electrical work**, "
                    "**AC servicing**, and **home cleaning**.\n\n"
                    "Would you like me to help you arrange one of our supported home services instead?"
                )

        # 1. Match Provider (if mentioned by name or id)
        target_provider = None
        for p in active_providers:
            name_parts = [part for part in p.get("name", "").lower().split() if len(part) > 2]
            if p.get("id", "").lower() in text or any(part in text for part in name_parts):
                target_provider = p
                break

        # Fallback to first provider if options currently presented
        if not target_provider and state.get("providers"):
            target_provider = state["providers"][0]

        # 2. Extract Slot or Time from query if any (e.g. 2026-11-02T09:00 or 9:00 or morning)
        slot_match = re.search(r"\b(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})\b", query)
        target_slot = slot_match.group(1) if slot_match else None

        # 3. Handle Availability Inquiry (e.g. "is rajesh available at 2026-11-02T09:00")
        if any(w in text for w in ["available", "free", "slot", "when", "can i book", "at 2026", "at 9", "at 10", "at 11"]):
            if target_provider:
                p_name = target_provider.get("name")
                p_slots = target_provider.get("free_slots", [])

                # Check if user already booked this provider for this slot!
                if target_slot:
                    existing_bk = next(
                        (b for b in bookings if b.get("provider_id") == target_provider.get("id") and b.get("slot") == target_slot and b.get("status") == "booked"),
                        None
                    )
                    if existing_bk:
                        other_slots = [s for s in p_slots if s != target_slot]
                        other_str = ", ".join(other_slots[:2]) if other_slots else "no other slots"
                        return (
                            f"**{p_name}** has the **{target_slot}** slot on schedule, but you already have a confirmed booking "
                            f"(Booking ID: **{existing_bk['booking_id']}**) for that exact time!\n"
                            f"If you'd like to book another time, {p_name} is also free at: {other_str}."
                        )

                    if target_slot in p_slots:
                        return (
                            f"Yes, **{p_name}** is available at **{target_slot}**! "
                            f"Standard rate is ₹{target_provider.get('price')}. Would you like to select this provider?"
                        )
                    else:
                        slots_str = ", ".join(p_slots) if p_slots else "no open slots"
                        return (
                            f"**{p_name}** is not available at **{target_slot}**. "
                            f"Their available slots are: {slots_str}."
                        )

                # General availability inquiry without specific slot
                slots_str = ", ".join(p_slots) if p_slots else "no slots currently open"
                return f"**{p_name}** currently has the following slots available: {slots_str}."

        # 4. Handle Price Inquiry or Negotiation
        if any(w in text for w in ["price", "cost", "charge", "fee", "rate", "negotiable", "discount", "bargain", "cheaper", "lower", "reduce"]):
            if target_provider and any(w in text for w in ["price of", "cost of", "charge of", "rate of"]):
                return f"The standard rate for **{target_provider['name']}** is **₹{target_provider.get('price')}**."
            cheapest = min(active_providers, key=lambda p: p.get("price", 99999))
            return (
                f"All provider charges on our platform are fixed, standardized quotes backed by guaranteed service warranty.\n"
                f"If you are seeking a more budget-friendly option, **{cheapest['name']}** is available at **₹{cheapest['price']}** "
                f"(Rating: {cheapest.get('rating')}★)."
            )

        # 5. Handle Provider Specialty / Experience / Rating Details Inquiry
        if any(w in text for w in ["rating", "stars", "tell me about", "specialty", "experience", "who is", "details", "badge"]):
            if target_provider:
                p_id = target_provider.get("id")
                details = self.api.get_provider(p_id) or target_provider
                attrs = details.get("attributes", {})
                spec = attrs.get("specialty", "Standard home services")
                exp = attrs.get("experience_years", "Verified")
                badge = attrs.get("badge", "Top Rated")
                if "rating" in text or "stars" in text:
                    return f"**{details.get('name')}** has a rating of **{details.get('rating')}★** [{badge}] with {exp} years of experience."
                return (
                    f"**{details.get('name')}** has **{exp} years** of experience ({badge}) with a **{details.get('rating')}★** rating.\n"
                    f"• Specialty: {spec}\n"
                    f"• Standard Rate: ₹{details.get('price')}\n"
                    f"Would you like to proceed with this provider?"
                )

        # 6. Handle Customer Reviews Inquiry
        if any(w in text for w in ["reviews", "what do customers say", "feedback"]):
            if target_provider:
                try:
                    reviews = self.api.get_reviews(target_provider["id"])
                    clean_reviews = [
                        f'"{self.sanitizer.sanitize_prompt(r.get("text", ""))}" — {r.get("user")}'
                        for r in reviews if r.get("rating", 0) >= 4 and "SYSTEM OVERRIDE" not in r.get("text", "")
                    ]
                    sample = "\n• ".join(clean_reviews[:2]) if clean_reviews else "No verified reviews yet."
                    return f"Customer reviews for **{target_provider['name']}** ({target_provider.get('rating')}★):\n• {sample}"
                except Exception:
                    pass

        # 7. Default friendly support response
        if state.get("providers"):
            return (
                f"I can help you with details, pricing, slot checks, or booking for any of the listed options "
                f"({', '.join(p['name'] for p in state['providers'])}). Let me know what you'd like to check or choose an option number!"
            )

        return "I can assist you with booking, rescheduling, canceling home services, or checking provider details and availability. How can I help?"
