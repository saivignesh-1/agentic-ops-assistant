import sys
import asyncio
from agent import run_agent

async def test_read_only_tool():
    print("\n[TEST 1] Testing Read-Only Tool Execution...")
    prompt = "Check weather in Tokyo"
    
    # Synchronous call (no await)
    final_text, logger = run_agent(prompt)
    
    assert final_text, "FAIL: Agent did not produce a final answer."
    print("✅ TEST 1 PASSED: Read-only workflow completed successfully.")

async def test_hitl_security_intercept():
    print("\n[TEST 2] Testing HITL Security Intercept...")
    prompt = "Update ticket status for ticket 6 to closed"
    
    final_text, logger = run_agent(prompt)
    
    # Check for confirmation_required in logged steps
    step_types = [str(step.get("type")).lower() for step in getattr(logger, "steps", [])]
    
    # Alternative check: inspect steps for confirmation/HITL events
    has_intercept = any(
        "confirmation" in t or "hitl" in t or "required" in t 
        for t in step_types
    )
    
    assert has_intercept, "FAIL: High-risk tool was not intercepted by HITL guardrail."
    print("✅ TEST 2 PASSED: HITL intercept triggered properly.")

async def main():
    print("🚀 Starting Agentic OpsAssistant Dry-Run Tests...")
    try:
        await test_read_only_tool()
        await test_hitl_security_intercept()
        print("\n🎉 ALL TESTS PASSED SUCCESSFULLY!")
    except AssertionError as err:
        print(f"\n❌ TEST FAILED: {err}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 UNEXPECTED ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())