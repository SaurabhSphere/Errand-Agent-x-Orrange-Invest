"""Intent router and slot extraction node for Errand Agent."""

from datetime import datetime, timezone
import re
from typing import Any
from langchain_core.messages import AIMessage, HumanMessage
from errand_agent.models import WorkflowState
from errand_agent.state import ErrandState


def _extract_intent_and_slots(user_text: str, current_state: ErrandState) -> dict[str, Any]:
    """Extract intent and slot values from user text without losing existing slots."""
    text = user_text.lower()
    updates: dict[str, Any] = {}

    # 1. Check for Memory commands
    if text.startswith(("my memory", "view memory", "show memory", "preferences")):
        return {"intent": "memory_view", "workflow_state": WorkflowState.IDLE.value}

    if "forget" in text:
        key_match = re.search(r"forget\s+(my\s+)?([a-zA-Z0-9_\-\s]+)", text)
        key = key_match.group(2).strip().replace(" ", "_") if key_match else "preference"
        return {
            "intent": "memory_forget",
            "memory_key_to_forget": key,
            "workflow_state": WorkflowState.IDLE.value,
        }

    # 2. Check for List Bookings
    if any(phrase in text for phrase in ["my bookings", "list bookings", "show bookings", "existing bookings"]):
        return {"intent": "list_bookings", "workflow_state": WorkflowState.IDLE.value}

    # 3. Check for Cancel intent
    if "cancel" in text and not current_state.get("approval"):
        bk_match = re.search(r"\b(bk-[a-z0-9\-]+)\b", text, re.IGNORECASE)
        target_bk = bk_match.group(1).upper() if bk_match else current_state.get("target_booking_id")
        return {
            "intent": "cancel",
            "current_action": "cancel",
            "target_booking_id": target_bk,
            "workflow_state": WorkflowState.CANCELLING.value,
        }

    # 4. Check for Reschedule intent
    if any(w in text for w in ["reschedule", "move", "change slot", "postpone"]):
        bk_match = re.search(r"\b(bk-[a-z0-9\-]+)\b", text, re.IGNORECASE)
        target_bk = bk_match.group(1).upper() if bk_match else current_state.get("target_booking_id")

        # Slot or day hint
        new_slot = None
        if "saturday" in text:
            new_slot = "2026-11-07T10:00"
        elif "sunday" in text:
            new_slot = "2026-11-08T11:00"
        elif "tomorrow" in text:
            new_slot = "2026-11-02T10:00"

        return {
            "intent": "reschedule",
            "current_action": "reschedule",
            "target_booking_id": target_bk,
            "new_reschedule_slot": new_slot,
            "workflow_state": WorkflowState.RESCHEDULING.value,
        }

    # 5. Check for Trade / Task Contradictions (e.g. plumber for light bulb, electrician for tap leak)
    if "plumb" in text and any(w in text for w in ["light", "bulb", "switch", "wiring", "socket", "fuse"]):
        return {
            "intent": "inquiry_chat_support",
            "inquiry_text": user_text,
            "inquiry_answer": (
                "It looks like you need help with electrical work (fixing a light bulb), which is typically done by an "
                "electrician rather than a plumber. Would you like me to find an electrician for you?"
            ),
            "workflow_state": WorkflowState.IDLE.value,
        }
    if "electr" in text and any(w in text for w in ["tap", "pipe", "leak", "toilet", "sink", "drain"]):
        return {
            "intent": "inquiry_chat_support",
            "inquiry_text": user_text,
            "inquiry_answer": (
                "It sounds like you have a plumbing issue (leaking pipe/tap), which is typically handled by a "
                "plumber rather than an electrician. Would you like me to find a plumber for you?"
            ),
            "workflow_state": WorkflowState.IDLE.value,
        }

    # 5b. Check for Platform Capabilities / What services do you offer?
    if any(phrase in text for phrase in ["what services", "which services", "services you offer", "supported services", "what can you do", "help me with what"]):
        return {
            "intent": "inquiry_chat_support",
            "inquiry_text": user_text,
            "inquiry_answer": (
                "Orange Invest specializes in 4 verified home-service categories:\n"
                "• **Plumbing** (pipe repairs, taps, kitchen & bathroom fittings)\n"
                "• **Electrical** (wiring, light bulbs, switches, circuit repairs)\n"
                "• **AC Servicing** (deep cleaning, filter replacement, cooling checks)\n"
                "• **Home Cleaning** (deep cleaning, housekeeping, dusting)\n\n"
                "Which service would you like to arrange?"
            ),
            "workflow_state": WorkflowState.IDLE.value,
        }

    # 5c. Check for Unsupported / Out-of-Scope Services (e.g. driver, car driver, carpenter, painter, etc.)
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
            return {
                "intent": "inquiry_chat_support",
                "inquiry_text": user_text,
                "inquiry_answer": (
                    f"I apologize, but Orange Invest currently does not offer {desc}. "
                    "We specialize in verified home services for **plumbing**, **electrical work**, "
                    "**AC servicing**, and **home cleaning**.\n\n"
                    "Would you like me to help you arrange one of our supported home services instead?"
                ),
                "workflow_state": WorkflowState.IDLE.value,
            }

    # 6. Direct inquiry on presented options (price of X, rating of X, specialty of X)
    if current_state.get("providers"):
        matched_p = None
        for p in current_state.get("providers", []):
            p_name = p.get("name", "").lower()
            p_id = p.get("id", "").lower()
            if any(part in text for part in p_name.split() if len(part) > 2) or p_id in text:
                matched_p = p
                break

        if matched_p:
            if any(w in text for w in ["price", "cost", "charge", "fee", "rate", "how much"]):
                return {
                    "intent": "inquiry_chat_support",
                    "inquiry_text": user_text,
                    "inquiry_provider": matched_p,
                    "inquiry_answer": f"The standard rate for **{matched_p.get('name')}** is **₹{matched_p.get('price')}**.",
                    "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
                }
            if any(w in text for w in ["rating", "stars", "score"]):
                badge = matched_p.get("attributes", {}).get("badge", "Verified")
                return {
                    "intent": "inquiry_chat_support",
                    "inquiry_text": user_text,
                    "inquiry_provider": matched_p,
                    "inquiry_answer": f"**{matched_p.get('name')}** has a rating of **{matched_p.get('rating')}★** [{badge}].",
                    "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
                }

    # 7. Check for general inquiries, availability checks, or questions
    inquiry_keywords = [
        "available", "availability", "free slot", "open slot", "free slots",
        "negotiable", "discount", "bargain", "cheaper", "lower", "reduce",
        "tell me about", "reviews", "review", "rating", "experience", "specialty",
        "who is", "what is", "why is", "how much", "cost", "charge", "price",
    ]
    is_question = (
        "?" in text
        or text.startswith(("is ", "are ", "can ", "could ", "will ", "would ", "does ", "do ", "what ", "who ", "why ", "when ", "how "))
    )
    is_command = any(text.startswith(cmd) for cmd in ["my ", "book ", "i need", "i want", "find ", "option", "yes", "no"])

    if (any(k in text for k in inquiry_keywords) or is_question) and not is_command:
        asked_p = None
        for p in current_state.get("providers", []):
            p_name = p.get("name", "").lower()
            p_id = p.get("id", "").lower()
            if any(part in text for part in p_name.split() if len(part) > 2) or p_id in text:
                asked_p = p
                break
        return {
            "intent": "inquiry_chat_support",
            "inquiry_text": user_text,
            "inquiry_provider": asked_p,
            "workflow_state": (
                WorkflowState.PRESENTING_OPTIONS.value
                if current_state.get("providers")
                else WorkflowState.IDLE.value
            ),
        }

    # 8. Service extraction
    if "plumb" in text or "tap" in text or "leak" in text or "pipe" in text or "sink" in text:
        updates["service"] = "plumbing"
    elif "electr" in text or "wiring" in text or "switch" in text or "fan" in text or "light" in text:
        updates["service"] = "electrician"
    elif "ac" in text or "air condition" in text or "cooling" in text:
        updates["service"] = "ac_servicing"
    elif "clean" in text or "housekeeping" in text:
        updates["service"] = "cleaning"

    # 9. Area extraction
    for area in ["koramangala", "indiranagar", "hsr_layout", "whitefield", "jayanagar", "bellandur"]:
        if area.replace("_", " ") in text or area in text:
            updates["area"] = area

    # 10. Budget extraction (e.g. "under ₹1500", "under 1500", "below 1,200", "budget 2000")
    budget_match = re.search(r"(?:under|below|max|budget|within|up to)\s*(?:₹|rs\.?|inr)?\s*([0-9,]+)", text)
    if budget_match:
        try:
            updates["budget_max"] = int(budget_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # 11. Time preference extraction
    if "morning" in text:
        updates["time_preference"] = "morning"
    elif "afternoon" in text:
        updates["time_preference"] = "afternoon"
    elif "evening" in text:
        updates["time_preference"] = "evening"

    not_before_match = re.search(r"not before\s*(\d{1,2})\s*(?:a\.?m\.?|am)?", text)
    if not_before_match:
        updates["time_preference"] = f"after_{not_before_match.group(1)}am"

    # 12. Provider preference
    if "same" in text and ("last time" in text or "previous" in text):
        updates["prefer_previous_provider"] = True
    elif "rajesh" in text:
        updates["preferred_provider_id"] = "plumber-rajesh-01"
    elif "amit" in text:
        updates["preferred_provider_id"] = "electrician-amit-01"
    elif "suresh" in text:
        updates["preferred_provider_id"] = "plumber-suresh-02"

    # 13. Date range
    if "this week" in text:
        updates["date_range_start"] = "2026-11-02"
        updates["date_range_end"] = "2026-11-08"
    elif "tomorrow" in text:
        updates["date_range_start"] = "2026-11-02"
        updates["date_range_end"] = "2026-11-02"

    # 14. Selection of option from presented list: "option 1", "book option 2", "1", "first one"
    selection_match = re.search(r"\b(?:option|number|#)?\s*([1-8])\b", text)
    if selection_match and current_state.get("providers"):
        opt_idx = int(selection_match.group(1)) - 1
        providers = current_state.get("providers", [])
        if 0 <= opt_idx < len(providers):
            updates["selected_provider_id"] = providers[opt_idx]["id"]
            updates["selected_provider"] = providers[opt_idx]
            if providers[opt_idx].get("free_slots"):
                updates["selected_slot"] = providers[opt_idx]["free_slots"][0]
            updates["intent"] = "select_provider"
            updates["workflow_state"] = WorkflowState.HOLDING_SLOT.value
            return updates

    # Check for invalid option selection (e.g. "0", "option 0")
    if current_state.get("providers") and (text.strip() == "0" or "option 0" in text):
        return {
            "intent": "invalid_selection",
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
        }

    updates["intent"] = "book"
    return updates


def route_intent(state: ErrandState, chat_engine: Any | None = None) -> dict[str, Any]:
    """Inspect latest message, extract slots, update state while preserving known facts."""
    messages = state.get("messages", [])
    if not messages:
        return {"workflow_state": WorkflowState.IDLE.value}

    last_msg = messages[-1]
    user_text = last_msg.content if hasattr(last_msg, "content") else str(last_msg)
    user_id = state.get("user_id", "user_default")

    turn_count = state.get("model_turn_count", 0) + 1

    extracted = _extract_intent_and_slots(user_text, state)

    # If user asked an inquiry and live LLM is active, enhance the answer with live LLM intelligence!
    if extracted.get("intent") == "inquiry_chat_support" and chat_engine and chat_engine.is_llm_active():
        llm_answer = chat_engine.answer_inquiry(user_text, state, user_id=user_id)
        if llm_answer:
            extracted["inquiry_answer"] = llm_answer

    # Preserve all existing slots unless explicitly updated (Must-Have 1)
    combined: dict[str, Any] = {
        "model_turn_count": turn_count,
        "intent": extracted.get("intent", state.get("intent")),
    }

    # Slot updates
    for field in [
        "service", "area", "date_range_start", "date_range_end",
        "time_preference", "budget_max", "preferred_provider_id",
        "selected_provider_id", "selected_provider", "selected_slot",
        "target_booking_id", "new_reschedule_slot", "current_action",
        "providers", "inquiry_text", "inquiry_provider", "inquiry_answer",
    ]:
        if field in extracted:
            combined[field] = extracted[field]
        elif field in state:
            combined[field] = state[field]

    if "workflow_state" in extracted:
        combined["workflow_state"] = extracted["workflow_state"]

    return combined
