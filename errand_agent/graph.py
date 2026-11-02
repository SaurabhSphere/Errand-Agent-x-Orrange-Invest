"""LangGraph StateGraph definition and workflow compiler for Errand Agent."""

from typing import Any, Literal
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from mcp_server.provider_api import MockProviderAPI
from errand_agent.approval import ApprovalController
from errand_agent.memory import MemoryManager
from errand_agent.models import ActionType, WorkflowState
from errand_agent.nodes.await_approval import await_approval_node
from errand_agent.nodes.execute_booking import execute_booking_node
from errand_agent.nodes.execute_cancel import execute_cancel_node
from errand_agent.nodes.execute_reschedule import execute_reschedule_node
from errand_agent.nodes.gather_info import gather_info
from errand_agent.nodes.hold_slot import hold_slot_node
from errand_agent.nodes.present_options import present_options_node
from errand_agent.nodes.router import route_intent
from errand_agent.nodes.search_providers import search_providers_node
from errand_agent.nodes.verify_booking import verify_booking_node
from errand_agent.state import ErrandState
from errand_agent.tracer import Tracer


def build_errand_graph(
    api: MockProviderAPI,
    approval_controller: ApprovalController,
    memory_manager: MemoryManager | None = None,
    tracer: Tracer | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Any:
    """Construct and compile the full Errand Agent LangGraph StateGraph."""

    builder = StateGraph(ErrandState)

    # 1. Define Node Functions (injecting dependencies)
    def node_route_intent(state: ErrandState) -> dict[str, Any]:
        return route_intent(state)

    def node_gather_info(state: ErrandState) -> dict[str, Any]:
        return gather_info(state, memory_manager=memory_manager)

    def node_search(state: ErrandState) -> dict[str, Any]:
        return search_providers_node(state, api=api, tracer=tracer)

    def node_present(state: ErrandState) -> dict[str, Any]:
        return present_options_node(state)

    def node_hold(state: ErrandState) -> dict[str, Any]:
        return hold_slot_node(state, api=api, tracer=tracer)

    def node_await_approval(state: ErrandState) -> dict[str, Any]:
        return await_approval_node(state, approval_controller=approval_controller)

    def node_execute_booking(state: ErrandState) -> dict[str, Any]:
        return execute_booking_node(
            state,
            api=api,
            approval_controller=approval_controller,
            tracer=tracer,
        )

    def node_verify(state: ErrandState) -> dict[str, Any]:
        return verify_booking_node(state, api=api, tracer=tracer)

    def node_execute_cancel(state: ErrandState) -> dict[str, Any]:
        return execute_cancel_node(
            state,
            api=api,
            approval_controller=approval_controller,
            tracer=tracer,
        )

    def node_execute_reschedule(state: ErrandState) -> dict[str, Any]:
        return execute_reschedule_node(
            state,
            api=api,
            approval_controller=approval_controller,
            tracer=tracer,
        )

    def node_list_bookings(state: ErrandState) -> dict[str, Any]:
        user_id = state.get("user_id", "user_default")
        bookings = api.list_bookings(user_id=user_id)
        if not bookings:
            msg = "You have no past or upcoming bookings."
        else:
            lines = ["Here are your bookings:"]
            for b in bookings:
                lines.append(
                    f"• **{b['booking_id']}**: {b.get('service', 'Service')} with {b.get('provider_name', 'Provider')} "
                    f"at {b.get('slot', 'N/A')} (Status: {b.get('status')})"
                )
            msg = "\n".join(lines)
        return {
            "workflow_state": WorkflowState.IDLE.value,
            "messages": [AIMessage(content=msg)],
        }

    def node_memory_view(state: ErrandState) -> dict[str, Any]:
        user_id = state.get("user_id", "user_default")
        if not memory_manager:
            return {"messages": [AIMessage(content="Memory store is not enabled.")]}
        facts = memory_manager.view_all(user_id)
        if not facts:
            msg = "No preferences currently saved in memory."
        else:
            lines = ["Your saved preferences:"]
            for f in facts:
                lines.append(f"• **{f['key']}**: {f['value']} (Source: {f['source']})")
            msg = "\n".join(lines)
        return {"workflow_state": WorkflowState.IDLE.value, "messages": [AIMessage(content=msg)]}

    def node_memory_forget(state: ErrandState) -> dict[str, Any]:
        user_id = state.get("user_id", "user_default")
        key = state.get("memory_key_to_forget", "preferred_area")
        if memory_manager:
            memory_manager.forget(user_id, key)
            msg = f"I have forgotten your preference: **{key}**. It will not be reused."
        else:
            msg = "Memory manager is not available."
        return {"workflow_state": WorkflowState.IDLE.value, "messages": [AIMessage(content=msg)]}

    def node_inquiry_pricing(state: ErrandState) -> dict[str, Any]:
        providers = state.get("providers", [])
        lines = [
            "All rates listed by our verified home-service partners are fixed, standardized platform quotes with full service warranty and quality guarantee, so they are not negotiable."
        ]
        if providers:
            cheapest = min(providers, key=lambda p: p.get("price", 99999))
            lines.append(
                f"\nIf you are looking for the most economical option, **{cheapest['name']}** is available at **₹{cheapest['price']}**."
            )
            lines.append("\nPlease reply with the option number you would like to proceed with (e.g. 'Option 1' or 'Option 3').")
        return {
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
            "messages": [AIMessage(content="\n".join(lines))],
        }

    def node_invalid_selection(state: ErrandState) -> dict[str, Any]:
        providers = state.get("providers", [])
        max_opt = len(providers) if providers else 3
        msg = f"Option 0 is not a valid choice. Please choose between Option 1 and Option {max_opt}, or type 'cancel' to exit."
        return {
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
            "messages": [AIMessage(content=msg)],
        }

    def node_inquiry_provider(state: ErrandState) -> dict[str, Any]:
        p = state.get("inquiry_provider") or (state.get("providers", [])[0] if state.get("providers") else None)
        if not p:
            return {"messages": [AIMessage(content="Could not find details for that provider.")]}

        p_id = p.get("id")
        details = api.get_provider(p_id) if api else p
        attrs = details.get("attributes", {})
        spec = attrs.get("specialty", "General home services")
        exp = attrs.get("experience_years", "Experienced")
        badge = attrs.get("badge", "Verified")

        msg = (
            f"Here are the details for **{details.get('name', p_id)}**:\n"
            f"• Rating: **{details.get('rating', 'N/A')}★** [{badge}]\n"
            f"• Standard Rate: **₹{details.get('price', 'N/A')}**\n"
            f"• Experience: **{exp} years**\n"
            f"• Specialty: {spec}\n\n"
            f"Would you like to select this provider? (Reply with the option number, e.g. 'Option 1')"
        )
        return {
            "workflow_state": WorkflowState.PRESENTING_OPTIONS.value,
            "messages": [AIMessage(content=msg)],
        }

    # 2. Add nodes to graph
    builder.add_node("route_intent", node_route_intent)
    builder.add_node("gather_info", node_gather_info)
    builder.add_node("search_providers", node_search)
    builder.add_node("present_options", node_present)
    builder.add_node("hold_slot", node_hold)
    builder.add_node("await_approval", node_await_approval)
    builder.add_node("execute_booking", node_execute_booking)
    builder.add_node("verify_booking", node_verify)
    builder.add_node("execute_cancel", node_execute_cancel)
    builder.add_node("execute_reschedule", node_execute_reschedule)
    builder.add_node("list_bookings", node_list_bookings)
    builder.add_node("memory_view", node_memory_view)
    builder.add_node("memory_forget", node_memory_forget)
    builder.add_node("inquiry_pricing", node_inquiry_pricing)
    builder.add_node("invalid_selection", node_invalid_selection)
    builder.add_node("inquiry_provider", node_inquiry_provider)

    # 3. Add Edges & Conditional Routing
    builder.add_edge(START, "route_intent")

    def route_after_intent(state: ErrandState) -> Literal[
        "gather_info", "hold_slot", "await_approval",
        "list_bookings", "memory_view", "memory_forget",
        "inquiry_pricing", "invalid_selection", "inquiry_provider"
    ]:
        intent = state.get("intent")
        if intent == "memory_view":
            return "memory_view"
        elif intent == "memory_forget":
            return "memory_forget"
        elif intent == "list_bookings":
            return "list_bookings"
        elif intent in ("cancel", "reschedule"):
            return "await_approval"
        elif intent == "select_provider":
            return "hold_slot"
        elif intent == "inquiry_pricing":
            return "inquiry_pricing"
        elif intent == "invalid_selection":
            return "invalid_selection"
        elif intent == "inquiry_provider":
            return "inquiry_provider"
        return "gather_info"

    builder.add_conditional_edges("route_intent", route_after_intent)

    def route_after_gather(state: ErrandState) -> Literal["search_providers", "__end__"]:
        if state.get("workflow_state") == WorkflowState.SEARCHING.value:
            return "search_providers"
        return "__end__"

    builder.add_conditional_edges("gather_info", route_after_gather, {
        "search_providers": "search_providers",
        "__end__": END,
    })

    builder.add_edge("search_providers", "present_options")
    builder.add_edge("present_options", END)

    def route_after_hold(state: ErrandState) -> Literal["await_approval", "present_options"]:
        if state.get("workflow_state") == WorkflowState.AWAITING_APPROVAL.value:
            return "await_approval"
        return "present_options"

    builder.add_conditional_edges("hold_slot", route_after_hold, {
        "await_approval": "await_approval",
        "present_options": "present_options",
    })

    # Route from await_approval to the appropriate action node
    # The interrupt_before will pause execution right before entering this node!
    def route_after_approval(state: ErrandState) -> Literal[
        "execute_booking", "execute_cancel", "execute_reschedule"
    ]:
        action = state.get("current_action", "book")
        if action == "cancel":
            return "execute_cancel"
        elif action == "reschedule":
            return "execute_reschedule"
        return "execute_booking"

    builder.add_conditional_edges("await_approval", route_after_approval, {
        "execute_booking": "execute_booking",
        "execute_cancel": "execute_cancel",
        "execute_reschedule": "execute_reschedule",
    })

    def route_after_booking(state: ErrandState) -> Literal[
        "verify_booking", "present_options", "hold_slot", "__end__"
    ]:
        wstate = state.get("workflow_state")
        if wstate == WorkflowState.VERIFYING.value:
            return "verify_booking"
        elif wstate == WorkflowState.PRESENTING_OPTIONS.value:
            return "present_options"
        elif wstate == WorkflowState.HOLDING_SLOT.value:
            return "hold_slot"
        return "__end__"

    builder.add_conditional_edges("execute_booking", route_after_booking, {
        "verify_booking": "verify_booking",
        "present_options": "present_options",
        "hold_slot": "hold_slot",
        "__end__": END,
    })

    builder.add_edge("verify_booking", END)
    builder.add_edge("execute_cancel", END)
    builder.add_edge("execute_reschedule", END)
    builder.add_edge("list_bookings", END)
    builder.add_edge("memory_view", END)
    builder.add_edge("memory_forget", END)
    builder.add_edge("inquiry_pricing", END)
    builder.add_edge("invalid_selection", END)
    builder.add_edge("inquiry_provider", END)

    # 4. Compile with checkpointer and human-in-the-loop interrupts (MUST-HAVE 2)
    checkpointer_inst = checkpointer or MemorySaver()

    graph = builder.compile(
        checkpointer=checkpointer_inst,
        interrupt_before=["execute_booking", "execute_cancel", "execute_reschedule"],
    )

    return graph
